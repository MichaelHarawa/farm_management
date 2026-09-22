from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (
    AccountingNature,
    AccountingPeriod,
    AllocationMethod,
    AllocationSourceType,
    CostAllocation,
    Expenditure,
    ExpenditurePaymentStatus,
    ExpenditureStatus,
    FinanceActionEvent,
    FundingAllocation,
    FundingClassification,
    FundingReceipt,
    FundingSource,
    FundingSourceType,
    OwnerContributor,
    OwnerDesignationStatus,
    PeriodStatus,
)
from apps.finance.services.owner_capital import (
    owner_contribution_report,
    record_owner_contribution,
    reverse_funding_receipt,
    reverse_owner_designation,
)
from apps.poultry.models import Batch, ChicksSource


User = get_user_model()


def aware(day: date):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


class OwnerCapitalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="owner-admin", email="owner-admin@example.com", password="password"
        )
        self.manager = User.objects.create_user(
            username="owner-manager", email="owner-manager@example.com", password="password"
        )
        admin_role, _ = Role.objects.get_or_create(
            slug=RoleChoices.ADMIN, defaults={"name": "Administrator"}
        )
        manager_role, _ = Role.objects.get_or_create(
            slug=RoleChoices.FARM_MANAGER, defaults={"name": "Farm manager"}
        )
        self.admin.roles.add(admin_role)
        self.manager.roles.add(manager_role)
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
        )
        self.batch_a = self.make_batch("OWNER-A")
        self.batch_b = self.make_batch("OWNER-B")
        self.owner = OwnerContributor.objects.create(
            display_name="Lead owner", created_by=self.admin
        )

    def make_batch(self, code):
        return Batch.objects.create(
            batch_id=code,
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 9, 1)),
            expected_maturity_date=aware(date(2026, 10, 13)),
            quantity=100,
            created_by=self.admin,
        )

    def contribution(self, *, amount="1000000.00", key="owner-capital-one"):
        contribution_amount = Decimal(amount)
        return record_owner_contribution(
            owner_id=self.owner.pk,
            amount=amount,
            receipt_date=date(2026, 9, 2),
            reference="BANK-001",
            notes="Initial working capital",
            designations=[
                {"batch": self.batch_a.pk, "amount": contribution_amount * Decimal("0.60")},
                {"batch": self.batch_b.pk, "amount": contribution_amount * Decimal("0.40")},
            ],
            designation_date=date(2026, 9, 2),
            idempotency_key=key,
            user=self.admin,
        )

    def paid_expenditure(self, source, amount, rows, *, classification="reinvestment"):
        owner_equity_outflow = classification in {
            FundingClassification.OWNER_CAPITAL_RETURN,
            FundingClassification.OWNER_DRAWING,
            FundingClassification.OWNER_DISTRIBUTION,
        }
        expenditure = Expenditure.objects.create(
            expenditure_date=date(2026, 9, 5),
            accounting_period=self.period,
            amount=Decimal(amount),
            accounting_nature=(
                AccountingNature.OWNER_WITHDRAWAL
                if owner_equity_outflow
                else AccountingNature.DIRECT_COST
            ),
            description=f"Owner-funded cost {amount}",
            status=ExpenditureStatus.POSTED,
            payment_status=ExpenditurePaymentStatus.PAID,
            created_by=self.admin,
            posted_by=self.admin,
            posted_at=timezone.now(),
        )
        for batch, allocated_amount in rows:
            CostAllocation.objects.create(
                accounting_period=self.period,
                batch=batch,
                source_type=AllocationSourceType.EXPENDITURE,
                expenditure=expenditure,
                allocation_method=AllocationMethod.MANUAL,
                allocation_percentage=Decimal("0.0000"),
                allocated_amount=Decimal(allocated_amount),
                generated_by=self.admin,
                manual_reason="Owner report fixture",
            )
        FundingAllocation.objects.create(
            expenditure=expenditure,
            funding_source=source,
            amount=Decimal(amount),
            allocation_date=date(2026, 9, 5),
            classification=classification,
            created_by=self.admin,
        )
        return expenditure

    def test_receipt_is_counted_once_and_actual_use_is_attributed_by_batch(self):
        receipt, created = self.contribution()
        self.assertTrue(created)
        self.paid_expenditure(
            receipt.funding_source,
            "500000.00",
            [(self.batch_a, "300000.00"), (self.batch_b, "200000.00")],
        )

        report = owner_contribution_report(date_to=date(2026, 9, 30))

        self.assertEqual(report["summary"]["cash_introduced_to_date"], Decimal("1000000.00"))
        self.assertEqual(report["summary"]["designated_to_batches_as_of"], Decimal("1000000.00"))
        self.assertEqual(report["summary"]["cash_used_to_date"], Decimal("500000.00"))
        self.assertEqual(report["summary"]["closing_cash_balance"], Decimal("500000.00"))
        by_batch = {row["batch_code"]: row for row in report["batches"]}
        self.assertEqual(by_batch["OWNER-A"]["owner_cash_spent_to_date"], Decimal("300000.00"))
        self.assertEqual(by_batch["OWNER-B"]["owner_cash_spent_to_date"], Decimal("200000.00"))
        selected = owner_contribution_report(
            date_to=date(2026, 9, 30), batch_ids={self.batch_a.pk}
        )
        self.assertEqual(selected["summary"]["cash_used_to_date"], Decimal("500000.00"))
        self.assertEqual(
            selected["selected_batch_summary"]["owner_cash_spent_to_date"],
            Decimal("300000.00"),
        )
        period = owner_contribution_report(
            date_from=date(2026, 9, 4), date_to=date(2026, 9, 30)
        )
        self.assertEqual(period["summary"]["opening_cash_balance"], Decimal("1000000.00"))
        self.assertEqual(period["summary"]["cash_used_in_period"], Decimal("500000.00"))
        self.assertEqual(period["timeline_closing_cash_balance"], Decimal("500000.00"))

    def test_complete_beneficiary_set_allocates_rounding_cent_deterministically(self):
        receipt, _ = self.contribution(amount="100.00", key="rounding")
        batch_c = self.make_batch("OWNER-C")
        self.paid_expenditure(
            receipt.funding_source,
            "100.00",
            [
                (self.batch_a, "33.33"),
                (self.batch_b, "33.33"),
                (batch_c, "33.34"),
            ],
        )
        report = owner_contribution_report(
            date_to=date(2026, 9, 30), batch_ids={self.batch_a.pk}
        )
        self.assertEqual(report["summary"]["cash_used_to_date"], Decimal("100.00"))
        self.assertEqual(len(report["batches"]), 1)
        self.assertIn(
            report["batches"][0]["owner_cash_spent_to_date"],
            {Decimal("33.33"), Decimal("33.34")},
        )

    def test_capital_return_reduces_net_capital_but_drawing_does_not(self):
        receipt, _ = self.contribution()
        self.paid_expenditure(
            receipt.funding_source,
            "100000.00",
            [],
            classification=FundingClassification.OWNER_CAPITAL_RETURN,
        )
        self.paid_expenditure(
            receipt.funding_source,
            "50000.00",
            [],
            classification=FundingClassification.OWNER_DRAWING,
        )
        report = owner_contribution_report(date_to=date(2026, 9, 30))
        self.assertEqual(report["summary"]["net_contributed_capital"], Decimal("900000.00"))
        self.assertEqual(report["summary"]["owner_drawings_to_date"], Decimal("50000.00"))
        self.assertEqual(report["summary"]["closing_cash_balance"], Decimal("850000.00"))

    def test_idempotency_reuses_same_receipt_and_rejects_changed_payload(self):
        first, _ = self.contribution()
        second, created = self.contribution()
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        with self.assertRaises(ValidationError):
            self.contribution(amount="999999.00")

    def test_designation_and_receipt_reversals_are_dated_and_audited(self):
        receipt, _ = self.contribution()
        designation = receipt.owner_designations.get(batch=self.batch_a)
        reverse_owner_designation(
            designation_id=designation.pk, reason="Designation corrected", user=self.admin
        )
        designation.refresh_from_db()
        self.assertEqual(designation.status, OwnerDesignationStatus.REVERSED)
        reverse_funding_receipt(
            receipt_id=receipt.pk, reason="Bank receipt reversed", user=self.admin
        )
        historical = owner_contribution_report(date_to=date(2026, 9, 3))
        self.assertEqual(
            historical["summary"]["cash_introduced_to_date"], Decimal("1000000.00")
        )
        self.assertTrue(
            FinanceActionEvent.objects.filter(action="owner_contribution_reversed").exists()
        )
        event = FinanceActionEvent.objects.first()
        with self.assertRaises(DjangoValidationError):
            event.delete()

    def test_spent_receipt_cannot_be_reversed(self):
        receipt, _ = self.contribution()
        self.paid_expenditure(
            receipt.funding_source, "10.00", [(self.batch_a, "10.00")]
        )
        with self.assertRaises(ValidationError):
            reverse_funding_receipt(
                receipt_id=receipt.pk, reason="Cannot remove spent cash", user=self.admin
            )

    def test_legacy_owner_source_is_reported_without_guessing_identity(self):
        source = FundingSource.objects.create(
            source_type=FundingSourceType.OWNER_CAPITAL,
            description="Old equity import",
        )
        FundingReceipt.objects.create(
            funding_source=source,
            amount=Decimal("250.00"),
            receipt_date=aware(date(2026, 9, 1)),
            created_by=self.admin,
        )
        report = owner_contribution_report(date_to=date(2026, 9, 30), unknown_owner=True)
        self.assertEqual(report["summary"]["unknown_owner_receipt_count"], 1)
        self.assertEqual(report["owners"][0]["owner_name"], "Unknown legacy owner")

    def test_owner_endpoints_are_protected_and_generic_picker_redacts_identity(self):
        receipt, _ = self.contribution()
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        manager_client = APIClient()
        manager_client.force_authenticate(self.manager)

        self.assertEqual(
            admin_client.get("/api/v1/finance/reports/owner-contributions").status_code,
            200,
        )
        self.assertEqual(
            manager_client.get("/api/v1/finance/reports/owner-contributions").status_code,
            403,
        )
        picker = manager_client.get(
            "/api/v1/finance/funding-sources",
            {"source_type": FundingSourceType.OWNER_CAPITAL},
        )
        self.assertEqual(picker.status_code, 200)
        self.assertEqual(picker.data["count"], 0)
        receipt_response = manager_client.get("/api/v1/finance/funding-receipts")
        receipt_rows = (
            receipt_response.data["results"]
            if isinstance(receipt_response.data, dict)
            else receipt_response.data
        )
        self.assertEqual(len(receipt_rows), 0)
        draft = Expenditure.objects.create(
            expenditure_date=date(2026, 9, 8),
            accounting_period=self.period,
            amount=Decimal("10.00"),
            accounting_nature=AccountingNature.DIRECT_COST,
            description="Attempted owner drawing",
            created_by=self.manager,
        )
        denied_payment = manager_client.post(
            f"/api/v1/finance/expenditures/{draft.pk}/post",
            {
                "funding_allocations": [
                    {
                        "funding_source": receipt.funding_source_id,
                        "amount": "10.00",
                        "classification": FundingClassification.OWNER_DRAWING,
                    }
                ],
                "payment_status": "paid",
            },
            format="json",
        )
        self.assertEqual(denied_payment.status_code, 403)

    def test_report_totals_do_not_depend_on_nested_pagination(self):
        self.contribution()
        record_owner_contribution(
            owner_id=self.owner.pk,
            amount="100.00",
            receipt_date=date(2026, 9, 3),
            reference="BANK-002",
            notes="Second receipt",
            designations=[],
            idempotency_key="owner-capital-two",
            user=self.admin,
        )
        client = APIClient()
        client.force_authenticate(self.admin)
        paged = client.get(
            "/api/v1/finance/reports/owner-contributions",
            {"receipt_page_size": 1},
        )
        full = client.get(
            "/api/v1/finance/reports/owner-contributions",
            {"export": 1},
        )
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(len(paged.data["receipts"]), 1)
        self.assertEqual(len(full.data["receipts"]), 2)
        self.assertEqual(paged.data["summary"], full.data["summary"])

    def test_closed_period_rejects_new_owner_cash(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.closed_at = timezone.now()
        self.period.closed_by = self.admin
        self.period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        with self.assertRaises(ValidationError):
            self.contribution()
