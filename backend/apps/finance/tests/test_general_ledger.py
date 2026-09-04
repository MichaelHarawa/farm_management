from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.finance.models import (
    AccountingPeriod,
    ChartOfAccount,
    JournalStatus,
    PeriodStatus,
)
from apps.finance.services.ledger import post_journal, reverse_journal, trial_balance
from apps.finance.services.reporting import (
    create_period_report_snapshot,
    monthly_profitability_report,
)


class GeneralLedgerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="ledger-test")
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
        )

    def test_balanced_journal_is_idempotent_and_posted_lines_are_immutable(self):
        payload = {
            "posting_date": date(2026, 1, 10),
            "description": "Owner funds farm cash",
            "source_model": "test.OwnerCapital",
            "source_identifier": "1",
            "idempotency_key": "test:owner-capital:1",
            "user": self.user,
            "lines": [
                {"account": "1000", "debit": Decimal("500.00")},
                {"account": "3000", "credit": Decimal("500.00")},
            ],
        }
        entry = post_journal(**payload)
        self.assertEqual(entry.status, JournalStatus.POSTED)
        self.assertEqual(post_journal(**payload).pk, entry.pk)
        balance = trial_balance()
        self.assertEqual(balance["debits"], balance["credits"])
        line = entry.lines.first()
        line.debit = Decimal("400.00")
        with self.assertRaises(DjangoValidationError):
            line.save()

    def test_unbalanced_and_closed_period_journals_are_rejected(self):
        with self.assertRaises(ValidationError):
            post_journal(
                posting_date=date(2026, 1, 10),
                description="Bad journal",
                source_model="test.Bad",
                source_identifier="1",
                idempotency_key="test:bad:1",
                lines=[{"account": "1000", "debit": Decimal("1.00")}],
            )
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            post_journal(
                posting_date=date(2026, 1, 10),
                description="Backdated journal",
                source_model="test.Bad",
                source_identifier="2",
                idempotency_key="test:bad:2",
                lines=[
                    {"account": "1000", "debit": Decimal("1.00")},
                    {"account": "3000", "credit": Decimal("1.00")},
                ],
            )

    def test_reversal_preserves_original_and_balances(self):
        entry = post_journal(
            posting_date=date(2026, 1, 10),
            description="Test posting",
            source_model="test.Source",
            source_identifier="1",
            idempotency_key="test:source:1",
            lines=[
                {"account": "1000", "debit": Decimal("75.00")},
                {"account": "3000", "credit": Decimal("75.00")},
            ],
        )
        reversal = reverse_journal(
            entry, posting_date=date(2026, 1, 20), reason="Incorrect source", user=self.user
        )
        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.reversal_of, entry)
        self.assertEqual(entry.lines.count(), 2)

    def test_closed_period_report_uses_immutable_snapshot(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status", "updated_at"])
        snapshot = create_period_report_snapshot(self.period, generated_by=self.user)
        first = monthly_profitability_report(self.period)
        self.assertEqual(first, snapshot.report_data)
        snapshot.report_data["revenue"]["total_revenue"] = "999999.00"
        second = monthly_profitability_report(self.period)
        self.assertNotEqual(second["revenue"]["total_revenue"], "999999.00")
