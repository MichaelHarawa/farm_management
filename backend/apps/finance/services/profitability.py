from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.poultry.models import (
    Batch,
    BatchStatus,
    InputCosts,
    PaymentStatus,
    ProductType,
    Sales,
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
from apps.poultry.services.batch_lifecycle import calculate_bird_balance


ZERO = Decimal("0.00")


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
    return _sum_decimal(InputCosts.objects.filter(batch=batch), expression)


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
    return money(valid_sales(batch).aggregate(total=Sum("amount_paid"))["total"])


def receivables(batch: Batch) -> Decimal:
    return money(valid_sales(batch).aggregate(total=Sum("balance"))["total"])


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
    return money(
        payroll.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(shared_labour.aggregate(total=Sum("allocated_amount"))["total"]) + money(
        shared_expenses.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        consumables.aggregate(total=Sum("allocated_amount"))["total"]
    ) + money(
        depreciation.aggregate(total=Sum("allocated_amount"))["total"]
    )


def selling_cost_total(batch: Batch) -> Decimal:
    labour = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.AD_HOC_LABOUR,
        ad_hoc_labour_payment__cost_scope=CostScope.SELLING_AND_DISTRIBUTION,
    )
    expenses = CostAllocation.objects.filter(
        batch=batch,
        source_type=AllocationSourceType.SHARED_EXPENSE,
        shared_expense__scope=SharedExpenseScope.SELLING_EXPENSE,
    )
    return money(labour.aggregate(total=Sum("allocated_amount"))["total"]) + money(
        expenses.aggregate(total=Sum("allocated_amount"))["total"]
    )


def batch_profitability(batch: Batch) -> dict:
    balance = calculate_bird_balance(batch)
    revenue = sales_revenue(batch)
    collected = cash_collected(batch)
    outstanding = receivables(batch)
    direct_cost = (
        input_cost_total(batch)
        + direct_labour_total(batch)
        + direct_production_expense_total(batch)
        + direct_consumable_usage_total(batch)
    )
    allocated_cost = allocated_production_total(batch)
    total_production_cost = direct_cost + allocated_cost
    gross_profit = revenue - total_production_cost
    selling_cost = selling_cost_total(batch)
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

    break_even_price = None
    if remaining:
        break_even_price = money(max(total_production_cost - revenue, ZERO) / remaining)

    return {
        "batch": batch.pk,
        "batch_id": batch.batch_id,
        "status": batch.status,
        "profitability_status": "final" if is_final else "provisional",
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
        "additional_revenue_required_to_break_even": max(
            total_production_cost - revenue,
            ZERO,
        ),
        "active_batch_cost_exposure": (
            total_production_cost if not is_final else ZERO
        ),
    }


def create_final_snapshot(batch: Batch, *, generated_by=None) -> BatchProfitabilitySnapshot:
    data = batch_profitability(batch)
    snapshot, _ = BatchProfitabilitySnapshot.objects.get_or_create(
        batch=batch,
        final=True,
        defaults={
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
