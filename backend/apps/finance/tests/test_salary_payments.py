from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.finance.models import (
    AccountingPeriod, AllocationSourceType, CostAllocation, EmployeeProfile, EmploymentType,
    FinancePaymentStatus, FundingReceipt, FundingSource, FundingSourceType,
    PayrollPayment, PayrollPaymentStatus,
)
from apps.finance.services.payroll import generate_payroll_for_period
from apps.finance.services.expenditures import record_expenditure_payment
from apps.finance.services.profitability import (
    available_funding_source_cash,
    batch_profitability,
)
from apps.finance.services.salary_payments import (
    record_salary_payment, reverse_salary_payment, set_salary_cost_allocations,
)
from apps.poultry.models import Batch, ChicksSource


class SalaryPaymentLedgerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_superuser(username="payroll-manager", email="manager@payroll.test")
        employee_user = User.objects.create_user(username="payroll-worker", email="worker@payroll.test")
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
        )
        EmployeeProfile.objects.create(
            user=employee_user, employee_number="PAY-001", employment_type=EmploymentType.PERMANENT,
            job_title="Flock attendant", employment_start_date=date(2025, 1, 1),
            base_monthly_salary=Decimal("300.00"), production_percentage=Decimal("100.00"),
            administration_percentage=Decimal("0.00"), selling_percentage=Decimal("0.00"),
            created_by=self.manager,
        )
        self.entry = generate_payroll_for_period(self.period, created_by=self.manager)[0]
        self.entry.deductions = Decimal("30.00")
        self.entry.save()
        self.batch_a = self.batch("SAL-A")
        self.batch_b = self.batch("SAL-B")
        self.source = FundingSource.objects.create(
            source_type=FundingSourceType.OWNER_CAPITAL, description="Payroll bank account"
        )
        FundingReceipt.objects.create(
            funding_source=self.source, amount=Decimal("500.00"),
            receipt_date=timezone.make_aware(datetime.combine(date(2026, 1, 1), time(hour=8))),
            created_by=self.manager,
        )

    def batch(self, code):
        arrival = timezone.make_aware(datetime.combine(date(2026, 1, 1), time(hour=8)))
        return Batch.objects.create(
            batch_id=code, bird_type="broilers", source=ChicksSource.PROTO,
            entry_date=arrival, expected_maturity_date=arrival, quantity=100,
            actual_quantity_received=100, created_by=self.manager,
        )

    def pay(self, amount, key):
        return record_salary_payment(
            payroll_entry_id=self.entry.pk, amount=amount, payment_date="2026-01-31",
            payment_method="Bank transfer",
            funding_rows=[{"funding_source": self.source.pk, "amount": amount}],
            idempotency_key=key, external_reference="BANK-1", user=self.manager,
        )

    def test_partial_full_duplicate_and_reversal(self):
        first = self.pay("100.00", "salary-partial")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.payment_status, FinancePaymentStatus.PARTIAL)
        self.assertEqual(self.entry.outstanding_salary, Decimal("170.00"))
        retry = self.pay("100.00", "salary-partial")
        self.assertEqual(retry.pk, first.pk)
        second = self.pay("170.00", "salary-final")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.payment_status, FinancePaymentStatus.PAID)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("230.00"))
        reverse_salary_payment(payment_id=second.pk, reason="Bank rejected transfer", user=self.manager)
        second.refresh_from_db(); self.entry.refresh_from_db()
        self.assertEqual(second.status, PayrollPaymentStatus.REVERSED)
        self.assertEqual(self.entry.outstanding_salary, Decimal("170.00"))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("400.00"))

    def test_salary_cost_split_is_independent_of_funding(self):
        set_salary_cost_allocations(
            payroll_entry_id=self.entry.pk,
            rows=[
                {"beneficiary_type": "batch", "batch": self.batch_a.pk, "amount": "150.00"},
                {"beneficiary_type": "batch", "batch": self.batch_b.pk, "amount": "90.00"},
                {"beneficiary_type": "administration", "amount": "60.00"},
            ],
            user=self.manager,
        )
        allocations = {row.batch_id: row.allocated_amount for row in CostAllocation.objects.filter(payroll_entry=self.entry)}
        self.assertEqual(allocations, {self.batch_a.pk: Decimal("150.00"), self.batch_b.pk: Decimal("90.00")})
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))

    def test_salary_paid_through_expenditure_is_reconciled_once(self):
        set_salary_cost_allocations(
            payroll_entry_id=self.entry.pk,
            rows=[
                {"beneficiary_type": "batch", "batch": self.batch_a.pk, "amount": "150.00"},
                {"beneficiary_type": "batch", "batch": self.batch_b.pk, "amount": "90.00"},
                {"beneficiary_type": "administration", "amount": "60.00"},
            ],
            user=self.manager,
        )
        self.entry.refresh_from_db()
        expenditure = self.entry.expenditure

        # Guard against a projected salary expenditure being allocated as a
        # second economic cost in addition to its payroll allocation.
        CostAllocation.objects.create(
            accounting_period=self.period,
            batch=self.batch_a,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure=expenditure,
            allocation_method="manual",
            driver_quantity=Decimal("150.00"),
            total_driver_quantity=Decimal("300.00"),
            allocation_percentage=Decimal("50.00"),
            allocated_amount=Decimal("150.00"),
            generated_by=self.manager,
        )
        self.assertEqual(
            batch_profitability(self.batch_a)["allocated_production_cost"],
            Decimal("150.00"),
        )

        record_expenditure_payment(
            expenditure_id=expenditure.pk,
            funding_rows=[{"funding_source": self.source.pk, "amount": "300.00"}],
            payment_group_key="salary-through-expenditure",
            payment_date=date(2026, 1, 31),
            user=self.manager,
        )
        self.entry.refresh_from_db()
        expenditure.refresh_from_db()

        self.assertEqual(self.entry.amount_paid, Decimal("270.00"))
        self.assertEqual(self.entry.payment_status, FinancePaymentStatus.PAID)
        self.assertEqual(expenditure.payment_status, "paid")
        self.assertEqual(available_funding_source_cash(self.source), Decimal("200.00"))
        with self.assertRaisesMessage(
            ValidationError, "already being paid through its linked expenditure"
        ):
            self.pay("1.00", "duplicate-payment-channel")

    def test_insufficient_funding_rolls_back(self):
        low_source = FundingSource.objects.create(
            source_type=FundingSourceType.OWNER_CAPITAL, description="Small cash account"
        )
        FundingReceipt.objects.create(
            funding_source=low_source, amount=Decimal("100.00"),
            receipt_date=timezone.make_aware(datetime.combine(date(2026, 1, 1), time(hour=8))),
            created_by=self.manager,
        )
        with self.assertRaises(ValidationError):
            record_salary_payment(
                payroll_entry_id=self.entry.pk, amount="270.00", payment_date="2026-01-31",
                payment_method="Cash", funding_rows=[{"funding_source": low_source.pk, "amount": "270.00"}],
                idempotency_key="insufficient", external_reference="", user=self.manager,
            )
        self.assertFalse(PayrollPayment.objects.filter(idempotency_key="insufficient").exists())
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
