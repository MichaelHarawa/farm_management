from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.finance.models import (
    AccountingPeriod,
    EmployeeProfile,
    EmployeeSalaryAdjustment,
    EmploymentType,
)
from apps.finance.services.payroll import (
    generate_payroll_for_period,
    record_salary_adjustment,
)


class EmployeeSalaryAdjustmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_superuser(
            username="salary-manager",
            email="salary-manager@example.com",
        )
        employee_user = User.objects.create_user(
            username="salary-worker",
            email="salary-worker@example.com",
        )
        self.employee = EmployeeProfile.objects.create(
            user=employee_user,
            employee_number="SAL-001",
            employment_type=EmploymentType.PERMANENT,
            job_title="Farm attendant",
            employment_start_date=date(2025, 1, 1),
            base_monthly_salary=Decimal("100000.00"),
            production_percentage=Decimal("70.00"),
            administration_percentage=Decimal("20.00"),
            selling_percentage=Decimal("10.00"),
            created_by=self.manager,
        )
        self.january = self.period(1, 31)
        self.february = self.period(2, 28)
        self.march = self.period(3, 31)

    @staticmethod
    def period(month, end_day):
        return AccountingPeriod.objects.create(
            period_start=date(2026, month, 1),
            period_end=date(2026, month, end_day),
        )

    def test_increase_and_reduction_apply_only_to_future_generated_payroll(self):
        january_entry = generate_payroll_for_period(
            self.january,
            created_by=self.manager,
        )[0]

        increase = record_salary_adjustment(
            employee=self.employee,
            effective_period=self.february,
            new_salary="120000.00",
            reason="Annual salary review",
            created_by=self.manager,
        )
        february_entry = generate_payroll_for_period(
            self.february,
            created_by=self.manager,
        )[0]
        reduction = record_salary_adjustment(
            employee=self.employee,
            effective_period=self.march,
            new_salary="110000.00",
            reason="Reduced working schedule",
            created_by=self.manager,
        )
        march_entry = generate_payroll_for_period(
            self.march,
            created_by=self.manager,
        )[0]

        january_entry.refresh_from_db()
        self.employee.refresh_from_db()
        self.assertEqual(january_entry.gross_salary, Decimal("100000.00"))
        self.assertEqual(february_entry.gross_salary, Decimal("120000.00"))
        self.assertEqual(march_entry.gross_salary, Decimal("110000.00"))
        self.assertEqual(increase.change_type, "increase")
        self.assertEqual(reduction.change_type, "reduction")
        self.assertEqual(self.employee.base_monthly_salary, Decimal("110000.00"))

    def test_adjustment_endpoint_records_auditable_change(self):
        client = APIClient()
        client.force_authenticate(self.manager)

        response = client.post(
            "/api/v1/finance/salary-adjustments",
            {
                "employee": self.employee.pk,
                "effective_period": self.february.pk,
                "new_salary": "125000.00",
                "reason": "Promotion to lead attendant",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["change_type"], "increase")
        self.assertEqual(response.data["previous_salary"], "100000.00")
        adjustment = EmployeeSalaryAdjustment.objects.get()
        self.assertEqual(adjustment.created_by, self.manager)
        self.assertEqual(adjustment.reason, "Promotion to lead attendant")

    def test_generated_period_cannot_be_repriced(self):
        generate_payroll_for_period(self.february, created_by=self.manager)

        with self.assertRaisesMessage(ValueError, "Payroll has already been generated"):
            record_salary_adjustment(
                employee=self.employee,
                effective_period=self.february,
                new_salary="90000.00",
                reason="Reduced working schedule",
                created_by=self.manager,
            )
