from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
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
    AccountingNature,
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    Asset,
    AssetDepreciationEntry,
    AssetStatus,
    BatchProfitabilitySnapshot,
    ConsumableUsage,
    ConsumableUsageScope,
    CostAllocation,
    CostScope,
    ExpenseRecognitionSchedule,
    ExpenseRecognitionType,
    Expenditure,
    ExpenditureStatus,
    FinancePaymentStatus,
    FundingAllocation,
    FundingReceipt,
    FundingReceiptStatus,
    FundingSourceType,
    PayrollPayment,
    PayrollPaymentStatus,
    PeriodReportSnapshot,
    PeriodStatus,
    ReportingPolicy,
    PayrollEntry,
    SalePayment,
    SalePaymentStatus,
    ReplacementReserveTransaction,
    ReserveTransactionType,
    SharedConsumableLot,
    SharedExpense,
    SharedExpenseScope,
)
from apps.poultry.services.batch_lifecycle import calculate_bird_balance
from .profitability import batch_profitability, money, percent
from .warnings import finance_warning


PRE_PRODUCTION_BATCH_STATUSES = [
    BatchStatus.BOOKED,
    BatchStatus.DELIVERED,
]
ACTIVE_BATCH_EXCLUDED_STATUSES = [
    *PRE_PRODUCTION_BATCH_STATUSES,
    BatchStatus.CLOSED,
]


def _active_production_batches():
    return Batch.objects.exclude(status__in=ACTIVE_BATCH_EXCLUDED_STATUSES)


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


def _management_cogs(period: AccountingPeriod) -> Decimal:
    bird_sales = (
        _period_sales(period)
        .filter(
            product_type__in=[
                ProductType.LIVE_CHICKEN,
                ProductType.DRESSED_CHICKEN,
            ]
        )
        .values("batch_id")
        .annotate(units=Sum("quantity_sold"))
    )
    cogs = Decimal("0.00")

    for row in bird_sales:
        batch = Batch.objects.get(pk=row["batch_id"])
        data = batch_profitability(batch)
        cost_per_bird = (
            data["final_cost_per_bird_sold"]
            if data["profitability_status"] == "final"
            else data["provisional_cost_per_saleable_bird"]
        )
        if cost_per_bird:
            cogs += money(Decimal(row["units"] or 0) * cost_per_bird)

    return money(cogs)


def _calculate_monthly_profitability_report(period: AccountingPeriod) -> dict:
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
    cash_received = money(
        SalePayment.objects.filter(
            status=SalePaymentStatus.POSTED,
            payment_date__date__gte=period.period_start,
            payment_date__date__lte=period.period_end,
        )
        .exclude(sale__payment_status=PaymentStatus.CANCELLED)
        .aggregate(total=Sum("amount"))["total"]
    )
    collected_against_period_sales = money(
        SalePayment.objects.filter(
            sale__in=sales,
            status=SalePaymentStatus.POSTED,
            payment_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    accounts_receivable = money(max(total_revenue - collected_against_period_sales, Decimal("0.00")))
    opening_sales = Sales.objects.filter(sale_date__date__lt=period.period_start).exclude(
        payment_status=PaymentStatus.CANCELLED
    )
    opening_invoiced = money(opening_sales.aggregate(total=Sum(_sales_expression()))["total"])
    opening_collected = money(
        SalePayment.objects.filter(
            sale__in=opening_sales,
            status=SalePaymentStatus.POSTED,
            payment_date__date__lt=period.period_start,
        ).aggregate(total=Sum("amount"))["total"]
    )
    opening_receivables = max(opening_invoiced - opening_collected, Decimal("0.00"))
    collections_against_opening = money(
        SalePayment.objects.filter(
            sale__sale_date__date__lt=period.period_start,
            status=SalePaymentStatus.POSTED,
            payment_date__date__gte=period.period_start,
            payment_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    cohort_collections_in_period = money(
        SalePayment.objects.filter(
            sale__in=sales,
            status=SalePaymentStatus.POSTED,
            payment_date__date__gte=period.period_start,
            payment_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    all_sales_to_cutoff = Sales.objects.filter(sale_date__date__lte=period.period_end).exclude(
        payment_status=PaymentStatus.CANCELLED
    )
    invoiced_to_cutoff = money(
        all_sales_to_cutoff.aggregate(total=Sum(_sales_expression()))["total"]
    )
    collected_to_cutoff = money(
        SalePayment.objects.filter(
            sale__in=all_sales_to_cutoff,
            status=SalePaymentStatus.POSTED,
            payment_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    closing_receivables = max(invoiced_to_cutoff - collected_to_cutoff, Decimal("0.00"))

    direct_batch_costs = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure__status=ExpenditureStatus.POSTED,
            expenditure__accounting_nature=AccountingNature.DIRECT_COST,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        InputCosts.objects.filter(
            expenditure__isnull=True,
            purchase_date__date__gte=period.period_start,
            purchase_date__date__lte=period.period_end,
        )
        .exclude(batch__status__in=PRE_PRODUCTION_BATCH_STATUSES)
        .aggregate(total=Sum(_input_cost_expression()))["total"]
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
    direct_consumable_usage = money(
        ConsumableUsage.objects.filter(
            accounting_period=period,
            usage_scope=ConsumableUsageScope.BATCH_DIRECT,
        ).aggregate(total=Sum("recognized_cost"))["total"]
    )
    shared_consumable_allocations = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.CONSUMABLE_USAGE,
            consumable_usage__usage_scope=ConsumableUsageScope.SHARED_PRODUCTION,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    production_depreciation = money(
        CostAllocation.objects.filter(
            accounting_period=period,
            source_type=AllocationSourceType.DEPRECIATION,
        ).aggregate(total=Sum("allocated_amount"))["total"]
    )
    total_production_costs = (
        direct_batch_costs
        + batch_direct_labour
        + direct_consumable_usage
        + allocated_payroll
        + temporary_production_labour
        + shared_production_overhead
        + shared_consumable_allocations
        + production_depreciation
    )

    active_batch_work_in_progress = Decimal("0.00")
    cutoff_batches = Batch.objects.filter(entry_date__date__lte=period.period_end).exclude(
        status__in=PRE_PRODUCTION_BATCH_STATUSES
    )
    for batch in cutoff_batches:
        sold_to_cutoff = (
            Sales.objects.filter(
                batch=batch,
                sale_date__date__lte=period.period_end,
                product_type__in=[ProductType.LIVE_CHICKEN, ProductType.DRESSED_CHICKEN],
            ).exclude(payment_status=PaymentStatus.CANCELLED).aggregate(total=Sum("quantity_sold"))["total"]
            or 0
        )
        mortality_to_cutoff = (
            Mortality.objects.filter(
                batch=batch, mortality_date__date__lte=period.period_end
            ).aggregate(total=Sum("quantity_dead"))["total"]
            or 0
        )
        remaining_to_cutoff = max(batch.quantity - sold_to_cutoff - mortality_to_cutoff, 0)
        if not remaining_to_cutoff:
            continue
        allocated_to_cutoff = money(
            CostAllocation.objects.filter(
                batch=batch, accounting_period__period_end__lte=period.period_end
            ).aggregate(total=Sum("allocated_amount"))["total"]
        )
        legacy_to_cutoff = money(
            InputCosts.objects.filter(
                batch=batch, expenditure__isnull=True, purchase_date__date__lte=period.period_end
            ).aggregate(total=Sum(_input_cost_expression()))["total"]
        )
        total_units = remaining_to_cutoff + sold_to_cutoff
        if total_units:
            active_batch_work_in_progress += money(
                (allocated_to_cutoff + legacy_to_cutoff)
                * Decimal(remaining_to_cutoff)
                / Decimal(total_units)
            )

    # Management COGS uses the same provisional/final batch cost-per-bird logic
    # as the batch profitability endpoint. Closed batches use final cost per
    # bird; active/selling batches use provisional saleable-bird cost.
    cost_of_goods_sold = _management_cogs(period)
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
    administration_ad_hoc_labour = money(
        AdHocLabourPayment.objects.filter(
            accounting_period=period,
            cost_scope=CostScope.FARM_ADMINISTRATION,
        ).aggregate(total=Sum("payment_amount"))["total"]
    )
    administration_consumables = money(
        ConsumableUsage.objects.filter(
            accounting_period=period,
            usage_scope=ConsumableUsageScope.ADMINISTRATION,
        ).aggregate(total=Sum("recognized_cost"))["total"]
    )
    general_operating_expenses = money(
        SharedExpense.objects.filter(
            accounting_period=period,
            scope__in=[SharedExpenseScope.ADMIN_OVERHEAD, SharedExpenseScope.OTHER],
        )
        .exclude(
            recognition_type__in=[
                ExpenseRecognitionType.CAPITAL_EXPENDITURE,
                ExpenseRecognitionType.PREPAID_EXPENSE,
                ExpenseRecognitionType.SHARED_CONSUMABLE,
            ]
        ).aggregate(total=Sum("amount"))["total"]
    )
    asset_depreciation = AssetDepreciationEntry.objects.filter(
        accounting_period=period
    )
    administration_depreciation = money(
        asset_depreciation.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("period_depreciation")
                    * F("asset__administration_percentage")
                    / Decimal("100.00"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
    )
    selling_asset_depreciation = money(
        asset_depreciation.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F("period_depreciation")
                    * F("asset__selling_percentage")
                    / Decimal("100.00"),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )["total"]
    )
    idle_capacity_depreciation = money(
        asset_depreciation.filter(asset__status=AssetStatus.IDLE).aggregate(
            total=Sum("period_depreciation")
        )["total"]
    )
    selling_ad_hoc_labour = money(
        AdHocLabourPayment.objects.filter(
            accounting_period=period,
            cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
        ).aggregate(total=Sum("payment_amount"))["total"]
    )
    selling_consumables = money(
        ConsumableUsage.objects.filter(
            accounting_period=period,
            usage_scope=ConsumableUsageScope.SELLING_AND_DISTRIBUTION,
        ).aggregate(total=Sum("recognized_cost"))["total"]
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
    ) + selling_asset_depreciation + selling_ad_hoc_labour + selling_consumables
    operating_profit = (
        gross_profit
        - administration_payroll
        - administration_ad_hoc_labour
        - administration_consumables
        - general_operating_expenses
        - administration_depreciation
        - selling_distribution_costs
        - idle_capacity_depreciation
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

    dated_payments = FundingAllocation.objects.filter(
        allocation_date__gte=period.period_start,
        allocation_date__lte=period.period_end,
        expenditure__status=ExpenditureStatus.POSTED,
    )
    legacy_paid_dates = (
        Q(payment_date__gte=period.period_start, payment_date__lte=period.period_end)
        | Q(
            payment_date__isnull=True,
            expense_date__gte=period.period_start,
            expense_date__lte=period.period_end,
        )
    )
    legacy_paid = SharedExpense.objects.filter(
        legacy_paid_dates,
        payment_status=FinancePaymentStatus.PAID,
        expenditure__funding_allocations__isnull=True,
    )
    legacy_operating_paid = money(
        legacy_paid.exclude(
            Q(recognition_type=ExpenseRecognitionType.CAPITAL_EXPENDITURE)
            | Q(scope=SharedExpenseScope.CAPITAL_EXPENDITURE)
        ).aggregate(total=Sum("amount"))["total"]
    )
    legacy_investing_paid = money(
        legacy_paid.filter(
            Q(recognition_type=ExpenseRecognitionType.CAPITAL_EXPENDITURE)
            | Q(scope=SharedExpenseScope.CAPITAL_EXPENDITURE)
        ).aggregate(total=Sum("amount"))["total"]
    )
    operating_cash_paid = money(
        dated_payments.filter(
            expenditure__accounting_nature__in=[
                AccountingNature.DIRECT_COST,
                AccountingNature.INDIRECT_OPERATING_EXPENSE,
                AccountingNature.OTHER,
            ]
        ).aggregate(total=Sum("amount"))["total"]
    ) + money(
        PayrollPayment.objects.filter(
            payment_date__gte=period.period_start,
            payment_date__lte=period.period_end,
            status=PayrollPaymentStatus.POSTED,
        ).aggregate(total=Sum("amount"))["total"]
    ) + legacy_operating_paid
    investing_cash_paid = money(
        dated_payments.filter(
            expenditure__accounting_nature=AccountingNature.CAPITAL_EXPENDITURE
        ).aggregate(total=Sum("amount"))["total"]
    ) + legacy_investing_paid
    financing_cash_paid = money(
        dated_payments.filter(
            expenditure__accounting_nature__in=[
                AccountingNature.LOAN_REPAYMENT,
                AccountingNature.OWNER_WITHDRAWAL,
                AccountingNature.TRANSFER,
            ]
        ).aggregate(total=Sum("amount"))["total"]
    )
    non_sales_receipts = FundingReceipt.objects.filter(
        receipt_date__date__gte=period.period_start,
        receipt_date__date__lte=period.period_end,
        status=FundingReceiptStatus.POSTED,
    )
    operating_cash_in = cash_received + money(
        non_sales_receipts.filter(
            funding_source__source_type__in=[FundingSourceType.OTHER_INCOME, FundingSourceType.GRANT]
        ).aggregate(total=Sum("amount"))["total"]
    )
    financing_cash_in = money(
        non_sales_receipts.filter(
            funding_source__source_type__in=[FundingSourceType.OWNER_CAPITAL, FundingSourceType.LOAN]
        ).aggregate(total=Sum("amount"))["total"]
    )
    cash_paid = money(operating_cash_paid + investing_cash_paid + financing_cash_paid)
    capital_expenditure_paid = investing_cash_paid
    net_cash_movement = money(operating_cash_in + financing_cash_in - cash_paid)
    opening_cash_receipts = money(
        SalePayment.objects.filter(
            status=SalePaymentStatus.POSTED, payment_date__date__lt=period.period_start
        ).aggregate(total=Sum("amount"))["total"]
    ) + money(
        FundingReceipt.objects.filter(
            status=FundingReceiptStatus.POSTED, receipt_date__date__lt=period.period_start
        ).aggregate(total=Sum("amount"))["total"]
    )
    opening_cash_payments = money(
        FundingAllocation.objects.filter(
            expenditure__status=ExpenditureStatus.POSTED,
            allocation_date__lt=period.period_start,
        ).aggregate(total=Sum("amount"))["total"]
    ) + money(
        PayrollPayment.objects.filter(
            status=PayrollPaymentStatus.POSTED, payment_date__lt=period.period_start
        ).aggregate(total=Sum("amount"))["total"]
    )
    opening_cash = money(opening_cash_receipts - opening_cash_payments)
    closing_cash = money(opening_cash + net_cash_movement)
    reserve_contributions = money(
        ReplacementReserveTransaction.objects.filter(
            accounting_period=period,
            transaction_type=ReserveTransactionType.CONTRIBUTION,
        ).aggregate(total=Sum("amount"))["total"]
    )
    reserve_withdrawals = money(
        ReplacementReserveTransaction.objects.filter(
            accounting_period=period,
            transaction_type=ReserveTransactionType.WITHDRAWAL,
        ).aggregate(total=Sum("amount"))["total"]
    )
    consumables_purchased = money(
        SharedConsumableLot.objects.filter(
            purchase_date__gte=period.period_start,
            purchase_date__lte=period.period_end,
        ).aggregate(total=Sum("total_purchase_cost"))["total"]
    )
    consumables_consumed = money(
        ConsumableUsage.objects.filter(
            accounting_period=period,
        ).aggregate(total=Sum("recognized_cost"))["total"]
    )
    closing_consumable_inventory = max(
        money(
            SharedConsumableLot.objects.filter(purchase_date__lte=period.period_end).aggregate(
                total=Sum("total_purchase_cost")
            )["total"]
        )
        - money(
            ConsumableUsage.objects.filter(usage_date__lte=period.period_end).aggregate(
                total=Sum("recognized_cost")
            )["total"]
        ),
        Decimal("0.00"),
    )
    prepaid_recognized = money(
        ExpenseRecognitionSchedule.objects.filter(accounting_period=period).aggregate(
            total=Sum("amount_recognized")
        )["total"]
    )
    prepaid_closing_balance = money(
        ExpenseRecognitionSchedule.objects.aggregate(
            total=Sum("remaining_deferred_amount")
        )["total"]
    )
    asset_additions = money(
        Asset.objects.filter(
            purchase_date__gte=period.period_start,
            purchase_date__lte=period.period_end,
        ).aggregate(total=Sum("total_capitalized_cost"))["total"]
    )
    disposal_proceeds = money(
        Asset.objects.filter(
            disposal_date__gte=period.period_start,
            disposal_date__lte=period.period_end,
        ).aggregate(total=Sum("disposal_proceeds"))["total"]
    )
    net_cash_movement = money(
        operating_cash_in
        + financing_cash_in
        + disposal_proceeds
        - operating_cash_paid
        - investing_cash_paid
        - financing_cash_paid
    )
    closing_cash = money(opening_cash + net_cash_movement)
    gross_asset_cost = money(
        Asset.objects.filter(purchase_date__lte=period.period_end)
        .exclude(disposal_date__lt=period.period_start)
        .aggregate(total=Sum("total_capitalized_cost"))["total"]
    )
    accumulated_depreciation = money(
        AssetDepreciationEntry.objects.filter(
            accounting_period__period_end__lte=period.period_end
        ).aggregate(total=Sum("period_depreciation"))["total"]
    )
    impairment = money(Asset.objects.aggregate(total=Sum("recognized_impairment_amount"))["total"])
    carrying_amount = gross_asset_cost - accumulated_depreciation - impairment
    supplier_payables = Decimal("0.00")
    payable_ageing = {"current": Decimal("0.00"), "31_60": Decimal("0.00"), "61_90": Decimal("0.00"), "over_90": Decimal("0.00")}
    for expenditure in Expenditure.objects.filter(
        status=ExpenditureStatus.POSTED,
        expenditure_date__lte=period.period_end,
        payroll_entry__isnull=True,
    ).prefetch_related("funding_allocations"):
        paid_to_cutoff = money(
            sum(
                (
                    payment.amount
                    for payment in expenditure.funding_allocations.all()
                    if payment.allocation_date <= period.period_end
                ),
                Decimal("0.00"),
            )
        )
        outstanding = max(money(expenditure.amount) - paid_to_cutoff, Decimal("0.00"))
        if not outstanding:
            continue
        supplier_payables += outstanding
        age = (period.period_end - expenditure.expenditure_date).days
        bucket = "current" if age <= 30 else "31_60" if age <= 60 else "61_90" if age <= 90 else "over_90"
        payable_ageing[bucket] += outstanding
    payroll_payable = Decimal("0.00")
    for entry in PayrollEntry.objects.filter(
        accounting_period__period_end__lte=period.period_end
    ).prefetch_related("payments", "expenditure__funding_allocations"):
        direct_paid = money(
            sum(
                (payment.amount for payment in entry.payments.all() if payment.status == PayrollPaymentStatus.POSTED and payment.payment_date <= period.period_end),
                Decimal("0.00"),
            )
        )
        expenditure_paid = money(
            sum(
                (payment.amount for payment in entry.expenditure.funding_allocations.all() if payment.allocation_date <= period.period_end),
                Decimal("0.00"),
            ) if entry.expenditure_id else Decimal("0.00")
        )
        payroll_payable += max(money(entry.net_salary_payable) - max(direct_paid, expenditure_paid), Decimal("0.00"))
    loans = money(
        FundingReceipt.objects.filter(
            status=FundingReceiptStatus.POSTED,
            funding_source__source_type=FundingSourceType.LOAN,
            receipt_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    ) - money(
        FundingAllocation.objects.filter(
            expenditure__status=ExpenditureStatus.POSTED,
            expenditure__accounting_nature=AccountingNature.LOAN_REPAYMENT,
            allocation_date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    owner_equity = money(
        FundingReceipt.objects.filter(
            status=FundingReceiptStatus.POSTED,
            funding_source__source_type=FundingSourceType.OWNER_CAPITAL,
            receipt_date__date__lte=period.period_end,
        ).aggregate(total=Sum("amount"))["total"]
    )
    total_assets = money(closing_cash + closing_receivables + closing_consumable_inventory + active_batch_work_in_progress + carrying_amount)
    total_liabilities = money(supplier_payables + payroll_payable + max(loans, Decimal("0.00")))
    net_assets = money(total_assets - total_liabilities)
    previous_period = AccountingPeriod.objects.filter(period_end__lt=period.period_start).order_by("-period_end").first()
    previous_revenue = money(
        _period_sales(previous_period).aggregate(total=Sum(_sales_expression()))["total"]
    ) if previous_period else Decimal("0.00")
    ytd_revenue = money(
        Sales.objects.filter(
            sale_date__date__gte=date(period.period_start.year, 1, 1),
            sale_date__date__lte=period.period_end,
        ).exclude(payment_status=PaymentStatus.CANCELLED).aggregate(total=Sum(_sales_expression()))["total"]
    )
    reserve_balance = (
        money(
            ReplacementReserveTransaction.objects.filter(
                transaction_type__in=[
                    ReserveTransactionType.CONTRIBUTION,
                    ReserveTransactionType.RETURN,
                ]
            ).aggregate(total=Sum("amount"))["total"]
        )
        - money(
            ReplacementReserveTransaction.objects.filter(
                transaction_type=ReserveTransactionType.WITHDRAWAL
            ).aggregate(total=Sum("amount"))["total"]
        )
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
        )
        .exclude(status__in=PRE_PRODUCTION_BATCH_STATUSES)
        .aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    birds_remaining = 0
    period_batches = Batch.objects.filter(entry_date__date__lte=period.period_end).filter(
        Q(closed_at__isnull=True) | Q(closed_at__date__gte=period.period_start)
    ).exclude(status__in=PRE_PRODUCTION_BATCH_STATUSES)
    from .bird_days import calculate_batch_bird_days
    for batch in period_batches:
        birds_remaining += max(int(calculate_batch_bird_days(batch, period)["closing_live_birds"]), 0)

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
        "reporting_basis": "MTD / provisional" if period.status == PeriodStatus.OPEN else "closed snapshot",
        "as_of": period.period_end,
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
            "credit_sales": total_revenue,
            "accounts_receivable": closing_receivables,
            "collection_rate_percent": percent(
                min(collected_against_period_sales, total_revenue), total_revenue
            ),
            "collection_overpayment": max(
                collected_against_period_sales - total_revenue, Decimal("0.00")
            ),
            "roll_forward": {
                "opening_receivables": opening_receivables,
                "current_period_sales": total_revenue,
                "collections_against_opening": collections_against_opening,
                "collections_against_current_sales": cohort_collections_in_period,
                "credit_notes_and_reversals": Decimal("0.00"),
                "write_offs": Decimal("0.00"),
                "closing_receivables": closing_receivables,
            },
        },
        "production": {
            "direct_batch_costs": direct_batch_costs + batch_direct_labour,
            "direct_consumable_usage": direct_consumable_usage,
            "allocated_production_payroll": allocated_payroll,
            "temporary_production_labour": temporary_production_labour,
            "shared_production_overhead": shared_production_overhead,
            "shared_consumable_allocations": shared_consumable_allocations,
            "production_depreciation": production_depreciation,
            "cost_of_goods_sold": cost_of_goods_sold,
            "active_batch_work_in_progress": active_batch_work_in_progress,
            "gross_profit": gross_profit,
            "gross_margin_percent": percent(gross_profit, total_revenue),
        },
        "operating_costs": {
            "administration_payroll": administration_payroll,
            "administration_ad_hoc_labour": administration_ad_hoc_labour,
            "administration_consumables": administration_consumables,
            "general_operating_expenses": general_operating_expenses,
            "administration_depreciation": administration_depreciation,
            "selling_ad_hoc_labour": selling_ad_hoc_labour,
            "selling_consumables": selling_consumables,
            "selling_distribution_costs": selling_distribution_costs,
            "selling_asset_depreciation": selling_asset_depreciation,
            "idle_capacity_depreciation": idle_capacity_depreciation,
            "operating_profit": operating_profit,
        },
        "other_costs": {
            "finance_costs": finance_costs,
            "tax_expenses": tax_expenses,
            "net_profit_before_tax": net_profit_before_tax,
            "net_profit_after_recorded_tax": net_profit_after_recorded_tax,
        },
        "cash_flow": {
            "opening_cash": opening_cash,
            "cash_received": cash_received,
            "cash_paid": cash_paid,
            "capital_expenditure_paid": capital_expenditure_paid,
            "asset_purchases": asset_additions,
            "reserve_contributions": reserve_contributions,
            "reserve_withdrawals": reserve_withdrawals,
            "disposal_proceeds": disposal_proceeds,
            "operating": {
                "inflows": operating_cash_in,
                "outflows": operating_cash_paid,
                "net": money(operating_cash_in - operating_cash_paid),
            },
            "investing": {
                "inflows": disposal_proceeds,
                "outflows": investing_cash_paid,
                "net": money(disposal_proceeds - investing_cash_paid),
            },
            "financing": {
                "inflows": financing_cash_in,
                "outflows": financing_cash_paid,
                "net": money(financing_cash_in - financing_cash_paid),
            },
            "net_cash_movement": net_cash_movement,
            "closing_cash": closing_cash,
            "reconciles": money(opening_cash + net_cash_movement) == closing_cash,
        },
        "deferred_balances": {
            "consumables_purchased": consumables_purchased,
            "consumables_consumed": consumables_consumed,
            "closing_consumable_inventory": closing_consumable_inventory,
            "prepaid_expense_opening_balance": None,
            "prepaid_expense_recognized": prepaid_recognized,
            "prepaid_expense_closing_balance": prepaid_closing_balance,
        },
        "asset_reporting": {
            "additions": asset_additions,
            "disposals": Asset.objects.filter(
                disposal_date__gte=period.period_start,
                disposal_date__lte=period.period_end,
            ).count(),
            "gross_asset_cost": gross_asset_cost,
            "accumulated_depreciation": accumulated_depreciation,
            "carrying_amount": carrying_amount,
            "impairment": impairment,
            "reserve_balance": reserve_balance,
            "current_replacement_estimate": money(
                Asset.objects.filter(replacement_plan__isnull=False).aggregate(
                    total=Sum("replacement_plan__current_replacement_cost")
                )["total"]
            ),
            "projected_future_replacement_cost": money(
                Asset.objects.filter(replacement_plan__isnull=False).aggregate(
                    total=Sum("replacement_plan__projected_future_replacement_cost")
                )["total"]
            ),
            "replacement_funding_gap": max(
                money(
                    Asset.objects.filter(replacement_plan__isnull=False).aggregate(
                        total=Sum("replacement_plan__target_reserve_balance")
                    )["total"]
                )
                - reserve_balance,
                Decimal("0.00"),
            ),
        },
        "statement_of_financial_position": {
            "cash": closing_cash,
            "receivables": closing_receivables,
            "consumable_inventory": closing_consumable_inventory,
            "poultry_wip_management_cost": active_batch_work_in_progress,
            "fixed_assets_net": carrying_amount,
            "total_assets": total_assets,
            "supplier_payables": supplier_payables,
            "payroll_and_statutory_liabilities": payroll_payable,
            "loans": max(loans, Decimal("0.00")),
            "total_liabilities": total_liabilities,
            "owner_contributed_equity": owner_equity,
            "net_assets": net_assets,
            "basis": "management-cost balance sheet; biological fair value is not recorded",
        },
        "ageing": {
            "payables": payable_ageing,
            "receivables": {
                "total": closing_receivables,
                "note": "Detailed due-date ageing is available in Sales & Receivables.",
            },
        },
        "comparatives": {
            "current_period_revenue": total_revenue,
            "previous_period_revenue": previous_revenue,
            "revenue_change": money(total_revenue - previous_revenue),
            "ytd_revenue": ytd_revenue,
        },
        "close_readiness": {
            "unresolved_warning_count": len(dashboard_warnings(period)),
            "is_closed": period.status == PeriodStatus.CLOSED,
            "checklist": [
                "Reconcile sales receipts and receivables",
                "Reconcile supplier and payroll liabilities",
                "Post inventory usage and period depreciation",
                "Resolve allocation and period-lock warnings",
                "Review cash reconciliation before close",
            ],
        },
        "operational_metrics": {
            "batches_active": _active_production_batches().count(),
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


def _snapshot_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _snapshot_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_safe(item) for item in value]
    return value


def create_period_report_snapshot(period: AccountingPeriod, *, generated_by=None):
    """Create a new immutable close-report version without erasing prior versions."""

    previous = PeriodReportSnapshot.objects.filter(accounting_period=period).first()
    version = (previous.version + 1) if previous else 1
    policy = ReportingPolicy.objects.filter(
        is_active=True, effective_from__lte=period.period_end
    ).order_by("-effective_from", "-version").first()
    report = _calculate_monthly_profitability_report(period)
    report["snapshot_version"] = version
    report["reporting_policy"] = policy.code if policy else None
    return PeriodReportSnapshot.objects.create(
        accounting_period=period,
        version=version,
        report_data=_snapshot_safe(report),
        reporting_policy=policy,
        generated_by=generated_by,
        supersedes=previous,
    )


def monthly_profitability_report(period: AccountingPeriod) -> dict:
    if period.status == PeriodStatus.CLOSED:
        snapshot = PeriodReportSnapshot.objects.filter(accounting_period=period).first()
        if snapshot:
            return snapshot.report_data
    report = _calculate_monthly_profitability_report(period)
    report["snapshot_version"] = None
    policy = ReportingPolicy.objects.filter(
        is_active=True, effective_from__lte=period.period_end
    ).order_by("-effective_from", "-version").first()
    report["reporting_policy"] = policy.code if policy else None
    return report


def dashboard_warnings(period: AccountingPeriod | None = None) -> list[dict[str, str]]:
    thresholds = getattr(settings, "FINANCE_WARNING_THRESHOLDS", {})
    high_mortality_rate = Decimal(str(thresholds.get("high_mortality_rate", "8.0")))
    receivable_days = int(thresholds.get("receivable_overdue_days", 14))
    stale_update_days = int(thresholds.get("stale_batch_update_days", 7))
    today = timezone.localdate()
    warnings: list[dict[str, str]] = []

    for batch in _active_production_batches():
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
                    "action_href": f"/poultry/batches/{batch.pk}?tab=mortality",
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
                    "action_href": f"/poultry/batches/{batch.pk}?tab=sales",
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
                    "action_href": f"/poultry/batches/{batch.pk}?tab=feed",
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
            directly_assigned_batch__isnull=True,
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
            production_percentage__gt=0,
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

        unallocated_shared_labour = AdHocLabourPayment.objects.filter(
            accounting_period=period,
            cost_scope=CostScope.SHARED_PRODUCTION,
            cost_allocations__isnull=True,
        )
        if unallocated_shared_labour.exists():
            warnings.append(
                {
                    "code": "unallocated_shared_labour",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_shared_labour.count()} shared production "
                        "labour payment(s) are not allocated."
                    ),
                }
            )

        unallocated_production_consumables = ConsumableUsage.objects.filter(
            accounting_period=period,
            usage_scope=ConsumableUsageScope.SHARED_PRODUCTION,
            cost_allocations__isnull=True,
        )
        if unallocated_production_consumables.exists():
            warnings.append(
                {
                    "code": "unallocated_production_consumables",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_production_consumables.count()} shared "
                        "production consumable usage(s) are not allocated."
                    ),
                }
            )

        unallocated_selling_labour = AdHocLabourPayment.objects.filter(
            accounting_period=period,
            cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
            batch__isnull=True,
            cost_allocations__isnull=True,
        )
        if unallocated_selling_labour.exists():
            warnings.append(
                {
                    "code": "unallocated_selling_labour",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_selling_labour.count()} shared selling "
                        "labour payment(s) are not allocated."
                    ),
                }
            )

        unallocated_selling_expenses = SharedExpense.objects.filter(
            accounting_period=period,
            scope=SharedExpenseScope.SELLING_EXPENSE,
            directly_assigned_batch__isnull=True,
            cost_allocations__isnull=True,
        )
        if unallocated_selling_expenses.exists():
            warnings.append(
                {
                    "code": "unallocated_selling_expenses",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_selling_expenses.count()} shared selling "
                        "expense(s) are not allocated."
                    ),
                }
            )

        unallocated_selling_consumables = ConsumableUsage.objects.filter(
            accounting_period=period,
            usage_scope=ConsumableUsageScope.SELLING_AND_DISTRIBUTION,
            batch__isnull=True,
            cost_allocations__isnull=True,
        )
        if unallocated_selling_consumables.exists():
            warnings.append(
                {
                    "code": "unallocated_selling_consumables",
                    "severity": "warning",
                    "message": (
                        f"{unallocated_selling_consumables.count()} shared "
                        "selling consumable usage(s) are not allocated."
                    ),
                }
            )

        unlinked_capex = SharedExpense.objects.filter(
            accounting_period=period,
            recognition_type=ExpenseRecognitionType.CAPITAL_EXPENDITURE,
            capitalized_asset_links__isnull=True,
        )
        if unlinked_capex.exists():
            warnings.append(
                {
                    "code": "capital_expenditure_not_linked",
                    "severity": "warning",
                    "message": (
                        f"{unlinked_capex.count()} capital expenditure item(s) "
                        "are not linked to an asset."
                    ),
                }
            )

        depreciation_entries = AssetDepreciationEntry.objects.filter(
            accounting_period=period
        )
        unreconciled_depreciation = 0
        for entry in depreciation_entries:
            allocated = money(
                entry.cost_allocations.aggregate(total=Sum("allocated_amount"))[
                    "total"
                ]
            )
            expected = money(
                entry.period_depreciation
                * entry.asset.production_percentage
                / Decimal("100.00")
            )
            if expected and allocated != expected:
                unreconciled_depreciation += 1
        if unreconciled_depreciation:
            warnings.append(
                {
                    "code": "depreciation_allocations_not_reconciling",
                    "severity": "warning",
                    "message": (
                        f"{unreconciled_depreciation} depreciation allocation(s) "
                        "do not reconcile to the production share."
                    ),
                }
            )

    legacy_final_snapshots = BatchProfitabilitySnapshot.objects.filter(
        final=True,
        accounting_period__isnull=True,
    )
    if legacy_final_snapshots.exists():
        warnings.append(
            {
                "code": "legacy_final_snapshots_require_reconciliation",
                "severity": "warning",
                "message": (
                    f"{legacy_final_snapshots.count()} legacy batch snapshot(s) "
                    "must be reconciled by reopening and reclosing their "
                    "accounting period. They are excluded from final profit."
                ),
            }
        )

    expired_lots = SharedConsumableLot.objects.filter(
        expiry_date__lt=today,
        quantity_available__gt=0,
    )
    if expired_lots.exists():
        warnings.append(
            {
                "code": "expired_consumables",
                "severity": "warning",
                "message": (
                    f"{expired_lots.count()} consumable lot(s) are expired "
                    "and still show available stock."
                ),
            }
        )

    overdue_maintenance = Asset.objects.filter(
        status__in=[
            AssetStatus.AVAILABLE_FOR_USE,
            AssetStatus.IDLE,
            AssetStatus.UNDER_MAINTENANCE,
            AssetStatus.IMPAIRED,
        ],
        maintenance_records__next_due_date__lt=today,
    ).distinct()
    if overdue_maintenance.exists():
        warnings.append(
            {
                "code": "maintenance_overdue",
                "severity": "warning",
                "message": (
                    f"{overdue_maintenance.count()} asset(s) have overdue maintenance."
                ),
            }
        )

    return [finance_warning(**warning) for warning in warnings]


def dashboard_indicators() -> dict:
    latest_period = AccountingPeriod.objects.order_by("-period_start").first()
    active_batches = _active_production_batches()
    active_cost_exposure = Decimal("0.00")
    closed_batch_profit = money(
        BatchProfitabilitySnapshot.objects.filter(
            final=True,
            accounting_period__isnull=False,
        ).aggregate(
            total=Sum("batch_gross_profit")
        )["total"]
    )

    for batch in active_batches:
        data = batch_profitability(batch)
        active_cost_exposure += data["active_batch_cost_exposure"]

    receivable_total = money(
        Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED).aggregate(
            total=Sum("balance")
        )["total"]
    )

    latest_report = monthly_profitability_report(latest_period) if latest_period else None
    active_reports = [batch_profitability(batch) for batch in active_batches]
    forecast_profit = money(sum((row.get("forecast_final_profit", Decimal("0.00")) for row in active_reports), Decimal("0.00")))
    forecast_revenue = money(sum((row.get("forecast_revenue_at_completion", Decimal("0.00")) for row in active_reports), Decimal("0.00")))
    overdue_receivables = money(
        Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED)
        .filter(balance__gt=0, due_date__lt=timezone.localdate())
        .aggregate(total=Sum("balance"))["total"]
    )
    low_stock_count = SharedConsumableLot.objects.filter(
        quantity_available__gt=0,
        quantity_available__lte=F("quantity_purchased") * Decimal("0.20"),
    ).count()
    expiring_count = SharedConsumableLot.objects.filter(
        quantity_available__gt=0,
        expiry_date__lte=timezone.localdate() + timedelta(days=30),
    ).count()
    statement = latest_report.get("statement_of_financial_position", {}) if latest_report else {}
    close = latest_report.get("close_readiness", {}) if latest_report else {}
    current_cash = latest_report["cash_flow"]["closing_cash"] if latest_report else Decimal("0.00")
    mtd_net = latest_report["other_costs"]["net_profit_after_recorded_tax"] if latest_report else Decimal("0.00")
    ytd_revenue = latest_report.get("comparatives", {}).get("ytd_revenue", Decimal("0.00")) if latest_report else Decimal("0.00")

    return {
        "active_batches": active_batches.count(),
        "active_batch_cost_exposure": active_cost_exposure,
        "closed_batch_profit": closed_batch_profit,
        "receivables": receivable_total,
        "current_cash": current_cash,
        "mtd_net_result": mtd_net,
        "ytd_revenue": ytd_revenue,
        "overdue_receivables": overdue_receivables,
        "supplier_payables": statement.get("supplier_payables", Decimal("0.00")),
        "payroll_liabilities": statement.get("payroll_and_statutory_liabilities", Decimal("0.00")),
        "inventory_value": statement.get("consumable_inventory", Decimal("0.00")),
        "fixed_asset_carrying_amount": statement.get("fixed_assets_net", Decimal("0.00")),
        "poultry_wip_management_cost": statement.get("poultry_wip_management_cost", Decimal("0.00")),
        "active_batch_forecast_profit": forecast_profit,
        "active_batch_forecast_margin_percent": percent(forecast_profit, forecast_revenue),
        "low_stock_count": low_stock_count,
        "expiring_stock_count": expiring_count,
        "period_status": latest_period.status if latest_period else None,
        "close_readiness": close,
        "latest_month": latest_report,
        "warnings": dashboard_warnings(latest_period),
    }


def receivables_report(filters=None) -> dict:
    filters = filters or {}
    selected_status = filters.get("status", "open") if hasattr(filters, "get") else "open"
    sales = Sales.objects.all()
    if selected_status == PaymentStatus.CANCELLED:
        sales = sales.filter(payment_status=PaymentStatus.CANCELLED)
    else:
        sales = sales.exclude(payment_status=PaymentStatus.CANCELLED)
    batch_ids = filters.getlist("batch") if hasattr(filters, "getlist") else []
    if batch_ids:
        sales = sales.filter(batch_id__in=batch_ids)
    buyer = (filters.get("buyer", "") if hasattr(filters, "get") else "").strip()
    if buyer:
        sales = sales.filter(buyer_name__icontains=buyer)
    date_from = filters.get("date_from") if hasattr(filters, "get") else None
    date_to = filters.get("date_to") if hasattr(filters, "get") else None
    if date_from:
        sales = sales.filter(due_date__gte=date_from)
    if date_to:
        sales = sales.filter(due_date__lte=date_to)
    if selected_status == "paid":
        sales = sales.filter(balance=0)
    elif selected_status in {PaymentStatus.PARTIAL, PaymentStatus.UNPAID}:
        sales = sales.filter(payment_status=selected_status, balance__gt=0)
    elif selected_status == "overdue":
        sales = sales.filter(balance__gt=0, due_date__lt=timezone.localdate())
    elif selected_status == PaymentStatus.CANCELLED:
        pass
    elif selected_status != "all":
        sales = sales.filter(balance__gt=0)

    focus_sale = filters.get("sale") if hasattr(filters, "get") else None
    if focus_sale:
        sales = sales.filter(sale_id=focus_sale)

    open_sales = sales
    ordering = filters.get("ordering", "sale_date") if hasattr(filters, "get") else "sale_date"
    if ordering not in {"sale_date", "-sale_date", "due_date", "-due_date", "balance", "-balance"}:
        ordering = "sale_date"
    try:
        page_number = max(int(filters.get("page", 1)), 1)
        page_size = min(max(int(filters.get("page_size", 20)), 1), 100)
    except (TypeError, ValueError):
        page_number, page_size = 1, 20
    count = open_sales.count()
    page_count = max((count + page_size - 1) // page_size, 1)
    page_number = min(page_number, page_count)
    start = (page_number - 1) * page_size
    today = timezone.localdate()
    rows = [
        {
            "id": sale.pk,
            "sale_id": sale.sale_id,
            "batch": sale.batch_id,
            "batch_id": sale.batch.batch_id,
            "buyer_name": sale.buyer_name,
            "sale_date": sale.sale_date,
            "due_date": sale.due_date,
            "age_days": max((today - sale.sale_date.date()).days, 0),
            "days_overdue": max((today - sale.due_date).days, 0) if sale.due_date else 0,
            "sale_total": sale.sale_total,
            "amount_paid": sale.amount_paid,
            "balance": sale.balance,
            "payment_status": sale.payment_status,
            "receivable_status": (
                "cancelled"
                if sale.payment_status == PaymentStatus.CANCELLED
                else "overdue"
                if sale.due_date and sale.due_date < today and sale.balance > 0
                else "paid"
                if sale.balance == 0
                else "partially_paid"
                if sale.amount_paid > 0
                else "unpaid"
            ),
            "is_overdue": bool(sale.due_date and sale.due_date < today and sale.balance > 0),
            "payments": [
                {
                    "id": payment.pk,
                    "payment_reference": payment.payment_reference,
                    "amount": payment.amount,
                    "payment_date": payment.payment_date,
                    "payment_method": payment.payment_method,
                    "external_reference": payment.external_reference,
                    "received_by_name": payment.received_by_name,
                    "notes": payment.notes,
                    "status": payment.status,
                    "reversed_at": payment.reversed_at,
                    "reversal_reason": payment.reversal_reason,
                }
                for payment in sale.payments.all()
            ],
        }
        for sale in open_sales.select_related("batch").prefetch_related("payments").order_by(ordering, "pk")[start:start + page_size]
    ]
    return {
        "total_receivable": money(open_sales.aggregate(total=Sum("balance"))["total"]),
        "count": count,
        "page": page_number,
        "page_size": page_size,
        "pages": page_count,
        "next": page_number + 1 if page_number < page_count else None,
        "previous": page_number - 1 if page_number > 1 else None,
        "results": rows,
    }
