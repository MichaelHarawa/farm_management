from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch

from ..models import (
    AccountingPeriod,
    ExpenditureStatus,
    FundingAllocation,
    FundingClassification,
    FundingReceipt,
    FundingReceiptStatus,
    FundingSource,
    FundingSourceType,
    OwnerContributor,
    OwnerDesignationStatus,
    OwnerReceiptDesignation,
    PeriodStatus,
    PayrollPaymentFunding,
    PayrollPaymentStatus,
)
from .action_audit import record_finance_action
from .funding_attribution import (
    expenditure_payment_beneficiary_shares,
    payroll_payment_beneficiary_shares,
)


ZERO = Decimal("0.00")
CENT = Decimal("0.01")
OWNER_CASH_CLASSIFICATIONS = {
    FundingClassification.OWNER_CAPITAL_RETURN,
    FundingClassification.OWNER_DRAWING,
    FundingClassification.OWNER_COMPENSATION,
    FundingClassification.OWNER_DISTRIBUTION,
}


def money(value) -> Decimal:
    try:
        return Decimal(str(value or ZERO)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid monetary amount."})


def _as_date(value, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError({field: "Enter a valid date."})


def _as_datetime(value, *, field: str) -> datetime:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    parsed = _as_date(value, field=field)
    return timezone.make_aware(datetime.combine(parsed, time(hour=12)))


def _normalize_designations(rows, *, receipt_amount: Decimal) -> list[dict]:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValidationError({"designations": "Provide a list of batch designations."})
    normalized = []
    batch_ids: set[int] = set()
    total = ZERO
    for row in rows:
        try:
            batch_id = int(row.get("batch"))
        except (TypeError, ValueError):
            raise ValidationError({"designations": "Each designation requires a batch."})
        if batch_id in batch_ids:
            raise ValidationError({"designations": "Combine duplicate batch designations."})
        amount = money(row.get("amount"))
        if amount <= ZERO:
            raise ValidationError({"designations": "Designation amounts must be positive."})
        batch_ids.add(batch_id)
        total += amount
        normalized.append(
            {
                "batch": batch_id,
                "amount": amount,
                "notes": str(row.get("notes", "")).strip(),
            }
        )
    if total > receipt_amount:
        raise ValidationError(
            {"designations": "Batch designations cannot exceed the owner receipt."}
        )
    if set(Batch.objects.filter(pk__in=batch_ids).values_list("pk", flat=True)) != batch_ids:
        raise ValidationError({"designations": "A selected poultry batch does not exist."})
    return normalized


def _fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _ensure_open_period(value: date, *, field: str) -> None:
    period = AccountingPeriod.objects.filter(
        period_start__lte=value,
        period_end__gte=value,
    ).first()
    if period and period.status == PeriodStatus.CLOSED:
        raise ValidationError(
            {field: "This accounting period is closed. Reopen it before recording the change."}
        )


@transaction.atomic
def record_owner_contribution(
    *,
    owner_id: int,
    amount,
    receipt_date,
    reference: str,
    notes: str,
    designations,
    designation_date=None,
    idempotency_key: str,
    user,
    funding_source_id: int | None = None,
    source_description: str = "",
) -> tuple[FundingReceipt, bool]:
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError({"idempotency_key": "A submission key is required."})
    contribution = money(amount)
    if contribution <= ZERO:
        raise ValidationError({"amount": "Owner contribution must be positive."})
    received_at = _as_datetime(receipt_date, field="receipt_date")
    _ensure_open_period(received_at.date(), field="receipt_date")
    effective_designation_date = _as_date(
        designation_date or received_at.date(),
        field="designation_date",
    )
    normalized = _normalize_designations(
        designations,
        receipt_amount=contribution,
    )
    requested_payload = {
        "owner": int(owner_id),
        "funding_source": int(funding_source_id) if funding_source_id else None,
        "source_description": (source_description or "").strip(),
        "amount": str(contribution),
        "receipt_date": received_at.isoformat(),
        "reference": (reference or "").strip(),
        "notes": (notes or "").strip(),
        "designation_date": effective_designation_date.isoformat(),
        "designations": [
            {"batch": row["batch"], "amount": str(row["amount"]), "notes": row["notes"]}
            for row in sorted(normalized, key=lambda item: item["batch"])
        ],
    }
    fingerprint = _fingerprint(requested_payload)
    existing = FundingReceipt.objects.select_for_update().filter(
        idempotency_key=key
    ).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ValidationError(
                {"idempotency_key": "This submission key was already used for different contribution details."}
            )
        return existing, False

    owner = OwnerContributor.objects.select_for_update().filter(
        pk=owner_id,
        is_active=True,
    ).first()
    if owner is None:
        raise ValidationError({"owner": "Select an active owner or contributor."})

    # The owner row serializes normal retries so two simultaneous submissions do
    # not create duplicate sources or receipts before the unique key is visible.
    existing = FundingReceipt.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.request_fingerprint != fingerprint:
            raise ValidationError(
                {"idempotency_key": "This submission key was already used for different contribution details."}
            )
        return existing, False

    if funding_source_id:
        source = FundingSource.objects.select_for_update().filter(
            pk=funding_source_id,
            source_type=FundingSourceType.OWNER_CAPITAL,
            owner=owner,
            is_active=True,
        ).first()
        if source is None:
            raise ValidationError(
                {"funding_source": "Select an active owner-capital source belonging to this owner."}
            )
    else:
        source = FundingSource.objects.select_for_update().filter(
            source_type=FundingSourceType.OWNER_CAPITAL,
            owner=owner,
            is_active=True,
        ).order_by("pk").first()
        if source is None:
            source = FundingSource.objects.create(
                source_type=FundingSourceType.OWNER_CAPITAL,
                owner=owner,
                description=(source_description or "").strip() or "Owner capital account",
            )

    try:
        with transaction.atomic():
            receipt = FundingReceipt.objects.create(
                funding_source=source,
                amount=contribution,
                receipt_date=received_at,
                reference=requested_payload["reference"],
                notes=requested_payload["notes"],
                idempotency_key=key,
                request_fingerprint=fingerprint,
                created_by=user,
            )
    except IntegrityError:
        existing = FundingReceipt.objects.filter(idempotency_key=key).first()
        if existing and existing.request_fingerprint == fingerprint:
            return existing, False
        raise ValidationError(
            {"idempotency_key": "This submission key was already used for different contribution details."}
        )
    created_designations = [
        OwnerReceiptDesignation.objects.create(
            receipt=receipt,
            batch_id=row["batch"],
            amount=row["amount"],
            designation_date=effective_designation_date,
            notes=row["notes"],
            created_by=user,
        )
        for row in normalized
    ]
    record_finance_action(
        actor=user,
        action="owner_contribution_recorded",
        entity_type="finance.FundingReceipt",
        entity_id=receipt.pk,
        after_data={
            "owner_id": owner.pk,
            "owner_public_id": owner.public_id,
            "funding_source_id": source.pk,
            "amount": contribution,
            "receipt_date": received_at,
            "designation_total": sum(
                (row.amount for row in created_designations),
                ZERO,
            ),
            "designation_ids": [row.pk for row in created_designations],
        },
    )
    return receipt, True


@transaction.atomic
def add_owner_designations(
    *,
    receipt_id: int,
    designation_date,
    designations,
    user,
) -> list[OwnerReceiptDesignation]:
    receipt = FundingReceipt.objects.select_for_update().select_related(
        "funding_source"
    ).get(pk=receipt_id)
    if receipt.funding_source.source_type != FundingSourceType.OWNER_CAPITAL:
        raise ValidationError({"receipt": "Only owner-capital receipts can be designated."})
    if receipt.status != FundingReceiptStatus.POSTED:
        raise ValidationError({"receipt": "Only a posted owner receipt can be designated."})
    existing_total = money(
        receipt.owner_designations.filter(
            status=OwnerDesignationStatus.POSTED
        ).aggregate(total=Sum("amount"))["total"]
    )
    normalized = _normalize_designations(
        designations,
        receipt_amount=money(receipt.amount - existing_total),
    )
    if not normalized:
        raise ValidationError({"designations": "Add at least one batch designation."})
    existing_batches = set(
        receipt.owner_designations.filter(
            status=OwnerDesignationStatus.POSTED,
            batch_id__in=[row["batch"] for row in normalized],
        ).values_list("batch_id", flat=True)
    )
    if existing_batches:
        raise ValidationError(
            {"designations": "Reverse the existing designation before replacing a batch amount."}
        )
    effective_date = _as_date(designation_date, field="designation_date")
    _ensure_open_period(effective_date, field="designation_date")
    rows = [
        OwnerReceiptDesignation.objects.create(
            receipt=receipt,
            batch_id=row["batch"],
            amount=row["amount"],
            designation_date=effective_date,
            notes=row["notes"],
            created_by=user,
        )
        for row in normalized
    ]
    record_finance_action(
        actor=user,
        action="owner_receipt_designated",
        entity_type="finance.FundingReceipt",
        entity_id=receipt.pk,
        after_data={
            "designation_ids": [row.pk for row in rows],
            "designation_total": sum((row.amount for row in rows), ZERO),
            "designation_date": effective_date,
        },
    )
    return rows


@transaction.atomic
def reverse_owner_designation(*, designation_id: int, reason: str, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reversal reason is required."})
    _ensure_open_period(timezone.localdate(), field="reversal_date")
    designation = OwnerReceiptDesignation.objects.select_for_update().get(
        pk=designation_id
    )
    if designation.status != OwnerDesignationStatus.POSTED:
        raise ValidationError({"detail": "Only a posted designation can be reversed."})
    designation.status = OwnerDesignationStatus.REVERSED
    designation.reversed_at = timezone.now()
    designation.reversed_by = user
    designation.reversal_reason = reason
    designation.save(
        update_fields=[
            "status",
            "reversed_at",
            "reversed_by",
            "reversal_reason",
            "updated_at",
        ]
    )
    record_finance_action(
        actor=user,
        action="owner_designation_reversed",
        entity_type="finance.OwnerReceiptDesignation",
        entity_id=designation.pk,
        before_data={"status": OwnerDesignationStatus.POSTED},
        after_data={"status": designation.status},
        reason=reason,
    )
    return designation


@transaction.atomic
def reverse_funding_receipt(*, receipt_id: int, reason: str, user):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reversal reason is required."})
    _ensure_open_period(timezone.localdate(), field="reversal_date")
    receipt = FundingReceipt.objects.select_for_update().select_related(
        "funding_source"
    ).get(pk=receipt_id)
    if receipt.status != FundingReceiptStatus.POSTED:
        raise ValidationError({"detail": "Only posted receipts can be reversed."})
    source = FundingSource.objects.select_for_update().get(
        pk=receipt.funding_source_id
    )
    from .profitability import available_funding_source_cash

    if available_funding_source_cash(source) < receipt.amount:
        raise ValidationError(
            {"detail": "This receipt funds posted expenditures and cannot be reversed."}
        )
    receipt.status = FundingReceiptStatus.REVERSED
    reversed_at = timezone.now()
    receipt.reversed_at = reversed_at
    receipt.reversed_by = user
    receipt.reversal_reason = reason
    receipt.save(
        update_fields=[
            "status",
            "reversed_at",
            "reversed_by",
            "reversal_reason",
            "updated_at",
        ]
    )
    if source.source_type == FundingSourceType.OWNER_CAPITAL:
        designation_ids = list(
            receipt.owner_designations.filter(
                status=OwnerDesignationStatus.POSTED
            ).values_list("pk", flat=True)
        )
        if designation_ids:
            OwnerReceiptDesignation.objects.filter(pk__in=designation_ids).update(
                status=OwnerDesignationStatus.REVERSED,
                reversed_at=reversed_at,
                reversed_by=user,
                reversal_reason=f"Source receipt reversed: {reason}",
                updated_at=reversed_at,
            )
        record_finance_action(
            actor=user,
            action="owner_contribution_reversed",
            entity_type="finance.FundingReceipt",
            entity_id=receipt.pk,
            before_data={"status": FundingReceiptStatus.POSTED},
            after_data={
                "status": receipt.status,
                "amount": receipt.amount,
                "coordinated_designation_reversals": designation_ids,
            },
            reason=reason,
        )
    return receipt


def _effective_receipt_q(as_of: date) -> Q:
    return Q(status=FundingReceiptStatus.POSTED) | Q(
        status=FundingReceiptStatus.REVERSED,
        reversed_at__date__gt=as_of,
    )


def _effective_expenditure_q(as_of: date) -> Q:
    return Q(expenditure__status=ExpenditureStatus.POSTED) | Q(
        expenditure__status=ExpenditureStatus.VOID,
        expenditure__reversed_at__date__gt=as_of,
    )


def _effective_payroll_q(as_of: date) -> Q:
    return Q(payment__status=PayrollPaymentStatus.POSTED) | Q(
        payment__status=PayrollPaymentStatus.REVERSED,
        payment__reversed_at__date__gt=as_of,
    )


def _effective_designation_q(as_of: date) -> Q:
    return Q(status=OwnerDesignationStatus.POSTED) | Q(
        status=OwnerDesignationStatus.REVERSED,
        reversed_at__date__gt=as_of,
    )


def owner_contribution_report(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    owner_id: int | None = None,
    unknown_owner: bool = False,
    batch_ids: set[int] | None = None,
) -> dict:
    """Cash and analytical owner-capital history without duplicating source ledgers."""

    end = date_to or timezone.localdate()
    start = date_from
    if start and start > end:
        raise ValidationError({"date_from": "Start date cannot be after end date."})
    selected_batches = set(batch_ids or set())

    source_filter = Q(funding_source__source_type=FundingSourceType.OWNER_CAPITAL)
    allocation_source_filter = Q(
        funding_source__source_type=FundingSourceType.OWNER_CAPITAL
    )
    if owner_id:
        source_filter &= Q(funding_source__owner_id=owner_id)
        allocation_source_filter &= Q(funding_source__owner_id=owner_id)
    elif unknown_owner:
        source_filter &= Q(funding_source__owner__isnull=True)
        allocation_source_filter &= Q(funding_source__owner__isnull=True)

    receipts = list(
        FundingReceipt.objects.filter(
            source_filter,
            receipt_date__date__lte=end,
        )
        .filter(_effective_receipt_q(end))
        .select_related("funding_source__owner", "created_by", "reversed_by")
        .prefetch_related(
            Prefetch(
                "owner_designations",
                queryset=OwnerReceiptDesignation.objects.select_related(
                    "batch", "created_by", "reversed_by"
                ).order_by("designation_date", "pk"),
            )
        )
        .order_by("receipt_date", "pk")
    )

    expenditure_funding = list(
        FundingAllocation.objects.filter(
            allocation_source_filter,
            allocation_date__lte=end,
        )
        .filter(_effective_expenditure_q(end))
        .select_related(
            "funding_source__owner",
            "expenditure__category",
        )
        .prefetch_related(
            "expenditure__cost_allocations__batch",
        )
        .order_by("allocation_date", "pk")
    )
    payroll_funding = list(
        PayrollPaymentFunding.objects.filter(
            allocation_source_filter,
            payment__payment_date__lte=end,
        )
        .filter(_effective_payroll_q(end))
        .select_related(
            "funding_source__owner",
            "payment__payroll_entry__employee",
        )
        .prefetch_related("payment__payroll_entry__cost_allocations__batch")
        .order_by("payment__payment_date", "pk")
    )

    receipt_ids = [receipt.pk for receipt in receipts]
    designations = list(
        OwnerReceiptDesignation.objects.filter(
            receipt_id__in=receipt_ids,
            designation_date__lte=end,
        )
        .filter(_effective_designation_q(end))
        .select_related("receipt__funding_source__owner", "batch")
        .order_by("designation_date", "pk")
    )

    receipt_total_to_date = money(sum((row.amount for row in receipts), ZERO))
    expenditure_total_to_date = money(
        sum((row.amount for row in expenditure_funding), ZERO)
    )
    payroll_total_to_date = money(sum((row.amount for row in payroll_funding), ZERO))
    total_used_to_date = money(expenditure_total_to_date + payroll_total_to_date)

    def in_period(value: date) -> bool:
        return (start is None or value >= start) and value <= end

    period_receipts = [row for row in receipts if in_period(row.receipt_date.date())]
    period_expenditure = [
        row for row in expenditure_funding if in_period(row.allocation_date)
    ]
    period_payroll = [
        row for row in payroll_funding if in_period(row.payment.payment_date)
    ]
    introduced_in_period = money(sum((row.amount for row in period_receipts), ZERO))
    used_in_period = money(
        sum((row.amount for row in period_expenditure), ZERO)
        + sum((row.amount for row in period_payroll), ZERO)
    )

    capital_returns_to_date = money(
        sum(
            (
                row.amount
                for row in expenditure_funding
                if row.classification == FundingClassification.OWNER_CAPITAL_RETURN
            ),
            ZERO,
        )
    )
    capital_returns_in_period = money(
        sum(
            (
                row.amount
                for row in period_expenditure
                if row.classification == FundingClassification.OWNER_CAPITAL_RETURN
            ),
            ZERO,
        )
    )

    classification_totals = {
        classification: money(
            sum(
                (
                    row.amount
                    for row in expenditure_funding
                    if row.classification == classification
                ),
                ZERO,
            )
        )
        for classification in OWNER_CASH_CLASSIFICATIONS
    }

    batch_totals: dict[int, dict] = {}
    farm_wide_to_date = ZERO
    farm_wide_in_period = ZERO

    def add_batch_use(*, batch_id: int, amount: Decimal, movement_date: date, owner):
        row = batch_totals.setdefault(
            batch_id,
            {
                "batch_id": batch_id,
                "batch_code": None,
                "designated_as_of": ZERO,
                "owner_cash_spent_to_date": ZERO,
                "owner_cash_spent_in_period": ZERO,
                "owners": set(),
            },
        )
        row["owner_cash_spent_to_date"] += amount
        if in_period(movement_date):
            row["owner_cash_spent_in_period"] += amount
        row["owners"].add(owner.pk if owner else None)

    expenditure_attribution: dict[int, dict] = {}
    for allocation in expenditure_funding:
        shares = expenditure_payment_beneficiary_shares(
            allocation.expenditure,
            allocation.amount,
        )
        expenditure_attribution[allocation.pk] = shares
        farm_wide_to_date += shares["farm_wide"]
        if in_period(allocation.allocation_date):
            farm_wide_in_period += shares["farm_wide"]
        for batch_id, amount in shares["batch_amounts"].items():
            add_batch_use(
                batch_id=batch_id,
                amount=amount,
                movement_date=allocation.allocation_date,
                owner=allocation.funding_source.owner,
            )

    payroll_attribution: dict[int, dict] = {}
    for funding in payroll_funding:
        shares = payroll_payment_beneficiary_shares(
            funding.payment.payroll_entry,
            funding.amount,
        )
        payroll_attribution[funding.pk] = shares
        farm_wide_to_date += shares["farm_wide"]
        if in_period(funding.payment.payment_date):
            farm_wide_in_period += shares["farm_wide"]
        for batch_id, amount in shares["batch_amounts"].items():
            add_batch_use(
                batch_id=batch_id,
                amount=amount,
                movement_date=funding.payment.payment_date,
                owner=funding.funding_source.owner,
            )

    designation_by_receipt: dict[int, Decimal] = {}
    for designation in designations:
        designation_by_receipt[designation.receipt_id] = money(
            designation_by_receipt.get(designation.receipt_id, ZERO)
            + designation.amount
        )
        row = batch_totals.setdefault(
            designation.batch_id,
            {
                "batch_id": designation.batch_id,
                "batch_code": designation.batch.batch_id,
                "designated_as_of": ZERO,
                "owner_cash_spent_to_date": ZERO,
                "owner_cash_spent_in_period": ZERO,
                "owners": set(),
            },
        )
        row["batch_code"] = designation.batch.batch_id
        row["designated_as_of"] += designation.amount
        owner = designation.receipt.funding_source.owner
        row["owners"].add(owner.pk if owner else None)

    missing_batch_codes = [
        batch_id for batch_id, row in batch_totals.items() if row["batch_code"] is None
    ]
    batch_codes = dict(
        Batch.objects.filter(pk__in=missing_batch_codes).values_list("pk", "batch_id")
    )
    for batch_id in missing_batch_codes:
        batch_totals[batch_id]["batch_code"] = batch_codes.get(
            batch_id, f"Batch #{batch_id}"
        )

    receipt_rows = []
    unassigned_as_of = ZERO
    for receipt in receipts:
        designated = designation_by_receipt.get(receipt.pk, ZERO)
        unassigned = money(max(receipt.amount - designated, ZERO))
        unassigned_as_of += unassigned
        receipt_rows.append(
            {
                "id": receipt.pk,
                "owner_id": receipt.funding_source.owner_id,
                "owner_name": (
                    receipt.funding_source.owner.display_name
                    if receipt.funding_source.owner_id
                    else "Unknown legacy owner"
                ),
                "funding_source_id": receipt.funding_source_id,
                "source_description": str(receipt.funding_source),
                "amount": money(receipt.amount),
                "receipt_date": receipt.receipt_date,
                "reference": receipt.reference,
                "notes": receipt.notes,
                "current_status": receipt.status,
                "reversed_at": receipt.reversed_at,
                "reversal_reason": receipt.reversal_reason,
                "designated_as_of": designated,
                "unassigned_as_of": unassigned,
                "designations": [
                    {
                        "id": designation.pk,
                        "batch_id": designation.batch_id,
                        "batch_code": designation.batch.batch_id,
                        "amount": money(designation.amount),
                        "designation_date": designation.designation_date,
                        "current_status": designation.status,
                        "reversed_at": designation.reversed_at,
                        "reversal_reason": designation.reversal_reason,
                    }
                    for designation in receipt.owner_designations.all()
                    if designation.designation_date <= end
                ],
            }
        )

    owner_rows: dict[int | None, dict] = {}
    for receipt in receipts:
        owner = receipt.funding_source.owner
        key = owner.pk if owner else None
        row = owner_rows.setdefault(
            key,
            {
                "owner_id": key,
                "owner_public_id": str(owner.public_id) if owner else None,
                "owner_name": owner.display_name if owner else "Unknown legacy owner",
                "cash_introduced_to_date": ZERO,
                "cash_used_to_date": ZERO,
                "capital_returns_to_date": ZERO,
                "net_contributed_capital": ZERO,
                "remaining_cash": ZERO,
                "designated_as_of": ZERO,
            },
        )
        row["cash_introduced_to_date"] += receipt.amount
        row["designated_as_of"] += designation_by_receipt.get(receipt.pk, ZERO)
    for allocation in expenditure_funding:
        owner = allocation.funding_source.owner
        key = owner.pk if owner else None
        row = owner_rows.setdefault(
            key,
            {
                "owner_id": key,
                "owner_public_id": str(owner.public_id) if owner else None,
                "owner_name": owner.display_name if owner else "Unknown legacy owner",
                "cash_introduced_to_date": ZERO,
                "cash_used_to_date": ZERO,
                "capital_returns_to_date": ZERO,
                "net_contributed_capital": ZERO,
                "remaining_cash": ZERO,
                "designated_as_of": ZERO,
            },
        )
        row["cash_used_to_date"] += allocation.amount
        if allocation.classification == FundingClassification.OWNER_CAPITAL_RETURN:
            row["capital_returns_to_date"] += allocation.amount
    for funding in payroll_funding:
        owner = funding.funding_source.owner
        key = owner.pk if owner else None
        row = owner_rows.setdefault(
            key,
            {
                "owner_id": key,
                "owner_public_id": str(owner.public_id) if owner else None,
                "owner_name": owner.display_name if owner else "Unknown legacy owner",
                "cash_introduced_to_date": ZERO,
                "cash_used_to_date": ZERO,
                "capital_returns_to_date": ZERO,
                "net_contributed_capital": ZERO,
                "remaining_cash": ZERO,
                "designated_as_of": ZERO,
            },
        )
        row["cash_used_to_date"] += funding.amount
    for row in owner_rows.values():
        row["cash_introduced_to_date"] = money(row["cash_introduced_to_date"])
        row["cash_used_to_date"] = money(row["cash_used_to_date"])
        row["capital_returns_to_date"] = money(row["capital_returns_to_date"])
        row["designated_as_of"] = money(row["designated_as_of"])
        row["net_contributed_capital"] = money(
            row["cash_introduced_to_date"] - row["capital_returns_to_date"]
        )
        row["remaining_cash"] = money(
            row["cash_introduced_to_date"] - row["cash_used_to_date"]
        )

    events = []
    for receipt in receipts:
        event_date = receipt.receipt_date.date()
        if in_period(event_date):
            events.append(
                {
                    "sort_key": (event_date, 0, receipt.pk),
                    "date": event_date,
                    "event_type": "contribution",
                    "reference": receipt.reference or f"Receipt #{receipt.pk}",
                    "description": "Owner cash introduced",
                    "owner_id": receipt.funding_source.owner_id,
                    "owner_name": (
                        receipt.funding_source.owner.display_name
                        if receipt.funding_source.owner_id
                        else "Unknown legacy owner"
                    ),
                    "inflow": money(receipt.amount),
                    "outflow": ZERO,
                    "capital_movement": money(receipt.amount),
                    "source_href": None,
                }
            )
    for allocation in expenditure_funding:
        if in_period(allocation.allocation_date):
            is_return = allocation.classification == FundingClassification.OWNER_CAPITAL_RETURN
            events.append(
                {
                    "sort_key": (allocation.allocation_date, 1, allocation.pk),
                    "date": allocation.allocation_date,
                    "event_type": allocation.classification,
                    "reference": allocation.expenditure.expenditure_reference,
                    "description": allocation.expenditure.description,
                    "owner_id": allocation.funding_source.owner_id,
                    "owner_name": (
                        allocation.funding_source.owner.display_name
                        if allocation.funding_source.owner_id
                        else "Unknown legacy owner"
                    ),
                    "inflow": ZERO,
                    "outflow": money(allocation.amount),
                    "capital_movement": -money(allocation.amount) if is_return else ZERO,
                    "source_href": f"/finance/expenditures/{allocation.expenditure_id}",
                }
            )
    for funding in payroll_funding:
        payment = funding.payment
        if in_period(payment.payment_date):
            events.append(
                {
                    "sort_key": (payment.payment_date, 2, funding.pk),
                    "date": payment.payment_date,
                    "event_type": "payroll_payment",
                    "reference": f"Payroll payment #{payment.pk}",
                    "description": f"Payroll payment: {payment.payroll_entry.employee}",
                    "owner_id": funding.funding_source.owner_id,
                    "owner_name": (
                        funding.funding_source.owner.display_name
                        if funding.funding_source.owner_id
                        else "Unknown legacy owner"
                    ),
                    "inflow": ZERO,
                    "outflow": money(funding.amount),
                    "capital_movement": ZERO,
                    "source_href": "/finance/payroll",
                }
            )

    opening_receipts = money(
        sum(
            (row.amount for row in receipts if start and row.receipt_date.date() < start),
            ZERO,
        )
    )
    opening_expenditure = money(
        sum(
            (row.amount for row in expenditure_funding if start and row.allocation_date < start),
            ZERO,
        )
    )
    opening_payroll = money(
        sum(
            (
                row.amount
                for row in payroll_funding
                if start and row.payment.payment_date < start
            ),
            ZERO,
        )
    )
    opening_cash = money(opening_receipts - opening_expenditure - opening_payroll)
    opening_capital_returns = money(
        sum(
            (
                row.amount
                for row in expenditure_funding
                if start
                and row.allocation_date < start
                and row.classification == FundingClassification.OWNER_CAPITAL_RETURN
            ),
            ZERO,
        )
    )
    opening_net_capital = money(opening_receipts - opening_capital_returns)
    running_cash = opening_cash
    running_capital = opening_net_capital
    timeline = []
    for event in sorted(events, key=lambda row: row["sort_key"]):
        running_cash = money(running_cash + event["inflow"] - event["outflow"])
        running_capital = money(running_capital + event["capital_movement"])
        timeline.append(
            {
                key: value for key, value in event.items() if key != "sort_key"
            }
            | {
                "running_cash_balance": running_cash,
                "running_net_contributed_capital": running_capital,
            }
        )

    batch_rows = []
    for batch_id, row in batch_totals.items():
        if selected_batches and batch_id not in selected_batches:
            continue
        batch_rows.append(
            {
                **row,
                "designated_as_of": money(row["designated_as_of"]),
                "owner_cash_spent_to_date": money(row["owner_cash_spent_to_date"]),
                "owner_cash_spent_in_period": money(row["owner_cash_spent_in_period"]),
                "owners": sorted(
                    owner for owner in row["owners"] if owner is not None
                ),
                "has_unknown_owner": None in row["owners"],
            }
        )
    batch_rows.sort(key=lambda row: row["batch_code"])
    selected_batch_summary = {
        "batch_count": len(batch_rows),
        "designated_as_of": money(
            sum((row["designated_as_of"] for row in batch_rows), ZERO)
        ),
        "owner_cash_spent_in_period": money(
            sum((row["owner_cash_spent_in_period"] for row in batch_rows), ZERO)
        ),
        "owner_cash_spent_to_date": money(
            sum((row["owner_cash_spent_to_date"] for row in batch_rows), ZERO)
        ),
    }

    unknown_receipts = [
        row for row in receipts if row.funding_source.owner_id is None
    ]
    return {
        "currency": "MWK",
        "basis": (
            "Cash introduced uses owner FundingReceipt dates; cash used uses dated "
            "FundingAllocation and PayrollPaymentFunding rows. Batch designations are "
            "analytical assignments, not additional cash or expenditure."
        ),
        "date_from": start,
        "date_to": end,
        "owner_filter": "unknown" if unknown_owner else owner_id,
        "batch_filter": sorted(selected_batches),
        "summary": {
            "opening_cash_balance": opening_cash,
            "cash_introduced_in_period": introduced_in_period,
            "cash_used_in_period": used_in_period,
            "closing_cash_balance": money(receipt_total_to_date - total_used_to_date),
            "cash_introduced_to_date": receipt_total_to_date,
            "cash_used_to_date": total_used_to_date,
            "capital_returns_in_period": capital_returns_in_period,
            "capital_returns_to_date": capital_returns_to_date,
            "net_contributed_capital": money(
                receipt_total_to_date - capital_returns_to_date
            ),
            "designated_to_batches_as_of": money(
                sum((row.amount for row in designations), ZERO)
            ),
            "unassigned_contributions_as_of": money(unassigned_as_of),
            "farm_wide_use_in_period": money(farm_wide_in_period),
            "farm_wide_use_to_date": money(farm_wide_to_date),
            "owner_drawings_to_date": classification_totals[
                FundingClassification.OWNER_DRAWING
            ],
            "owner_compensation_to_date": classification_totals[
                FundingClassification.OWNER_COMPENSATION
            ],
            "profit_distributions_to_date": classification_totals[
                FundingClassification.OWNER_DISTRIBUTION
            ],
            "unknown_owner_receipt_count": len(unknown_receipts),
            "unknown_owner_receipt_amount": money(
                sum((row.amount for row in unknown_receipts), ZERO)
            ),
        },
        "owners": sorted(
            owner_rows.values(),
            key=lambda row: (row["owner_name"], row["owner_id"] or 0),
        ),
        "selected_batch_summary": selected_batch_summary,
        "batches": batch_rows,
        "receipts": sorted(
            receipt_rows,
            key=lambda row: (row["receipt_date"], row["id"]),
            reverse=True,
        ),
        "timeline": timeline,
        "timeline_opening_cash_balance": opening_cash,
        "timeline_opening_net_contributed_capital": opening_net_capital,
        "timeline_closing_cash_balance": running_cash,
        "timeline_closing_net_contributed_capital": running_capital,
    }
