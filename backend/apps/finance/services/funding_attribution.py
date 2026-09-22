from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from ..models import CostAllocation, Expenditure, PayrollEntry
from .allocations import allocate_amount_by_driver


ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(Decimal("0.01"))


def _beneficiary_shares(
    *,
    amount: Decimal,
    total_cost: Decimal,
    allocations: Iterable[CostAllocation],
) -> dict:
    allocation_rows = list(allocations)
    drivers = {
        row.pk: Decimal(row.allocated_amount)
        for row in allocation_rows
        if Decimal(row.allocated_amount) > ZERO
    }
    allocated_cost = sum(drivers.values(), ZERO)
    farm_wide_driver = max(Decimal(total_cost) - allocated_cost, ZERO)
    if farm_wide_driver > ZERO:
        drivers[0] = farm_wide_driver
    elif not drivers:
        drivers[0] = Decimal(total_cost) if Decimal(total_cost) > ZERO else Decimal("1")

    shares = allocate_amount_by_driver(money(amount), drivers)
    batch_amounts: dict[int, Decimal] = {}
    allocation_shares: dict[int, Decimal] = {}
    farm_wide = shares.get(0, ZERO)
    by_id = {row.pk: row for row in allocation_rows}
    for allocation_id, share in shares.items():
        if allocation_id == 0:
            continue
        allocation_shares[allocation_id] = share
        row = by_id[allocation_id]
        batch_amounts[row.batch_id] = money(
            batch_amounts.get(row.batch_id, ZERO) + share
        )

    return {
        "batch_amounts": batch_amounts,
        "farm_wide": money(farm_wide),
        "allocation_shares": allocation_shares,
        "reconciled_total": money(sum(shares.values(), ZERO)),
    }


def expenditure_payment_beneficiary_shares(
    expenditure: Expenditure,
    amount: Decimal,
) -> dict:
    """Allocate one payment across every beneficiary before any batch filter."""

    return _beneficiary_shares(
        amount=amount,
        total_cost=money(expenditure.amount),
        allocations=expenditure.cost_allocations.all(),
    )


def payroll_payment_beneficiary_shares(
    payroll_entry: PayrollEntry,
    amount: Decimal,
) -> dict:
    """Allocate a cash salary payment over its stored payroll cost beneficiaries."""

    return _beneficiary_shares(
        amount=amount,
        total_cost=money(payroll_entry.total_employer_cost),
        allocations=payroll_entry.cost_allocations.all(),
    )
