from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch, InputCosts

from ..models import (
    AccountingPeriod,
    AllocationSourceType,
    CostAllocation,
    Expenditure,
    ExpenditureCategory,
    ExpenditureOrigin,
    ExpenditurePaymentStatus,
    ExpenditureStatus,
    FundingAllocation,
    FundingSource,
    InputCostReconciliation,
    PeriodStatus,
)
from .profitability import available_funding_source_cash


ZERO = Decimal("0.00")


def money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid monetary amount."})


def accounting_period_for(transaction_date: date, *, require_open: bool = True):
    periods = AccountingPeriod.objects.filter(
        period_start__lte=transaction_date,
        period_end__gte=transaction_date,
    )
    if require_open:
        periods = periods.filter(status=PeriodStatus.OPEN)
    period = periods.order_by("-period_start").first()
    if period is None:
        state = "open " if require_open else ""
        raise ValidationError(
            {"expenditure_date": f"Create an {state}accounting period covering {transaction_date}."}
        )
    return period


def validate_cost_allocations(expenditure: Expenditure, rows) -> list[tuple[int, Decimal]]:
    if not isinstance(rows, list):
        raise ValidationError({"cost_allocations": "Cost assignments must be a list."})
    normalized = []
    seen = set()
    for row in rows:
        try:
            batch_id = int(row.get("batch"))
        except (AttributeError, TypeError, ValueError):
            raise ValidationError({"cost_allocations": "Each assignment requires a batch."})
        amount = money(row.get("amount"))
        if amount <= ZERO:
            raise ValidationError({"cost_allocations": "Assigned amounts must be greater than zero."})
        if batch_id in seen:
            raise ValidationError(
                {"cost_allocations": f"Batch {batch_id} appears more than once; combine the rows."}
            )
        seen.add(batch_id)
        normalized.append((batch_id, amount))
    missing = seen.difference(Batch.objects.filter(pk__in=seen).values_list("pk", flat=True))
    if missing:
        raise ValidationError(
            {"cost_allocations": f"Unknown batch selection: {', '.join(map(str, sorted(missing)))}."}
        )
    total = sum((amount for _, amount in normalized), ZERO)
    if total != money(expenditure.amount):
        raise ValidationError(
            {"cost_allocations": f"Cost assignments must total {money(expenditure.amount)}; received {total}."}
        )
    return normalized


def _validate_payment_rows(rows, expected_total: Decimal, *, allow_less: bool) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValidationError({"funding_allocations": "Select at least one payment source."})
    normalized = []
    source_totals: dict[int, Decimal] = {}
    for row in rows:
        try:
            source_id = int(row.get("funding_source"))
        except (AttributeError, TypeError, ValueError):
            raise ValidationError({"funding_allocations": "Each payment row requires a funding source."})
        amount = money(row.get("amount"))
        if amount <= ZERO:
            raise ValidationError({"funding_allocations": "Payment amounts must be greater than zero."})
        source_totals[source_id] = source_totals.get(source_id, ZERO) + amount
        normalized.append(
            {
                "funding_source": source_id,
                "amount": amount,
                "classification": row.get("classification") or "reinvestment",
            }
        )
    total = sum((row["amount"] for row in normalized), ZERO)
    if total > expected_total or (not allow_less and total != expected_total):
        qualifier = "must not exceed" if allow_less else "must equal"
        raise ValidationError(
            {"funding_allocations": f"Payment allocations {qualifier} {expected_total}; received {total}."}
        )
    sources = {
        source.pk: source
        # PostgreSQL cannot apply FOR UPDATE to the nullable side of the outer
        # join produced by select_related("batch"). Lock the cash-source rows
        # themselves; the batch label can be loaded lazily for error messages.
        for source in FundingSource.objects.select_for_update().filter(pk__in=source_totals)
    }
    missing = set(source_totals).difference(sources)
    if missing:
        raise ValidationError(
            {"funding_allocations": f"Unknown funding source: {', '.join(map(str, sorted(missing)))}."}
        )
    for source_id, required in source_totals.items():
        available = available_funding_source_cash(sources[source_id])
        if required > available:
            raise ValidationError(
                {
                    "funding_allocations": (
                        f"{sources[source_id]} has {available} available, less than the requested {required}."
                    )
                }
            )
    return normalized


def funded_total(expenditure: Expenditure) -> Decimal:
    total = expenditure.funding_allocations.aggregate(total=Sum("amount"))["total"]
    return money(total or ZERO)


def sync_payment_status(expenditure: Expenditure) -> None:
    paid = funded_total(expenditure)
    if paid >= money(expenditure.amount):
        status = ExpenditurePaymentStatus.PAID
    elif paid > ZERO:
        status = ExpenditurePaymentStatus.PARTIAL
    elif expenditure.origin == ExpenditureOrigin.HISTORICAL_INPUT_COST:
        status = ExpenditurePaymentStatus.HISTORICAL_UNASSIGNED
    else:
        status = ExpenditurePaymentStatus.UNPAID
    if expenditure.payment_status != status:
        expenditure.payment_status = status
        expenditure.save(update_fields=["payment_status", "updated_at"])


def _create_cost_allocations(expenditure, rows, *, user, period=None):
    normalized = validate_cost_allocations(expenditure, rows)
    period = period or expenditure.accounting_period or accounting_period_for(
        expenditure.expenditure_date
    )
    total = sum((amount for _, amount in normalized), ZERO)
    for batch_id, amount in normalized:
        CostAllocation.objects.create(
            accounting_period=period,
            batch_id=batch_id,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure=expenditure,
            allocation_method="direct",
            driver_quantity=amount,
            total_driver_quantity=total,
            allocation_percentage=(amount * Decimal("100") / total).quantize(Decimal("0.0001")),
            allocated_amount=amount,
            generated_by=user,
        )


def _create_funding_rows(expenditure, rows, *, user, payment_group_key, allocation_date):
    for row in rows:
        FundingAllocation.objects.create(
            expenditure=expenditure,
            funding_source_id=row["funding_source"],
            amount=row["amount"],
            allocation_date=allocation_date,
            classification=row["classification"],
            payment_group_key=payment_group_key,
            created_by=user,
        )


@transaction.atomic
def post_expenditure(
    *,
    expenditure_id: int,
    user,
    funding_rows=None,
    cost_rows=None,
    allow_unpaid: bool = False,
) -> Expenditure:
    expenditure = Expenditure.objects.select_for_update().get(pk=expenditure_id)
    if expenditure.status != ExpenditureStatus.DRAFT:
        raise ValidationError({"detail": "Only draft expenditures can be posted."})

    if cost_rows is None:
        cost_rows = expenditure.cost_allocation_plan or []
    if cost_rows and not expenditure.cost_allocations.exists():
        _create_cost_allocations(expenditure, cost_rows, user=user)

    use_stored_funding = funding_rows is None
    if use_stored_funding:
        funding_rows = list(
            expenditure.funding_allocations.values(
                "funding_source", "amount", "classification"
            )
        )
    else:
        expenditure.funding_allocations.all().delete()

    if funding_rows:
        normalized = _validate_payment_rows(
            funding_rows,
            money(expenditure.amount),
            allow_less=allow_unpaid,
        )
        if not use_stored_funding:
            _create_funding_rows(
                expenditure,
                normalized,
                user=user,
                payment_group_key=f"post-{expenditure.pk}",
                allocation_date=expenditure.expenditure_date,
            )
    elif not allow_unpaid:
        raise ValidationError(
            {"funding_allocations": "Paid expenditures require a funding source before posting."}
        )

    expenditure.status = ExpenditureStatus.POSTED
    expenditure.posted_by = user
    expenditure.posted_at = timezone.now()
    expenditure.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    sync_payment_status(expenditure)
    return expenditure


@transaction.atomic
def create_batch_cost_transaction(*, batch: Batch, data: dict, user) -> InputCosts:
    idempotency_key = (data.pop("idempotency_key", "") or "").strip()
    if not idempotency_key:
        raise ValidationError({"idempotency_key": "A submission key is required."})
    existing = Expenditure.objects.select_for_update().filter(idempotency_key=idempotency_key).first()
    if existing:
        try:
            return existing.input_cost_detail
        except InputCosts.DoesNotExist:
            raise ValidationError({"idempotency_key": "This submission key is already in use."})

    payment_choice = data.pop("payment_status")
    funding_rows = data.pop("funding_allocations", []) or []
    category_id = data.pop("category_id")
    data.pop("category", None)
    category = ExpenditureCategory.objects.filter(pk=category_id, is_active=True).first()
    if category is None:
        raise ValidationError({"category_id": "Select an active expenditure category."})

    total = (
        Decimal(data["quantity"]) * Decimal(data["unit"]) * money(data["unit_cost"])
    ).quantize(Decimal("0.01"))
    if total <= ZERO:
        raise ValidationError({"unit_cost": "Calculated cost must be greater than zero."})
    transaction_date = data["purchase_date"].date()
    period = accounting_period_for(transaction_date)

    expenditure = Expenditure.objects.create(
        expenditure_date=transaction_date,
        accounting_period=period,
        amount=total,
        category=category,
        accounting_nature=category.default_accounting_nature,
        description=data["item"],
        status=ExpenditureStatus.DRAFT,
        payment_status=ExpenditurePaymentStatus.UNPAID,
        origin=ExpenditureOrigin.BATCH_COST,
        idempotency_key=idempotency_key,
        beneficiary_type="one_poultry_batch",
        beneficiary_detail=batch.batch_id,
        cost_allocation_plan=[{"batch": batch.pk, "amount": str(total)}],
        notes=data.get("notes", ""),
        created_by=user,
    )
    input_cost = InputCosts.objects.create(
        expenditure=expenditure,
        batch=batch,
        item=data["item"],
        category=category.name,
        quantity=data["quantity"],
        unit_measurement=data["unit_measurement"],
        unit=data["unit"],
        unit_cost=data["unit_cost"],
        purchase_date=data["purchase_date"],
        notes=data.get("notes", ""),
        created_by=user,
    )
    _create_cost_allocations(
        expenditure,
        expenditure.cost_allocation_plan,
        user=user,
        period=period,
    )

    if payment_choice == "paid":
        normalized = _validate_payment_rows(funding_rows, total, allow_less=False)
        _create_funding_rows(
            expenditure,
            normalized,
            user=user,
            payment_group_key=f"initial-{idempotency_key}",
            allocation_date=transaction_date,
        )
    elif payment_choice != "credit":
        raise ValidationError({"payment_status": "Select paid now or bought on credit."})
    elif funding_rows:
        raise ValidationError(
            {"funding_allocations": "A credit purchase must not withdraw cash until payment is recorded."}
        )

    expenditure.status = ExpenditureStatus.POSTED
    expenditure.posted_by = user
    expenditure.posted_at = timezone.now()
    expenditure.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    sync_payment_status(expenditure)
    return input_cost


@transaction.atomic
def record_expenditure_payment(
    *,
    expenditure_id: int,
    funding_rows,
    payment_group_key: str,
    user,
    payment_date=None,
) -> Expenditure:
    expenditure = Expenditure.objects.select_for_update().get(pk=expenditure_id)
    if expenditure.status != ExpenditureStatus.POSTED:
        raise ValidationError({"detail": "Only posted expenditures can receive payments."})
    payment_group_key = (payment_group_key or "").strip()
    if not payment_group_key:
        raise ValidationError({"idempotency_key": "A payment submission key is required."})
    if expenditure.funding_allocations.filter(payment_group_key=payment_group_key).exists():
        return expenditure
    outstanding = money(expenditure.amount) - funded_total(expenditure)
    if outstanding <= ZERO:
        raise ValidationError({"detail": "This expenditure is already fully paid."})
    normalized = _validate_payment_rows(funding_rows, outstanding, allow_less=True)
    if isinstance(payment_date, str):
        try:
            payment_date = date.fromisoformat(payment_date)
        except ValueError:
            raise ValidationError({"payment_date": "Enter a valid payment date."})
    _create_funding_rows(
        expenditure,
        normalized,
        user=user,
        payment_group_key=payment_group_key,
        allocation_date=payment_date or timezone.localdate(),
    )
    sync_payment_status(expenditure)
    return expenditure


@transaction.atomic
def reverse_expenditure(*, expenditure_id: int, reason: str, user) -> Expenditure:
    expenditure = Expenditure.objects.select_for_update().get(pk=expenditure_id)
    if expenditure.status != ExpenditureStatus.POSTED:
        raise ValidationError({"detail": "Only posted expenditures can be reversed."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reversal reason is required."})
    expenditure.status = ExpenditureStatus.VOID
    expenditure.reversal_reason = reason
    expenditure.reversed_at = timezone.now()
    expenditure.reversed_by = user
    expenditure.save(
        update_fields=["status", "reversal_reason", "reversed_at", "reversed_by", "updated_at"]
    )
    return expenditure


def batch_cost_records(batch: Batch) -> list[dict]:
    records = []
    allocations = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.EXPENDITURE,
        expenditure__status=ExpenditureStatus.POSTED,
    ).select_related("expenditure", "expenditure__category").prefetch_related(
        "expenditure__funding_allocations__funding_source"
    ).order_by("-expenditure__expenditure_date", "-created_at")
    for allocation in allocations:
        expenditure = allocation.expenditure
        detail = getattr(expenditure, "input_cost_detail", None)
        funding_labels = [
            str(row.funding_source) for row in expenditure.funding_allocations.all()
        ]
        records.append(
            {
                "id": detail.pk if detail else f"allocation-{allocation.pk}",
                "batch": batch.pk,
                "item": detail.item if detail else expenditure.description,
                "category": detail.category if detail else (
                    expenditure.category.name if expenditure.category_id else "Uncategorized"
                ),
                "quantity": detail.quantity if detail else 1,
                "unit_measurement": detail.unit_measurement if detail else "expense",
                "unit": detail.unit if detail else 1,
                "unit_cost": detail.unit_cost if detail else allocation.allocated_amount,
                "direct_input_total": allocation.allocated_amount,
                "purchase_date": detail.purchase_date if detail else expenditure.expenditure_date,
                "notes": detail.notes if detail else expenditure.notes,
                "created_at": detail.created_at if detail else expenditure.created_at,
                "updated_at": detail.updated_at if detail else expenditure.updated_at,
                "created_by": detail.created_by_id if detail else expenditure.created_by_id,
                "created_by_name": (
                    (detail.created_by.get_full_name() or detail.created_by.username)
                    if detail and detail.created_by_id
                    else ""
                ),
                "expenditure": expenditure.pk,
                "expenditure_reference": expenditure.expenditure_reference,
                "payment_status": expenditure.payment_status,
                "amount_paid": funded_total(expenditure),
                "balance_due": money(expenditure.amount) - funded_total(expenditure),
                "funding_sources": funding_labels,
                "origin": expenditure.origin,
            }
        )

    # Transitional fallback: uncertain/unresolved legacy rows remain visible and
    # countable until an authorized reconciliation decision is made.
    linked_ids = {record["id"] for record in records if isinstance(record["id"], int)}
    for detail in batch.input_costs.filter(expenditure__isnull=True).exclude(pk__in=linked_ids):
        records.append(
            {
                "id": detail.pk,
                "batch": batch.pk,
                "item": detail.item,
                "category": detail.category,
                "quantity": detail.quantity,
                "unit_measurement": detail.unit_measurement,
                "unit": detail.unit,
                "unit_cost": detail.unit_cost,
                "direct_input_total": detail.direct_input_total,
                "purchase_date": detail.purchase_date,
                "notes": detail.notes,
                "created_at": detail.created_at,
                "updated_at": detail.updated_at,
                "created_by": detail.created_by_id,
                "created_by_name": detail.created_by.get_username() if detail.created_by_id else "",
                "expenditure": None,
                "expenditure_reference": "Historical — reconciliation required",
                "payment_status": ExpenditurePaymentStatus.HISTORICAL_UNASSIGNED,
                "amount_paid": ZERO,
                "balance_due": detail.direct_input_total,
                "funding_sources": [],
                "origin": ExpenditureOrigin.HISTORICAL_INPUT_COST,
            }
        )
    return sorted(records, key=lambda row: str(row["purchase_date"]), reverse=True)


def reconciliation_summary() -> dict:
    counts = {
        row["status"]: row["total"]
        for row in InputCostReconciliation.objects.values("status").annotate(total=Count("pk"))
    }
    return {
        "matched": counts.get("matched", 0),
        "migrated": counts.get("migrated", 0),
        "uncertain": counts.get("uncertain", 0),
        "unresolved": counts.get("unresolved", 0),
        "manual_review_required": InputCostReconciliation.objects.filter(
            requires_manual_review=True
        ).count(),
    }
