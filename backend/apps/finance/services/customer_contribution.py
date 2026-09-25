from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch, PaymentStatus, ProductType, Sales

from ..models import (
    AccountingNature,
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    CostAllocation,
    CostScope,
    Customer,
    CustomerContributionLabel,
    CustomerCostAttribution,
    CustomerCostAttributionStatus,
    CustomerCostCategory,
    CustomerCostEvidenceStatus,
    CustomerCostSourceType,
    Expenditure,
    ExpenditureStatus,
    LabourWorkflowStatus,
    PayrollEntry,
    PeriodStatus,
    SalePayment,
    SalePaymentStatus,
    SharedExpenseScope,
)
from .action_audit import record_finance_action
from .allocations import allocate_amount_by_driver
from .profitability import batch_survivor_cost_basis


ZERO = Decimal("0.00")
BIRD_PRODUCTS = {ProductType.LIVE_CHICKEN, ProductType.DRESSED_CHICKEN}
CATEGORIES = [
    CustomerCostCategory.DIRECT_DELIVERY,
    CustomerCostCategory.SUPPORT,
    CustomerCostCategory.REWORK,
    CustomerCostCategory.ACQUISITION,
]


def _source_href(attribution: CustomerCostAttribution):
    if attribution.source_type == CustomerCostSourceType.EXPENDITURE and attribution.source_id:
        return f"/finance/expenditures/{attribution.source_id}"
    if attribution.source_type == CustomerCostSourceType.PAYROLL and attribution.source_id:
        return f"/finance/payroll?entry={attribution.source_id}"
    if attribution.source_type == CustomerCostSourceType.LABOUR and attribution.source_id:
        return f"/finance/labour?record={attribution.source_id}"
    if attribution.source_type == CustomerCostSourceType.COST_ALLOCATION and attribution.batch_id:
        return f"/finance/batches/{attribution.batch_id}"
    return None


def money(value) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(Decimal("0.01"))


def percent(numerator: Decimal, denominator: Decimal):
    if not denominator:
        return None
    return (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        Decimal("0.01")
    )


def _assert_open_period(day: date, field: str = "attribution_date"):
    if AccountingPeriod.objects.filter(
        period_start__lte=day,
        period_end__gte=day,
        status=PeriodStatus.CLOSED,
    ).exists():
        raise ValidationError(
            {field: "This accounting period is closed. Reopen it before changing customer analysis."}
        )


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _cost_allocation_is_production(row: CostAllocation) -> bool:
    if row.source_type in {AllocationSourceType.PAYROLL, AllocationSourceType.DEPRECIATION}:
        return True
    if row.source_type == AllocationSourceType.AD_HOC_LABOUR:
        return row.ad_hoc_labour_payment.cost_scope == CostScope.SHARED_PRODUCTION
    if row.source_type == AllocationSourceType.SHARED_EXPENSE:
        return row.shared_expense.scope == SharedExpenseScope.SHARED_PRODUCTION
    if row.source_type == AllocationSourceType.CONSUMABLE_USAGE:
        return row.consumable_usage.usage_scope == "shared_production"
    if row.source_type == AllocationSourceType.EXPENDITURE:
        return row.expenditure.status == ExpenditureStatus.POSTED and row.expenditure.accounting_nature in {
            AccountingNature.DIRECT_COST,
            AccountingNature.INDIRECT_OPERATING_EXPENSE,
        }
    return False


def _source_details(source_type: str, source_id: int):
    if source_type == CustomerCostSourceType.EXPENDITURE:
        row = Expenditure.objects.select_for_update().get(pk=source_id)
        if row.status != ExpenditureStatus.POSTED or row.reversed_at:
            raise ValidationError({"source_id": "Select a posted, unreversed expenditure."})
        return {
            "record": row,
            "line_cap": money(row.amount),
            "key": f"expenditure:{row.pk}",
            "key_cap": money(row.amount),
            "label": f"{row.expenditure_reference or row.reference_number} · {row.description}",
            "date": row.expenditure_date,
            "production_batch_ids": (
                set(row.cost_allocations.values_list("batch_id", flat=True))
                if row.accounting_nature in {
                    AccountingNature.DIRECT_COST,
                    AccountingNature.INDIRECT_OPERATING_EXPENSE,
                }
                else set()
            ),
        }

    if source_type == CustomerCostSourceType.PAYROLL:
        row = (
            PayrollEntry.objects.select_for_update(of=("self",))
            .select_related("expenditure")
            .get(pk=source_id)
        )
        if row.expenditure_id:
            key = f"expenditure:{row.expenditure_id}"
            key_cap = money(row.expenditure.amount)
        else:
            key = f"payroll:{row.pk}"
            key_cap = money(row.total_employer_cost)
        return {
            "record": row,
            "line_cap": money(row.total_employer_cost),
            "key": key,
            "key_cap": key_cap,
            "label": f"Payroll #{row.pk} · {row.accounting_period}",
            "date": row.accounting_period.period_end,
            "production_batch_ids": set(row.cost_allocations.values_list("batch_id", flat=True)),
        }

    if source_type == CustomerCostSourceType.LABOUR:
        row = (
            AdHocLabourPayment.objects.select_for_update(of=("self",))
            .select_related("expenditure")
            .get(pk=source_id)
        )
        if row.workflow_status not in {
            LabourWorkflowStatus.POSTED,
            LabourWorkflowStatus.PARTIALLY_PAID,
            LabourWorkflowStatus.PAID,
        } or row.reversed_at:
            raise ValidationError({"source_id": "Select posted, unreversed labour."})
        if row.expenditure_id:
            key = f"expenditure:{row.expenditure_id}"
            key_cap = money(row.expenditure.amount)
        else:
            key = f"labour:{row.pk}"
            key_cap = money(row.payment_amount)
        return {
            "record": row,
            "line_cap": money(row.payment_amount),
            "key": key,
            "key_cap": key_cap,
            "label": f"Labour #{row.pk} · {row.worker_name} · {row.task_description}",
            "date": row.work_date,
            "production_batch_ids": (
                (({row.batch_id} if row.batch_id else set()) | set(row.cost_allocations.values_list("batch_id", flat=True)))
                if row.cost_scope in {CostScope.BATCH_DIRECT, CostScope.SHARED_PRODUCTION}
                else set()
            ),
        }

    if source_type == CustomerCostSourceType.COST_ALLOCATION:
        row = (
            CostAllocation.objects.select_for_update(of=("self",))
            .select_related(
                "batch",
                "expenditure",
                "payroll_entry__expenditure",
                "ad_hoc_labour_payment__expenditure",
                "shared_expense__expenditure",
            )
            .get(pk=source_id)
        )
        if row.expenditure_id:
            key = f"expenditure:{row.expenditure_id}"
            key_cap = money(row.expenditure.amount)
        elif row.payroll_entry_id:
            if row.payroll_entry.expenditure_id:
                key = f"expenditure:{row.payroll_entry.expenditure_id}"
                key_cap = money(row.payroll_entry.expenditure.amount)
            else:
                key = f"payroll:{row.payroll_entry_id}"
                key_cap = money(row.payroll_entry.total_employer_cost)
        elif row.ad_hoc_labour_payment_id:
            if row.ad_hoc_labour_payment.expenditure_id:
                key = f"expenditure:{row.ad_hoc_labour_payment.expenditure_id}"
                key_cap = money(row.ad_hoc_labour_payment.expenditure.amount)
            else:
                key = f"labour:{row.ad_hoc_labour_payment_id}"
                key_cap = money(row.ad_hoc_labour_payment.payment_amount)
        elif row.shared_expense_id:
            if row.shared_expense.expenditure_id:
                key = f"expenditure:{row.shared_expense.expenditure_id}"
                key_cap = money(row.shared_expense.expenditure.amount)
            else:
                key = f"shared-expense:{row.shared_expense_id}"
                key_cap = money(row.shared_expense.amount)
        else:
            key = f"cost-allocation:{row.pk}"
            key_cap = money(row.allocated_amount)
        return {
            "record": row,
            "line_cap": money(row.allocated_amount),
            "key": key,
            "key_cap": key_cap,
            "label": f"Batch allocation #{row.pk} · {row.batch.batch_id}",
            "date": row.accounting_period.period_end,
            "production_batch_ids": {row.batch_id} if _cost_allocation_is_production(row) else set(),
        }

    raise ValidationError({"source_type": "Select a supported recognized cost source."})


@transaction.atomic
def record_customer_cost_attribution(
    *,
    customer_id: int,
    sale_id: int | None,
    batch_id: int | None,
    attribution_date: date,
    category: str,
    amount: Decimal,
    source_type: str,
    source_id: int | None,
    evidence_status: str,
    attribution_basis: str,
    reason: str,
    idempotency_key: str,
    user,
) -> tuple[CustomerCostAttribution, bool]:
    amount = money(amount)
    if amount <= ZERO:
        raise ValidationError({"amount": "Amount must be greater than zero."})
    _assert_open_period(attribution_date)
    customer = Customer.objects.select_for_update().get(pk=customer_id)
    if not customer.is_active:
        raise ValidationError({"customer": "Select an active customer."})
    sale = Sales.objects.select_related("customer", "batch").filter(pk=sale_id).first() if sale_id else None
    if sale and sale.customer_id != customer.pk:
        raise ValidationError({"sale": "The sale must be linked to this customer first."})
    batch = Batch.objects.filter(pk=batch_id).first() if batch_id else None
    if sale:
        if batch and batch.pk != sale.batch_id:
            raise ValidationError({"batch": "The selected sale belongs to another batch."})
        batch = sale.batch
    if source_type == CustomerCostSourceType.MANUAL_ESTIMATE:
        if source_id is not None:
            raise ValidationError({"source_id": "Documented estimates do not use a recognized source ID."})
        if evidence_status != CustomerCostEvidenceStatus.ESTIMATED:
            raise ValidationError({"evidence_status": "A manual analytical allocation must be marked estimated."})
        source = {
            "key": f"estimate:{uuid.uuid4()}",
            "label": "Documented analytical estimate",
            "date": attribution_date,
            "production_batch_ids": set(),
        }
    else:
        if not source_id:
            raise ValidationError({"source_id": "Select a recognized cost source."})
        try:
            source = _source_details(source_type, source_id)
        except (Expenditure.DoesNotExist, PayrollEntry.DoesNotExist, AdHocLabourPayment.DoesNotExist, CostAllocation.DoesNotExist):
            raise ValidationError({"source_id": "The selected cost source does not exist."})
        production_batches = source.get("production_batch_ids", set())
        if production_batches and (batch is None or batch.pk in production_batches):
            raise ValidationError(
                {
                    "source_id": (
                        "This cost is already included in batch production cost and is allocated "
                        "to sold units automatically. Attributing it again would double-count it."
                    )
                }
            )

    normalized_key = (idempotency_key or "").strip()
    payload = {
        "customer": customer.pk,
        "sale": sale.pk if sale else None,
        "batch": batch.pk if batch else None,
        "attribution_date": attribution_date,
        "category": category,
        "amount": amount,
        "source_type": source_type,
        "source_id": source_id,
        "evidence_status": evidence_status,
        "attribution_basis": attribution_basis.strip(),
        "reason": reason.strip(),
    }
    fingerprint = _fingerprint(payload)
    if normalized_key:
        existing = CustomerCostAttribution.objects.filter(idempotency_key=normalized_key).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ValidationError({"idempotency_key": "This retry key was already used with different details."})
            return existing, False

    if source_type != CustomerCostSourceType.MANUAL_ESTIMATE:
        line_used = money(
            CustomerCostAttribution.objects.select_for_update()
            .filter(
                source_type=source_type,
                source_id=source_id,
                status=CustomerCostAttributionStatus.POSTED,
            )
            .aggregate(total=Sum("amount"))["total"]
        )
        if line_used + amount > source["line_cap"]:
            raise ValidationError(
                {"amount": f"This source has only {money(source['line_cap'] - line_used)} available for attribution."}
            )
        economic_used = money(
            CustomerCostAttribution.objects.select_for_update()
            .filter(
                economic_source_key=source["key"],
                status=CustomerCostAttributionStatus.POSTED,
            )
            .aggregate(total=Sum("amount"))["total"]
        )
        if economic_used + amount > source["key_cap"]:
            raise ValidationError(
                {"amount": "This economic cost is already fully attributed through this or a linked source record."}
            )

    period = AccountingPeriod.objects.filter(
        period_start__lte=attribution_date,
        period_end__gte=attribution_date,
    ).first()
    try:
        row = CustomerCostAttribution.objects.create(
            customer=customer,
            sale=sale,
            batch=batch,
            attribution_date=attribution_date,
            accounting_period=period,
            category=category,
            amount=amount,
            source_type=source_type,
            source_id=source_id,
            economic_source_key=source["key"],
            source_label=source["label"],
            evidence_status=evidence_status,
            attribution_basis=payload["attribution_basis"],
            reason=payload["reason"],
            idempotency_key=normalized_key or None,
            request_fingerprint=fingerprint,
            created_by=user,
        )
    except IntegrityError:
        if not normalized_key:
            raise
        row = CustomerCostAttribution.objects.get(idempotency_key=normalized_key)
        if row.request_fingerprint != fingerprint:
            raise ValidationError({"idempotency_key": "This retry key was already used with different details."})
        return row, False
    record_finance_action(
        actor=user,
        action="customer_cost_attribution_recorded",
        entity_type="finance.CustomerCostAttribution",
        entity_id=row.pk,
        after_data=payload | {"economic_source_key": row.economic_source_key},
        reason=row.reason,
    )
    return row, True


@transaction.atomic
def reverse_customer_cost_attribution(*, attribution_id: int, reason: str, user):
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValidationError({"reason": "Explain why this attribution is being reversed."})
    row = CustomerCostAttribution.objects.select_for_update().get(pk=attribution_id)
    if row.status != CustomerCostAttributionStatus.POSTED:
        raise ValidationError({"status": "This attribution is already reversed."})
    _assert_open_period(row.attribution_date)
    row.status = CustomerCostAttributionStatus.REVERSED
    row.reversed_at = timezone.now()
    row.reversed_by = user
    row.reversal_reason = reason
    row.save(update_fields=["status", "reversed_at", "reversed_by", "reversal_reason", "updated_at"])
    record_finance_action(
        actor=user,
        action="customer_cost_attribution_reversed",
        entity_type="finance.CustomerCostAttribution",
        entity_id=row.pk,
        before_data={"status": CustomerCostAttributionStatus.POSTED, "amount": row.amount},
        after_data={"status": row.status},
        reason=reason,
    )
    return row


@transaction.atomic
def link_sale_customer(*, sale_id: int, customer_id: int | None, reason: str, user):
    sale = (
        Sales.objects.select_for_update(of=("self",))
        .select_related("customer")
        .get(pk=sale_id)
    )
    _assert_open_period(sale.sale_date.date(), "sale")
    customer = None
    if customer_id:
        customer = Customer.objects.get(pk=customer_id, is_active=True)
    before_id = sale.customer_id
    if before_id == (customer.pk if customer else None):
        return sale
    if before_id and len((reason or "").strip()) < 3:
        raise ValidationError({"reason": "Explain why the existing customer link is changing."})
    sale.customer = customer
    sale.save(update_fields=["customer", "updated_at"])
    record_finance_action(
        actor=user,
        action="sale_customer_link_changed",
        entity_type="poultry.Sales",
        entity_id=sale.pk,
        before_data={"customer_id": before_id, "buyer_name": sale.buyer_name},
        after_data={"customer_id": sale.customer_id, "buyer_name": sale.buyer_name},
        reason=reason,
    )
    return sale


def _production_cost_by_sale(sales: list[Sales]) -> tuple[dict[int, Decimal], dict[int, dict]]:
    batches = list({sale.batch_id: sale.batch for sale in sales}.values())
    basis = batch_survivor_cost_basis(batches)
    all_batch_sales = list(
        Sales.objects.filter(batch_id__in=[batch.pk for batch in batches])
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .filter(product_type__in=BIRD_PRODUCTS)
        .order_by("pk")
    )
    by_batch: dict[int, list[Sales]] = defaultdict(list)
    for sale in all_batch_sales:
        by_batch[sale.batch_id].append(sale)
    result: dict[int, Decimal] = {}
    for batch_id, batch_sales in by_batch.items():
        row = basis.get(batch_id)
        if not row or not row["survived_birds"] or row["cost_per_survived_bird"] is None:
            continue
        total_sold = sum((sale.quantity_sold for sale in batch_sales), 0)
        sold_cost = money(
            Decimal(row["total_production_cost"])
            * Decimal(total_sold)
            / Decimal(row["survived_birds"])
        )
        result.update(
            allocate_amount_by_driver(
                sold_cost,
                {sale.pk: Decimal(sale.quantity_sold) for sale in batch_sales},
            )
        )
    return result, basis


def _recommended_label(contribution: Decimal, margin, coverage_status: str) -> str:
    if contribution < ZERO:
        return CustomerContributionLabel.UNPROFITABLE
    if coverage_status != "complete" or margin is None:
        return CustomerContributionLabel.REVIEW
    if margin >= Decimal("40.00"):
        return CustomerContributionLabel.IDEAL
    if margin >= Decimal("20.00"):
        return CustomerContributionLabel.HEALTHY
    return CustomerContributionLabel.REVIEW


def customer_contribution_report(
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    customer_ids: set[int] | None = None,
    product_type: str = "",
    search: str = "",
) -> dict:
    today = timezone.localdate()
    date_to = date_to or today
    customer_ids = customer_ids or set()
    customers = Customer.objects.select_related("reviewed_by").all()
    if customer_ids:
        customers = customers.filter(pk__in=customer_ids)
    if search:
        customers = customers.filter(
            Q(display_name__icontains=search)
            | Q(contact_name__icontains=search)
            | Q(phone__icontains=search)
        )
    customers = list(customers)
    selected_ids = {customer.pk for customer in customers}

    period_sales = (
        Sales.objects.select_related("customer", "batch")
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .filter(sale_date__date__lte=date_to)
    )
    if date_from:
        period_sales = period_sales.filter(sale_date__date__gte=date_from)
    if product_type:
        period_sales = period_sales.filter(product_type=product_type)
    all_valid_period_sales = list(period_sales)
    selected_sales = [sale for sale in all_valid_period_sales if sale.customer_id in selected_ids]
    sale_ids = [sale.pk for sale in selected_sales]
    production_costs, production_basis = _production_cost_by_sale(selected_sales)

    payments = (
        SalePayment.objects.filter(
            sale_id__in=sale_ids,
            status=SalePaymentStatus.POSTED,
            payment_date__date__lte=date_to,
        )
        .values("sale_id")
        .annotate(total=Sum("amount"))
    )
    collected_by_sale = {row["sale_id"]: money(row["total"]) for row in payments}

    attributions = CustomerCostAttribution.objects.select_related(
        "customer", "sale", "batch", "created_by", "reversed_by"
    ).filter(
        customer_id__in=selected_ids,
        attribution_date__lte=date_to,
    ).filter(
        Q(status=CustomerCostAttributionStatus.POSTED)
        | Q(
            status=CustomerCostAttributionStatus.REVERSED,
            reversed_at__date__gt=date_to,
        )
    )
    if date_from:
        attributions = attributions.filter(attribution_date__gte=date_from)
    if product_type:
        attributions = attributions.filter(sale__product_type=product_type)
    attribution_rows = list(attributions)
    by_customer_attribution: dict[int, list[CustomerCostAttribution]] = defaultdict(list)
    for row in attribution_rows:
        by_customer_attribution[row.customer_id].append(row)

    sales_by_customer: dict[int, list[Sales]] = defaultdict(list)
    for sale in selected_sales:
        sales_by_customer[sale.customer_id].append(sale)
    farm_revenue = money(sum((sale.sale_total for sale in all_valid_period_sales), ZERO))
    unlinked_sales = [sale for sale in all_valid_period_sales if sale.customer_id is None]
    report_rows = []
    product_totals: dict[str, dict] = defaultdict(lambda: {"revenue": ZERO, "contribution": ZERO, "sales": 0})

    for customer in customers:
        customer_sales = sales_by_customer.get(customer.pk, [])
        customer_attributions = by_customer_attribution.get(customer.pk, [])
        revenue = money(sum((sale.sale_total for sale in customer_sales), ZERO))
        collected = money(sum((collected_by_sale.get(sale.pk, ZERO) for sale in customer_sales), ZERO))
        receivables = money(max(revenue - collected, ZERO))
        explicit_costs = {category: ZERO for category in CATEGORIES}
        actual_explicit = ZERO
        estimated_explicit = ZERO
        for attribution in customer_attributions:
            explicit_costs[attribution.category] = money(
                explicit_costs[attribution.category] + attribution.amount
            )
            if attribution.evidence_status == CustomerCostEvidenceStatus.ACTUAL:
                actual_explicit += attribution.amount
            else:
                estimated_explicit += attribution.amount
        production_delivery = money(sum((production_costs.get(sale.pk, ZERO) for sale in customer_sales), ZERO))
        missing_production_sales = [
            sale for sale in customer_sales
            if sale.product_type in BIRD_PRODUCTS and sale.pk not in production_costs
        ]
        costs = dict(explicit_costs)
        costs[CustomerCostCategory.DIRECT_DELIVERY] = money(
            costs[CustomerCostCategory.DIRECT_DELIVERY] + production_delivery
        )
        total_cost = money(sum(costs.values(), ZERO))
        contribution = money(revenue - total_cost)
        margin = percent(contribution, revenue)
        category_coverage = {}
        for category in CATEGORIES:
            category_rows = [row for row in customer_attributions if row.category == category]
            if category == CustomerCostCategory.DIRECT_DELIVERY and production_delivery > ZERO:
                status = "partial" if missing_production_sales else (
                    "estimated" if any(row.evidence_status == CustomerCostEvidenceStatus.ESTIMATED for row in category_rows) else "actual"
                )
            elif not category_rows:
                status = "not_attributed"
            elif any(row.evidence_status == CustomerCostEvidenceStatus.ESTIMATED for row in category_rows):
                status = "estimated"
            else:
                status = "actual"
            category_coverage[category] = status
        coverage_status = (
            "complete"
            if not missing_production_sales and all(value != "not_attributed" for value in category_coverage.values())
            else "incomplete"
        )
        recommended = _recommended_label(contribution, margin, coverage_status)
        products = []
        for key in sorted({sale.product_type for sale in customer_sales}):
            product_sales = [sale for sale in customer_sales if sale.product_type == key]
            product_revenue = money(sum((sale.sale_total for sale in product_sales), ZERO))
            product_delivery = money(sum((production_costs.get(sale.pk, ZERO) for sale in product_sales), ZERO))
            products.append({
                "product_type": key,
                "sale_count": len(product_sales),
                "quantity": sum(sale.quantity_sold for sale in product_sales),
                "revenue": product_revenue,
                "production_delivery_cost": product_delivery,
            })
            product_totals[key]["revenue"] += product_revenue
            product_totals[key]["contribution"] += money(product_revenue - product_delivery)
            product_totals[key]["sales"] += len(product_sales)
        report_rows.append({
            "customer_id": customer.pk,
            "customer_public_id": customer.public_id,
            "customer_name": customer.display_name,
            "customer_type": customer.customer_type,
            "is_active": customer.is_active,
            "sale_count": len(customer_sales),
            "revenue": revenue,
            "cash_collected": collected,
            "receivables": receivables,
            "direct_delivery_cost": costs[CustomerCostCategory.DIRECT_DELIVERY],
            "support_cost": costs[CustomerCostCategory.SUPPORT],
            "rework_cost": costs[CustomerCostCategory.REWORK],
            "acquisition_cost": costs[CustomerCostCategory.ACQUISITION],
            "production_cost_in_direct_delivery": production_delivery,
            "contribution": contribution,
            "margin_percent": margin,
            "customer_concentration_percent": percent(revenue, farm_revenue),
            "actual_explicit_cost": money(actual_explicit),
            "estimated_explicit_cost": money(estimated_explicit),
            "coverage_status": coverage_status,
            "category_coverage": category_coverage,
            "missing_production_sale_count": len(missing_production_sales),
            "recommended_label": recommended,
            "management_label": customer.contribution_label or None,
            "review_notes": customer.review_notes,
            "reviewed_at": customer.reviewed_at,
            "reviewed_by": (
                customer.reviewed_by.get_full_name() or customer.reviewed_by.username
                if customer.reviewed_by else None
            ),
            "products": products,
            "sales": [
                {
                    "id": sale.pk,
                    "sale_id": sale.sale_id,
                    "sale_date": sale.sale_date,
                    "batch_id": sale.batch_id,
                    "batch_code": sale.batch.batch_id,
                    "product_type": sale.product_type,
                    "quantity": sale.quantity_sold,
                    "revenue": sale.sale_total,
                    "cash_collected": collected_by_sale.get(sale.pk, ZERO),
                    "production_delivery_cost": production_costs.get(sale.pk),
                    "production_cost_status": "available" if sale.pk in production_costs else (
                        "not_applicable" if sale.product_type not in BIRD_PRODUCTS else "missing"
                    ),
                    "cost_basis": production_basis.get(sale.batch_id),
                }
                for sale in customer_sales
            ],
            "attributions": [
                {
                    "id": attribution.pk,
                    "date": attribution.attribution_date,
                    "category": attribution.category,
                    "amount": attribution.amount,
                    "source_type": attribution.source_type,
                    "source_id": attribution.source_id,
                    "source_label": attribution.source_label,
                    "source_href": _source_href(attribution),
                    "evidence_status": attribution.evidence_status,
                    "attribution_basis": attribution.attribution_basis,
                    "reason": attribution.reason,
                    "sale_id": attribution.sale_id,
                    "batch_id": attribution.batch_id,
                    "created_by": (
                        attribution.created_by.get_full_name() or attribution.created_by.username
                        if attribution.created_by else None
                    ),
                }
                for attribution in customer_attributions
            ],
        })

    report_rows.sort(key=lambda row: (-row["revenue"], row["customer_name"].lower(), row["customer_id"]))
    summary_costs = {
        category: money(sum((row[f"{category}_cost"] for row in report_rows), ZERO))
        for category in CATEGORIES
    }
    summary_revenue = money(sum((row["revenue"] for row in report_rows), ZERO))
    summary_contribution = money(summary_revenue - sum(summary_costs.values(), ZERO))
    return {
        "date_from": date_from,
        "date_to": date_to,
        "product_type": product_type or None,
        "basis": (
            "Recognized, non-cancelled sales are revenue. Posted collections are shown separately. "
            "Direct delivery includes the canonical survived-bird production-cost share plus explicit delivery costs."
        ),
        "formula": "Revenue - Direct Delivery Cost - Support Cost - Rework Cost - Acquisition Cost",
        "summary": {
            "customer_count": len(report_rows),
            "revenue": summary_revenue,
            "cash_collected": money(sum((row["cash_collected"] for row in report_rows), ZERO)),
            "receivables": money(sum((row["receivables"] for row in report_rows), ZERO)),
            "direct_delivery_cost": summary_costs[CustomerCostCategory.DIRECT_DELIVERY],
            "support_cost": summary_costs[CustomerCostCategory.SUPPORT],
            "rework_cost": summary_costs[CustomerCostCategory.REWORK],
            "acquisition_cost": summary_costs[CustomerCostCategory.ACQUISITION],
            "contribution": summary_contribution,
            "margin_percent": percent(summary_contribution, summary_revenue),
            "incomplete_customer_count": sum(row["coverage_status"] != "complete" for row in report_rows),
            "unlinked_sale_count": len(unlinked_sales),
            "unlinked_revenue": money(sum((sale.sale_total for sale in unlinked_sales), ZERO)),
        },
        "customers": report_rows,
        "products": [
            {
                "product_type": key,
                "sale_count": value["sales"],
                "revenue": money(value["revenue"]),
                "contribution_before_explicit_customer_costs": money(value["contribution"]),
            }
            for key, value in sorted(product_totals.items())
        ],
    }


def customer_cost_source_candidates(*, search: str = "", limit: int = 100) -> list[dict]:
    rows = []
    expenditures = Expenditure.objects.filter(
        status=ExpenditureStatus.POSTED,
        reversed_at__isnull=True,
        cost_allocations__isnull=True,
    ).order_by("-expenditure_date", "-pk")
    if search:
        expenditures = expenditures.filter(
            Q(description__icontains=search)
            | Q(expenditure_reference__icontains=search)
            | Q(payee__icontains=search)
        )
    used_by_key = {
        row["economic_source_key"]: money(row["total"])
        for row in CustomerCostAttribution.objects.filter(
            status=CustomerCostAttributionStatus.POSTED
        ).values("economic_source_key").annotate(total=Sum("amount"))
    }
    for expenditure in expenditures[:limit]:
        key = f"expenditure:{expenditure.pk}"
        available = money(expenditure.amount - used_by_key.get(key, ZERO))
        if available <= ZERO:
            continue
        rows.append({
            "source_type": CustomerCostSourceType.EXPENDITURE,
            "source_id": expenditure.pk,
            "date": expenditure.expenditure_date,
            "label": f"{expenditure.expenditure_reference} · {expenditure.description}",
            "recognized_amount": money(expenditure.amount),
            "available_amount": available,
        })
    remaining = max(limit - len(rows), 0)
    if remaining:
        payroll_entries = PayrollEntry.objects.select_related(
            "employee", "employee__user", "accounting_period"
        ).filter(expenditure__isnull=True).order_by("-accounting_period__period_end", "-pk")
        if search:
            payroll_entries = payroll_entries.filter(
                Q(employee__employee_number__icontains=search)
                | Q(employee__user__username__icontains=search)
                | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
            )
        for payroll in payroll_entries[:remaining]:
            key = f"payroll:{payroll.pk}"
            available = money(payroll.total_employer_cost - used_by_key.get(key, ZERO))
            if available <= ZERO:
                continue
            rows.append({
                "source_type": CustomerCostSourceType.PAYROLL,
                "source_id": payroll.pk,
                "date": payroll.accounting_period.period_end,
                "label": f"Payroll #{payroll.pk} · {payroll.employee}",
                "recognized_amount": money(payroll.total_employer_cost),
                "available_amount": available,
            })
    remaining = max(limit - len(rows), 0)
    if remaining:
        labour_rows = AdHocLabourPayment.objects.filter(
            expenditure__isnull=True,
            workflow_status__in=[
                LabourWorkflowStatus.POSTED,
                LabourWorkflowStatus.PARTIALLY_PAID,
                LabourWorkflowStatus.PAID,
            ],
            reversed_at__isnull=True,
        ).order_by("-work_date", "-pk")
        if search:
            labour_rows = labour_rows.filter(
                Q(worker_name__icontains=search)
                | Q(task_description__icontains=search)
            )
        for labour in labour_rows[:remaining]:
            key = f"labour:{labour.pk}"
            available = money(labour.payment_amount - used_by_key.get(key, ZERO))
            if available <= ZERO:
                continue
            rows.append({
                "source_type": CustomerCostSourceType.LABOUR,
                "source_id": labour.pk,
                "date": labour.work_date,
                "label": f"Labour #{labour.pk} · {labour.worker_name} · {labour.task_description}",
                "recognized_amount": money(labour.payment_amount),
                "available_amount": available,
            })
    return rows
