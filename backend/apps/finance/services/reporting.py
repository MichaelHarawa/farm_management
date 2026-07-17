from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.poultry.models import (
    Batch,
    BatchStatus,
    FeedUsage,
    InputCosts,
    Mortality,
    PaymentStatus,
    ProductType,
    Sales,
)

from ..models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    CostAllocation,
    CostScope,
    PayrollEntry,
    SharedExpense,
    SharedExpenseScope,
)
from .batch_lifecycle import calculate_bird_balance
from .profitability import batch_profitability, money, percent


def _sales_expression():
    return ExpressionWrapper(
        F("quantity_sold") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _input_cost_expression():
    return ExpressionWrapper(
        F("quantity") * F("unit") * F("unit_cost"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def _period_sales(period: AccountingPeriod):
    return Sales.objects.filter(
        sale_date__date__gte=period.period_start,
        sale_date__date__lte=period.period_end,
    ).exclude(payment_status=PaymentStatus.CANCELLED)


def monthly_profitability_report(period: AccountingPeriod) -> dict:
    sales = _period_sales(period)
    revenue_rows = sales.values("product_type").annotate(total=Sum(_sales_expression()))
    revenue_by_product = {
        row["product_type"]: money(row["total"]) for row in revenue_rows
    }
    bird_sales = revenue_by_product.get(ProductType.LIVE_CHICKEN, Decimal("0.00")) + revenue_by_product.get(
        ProductType.DRESSED_CHICKEN, Decimal("0.00")
    )
    egg_sales = revenue_by_product.get(ProductType.EGGS, Decimal("0.00"))
    manure_sales = revenue_by_product.get(ProductType.MANURE, Decimal("0.00"))
    total_revenue = money(sum(revenue_by_product.values(), Decimal("0.00")))
    cash_received = money(sales.aggregate(total=Sum("amount_paid"))["total"])
    accounts_receivable = money(sales.aggregate(total=Sum("balance"))["total"])

    direct_batch_costs = money(
        InputCosts.objects.filter(
            purchase_date__date__gte=period.period_start,
            purchase_date__date__lte=period.period_end,
        ).aggregate(total=Sum(_input_cost_expression()))["total"]
    )
    batch_direct_labour = money(
        AdHocLabourPayment.objects.filter(
            accounting_period=period,
            cost_scope=CostScope.BATCH_DIRECT,
        ).aggregate(total=Sum("payment_amount"))["total"]
    )
    allocated_payroll = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.PAYROLL,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    temporary_production_labour = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.AD_HOC_LABOUR,
            ad_hoc_labour_payment__cost_scope=CostScope.SHARED_PRODUCTION,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    shared_production_overhead = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.SHARED_EXPENSE,
            shared_expense__scope=SharedExpenseScope.SHARED_PRODUCTION,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    total_production_costs = (
        direct_batch_costs
        + batch_direct_labour
        + allocated_payroll
        + temporary_production_labour
        + shared_production_overhead
    )

    active_batch_work_in_progress = Decimal("0.00")
    active_batches = Batch.objects.exclude(status=BatchStatus.CLOSED)
    for batch in active_batches.prefetch_related("sales_row", "input_costs"):
        active_batch_work_in_progress += batch_profitability(batch)[
            "active_batch_cost_exposure"
        ]

    # Management COGS uses the current provisional/final cost pool. Closed-batch
    # final snapshots can later true-up this line so cumulative recognized COGS
    # reconciles to final total production cost.
    cost_of_goods_sold = max(
        total_production_costs - active_batch_work_in_progress,
        Decimal("0.00"),
    )
    gross_profit = total_revenue - cost_of_goods_sold

    administration_payroll = money(
        PayrollEntry.objects.filter(accounting_period=period).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("total_employer_cost")
                    * F("administration_percentage")
                    / Decimal("100.00"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
    )
    general_operating_expenses = money(
        SharedExpense.objects.filter(
            accounting_period=period,
            scope__in=[SharedExpenseScope.ADMIN_OVERHEAD, SharedExpenseScope.OTHER],
        ).aggregate(total=Sum("amount"))["total"]
    )
    selling_distribution_costs = money(
        PayrollEntry.objects.filter(accounting_period=period).aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("total_employer_cost")
                    * F("selling_percentage")
                    / Decimal("100.00"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
    ) + money(
        SharedExpense.objects.filter(
            accounting_period=period,
            scope=SharedExpenseScope.SELLING_EXPENSE,
        ).aggregate(total=Sum("amount"))["total"]
    )
    operating_profit = (
        gross_profit
        - administration_payroll
        - general_operating_expenses
        - selling_distribution_costs
    )
    finance_costs = money(
        SharedExpense.objects.filter(
            accounting_period=period,
            scope=SharedExpenseScope.FINANCE_COST,
        ).aggregate(total=Sum("amount"))["total"]
    )
    tax_expenses = money(
        SharedExpense.objects.filter(
            accounting_period=period,
            scope=SharedExpenseScope.TAX,
        ).aggregate(total=Sum("amount"))["total"]
    )
    net_profit_before_tax = operating_profit - finance_costs
    net_profit_after_recorded_tax = net_profit_before_tax - tax_expenses

    cash_paid = money(
        PayrollEntry.objects.filter(
            accounting_period=period,
            payment_status=PaymentStatus.PAID,
        ).aggregate(total=Sum("total_employer_cost"))["total"]
    ) + money(
        AdHocLabourPayment.objects.filter(
            accounting_period=period,
            payment_status=PaymentStatus.PAID,
        ).aggregate(total=Sum("payment_amount"))["total"]
    ) + money(
        SharedExpense.objects.filter(
            accounting_period=period,
            payment_status=PaymentStatus.PAID,
        ).aggregate(total=Sum("amount"))["total"]
    )

    birds_sold = (
        sales.filter(
            product_type__in=[
                ProductType.LIVE_CHICKEN,
                ProductType.DRESSED_CHICKEN,
            ]
        ).aggregate(total=Sum("quantity_sold"))["total"]
        or 0
    )
    mortality = (
        Mortality.objects.filter(
            mortality_date__date__gte=period.period_start,
            mortality_date__date__lte=period.period_end,
        ).aggregate(total=Sum("quantity_dead"))["total"]
        or 0
    )
    birds_placed = (
        Batch.objects.filter(
            entry_date__date__gte=period.period_start,
            entry_date__date__lte=period.period_end,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    birds_remaining = 0
    for batch in Batch.objects.all():
        birds_remaining += max(calculate_bird_balance(batch).remaining_live_birds, 0)

    feed_consumed = (
        FeedUsage.objects.filter(
            feeding_start_date__date__gte=period.period_start,
            feeding_end_date__date__lte=period.period_end,
        ).aggregate(total=Sum("quantity_given"))["total"]
        or 0
    )

    return {
        "period": period.pk,
        "period_start": period.period_start,
        "period_end": period.period_end,
        "status": period.status,
        "revenue": {
            "bird_sales": bird_sales,
            "egg_sales": egg_sales,
            "manure_sales": manure_sales,
            "other_batch_revenue": max(
                total_revenue - bird_sales - egg_sales - manure_sales,
                Decimal("0.00"),
            ),
            "total_revenue": total_revenue,
        },
        "collections": {
            "cash_received": cash_received,
            "credit_sales": accounts_receivable,
            "accounts_receivable": accounts_receivable,
            "collection_rate_percent": percent(cash_received, total_revenue),
        },
        "production": {
            "direct_batch_costs": direct_batch_costs + batch_direct_labour,
            "allocated_production_payroll": allocated_payroll,
            "temporary_production_labour": temporary_production_labour,
            "shared_production_overhead": shared_production_overhead,
            "cost_of_goods_sold": cost_of_goods_sold,
            "active_batch_work_in_progress": active_batch_work_in_progress,
            "gross_profit": gross_profit,
            "gross_margin_percent": percent(gross_profit, total_revenue),
        },
        "operating_costs": {
            "administration_payroll": administration_payroll,
            "general_operating_expenses": general_operating_expenses,
            "selling_distribution_costs": selling_distribution_costs,
            "operating_profit": operating_profit,
        },
        "other_costs": {
            "finance_costs": finance_costs,
            "tax_expenses": tax_expenses,
            "net_profit_before_tax": net_profit_before_tax,
            "net_profit_after_recorded_tax": net_profit_after_recorded_tax,
        },
        "cash_flow": {
            "opening_cash": None,
            "cash_received": cash_received,
            "cash_paid": cash_paid,
            "net_cash_movement": cash_received - cash_paid,
            "closing_cash": None,
        },
        "operational_metrics": {
            "batches_active": Batch.objects.exclude(status=BatchStatus.CLOSED).count(),
            "batches_closed": Batch.objects.filter(status=BatchStatus.CLOSED).count(),
            "birds_placed": birds_placed,
            "birds_sold": birds_sold,
            "birds_remaining": birds_remaining,
            "mortality": mortality,
            "mortality_rate_percent": percent(
                Decimal(mortality),
                Decimal(birds_placed) if birds_placed else Decimal("0"),
            ),
            "feed_consumed": feed_consumed,
            "feed_cost_per_bird": (
                money(direct_batch_costs / Decimal(birds_placed))
                if birds_placed
                else None
            ),
            "labour_cost_per_bird": (
                money(
                    (allocated_payroll + temporary_production_labour)
                    / Decimal(birds_sold)
                )
                if birds_sold
                else None
            ),
            "average_selling_price": (
                money(bird_sales / Decimal(birds_sold)) if birds_sold else None
            ),
        },
        "warnings": dashboard_warnings(period),
    }


def dashboard_warnings(period: AccountingPeriod | None = None) -> list[dict[str, str]]:
    thresholds = getattr(settings, "FINANCE_WARNING_THRESHOLDS", {})
    high_mortality_rate = Decimal(str(thresholds.get("high_mortality_rate", "8.0")))
    receivable_days = int(thresholds.get("receivable_overdue_days", 14))
    stale_update_days = int(thresholds.get("stale_batch_update_days", 7))
    today = timezone.localdate()
    warnings: list[dict[str, str]] = []

    for batch in Batch.objects.exclude(status=BatchStatus.CLOSED):
        balance = calculate_bird_balance(batch)
        mortality_rate = percent(
            Decimal(balance.mortality),
            Decimal(balance.initial_birds),
        )
        if mortality_rate is not None and mortality_rate > high_mortality_rate:
            warnings.append(
                {
                    "code": "high_mortality",
                    "severity": "warning",
                    "message": f"{batch.batch_id} mortality is {mortality_rate}%.",
                }
            )
        if (
            batch.expected_maturity_date.date() < today
            and not batch.sales_row.exclude(
                payment_status=PaymentStatus.CANCELLED
            ).exists()
        ):
            warnings.append(
                {
                    "code": "past_maturity_no_sales",
                    "severity": "warning",
                    "message": f"{batch.batch_id} is past maturity with no valid sales.",
                }
            )
        recent_feed = batch.feed_usage_row.filter(
            feeding_end_date__date__gte=today - timedelta(days=stale_update_days)
        ).exists()
        recent_mortality = batch.mortality_row.filter(
            mortality_date__date__gte=today - timedelta(days=stale_update_days)
        ).exists()
        if not recent_feed and not recent_mortality:
            warnings.append(
                {
                    "code": "stale_batch_updates",
                    "severity": "info",
                    "message": f"{batch.batch_id} has no recent feed or mortality update.",
                }
            )

    overdue_sales = _period_sales(period) if period else Sales.objects.exclude(
        payment_status=PaymentStatus.CANCELLED
    )
    overdue_sales = overdue_sales.filter(
        balance__gt=0,
        sale_date__date__lte=today - timedelta(days=receivable_days),
    )
    if overdue_sales.exists():
        warnings.append(
            {
                "code": "overdue_receivables",
                "severity": "warning",
                "message": f"{overdue_sales.count()} sale(s) have overdue balances.",
            }
        )

    if period:
        unallocated_expenses = SharedExpense.objects.filter(
            accounting_period=period,
            scope=SharedExpenseScope.SHARED_PRODUCTION,
            cost_allocations__isnull=True,
        )
        if unallocated_expenses.exists():
            warnings.append(
                {
                    "code": "unallocated_shared_expenses",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_expenses.count()} shared production expense(s) "
                        "are not allocated."
                    ),
                }
            )

        unallocated_payroll = PayrollEntry.objects.filter(
            accounting_period=period,
            cost_allocations__isnull=True,
        )
        if unallocated_payroll.exists():
            warnings.append(
                {
                    "code": "unallocated_payroll",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_payroll.count()} payroll entrie(s) "
                        "are not allocated."
                    ),
                }
            )

    return warnings


def dashboard_indicators() -> dict:
    latest_period = AccountingPeriod.objects.order_by("-period_start").first()
    active_batches = Batch.objects.exclude(status=BatchStatus.CLOSED)
    active_cost_exposure = Decimal("0.00")
    closed_batch_profit = Decimal("0.00")

    for batch in Batch.objects.all():
        data = batch_profitability(batch)
        active_cost_exposure += data["active_batch_cost_exposure"]
        if data["profitability_status"] == "final":
            closed_batch_profit += data["batch_gross_profit"]

    receivable_total = money(
        Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED).aggregate(
            total=Sum("balance")
        )["total"]
    )

    latest_report = monthly_profitability_report(latest_period) if latest_period else None

    return {
        "active_batches": active_batches.count(),
        "active_batch_cost_exposure": active_cost_exposure,
        "closed_batch_profit": closed_batch_profit,
        "receivables": receivable_total,
        "latest_month": latest_report,
        "warnings": dashboard_warnings(latest_period),
    }


def receivables_report() -> dict:
    open_sales = Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED).filter(
        balance__gt=0
    )
    rows = [
        {
            "sale_id": sale.sale_id,
            "batch": sale.batch_id,
            "batch_id": sale.batch.batch_id,
            "buyer_name": sale.buyer_name,
            "sale_date": sale.sale_date,
            "sale_total": sale.sale_total,
            "amount_paid": sale.amount_paid,
            "balance": sale.balance,
            "payment_status": sale.payment_status,
        }
        for sale in open_sales.select_related("batch").order_by("sale_date")
    ]
    return {
        "total_receivable": money(open_sales.aggregate(total=Sum("balance"))["total"]),
        "count": len(rows),
        "results": rows,
    }
