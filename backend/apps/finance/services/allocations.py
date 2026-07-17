from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.poultry.models import PaymentStatus, Sales

from ..models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationMethod,
    AllocationSourceType,
    BirdDaySnapshot,
    CostAllocation,
    CostScope,
    PayrollEntry,
    PeriodStatus,
    SharedExpense,
    SharedExpenseScope,
)
from .bird_days import CALCULATION_VERSION, recalculate_bird_day_snapshots


ALLOCATION_VERSION = "allocation-v1"
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def allocate_amount_by_driver(
    amount: Decimal,
    drivers: dict[int, Decimal],
) -> dict[int, Decimal]:
    clean_drivers = {
        key: Decimal(value)
        for key, value in drivers.items()
        if Decimal(value) > Decimal("0")
    }
    total_driver = sum(clean_drivers.values(), Decimal("0"))
    if amount == Decimal("0.00") or total_driver == Decimal("0"):
        return {}

    allocations: dict[int, Decimal] = {}
    ordered_keys = sorted(clean_drivers)
    allocated_total = Decimal("0.00")

    for key in ordered_keys[:-1]:
        share = _money(amount * clean_drivers[key] / total_driver)
        allocations[key] = share
        allocated_total += share

    last_key = ordered_keys[-1]
    allocations[last_key] = _money(amount - allocated_total)

    return allocations


def _driver_map(period: AccountingPeriod) -> dict[int, Decimal]:
    snapshots = BirdDaySnapshot.objects.filter(
        accounting_period=period,
        calculation_version=CALCULATION_VERSION,
        bird_days__gt=0,
    )
    return {snapshot.batch_id: snapshot.bird_days for snapshot in snapshots}


def _total_driver(drivers: dict[int, Decimal]) -> Decimal:
    return sum(drivers.values(), Decimal("0.0000"))


def _source_locked(source_filter: dict) -> bool:
    return CostAllocation.objects.filter(locked=True, **source_filter).exists()


def _create_allocation(
    *,
    period: AccountingPeriod,
    batch_id: int,
    source_type: str,
    allocation_method: str,
    allocated_amount: Decimal,
    driver_quantity: Decimal,
    total_driver_quantity: Decimal,
    generated_by,
    payroll_entry: PayrollEntry | None = None,
    ad_hoc_labour_payment: AdHocLabourPayment | None = None,
    shared_expense: SharedExpense | None = None,
) -> CostAllocation:
    percentage = Decimal("0.0000")
    if total_driver_quantity:
        percentage = (
            driver_quantity * Decimal("100") / total_driver_quantity
        ).quantize(Decimal("0.0001"))

    allocation = CostAllocation(
        accounting_period=period,
        batch_id=batch_id,
        source_type=source_type,
        payroll_entry=payroll_entry,
        ad_hoc_labour_payment=ad_hoc_labour_payment,
        shared_expense=shared_expense,
        allocation_method=allocation_method,
        driver_quantity=driver_quantity,
        total_driver_quantity=total_driver_quantity,
        allocation_percentage=percentage,
        allocated_amount=_money(allocated_amount),
        calculation_version=ALLOCATION_VERSION,
        generated_at=timezone.now(),
        generated_by=generated_by,
    )
    allocation.full_clean()
    allocation.save()
    return allocation


def _allocate_by_bird_days(
    *,
    period: AccountingPeriod,
    amount: Decimal,
    source_type: str,
    generated_by,
    payroll_entry: PayrollEntry | None = None,
    ad_hoc_labour_payment: AdHocLabourPayment | None = None,
    shared_expense: SharedExpense | None = None,
) -> list[CostAllocation]:
    drivers = _driver_map(period)
    total = _total_driver(drivers)
    shares = allocate_amount_by_driver(_money(amount), drivers)
    allocations = []

    for batch_id, allocated_amount in shares.items():
        allocations.append(
            _create_allocation(
                period=period,
                batch_id=batch_id,
                source_type=source_type,
                payroll_entry=payroll_entry,
                ad_hoc_labour_payment=ad_hoc_labour_payment,
                shared_expense=shared_expense,
                allocation_method=AllocationMethod.BIRD_DAYS,
                driver_quantity=drivers[batch_id],
                total_driver_quantity=total,
                allocated_amount=allocated_amount,
                generated_by=generated_by,
            )
        )

    return allocations


def _sales_revenue_drivers(period: AccountingPeriod) -> dict[int, Decimal]:
    revenue_expression = ExpressionWrapper(
        F("quantity_sold") * F("unit_price"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    rows = (
        Sales.objects.filter(
            sale_date__date__gte=period.period_start,
            sale_date__date__lte=period.period_end,
        )
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .values("batch_id")
        .annotate(revenue=Sum(revenue_expression))
    )

    drivers: dict[int, Decimal] = {}
    for row in rows:
        revenue = row["revenue"] or Decimal("0.00")
        if revenue > 0:
            drivers[row["batch_id"]] = revenue
    return drivers


def _allocate_by_revenue_share(
    *,
    period: AccountingPeriod,
    amount: Decimal,
    source_type: str,
    generated_by,
    payroll_entry: PayrollEntry | None = None,
    ad_hoc_labour_payment: AdHocLabourPayment | None = None,
    shared_expense: SharedExpense | None = None,
) -> list[CostAllocation]:
    drivers = _sales_revenue_drivers(period)
    total = _total_driver(drivers)
    shares = allocate_amount_by_driver(_money(amount), drivers)
    allocations = []
    for batch_id, allocated_amount in shares.items():
        allocations.append(
            _create_allocation(
                period=period,
                batch_id=batch_id,
                source_type=source_type,
                payroll_entry=payroll_entry,
                ad_hoc_labour_payment=ad_hoc_labour_payment,
                shared_expense=shared_expense,
                allocation_method=AllocationMethod.REVENUE_SHARE,
                driver_quantity=drivers[batch_id],
                total_driver_quantity=total,
                allocated_amount=allocated_amount,
                generated_by=generated_by,
            )
        )
    return allocations


@transaction.atomic
def regenerate_allocations_for_period(
    period: AccountingPeriod,
    *,
    generated_by=None,
) -> list[CostAllocation]:
    if period.status == PeriodStatus.CLOSED:
        raise ValueError("Closed accounting periods cannot be recalculated.")

    recalculate_bird_day_snapshots(period)
    CostAllocation.objects.filter(accounting_period=period, locked=False).delete()

    allocations: list[CostAllocation] = []

    for payroll_entry in PayrollEntry.objects.filter(accounting_period=period):
        if _source_locked({"payroll_entry": payroll_entry}):
            continue
        production_amount = payroll_entry.production_amount
        allocations.extend(
            _allocate_by_bird_days(
                period=period,
                amount=production_amount,
                source_type=AllocationSourceType.PAYROLL,
                payroll_entry=payroll_entry,
                generated_by=generated_by,
            )
        )

    for labour in AdHocLabourPayment.objects.filter(accounting_period=period):
        if _source_locked({"ad_hoc_labour_payment": labour}):
            continue

        if labour.cost_scope == CostScope.BATCH_DIRECT and labour.batch_id:
            allocations.append(
                _create_allocation(
                    period=period,
                    batch_id=labour.batch_id,
                    source_type=AllocationSourceType.AD_HOC_LABOUR,
                    ad_hoc_labour_payment=labour,
                    allocation_method=AllocationMethod.DIRECT,
                    driver_quantity=Decimal("1.0000"),
                    total_driver_quantity=Decimal("1.0000"),
                    allocated_amount=labour.payment_amount,
                    generated_by=generated_by,
                )
            )
        elif labour.cost_scope == CostScope.SHARED_PRODUCTION:
            allocations.extend(
                _allocate_by_bird_days(
                    period=period,
                    amount=labour.payment_amount,
                    source_type=AllocationSourceType.AD_HOC_LABOUR,
                    ad_hoc_labour_payment=labour,
                    generated_by=generated_by,
                )
            )
        elif (
            labour.cost_scope == CostScope.SELLING_AND_DISTRIBUTION
            and labour.batch_id
        ):
            allocations.append(
                _create_allocation(
                    period=period,
                    batch_id=labour.batch_id,
                    source_type=AllocationSourceType.AD_HOC_LABOUR,
                    ad_hoc_labour_payment=labour,
                    allocation_method=AllocationMethod.DIRECT,
                    driver_quantity=Decimal("1.0000"),
                    total_driver_quantity=Decimal("1.0000"),
                    allocated_amount=labour.payment_amount,
                    generated_by=generated_by,
                )
            )
        elif labour.cost_scope == CostScope.SELLING_AND_DISTRIBUTION:
            allocations.extend(
                _allocate_by_revenue_share(
                    period=period,
                    amount=labour.payment_amount,
                    source_type=AllocationSourceType.AD_HOC_LABOUR,
                    ad_hoc_labour_payment=labour,
                    generated_by=generated_by,
                )
            )

    for expense in SharedExpense.objects.filter(accounting_period=period):
        if _source_locked({"shared_expense": expense}):
            continue

        if expense.scope == SharedExpenseScope.SHARED_PRODUCTION:
            if expense.directly_assigned_batch_id:
                allocations.append(
                    _create_allocation(
                        period=period,
                        batch_id=expense.directly_assigned_batch_id,
                        source_type=AllocationSourceType.SHARED_EXPENSE,
                        shared_expense=expense,
                        allocation_method=AllocationMethod.DIRECT,
                        driver_quantity=Decimal("1.0000"),
                        total_driver_quantity=Decimal("1.0000"),
                        allocated_amount=expense.amount,
                        generated_by=generated_by,
                    )
                )
            else:
                allocations.extend(
                    _allocate_by_bird_days(
                        period=period,
                        amount=expense.amount,
                        source_type=AllocationSourceType.SHARED_EXPENSE,
                        shared_expense=expense,
                        generated_by=generated_by,
                    )
                )
        elif expense.scope == SharedExpenseScope.SELLING_EXPENSE:
            if expense.directly_assigned_batch_id:
                allocations.append(
                    _create_allocation(
                        period=period,
                        batch_id=expense.directly_assigned_batch_id,
                        source_type=AllocationSourceType.SHARED_EXPENSE,
                        shared_expense=expense,
                        allocation_method=AllocationMethod.DIRECT,
                        driver_quantity=Decimal("1.0000"),
                        total_driver_quantity=Decimal("1.0000"),
                        allocated_amount=expense.amount,
                        generated_by=generated_by,
                    )
                )
            else:
                allocations.extend(
                    _allocate_by_revenue_share(
                        period=period,
                        amount=expense.amount,
                        source_type=AllocationSourceType.SHARED_EXPENSE,
                        shared_expense=expense,
                        generated_by=generated_by,
                    )
                )

    return allocations
