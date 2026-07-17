from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db import models

from ..models import (
    AccountingPeriod,
    EmployeeProfile,
    EmploymentType,
    PayrollEntry,
    PeriodStatus,
)


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
        entry, _ = PayrollEntry.objects.get_or_create(
            accounting_period=period,
            employee=employee,
            defaults={
                "gross_salary": employee.base_monthly_salary,
                "employer_costs": Decimal("0.00"),
                "deductions": Decimal("0.00"),
                "total_employer_cost": employee.base_monthly_salary,
                "production_percentage": employee.production_percentage,
                "administration_percentage": employee.administration_percentage,
                "selling_percentage": employee.selling_percentage,
                "created_by": created_by,
            },
        )
        entries.append(entry)

    return entries
