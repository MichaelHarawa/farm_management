from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db import models

from ..models import (
    AccountingPeriod,
    EmployeeProfile,
    EmployeeSalaryAdjustment,
    EmploymentType,
    PayrollEntry,
    PeriodStatus,
)


def salary_for_period(
    employee: EmployeeProfile,
    period: AccountingPeriod,
) -> Decimal:
    """Return the configured monthly salary at the start of a payroll period."""

    adjustments = EmployeeSalaryAdjustment.objects.filter(employee=employee)
    applicable = (
        adjustments.filter(
            effective_period__period_start__lte=period.period_start,
        )
        .select_related("effective_period")
        .order_by("-effective_period__period_start", "-pk")
        .first()
    )
    if applicable:
        return applicable.new_salary

    first_adjustment = (
        adjustments.select_related("effective_period")
        .order_by("effective_period__period_start", "pk")
        .first()
    )
    if first_adjustment:
        return first_adjustment.previous_salary
    return employee.base_monthly_salary


@transaction.atomic
def record_salary_adjustment(
    *,
    employee: EmployeeProfile,
    effective_period: AccountingPeriod,
    new_salary,
    reason: str,
    created_by=None,
) -> EmployeeSalaryAdjustment:
    """Schedule a chronological salary change without rewriting generated payroll."""

    employee = EmployeeProfile.objects.select_for_update().get(pk=employee.pk)
    effective_period = AccountingPeriod.objects.get(pk=effective_period.pk)
    if effective_period.status == PeriodStatus.CLOSED:
        raise ValueError("A salary change cannot start in a closed accounting period.")
    if effective_period.period_end < employee.employment_start_date:
        raise ValueError("The effective period is before this employee's start date.")
    if (
        employee.employment_end_date
        and effective_period.period_start > employee.employment_end_date
    ):
        raise ValueError("The effective period is after this employee's end date.")

    try:
        configured_salary = Decimal(str(new_salary)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError("Enter a valid new monthly salary.") from error
    if configured_salary <= 0:
        raise ValueError("The new monthly salary must be greater than zero.")

    latest_adjustment = (
        EmployeeSalaryAdjustment.objects.filter(employee=employee)
        .select_related("effective_period")
        .order_by("-effective_period__period_start", "-pk")
        .first()
    )
    if (
        latest_adjustment
        and effective_period.period_start
        <= latest_adjustment.effective_period.period_start
    ):
        raise ValueError(
            "Choose a period after the employee's latest salary adjustment."
        )
    if PayrollEntry.objects.filter(
        employee=employee,
        accounting_period__period_start__gte=effective_period.period_start,
    ).exists():
        raise ValueError(
            "Payroll has already been generated for this or a later period. "
            "Choose a later open period."
        )

    previous_salary = salary_for_period(employee, effective_period)
    if configured_salary == previous_salary:
        raise ValueError("The new salary must differ from the current salary.")
    reason = reason.strip()
    if not reason:
        raise ValueError("Explain why the salary is changing.")

    adjustment = EmployeeSalaryAdjustment.objects.create(
        employee=employee,
        effective_period=effective_period,
        previous_salary=previous_salary,
        new_salary=configured_salary,
        reason=reason,
        created_by=created_by,
    )
    employee.base_monthly_salary = configured_salary
    employee.save()
    return adjustment


@transaction.atomic
def generate_payroll_for_period(
    period: AccountingPeriod,
    *,
    created_by=None,
) -> list[PayrollEntry]:
    if period.status == PeriodStatus.CLOSED:
        raise ValueError("Cannot generate payroll for a closed period.")

    employees = EmployeeProfile.objects.select_related("user").filter(
        is_active=True,
        employment_type=EmploymentType.PERMANENT,
        employment_start_date__lte=period.period_end,
    ).filter(
        models.Q(employment_end_date__isnull=True)
        | models.Q(employment_end_date__gte=period.period_start)
    )

    entries: list[PayrollEntry] = []
    for employee in employees:
        gross_salary = salary_for_period(employee, period)
        entry, _ = PayrollEntry.objects.get_or_create(
            accounting_period=period,
            employee=employee,
            defaults={
                "gross_salary": gross_salary,
                "employer_costs": Decimal("0.00"),
                "deductions": Decimal("0.00"),
                "total_employer_cost": gross_salary,
                "production_percentage": employee.production_percentage,
                "administration_percentage": employee.administration_percentage,
                "selling_percentage": employee.selling_percentage,
                "created_by": created_by,
            },
        )
        from .salary_payments import create_deduction_liability, ensure_salary_expense

        create_deduction_liability(entry)
        ensure_salary_expense(entry, user=created_by)
        entries.append(entry)

    return entries
