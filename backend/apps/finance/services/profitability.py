from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from rest_framework.exceptions import ValidationError


from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from apps.poultry.models import (
    Batch,
    BatchStatus,
    InputCosts,
    Mortality,
    PaymentStatus,
    ProductType,
    Sales,
)

from ..models import (
    FundingSource,
    FundingSourceType,
    FundingReceipt,
    FundingReceiptStatus,
    SalePayment,
    SalePaymentStatus,
)


from ..models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    BatchProfitabilitySnapshot,
    ConsumableUsage,
    ConsumableUsageScope,
    CostAllocation,
    CostScope,
    SharedExpense,
    SharedExpenseScope,
)
from apps.poultry.services.batch_lifecycle import BirdBalance, calculate_bird_balance
from .warnings import finance_warning


ZERO = Decimal("0.00")
PRE_PRODUCTION_STATUSES = {
    BatchStatus.BOOKED,
    BatchStatus.DELIVERED,
}


def money(value: Decimal | int | None) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == ZERO:
        return None
    return (numerator * Decimal("100") / denominator).quantize(Decimal("0.01"))


def _sum_decimal(queryset, expression) -> Decimal:
    return money(queryset.aggregate(total=Sum(expression))["total"])


def input_cost_total(batch: Batch) -> Decimal:
    expression = ExpressionWrapper(
        F("quantity") * F("unit") * F("unit_cost"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    authoritative = money(
        CostAllocation.objects.filter(
            batch=batch,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure__status=ExpenditureStatus.POSTED,
            expenditure__accounting_nature=AccountingNature.DIRECT_COST,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    transitional_legacy = _sum_decimal(
        InputCosts.objects.filter(batch=batch, expenditure__isnull=True),
        expression,
    )
    return money(authoritative + transitional_legacy)


def valid_sales(batch: Batch):
    return Sales.objects.filter(batch=batch).exclude(
        payment_status=PaymentStatus.CANCELLED
    )


def sales_revenue(batch: Batch) -> Decimal:
    expression = ExpressionWrapper(
        F("quantity_sold") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    return _sum_decimal(valid_sales(batch), expression)


def cash_collected(batch: Batch) -> Decimal:
    return money(
        SalePayment.objects.filter(
            sale__batch=batch,
            sale__payment_status__in=[
                PaymentStatus.PAID,
                PaymentStatus.PARTIAL,
                PaymentStatus.UNPAID,
                PaymentStatus.LOAN,
            ],
            status=SalePaymentStatus.POSTED,
        ).aggregate(total=Sum("amount"))["total"]
    )


def receivables(batch: Batch) -> Decimal:
    return money(sales_revenue(batch) - cash_collected(batch))


def direct_labour_total(batch: Batch) -> Decimal:
    return money(
        AdHocLabourPayment.objects.filter(
            batch=batch,
            cost_scope=CostScope.BATCH_DIRECT,
        ).aggregate(total=Sum("payment_amount"))["total"]
    )


def direct_production_expense_total(batch: Batch) -> Decimal:
    return money(
        SharedExpense.objects.filter(
            directly_assigned_batch=batch,
            scope=SharedExpenseScope.SHARED_PRODUCTION,
        ).aggregate(total=Sum("amount"))["total"]
    )


def direct_consumable_usage_total(batch: Batch) -> Decimal:
    return money(
        ConsumableUsage.objects.filter(
            batch=batch,
            usage_scope=ConsumableUsageScope.BATCH_DIRECT,
        ).aggregate(total=Sum("recognized_cost"))["total"]
    )


def allocated_production_total(batch: Batch) -> Decimal:
    payroll = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.PAYROLL,
    )
    shared_labour = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.AD_HOC_LABOUR,
        ad_hoc_labour_payment__cost_scope=CostScope.SHARED_PRODUCTION,
    )
    shared_expenses = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.SHARED_EXPENSE,
        shared_expense__scope=SharedExpenseScope.SHARED_PRODUCTION,
        shared_expense__directly_assigned_batch__isnull=True,
    )
    consumables = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.CONSUMABLE_USAGE,
        consumable_usage__usage_scope=ConsumableUsageScope.SHARED_PRODUCTION,
    )
    depreciation = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.DEPRECIATION,
    )
    indirect_expenditures = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.EXPENDITURE,
        expenditure__status=ExpenditureStatus.POSTED,
        expenditure__accounting_nature=AccountingNature.INDIRECT_OPERATING_EXPENSE,
    )
    return money(
        payroll.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(shared_labour.aggregate(total=Sum("allocated_amount"))["total"]) + money(
        shared_expenses.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        consumables.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        depreciation.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        indirect_expenditures.aggregate(total=Sum("allocated_amount"))["total"]
    )


def selling_cost_total(batch: Batch) -> Decimal:
    direct_labour = AdHocLabourPayment.objects.filter(
        batch=batch,
        cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
    )
    shared_labour = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.AD_HOC_LABOUR,
        ad_hoc_labour_payment__cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
        ad_hoc_labour_payment__batch__isnull=True,
    )
    direct_expenses = SharedExpense.objects.filter(
        directly_assigned_batch=batch,
        scope=SharedExpenseScope.SELLING_EXPENSE,
    )
    shared_expenses = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.SHARED_EXPENSE,
        shared_expense__scope=SharedExpenseScope.SELLING_EXPENSE,
        shared_expense__directly_assigned_batch__isnull=True,
    )
    direct_consumables = ConsumableUsage.objects.filter(
        batch=batch,
        usage_scope=ConsumableUsageScope.SELLING_AND_DISTRIBUTION,
    )
    shared_consumables = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.CONSUMABLE_USAGE,
        consumable_usage__usage_scope=(
            ConsumableUsageScope.SELLING_AND_DISTRIBUTION
        ),
        consumable_usage__batch__isnull=True,
    )
    return (
        money(direct_labour.aggregate(total=Sum("payment_amount"))["total"])
        + money(shared_labour.aggregate(total=Sum("allocated_amount"))["total"])
        + money(direct_expenses.aggregate(total=Sum("amount"))["total"])
        + money(shared_expenses.aggregate(total=Sum("allocated_amount"))["total"])
        + money(direct_consumables.aggregate(total=Sum("recognized_cost"))["total"])
        + money(shared_consumables.aggregate(total=Sum("allocated_amount"))["total"])
            )


def ensure_batch_funding_source(batch: Batch) -> FundingSource:
    """
    Auto create (or get) a BATCH_COLLECTION FundingSource for the batch.
    Never store manual balance; computed from cash_collected - used.
    Safe to call multiple times.
    """
    fs, created = FundingSource.objects.get_or_create(
        source_type=FundingSourceType.BATCH_COLLECTION,
        batch=batch,
        defaults={
            "description": f"Batch {batch.batch_id} sales collections",
        },
    )
    return fs


def _build_batch_profitability(
    batch: Batch,
    *,
    balance: BirdBalance,
    revenue: Decimal,
    collected: Decimal,
    outstanding: Decimal,
    direct_cost: Decimal,
    allocated_cost: Decimal,
    selling_cost: Decimal,
) -> dict:
    is_pre_production = batch.status in PRE_PRODUCTION_STATUSES
    total_production_cost = direct_cost + allocated_cost
    gross_profit = revenue - total_production_cost
    fully_loaded_profit = gross_profit - selling_cost
    bird_units_sold = balance.valid_bird_units_sold
    remaining = max(balance.remaining_live_birds, 0)
    provisional_saleable_birds = bird_units_sold + remaining
    is_final = batch.status == BatchStatus.CLOSED

    provisional_cost_per_saleable_bird = None
    if provisional_saleable_birds:
        provisional_cost_per_saleable_bird = money(
            total_production_cost / Decimal(provisional_saleable_birds)
        )

    final_cost_per_bird_sold = None
    if is_final and bird_units_sold:
        final_cost_per_bird_sold = money(
            total_production_cost / Decimal(bird_units_sold)
        )

    additional_revenue_required = max(
        total_production_cost + selling_cost - revenue,
        ZERO,
    )
    break_even_price = None
    if remaining:
        break_even_price = money(additional_revenue_required / remaining)

    return {
        "batch": batch.pk,
        "batch_id": batch.batch_id,
        "status": batch.status,
        "profitability_status": (
            "booked"
            if is_pre_production
            else "final" if is_final else "provisional"
        ),
        "included_in_portfolio_summary": not is_pre_production,
        "revenue": revenue,
        "cash_collected": collected,
        "accounts_receivable": outstanding,
        "direct_batch_cost": direct_cost,
        "allocated_production_cost": allocated_cost,
        "total_production_cost": total_production_cost,
        "batch_gross_profit": gross_profit,
        "batch_gross_margin_percent": percent(gross_profit, revenue),
        "selling_cost": selling_cost,
        "allocated_administration_cost": ZERO,
        "fully_loaded_batch_profit": fully_loaded_profit,
        "fully_loaded_margin_percent": percent(fully_loaded_profit, revenue),
        "birds_placed": balance.initial_birds,
        "valid_bird_units_sold": bird_units_sold,
        "remaining_live_birds": remaining,
        "profit_per_bird_sold": (
            money(gross_profit / Decimal(bird_units_sold))
            if bird_units_sold
            else None
        ),
        "mortality": balance.mortality,
        "mortality_rate_percent": percent(
            Decimal(balance.mortality),
            Decimal(balance.initial_birds),
        ),
        "collection_rate_percent": percent(collected, revenue),
        "provisional_saleable_birds": provisional_saleable_birds,
        "provisional_cost_per_saleable_bird": provisional_cost_per_saleable_bird,
        "final_cost_per_bird_sold": final_cost_per_bird_sold,
        "break_even_selling_price_per_remaining_bird": break_even_price,
        "additional_revenue_required_to_break_even": additional_revenue_required,
        "active_batch_cost_exposure": (
            total_production_cost
            if not is_final and not is_pre_production
            else ZERO
        ),
    }


def _apply_final_snapshot(
    row: dict,
    snapshot: BatchProfitabilitySnapshot | None,
) -> dict:
    """Use the immutable close snapshot as the authoritative final result."""

    if snapshot is None:
        if row["status"] == BatchStatus.CLOSED:
            row["profitability_status"] = "pending_finalization"
            row["calculation_basis"] = "current_unfinalized"
        return row

    revenue = money(snapshot.revenue)
    collected = money(snapshot.cash_collected)
    receivable = money(snapshot.accounts_receivable)
    direct_cost = money(snapshot.direct_batch_cost)
    allocated_cost = money(snapshot.allocated_production_cost)
    production_cost = money(snapshot.total_production_cost)
    gross_profit = money(snapshot.batch_gross_profit)
    fully_loaded_profit = money(snapshot.fully_loaded_batch_profit)
    selling_cost = money(gross_profit - fully_loaded_profit)
    birds_sold = snapshot.valid_bird_units_sold
    remaining = snapshot.remaining_live_birds
    saleable_birds = birds_sold + remaining
    additional_revenue_required = max(
        production_cost + selling_cost - revenue,
        ZERO,
    )

    row.update(
        {
            "status": snapshot.status,
            "profitability_status": "final",
            "calculation_basis": "final_snapshot",
            "revenue": revenue,
            "cash_collected": collected,
            "accounts_receivable": receivable,
            "direct_batch_cost": direct_cost,
            "allocated_production_cost": allocated_cost,
            "total_production_cost": production_cost,
            "batch_gross_profit": gross_profit,
            "batch_gross_margin_percent": percent(gross_profit, revenue),
            "selling_cost": selling_cost,
            "fully_loaded_batch_profit": fully_loaded_profit,
            "fully_loaded_margin_percent": percent(fully_loaded_profit, revenue),
            "valid_bird_units_sold": birds_sold,
            "remaining_live_birds": remaining,
            "profit_per_bird_sold": (
                money(gross_profit / Decimal(birds_sold)) if birds_sold else None
            ),
            "provisional_saleable_birds": saleable_birds,
            "provisional_cost_per_saleable_bird": (
                money(production_cost / Decimal(saleable_birds))
                if saleable_birds
                else None
            ),
            "final_cost_per_bird_sold": (
                money(production_cost / Decimal(birds_sold)) if birds_sold else None
            ),
            "break_even_selling_price_per_remaining_bird": (
                money(additional_revenue_required / Decimal(remaining))
                if remaining
                else None
            ),
            "additional_revenue_required_to_break_even": additional_revenue_required,
            "active_batch_cost_exposure": ZERO,
        }
    )
    return row


def batch_profitability(batch: Batch) -> dict:
    direct_cost = (
        input_cost_total(batch)
        + direct_labour_total(batch)
        + direct_production_expense_total(batch)
        + direct_consumable_usage_total(batch)
    )
    collected = cash_collected(batch)
    row = _build_batch_profitability(
        batch,
        balance=calculate_bird_balance(batch),
        revenue=sales_revenue(batch),
        collected=collected,
        outstanding=receivables(batch),
        direct_cost=direct_cost,
        allocated_cost=allocated_production_total(batch),
        selling_cost=selling_cost_total(batch),
    )
    # Add new revenue utilization fields
    row["available_batch_cash"] = str(available_batch_cash(batch))
    row["cash_used_from_batch"] = str(cash_used_from_batch(batch))

    snapshot = None
    if batch.status == BatchStatus.CLOSED:
        snapshot = BatchProfitabilitySnapshot.objects.filter(
            batch=batch,
            final=True,
            accounting_period__isnull=False,
        ).first()
    return _apply_final_snapshot(row, snapshot)


def _money_by_group(queryset, group_field: str, expression) -> dict[int, Decimal]:
    return {
        row[group_field]: money(row["total"])
        for row in queryset.values(group_field).annotate(total=Sum(expression))
    }


def _portfolio_profitability_rows(batches: list[Batch]) -> list[dict]:
    """Build per-batch rows with a fixed number of grouped database queries."""

    if not batches:
        return []

    batch_ids = [batch.pk for batch in batches]
    final_snapshots = {
        snapshot.batch_id: snapshot
        for snapshot in BatchProfitabilitySnapshot.objects.filter(
            batch_id__in=batch_ids,
            final=True,
            accounting_period__isnull=False,
        )
    }
    sales_expression = ExpressionWrapper(
        F("quantity_sold") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    sales_rows = (
        Sales.objects.filter(batch_id__in=batch_ids)
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .values("batch_id")
        .annotate(
            revenue=Sum(sales_expression),
            birds_sold=Sum(
                "quantity_sold",
                filter=Q(
                    product_type__in=[
                        ProductType.LIVE_CHICKEN,
                        ProductType.DRESSED_CHICKEN,
                    ]
                ),
            ),
        )
    )
    collections_by_batch = {
        row["sale__batch_id"]: money(row["total"])
        for row in SalePayment.objects.filter(
            sale__batch_id__in=batch_ids,
            status=SalePaymentStatus.POSTED,
        )
        .exclude(sale__payment_status=PaymentStatus.CANCELLED)
        .values("sale__batch_id")
        .annotate(total=Sum("amount"))
    }
    sales_by_batch = {
        row["batch_id"]: {
            "revenue": money(row["revenue"]),
            "collected": collections_by_batch.get(row["batch_id"], ZERO),
            "outstanding": money(
                money(row["revenue"])
                - collections_by_batch.get(row["batch_id"], ZERO)
            ),
            "birds_sold": int(row["birds_sold"] or 0),
        }
        for row in sales_rows
    }
    mortality_by_batch = {
        row["batch_id"]: int(row["total"] or 0)
        for row in Mortality.objects.filter(batch_id__in=batch_ids)
        .values("batch_id")
        .annotate(total=Sum("quantity_dead"))
    }

    input_expression = ExpressionWrapper(
        F("quantity") * F("unit") * F("unit_cost"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    input_costs = _money_by_group(
        InputCosts.objects.filter(batch_id__in=batch_ids),
        "batch_id",
        input_expression,
    )
    direct_labour = _money_by_group(
        AdHocLabourPayment.objects.filter(
            batch_id__in=batch_ids,
            cost_scope=CostScope.BATCH_DIRECT,
        ),
        "batch_id",
        "payment_amount",
    )
    direct_expenses = _money_by_group(
        SharedExpense.objects.filter(
            directly_assigned_batch_id__in=batch_ids,
            scope=SharedExpenseScope.SHARED_PRODUCTION,
        ),
        "directly_assigned_batch_id",
        "amount",
    )
    consumable_rows = ConsumableUsage.objects.filter(
        batch_id__in=batch_ids,
        usage_scope__in=[
            ConsumableUsageScope.BATCH_DIRECT,
            ConsumableUsageScope.SELLING_AND_DISTRIBUTION,
        ],
    ).values("batch_id").annotate(
        direct_total=Sum(
            "recognized_cost",
            filter=Q(usage_scope=ConsumableUsageScope.BATCH_DIRECT),
        ),
        selling_total=Sum(
            "recognized_cost",
            filter=Q(
                usage_scope=ConsumableUsageScope.SELLING_AND_DISTRIBUTION
            ),
        ),
    )
    direct_consumables = {
        row["batch_id"]: money(row["direct_total"])
        for row in consumable_rows
    }
    direct_selling_consumables = {
        row["batch_id"]: money(row["selling_total"])
        for row in consumable_rows
    }

    production_allocation_scope = (
        Q(source_type=AllocationSourceType.PAYROLL)
        | Q(
            source_type=AllocationSourceType.AD_HOC_LABOUR,
            ad_hoc_labour_payment__cost_scope=CostScope.SHARED_PRODUCTION,
        )
        | Q(
            source_type=AllocationSourceType.SHARED_EXPENSE,
            shared_expense__scope=SharedExpenseScope.SHARED_PRODUCTION,
            shared_expense__directly_assigned_batch__isnull=True,
        )
        | Q(
            source_type=AllocationSourceType.CONSUMABLE_USAGE,
            consumable_usage__usage_scope=ConsumableUsageScope.SHARED_PRODUCTION,
        )
        | Q(source_type=AllocationSourceType.DEPRECIATION)
    )
    allocated_production = _money_by_group(
        CostAllocation.objects.filter(batch_id__in=batch_ids).filter(
            production_allocation_scope
        ),
        "batch_id",
        "allocated_amount",
    )

    direct_selling_labour = _money_by_group(
        AdHocLabourPayment.objects.filter(
            batch_id__in=batch_ids,
            cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
        ),
        "batch_id",
        "payment_amount",
    )
    direct_selling_expenses = _money_by_group(
        SharedExpense.objects.filter(
            directly_assigned_batch_id__in=batch_ids,
            scope=SharedExpenseScope.SELLING_EXPENSE,
        ),
        "directly_assigned_batch_id",
        "amount",
    )
    shared_selling_scope = Q(
        source_type=AllocationSourceType.AD_HOC_LABOUR,
        ad_hoc_labour_payment__cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
        ad_hoc_labour_payment__batch__isnull=True,
    ) | Q(
        source_type=AllocationSourceType.SHARED_EXPENSE,
        shared_expense__scope=SharedExpenseScope.SELLING_EXPENSE,
        shared_expense__directly_assigned_batch__isnull=True,
    ) | Q(
        source_type=AllocationSourceType.CONSUMABLE_USAGE,
        consumable_usage__usage_scope=(
            ConsumableUsageScope.SELLING_AND_DISTRIBUTION
        ),
        consumable_usage__batch__isnull=True,
    )
    allocated_selling = _money_by_group(
        CostAllocation.objects.filter(batch_id__in=batch_ids).filter(
            shared_selling_scope
        ),
        "batch_id",
        "allocated_amount",
    )

    rows = []
    for batch in batches:
        batch_sales = sales_by_batch.get(batch.pk, {})
        birds_sold = int(batch_sales.get("birds_sold", 0))
        mortality = mortality_by_batch.get(batch.pk, 0)
        balance = BirdBalance(
            initial_birds=batch.quantity,
            valid_bird_units_sold=birds_sold,
            mortality=mortality,
            remaining_live_birds=batch.quantity - birds_sold - mortality,
        )
        direct_cost = (
            input_costs.get(batch.pk, ZERO)
            + direct_labour.get(batch.pk, ZERO)
            + direct_expenses.get(batch.pk, ZERO)
            + direct_consumables.get(batch.pk, ZERO)
        )
        selling_cost = (
            direct_selling_labour.get(batch.pk, ZERO)
            + direct_selling_expenses.get(batch.pk, ZERO)
            + direct_selling_consumables.get(batch.pk, ZERO)
            + allocated_selling.get(batch.pk, ZERO)
        )
        rows.append(
            _apply_final_snapshot(
                _build_batch_profitability(
                    batch,
                    balance=balance,
                    revenue=batch_sales.get("revenue", ZERO),
                    collected=batch_sales.get("collected", ZERO),
                    outstanding=batch_sales.get("outstanding", ZERO),
                    direct_cost=money(direct_cost),
                    allocated_cost=allocated_production.get(batch.pk, ZERO),
                    selling_cost=money(selling_cost),
                ),
                (
                    final_snapshots.get(batch.pk)
                    if batch.status == BatchStatus.CLOSED
                    else None
                ),
            )
        )

    return rows


def batch_portfolio_report(batches: Iterable[Batch]) -> dict:
    """Aggregate lifecycle management profitability for selected poultry batches.

    Monetary amounts are summed from each batch's existing direct costs and stored
    allocations. Ratios are then recalculated from the portfolio totals so that a
    small flock does not carry the same weight as a large flock.
    """

    rows = _portfolio_profitability_rows(list(batches))
    included_rows = [row for row in rows if row["included_in_portfolio_summary"]]

    def total(field: str) -> Decimal:
        return money(sum((row[field] for row in included_rows), ZERO))

    revenue = total("revenue")
    collected = total("cash_collected")
    direct_cost = total("direct_batch_cost")
    allocated_cost = total("allocated_production_cost")
    production_cost = total("total_production_cost")
    gross_profit = total("batch_gross_profit")
    selling_cost = total("selling_cost")
    administration_cost = total("allocated_administration_cost")
    contribution_after_selling = total("fully_loaded_batch_profit")
    receivable = total("accounts_receivable")
    active_exposure = total("active_batch_cost_exposure")

    birds_placed = sum(row["birds_placed"] for row in included_rows)
    birds_sold = sum(row["valid_bird_units_sold"] for row in included_rows)
    remaining_birds = sum(row["remaining_live_birds"] for row in included_rows)
    mortality = sum(row["mortality"] for row in included_rows)
    saleable_birds = birds_sold + remaining_birds
    additional_revenue_required = max(
        production_cost + selling_cost - revenue,
        ZERO,
    )

    statuses = {row["profitability_status"] for row in rows}
    if not statuses:
        portfolio_status = "empty"
    elif len(statuses) == 1:
        portfolio_status = statuses.pop()
    else:
        portfolio_status = "mixed"

    warnings = [
        finance_warning(
            code="lifecycle_management_cost_basis",
            severity="info",
            message=(
                "Lifecycle management-cost view: active batches remain provisional; "
                "closed batches become final when their accounting period is closed."
            ),
        ),
        finance_warning(
            code="central_costs_excluded",
            severity="info",
            message=(
                "Central administration, finance costs and tax are not allocated to "
                "batches, so contribution after selling costs is not whole-farm net profit."
            ),
        ),
        finance_warning(
            code="selling_payroll_excluded",
            severity="info",
            message=(
                "Employee payroll selling percentages remain in the monthly whole-farm "
                "report and are not yet allocated to individual batches."
            ),
        ),
        finance_warning(
            code="ias_41_fair_value_not_recorded",
            severity="info",
            message=(
                "Living-bird fair value is not recorded; this report is not an IAS 41 "
                "biological-asset valuation."
            ),
        ),
        finance_warning(
            code="input_cost_recognition_basis",
            severity="info",
            message=(
                "Poultry InputCosts are recognized as batch costs when entered; unused "
                "feed or medicine is deferred only when purchased and issued through "
                "finance consumable lots."
            ),
        ),
        finance_warning(
            code="cash_receipt_ledger_limitation",
            severity="info",
            message=(
                "Cash collected reflects the amount currently stored on each sale, not "
                "a dated receipt ledger."
            ),
        ),
        finance_warning(
            code="closed_batch_snapshot_controls",
            severity="info",
            message=(
                "Closed batches use their stored final snapshot. Corrections require a "
                "controlled reopen or reversal workflow so finalized profit does not drift."
            ),
        ),
    ]
    if any(row["profitability_status"] == "booked" for row in rows):
        warnings.append(
            finance_warning(
                code="booked_batches_excluded",
                severity="warning",
                message=(
                    "Booked or delivered flocks are excluded from the combined performance "
                    "summary until delivery is confirmed."
                ),
            )
        )
    if any(row["profitability_status"] == "pending_finalization" for row in rows):
        warnings.append(
            finance_warning(
                code="pending_batch_finalization",
                severity="warning",
                message=(
                    "A closed flock is awaiting accounting-period close and allocation "
                    "reconciliation before its immutable final snapshot is created."
                ),
            )
        )

    return {
        "analysis_basis": "lifecycle_management_cost",
        "calculation_version": "batch-portfolio-v1",
        "selected_batch_ids": [row["batch"] for row in rows],
        "selected_batch_count": len(rows),
        "included_batch_count": len(included_rows),
        "profitability_status": portfolio_status,
        "summary": {
            "revenue": revenue,
            "cash_collected": collected,
            "accounts_receivable": receivable,
            "direct_batch_cost": direct_cost,
            "allocated_production_cost": allocated_cost,
            "total_production_cost": production_cost,
            "batch_gross_profit": gross_profit,
            "batch_gross_margin_percent": percent(gross_profit, revenue),
            "selling_cost": selling_cost,
            "allocated_administration_cost": administration_cost,
            "fully_loaded_batch_profit": contribution_after_selling,
            "fully_loaded_margin_percent": percent(
                contribution_after_selling,
                revenue,
            ),
            "birds_placed": birds_placed,
            "valid_bird_units_sold": birds_sold,
            "remaining_live_birds": remaining_birds,
            "mortality": mortality,
            "mortality_rate_percent": percent(
                Decimal(mortality),
                Decimal(birds_placed),
            ),
            "collection_rate_percent": percent(collected, revenue),
            "profit_per_bird_sold": (
                money(gross_profit / Decimal(birds_sold)) if birds_sold else None
            ),
            "production_cost_per_saleable_bird": (
                money(production_cost / Decimal(saleable_birds))
                if saleable_birds
                else None
            ),
            "break_even_selling_price_per_remaining_bird": (
                money(additional_revenue_required / Decimal(remaining_birds))
                if remaining_birds
                else None
            ),
            "additional_revenue_required_to_break_even": additional_revenue_required,
            "active_batch_cost_exposure": active_exposure,
        },
        "results": rows,
        "warnings": warnings,
    }


def create_final_snapshot(
    batch: Batch,
    *,
    accounting_period: AccountingPeriod,
    generated_by=None,
) -> BatchProfitabilitySnapshot:
    data = batch_profitability(batch)
    snapshot, _ = BatchProfitabilitySnapshot.objects.get_or_create(
        batch=batch,
        final=True,
        defaults={
            "accounting_period": accounting_period,
            "status": data["status"],
            "revenue": data["revenue"],
            "cash_collected": data["cash_collected"],
            "accounts_receivable": data["accounts_receivable"],
            "direct_batch_cost": data["direct_batch_cost"],
            "allocated_production_cost": data["allocated_production_cost"],
            "total_production_cost": data["total_production_cost"],
            "batch_gross_profit": data["batch_gross_profit"],
            "fully_loaded_batch_profit": data["fully_loaded_batch_profit"],
            "valid_bird_units_sold": data["valid_bird_units_sold"],
            "remaining_live_birds": data["remaining_live_birds"],
            "finalized_at": timezone.now(),
            "generated_by": generated_by,
        },
    )
    if batch.profitability_finalized_at is None:
        batch.profitability_finalized_at = snapshot.finalized_at
        batch.save(update_fields=["profitability_finalized_at", "updated_at"])
    return snapshot


# =============================================================================
# Revenue Utilization / Batch Cash Tracking (Funding dimension)
# =============================================================================

from ..models import (
    AccountingNature,
    Expenditure,
    ExpenditureStatus,
    FundingAllocation,
    FundingSource,
    FundingSourceType,
)


def batch_cash_collected(batch: Batch) -> Decimal:
    """Cash actually received from this batch's sales (excludes cancelled)."""
    return cash_collected(batch)


def cash_used_from_batch(batch: Batch) -> Decimal:
    """
    Total amount of this batch's collected revenue that has been allocated
    as funding to posted expenditures.
    """
    allocations = FundingAllocation.objects.filter(
        funding_source__source_type=FundingSourceType.BATCH_COLLECTION,
        funding_source__batch=batch,
        expenditure__status=ExpenditureStatus.POSTED,
    )
    total = allocations.aggregate(total=Sum("amount"))["total"] or ZERO
    return money(total)


def available_batch_cash(batch: Batch) -> Decimal:
    """
    How much of the cash collected from this batch is still available
    (has not been allocated as funding to other expenditures).
    """
    collected = batch_cash_collected(batch)
    used = cash_used_from_batch(batch)
    return money(collected - used)


def available_funding_source_cash(source: FundingSource) -> Decimal:
    if source.source_type == FundingSourceType.BATCH_COLLECTION:
        return available_batch_cash(source.batch) if source.batch_id else ZERO
    received = money(
        FundingReceipt.objects.filter(
            funding_source=source,
            status=FundingReceiptStatus.POSTED,
        ).aggregate(total=Sum("amount"))["total"]
    )
    used = money(
        FundingAllocation.objects.filter(
            funding_source=source,
            expenditure__status=ExpenditureStatus.POSTED,
        ).aggregate(total=Sum("amount"))["total"]
    )
    return money(received - used)


def batch_revenue_utilization(batch: Batch) -> dict:
    """
    Returns a summary of how a batch's collected revenue has been used.
    """
    collected = batch_cash_collected(batch)
    refunds = money(
        SalePayment.objects.filter(
            sale__batch=batch,
            status=SalePaymentStatus.REVERSED,
        ).aggregate(total=Sum("amount"))["total"]
    )
    gross_collections = money(collected + refunds)
    used = cash_used_from_batch(batch)
    available = money(collected - used)

    # Breakdown by category and nature from posted funding allocations
    posted_allocs = FundingAllocation.objects.filter(
        funding_source__source_type=FundingSourceType.BATCH_COLLECTION,
        funding_source__batch=batch,
        expenditure__status=ExpenditureStatus.POSTED,
    ).select_related("expenditure", "expenditure__category", "funding_source").order_by(
        "allocation_date", "created_at", "pk"
    )

    by_category = {}
    by_nature = {}
    beneficiaries = set()
    transactions = []
    running_cash = collected

    for alloc in posted_allocs:
        exp = alloc.expenditure
        category_label = exp.category.name if exp.category_id else "Uncategorized"
        by_category[category_label] = by_category.get(category_label, ZERO) + alloc.amount
        by_nature[exp.accounting_nature] = by_nature.get(exp.accounting_nature, ZERO) + alloc.amount
        beneficiary = exp.beneficiary_detail or exp.beneficiary_type or exp.farm_module
        if beneficiary:
            beneficiaries.add(beneficiary)
        running_cash = money(running_cash - alloc.amount)
        transactions.append(
            {
                "allocation_id": alloc.pk,
                "expenditure_id": exp.pk,
                "expenditure_reference": exp.expenditure_reference,
                "date": alloc.allocation_date,
                "description": exp.description,
                "amount": alloc.amount,
                "total_expenditure": exp.amount,
                "category": category_label,
                "accounting_nature": exp.accounting_nature,
                "beneficiary": beneficiary or "Not allocated",
                "funding_source": str(alloc.funding_source),
                "status": exp.status,
                "remaining_cash_after": running_cash,
            }
        )

    return {
        "batch_id": batch.pk,
        "batch_code": batch.batch_id,
        "cash_collected": collected,
        "gross_collections": gross_collections,
        "refunds": refunds,
        "cash_used": used,
        "available_cash": available,
        "utilization_percent": percent(used, collected),
        "by_category": {k: money(v) for k, v in by_category.items()},
        "by_accounting_nature": {k: money(v) for k, v in by_nature.items()},
        "beneficiary_modules": sorted(beneficiaries),
        "transactions": transactions,
    }


def validate_funding_allocations(expenditure: Expenditure, allocations_data: list[dict]) -> None:
    """
    Validates that funding allocations for an expenditure do not overspend
    any batch's collected cash.
    Called before posting an expenditure.
    """
    from decimal import Decimal as D

    if not allocations_data:
        raise ValidationError({"funding_allocations": "Full funding is required before posting."})

    source_usage = {}
    allocation_total = ZERO

    for alloc in allocations_data:
        fs_id = alloc.get("funding_source")
        amount = D(str(alloc.get("amount", "0")))

        if amount <= ZERO:
            raise ValidationError({"funding_allocations": "Every funding amount must be greater than zero."})

        try:
            fs = FundingSource.objects.get(pk=fs_id)
        except FundingSource.DoesNotExist:
            raise ValidationError({"funding_source": f"Funding source {fs_id} not found."})

        source_usage[fs.pk] = source_usage.get(fs.pk, ZERO) + amount
        allocation_total += amount

    if money(allocation_total) != money(expenditure.amount):
        raise ValidationError(
            {
                "funding_allocations": (
                    f"Funding must equal the expenditure amount of {money(expenditure.amount)}; "
                    f"received {money(allocation_total)}."
                )
            }
        )

    for source_id, additional in source_usage.items():
        source = FundingSource.objects.select_related("batch").get(pk=source_id)
        available = available_funding_source_cash(source)
        if additional > available:
            raise ValidationError(
                {
                    "funding_allocations": (
                        f"Cannot allocate {money(additional)} from {source}. "
                        f"Available cash is {available}."
                    )
                }
            )
