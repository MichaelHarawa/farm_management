"""Source-linked loan correction tests; every fixture is disposable synthetic data."""
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role
from apps.finance.models import (AccountingPeriod, ChartOfAccount, EmployeeProfile, EmploymentType,
    FinanceActionEvent, FinancialCommandReceipt, FundingAllocation, FundingReceipt, FundingReceiptReversal,
    FundingReceiptStatus, FundingSource, FundingSourceType, JournalEntry, JournalLine, JournalStatus,
    PayrollEntry, PayrollPayment, PayrollPaymentFunding, PeriodStatus)
from apps.finance.services.financial_capture import (record_financial_expenditure,
    record_financial_sale, record_financial_supplier_payment)
from apps.finance.services.funding_capture import record_financial_funding_receipt
from apps.finance.services.funding_reversals import funding_receipt_version, reverse_financial_funding_receipt
from apps.finance.services.ledger import reverse_journal, trial_balance
from apps.finance.services.owner_capital import reverse_funding_receipt
from apps.finance.services.profitability import (available_batch_cash, available_funding_source_cash,
    funding_source_available_balances)
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.services.selling_cost_settlement import record_sale_cost_payment
from apps.finance.tests import test_financial_capture as fixtures
from apps.finance.tests import test_funding_capture as funding


def reversal_fixture(test):
    funding.funding_fixture(test)
    test.original_request = funding.funding_payload(test)
    test.receipt, _ = record_financial_funding_receipt(**test.original_request)
    test.journal = JournalEntry.objects.get()


def reverse_payload(test, **changes):
    return {**dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", receipt_id=test.receipt.pk,
        source_version=funding_receipt_version(test.receipt), reversal_date=date(2026, 1, 22),
        reason="Synthetic full cash correction; not farm records"), **changes}


def pay_service(test, amount="100.00", day=23):
    expense, _ = record_financial_expenditure(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        expenditure_date=date(2026, 1, 21), amount=amount, category_id=test.category.pk,
        accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
        cost_allocations=[{"batch": test.batch.pk, "amount": amount}], post=True)
    return expense, dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        expenditure_id=expense.pk, payment_date=date(2026, 1, day),
        funding_allocations=[{"funding_source": test.source.pk, "amount": amount}])


def corrupt_fixture(model, pk, column, value):
    """Simulate imported/corrupt old evidence only in the owned test DB.

    Normal managed writers deliberately refuse these changes. Identifier names
    are fixed model metadata/test constants; values remain SQL parameters.
    """
    with connection.cursor() as cursor:
        cursor.execute(f'UPDATE {connection.ops.quote_name(model._meta.db_table)} '
            f'SET {connection.ops.quote_name(column)}=%s WHERE {connection.ops.quote_name(model._meta.pk.column)}=%s',
            [value, pk])


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_FUNDING_RECEIPTS=True, FINANCE_FUNDING_REVERSALS=True)
class FundingReversalTests(TestCase):
    def setUp(self):
        reversal_fixture(self)

    def unchanged(self, row):
        return FundingReceipt.objects.filter(pk=row.pk).values().get()

    def no_reversal(self):
        self.assertEqual(FundingReceiptReversal.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 1)
        self.assertEqual(FinanceActionEvent.objects.count(), 1)

    def test_twenty_retries_keep_original_receipt_and_one_cash_debt_correction(self):
        original = self.unchanged(self.receipt)
        anchor = FinancialCommandReceipt.objects.filter(pk=self.original_request["submission_id"]).values().get()
        payload = reverse_payload(self)
        reversal, created = reverse_financial_funding_receipt(**payload)
        self.assertTrue(created)
        permanent = FinancialCommandReceipt.objects.filter(pk=payload["submission_id"]).values().get()
        for _ in range(20):
            replay, created = reverse_financial_funding_receipt(**payload)
            self.assertEqual(replay.pk, reversal.pk)
            self.assertFalse(created)
        self.assertEqual(self.unchanged(self.receipt), original)
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=self.original_request["submission_id"]).values().get(), anchor)
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=payload["submission_id"]).values().get(), permanent)
        self.assertEqual((FundingReceiptReversal.objects.count(), JournalEntry.objects.count(),
            FinancialCommandReceipt.objects.count(), FinanceActionEvent.objects.count()), (1, 2, 2, 2))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))
        self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("0.00")})
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.reversal_journal.reversal_of_id, self.journal.pk)
        self.assertEqual(list(reversal.reversal_journal.lines.order_by("account__code").values_list(
            "account__code", "debit", "credit", "batch_id", "funding_source_id")),
            [("1000", Decimal("0.00"), Decimal("500.00"), None, self.source.pk),
             ("2200", Decimal("500.00"), Decimal("0.00"), None, self.source.pk)])

    def test_dated_correction_does_not_rewrite_closed_month_or_create_profit(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        march = AccountingPeriod.objects.create(period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))
        reverse_financial_funding_receipt(**reverse_payload(self, reversal_date=date(2026, 2, 2)))
        jan, nxt, later = [monthly_profitability_report(period) for period in [self.period, feb, march]]
        self.assertEqual(jan["cash_flow"]["financing"]["inflows"], Decimal("500.00"))
        self.assertEqual(jan["cash_flow"]["closing_cash"], Decimal("500.00"))
        self.assertEqual(jan["statement_of_financial_position"]["loans"], Decimal("500.00"))
        self.assertEqual(nxt["cash_flow"]["opening_cash"], Decimal("500.00"))
        self.assertEqual(nxt["cash_flow"]["financing"]["outflows"], Decimal("500.00"))
        self.assertEqual(nxt["cash_flow"]["closing_cash"], Decimal("0.00"))
        self.assertEqual(nxt["statement_of_financial_position"]["loans"], Decimal("0.00"))
        self.assertEqual(later["cash_flow"]["opening_cash"], Decimal("0.00"))
        for report in [jan, nxt, later]:
            self.assertEqual(report["revenue"]["total_revenue"], Decimal("0.00"))
            self.assertEqual(report["other_costs"]["net_profit_after_recorded_tax"], Decimal("0.00"))
        before = trial_balance(cutoff=date(2026, 1, 31))
        after = trial_balance(cutoff=date(2026, 2, 28))
        self.assertEqual((before["debits"], before["credits"]), (Decimal("500.00"), Decimal("500.00")))
        self.assertEqual((after["debits"], after["credits"]), (Decimal("1000.00"), Decimal("1000.00")))
        self.assertTrue(all(row["balance"] == 0 for row in after["accounts"]))

    def test_changed_content_cannot_reuse_intent_or_cross_command_id(self):
        payload = reverse_payload(self)
        reverse_financial_funding_receipt(**payload)
        for change in [{"reason": "Different physical evidence"}, {"reversal_date": date(2026, 1, 23)},
                {"source_version": "0" * 64}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                reverse_financial_funding_receipt(**{**payload, **change})
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self, submission_id=self.original_request["submission_id"]))
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_new_intent_cannot_reverse_twice_or_reuse_original_reference(self):
        reverse_financial_funding_receipt(**reverse_payload(self))
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.assertIn("already_reversed", error.exception.detail)
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding.funding_payload(self))
        self.assertIn("duplicate_reference", error.exception.detail)
        original, created = record_financial_funding_receipt(**self.original_request)
        self.assertFalse(created)
        self.assertEqual(original.pk, self.receipt.pk)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))

    def test_management_authority_and_activity_apply_to_new_and_replayed_effect(self):
        for slug in ["general_worker", "stake_holder", "farm_supervisor", "farm_manager", "director"]:
            actor = get_user_model().objects.create_user(username=slug, email=slug + "@example.invalid")
            role, _ = Role.objects.get_or_create(slug=slug, defaults={"name": slug})
            actor.roles.add(role)
            if slug in {"farm_manager", "director"}:
                with transaction.atomic():
                    payload = reverse_payload(self, user=actor)
                    self.assertTrue(reverse_financial_funding_receipt(**payload)[1])
                    actor.roles.clear()
                    with self.assertRaises(PermissionDenied):
                        reverse_financial_funding_receipt(**payload)
                    transaction.set_rollback(True)
            else:
                with self.assertRaises(PermissionDenied):
                    reverse_financial_funding_receipt(**reverse_payload(self, user=actor))
        payload = reverse_payload(self)
        reverse_financial_funding_receipt(**payload)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            reverse_financial_funding_receipt(**payload)
        self.assertEqual(FundingReceiptReversal.objects.count(), 1)

    def test_inactive_source_metadata_does_not_prevent_correction_or_change_version(self):
        payload = reverse_payload(self)
        self.source.description = "Display-only label"
        self.source.notes = "Metadata"
        self.source.is_active = False
        self.source.save(update_fields=["description", "notes", "is_active"])
        self.receipt.refresh_from_db()
        self.assertEqual(funding_receipt_version(self.receipt), payload["source_version"])
        self.assertTrue(reverse_financial_funding_receipt(**payload)[1])
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        self.assertFalse(reverse_financial_funding_receipt(**payload)[1])

    def test_bad_id_date_reason_currency_version_and_submission_are_rejected(self):
        changes = [{"receipt_id": value} for value in [True, 1.2, "1.0", None, -1, "9223372036854775808"]]
        changes += [{"reversal_date": value} for value in [None, "2026-01-22", datetime(2026, 1, 22),
            timezone.localdate() + timedelta(days=1), date(2026, 1, 19)]]
        changes += [{"reason": value} for value in [None, {}, [], " ", "x" * 2001]]
        changes += [{"source_version": value} for value in [None, {}, "G" * 64, "0" * 64]]
        changes += [{"currency": "USD"}, {"submission_id": "not-a-uuid"}, {"receipt_id": 999999}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                reverse_financial_funding_receipt(**reverse_payload(self, **change))
        self.no_reversal()

    def test_missing_closed_and_overlapping_correction_periods_refuse(self):
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self, reversal_date=date(2026, 2, 2)))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.period.status = PeriodStatus.OPEN
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 1, 21), period_end=date(2026, 1, 23))
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.no_reversal()

    def test_long_reason_is_preserved_while_journal_caption_is_bounded(self):
        reason = "x" * 2000
        row, _ = reverse_financial_funding_receipt(**reverse_payload(self, reason=reason))
        self.journal.refresh_from_db()
        self.assertEqual(row.reason, reason)
        self.assertEqual(self.journal.reversal_reason, reason)
        self.assertEqual(len(row.reversal_journal.description), 255)
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=row.submission_id).result["reason"], reason)

    def test_spent_cash_and_committed_later_cash_use_require_review(self):
        _, payment = pay_service(self, day=23)
        record_financial_supplier_payment(**payment)
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self, reversal_date=date(2026, 1, 22)))
        self.assertIn("insufficient_cash", error.exception.detail)
        self.assertEqual(FundingReceiptReversal.objects.count(), 0)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("400.00"))

    def test_future_receipt_cannot_fund_backdated_reversal(self):
        _, payment = pay_service(self)
        record_financial_supplier_payment(**payment)
        record_financial_funding_receipt(**funding.funding_payload(self, receipt_date=fixtures.instant(day=25),
            reference="Synthetic later loan", amount="100.00"))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self, reversal_date=date(2026, 1, 24)))
        self.assertIn("insufficient_cash", error.exception.detail)
        row, _ = reverse_financial_funding_receipt(**reverse_payload(self, reversal_date=date(2026, 1, 25)))
        self.assertEqual(row.amount, Decimal("500.00"))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))

    def test_payroll_cash_use_is_reserved_without_charging_it_twice(self):
        employee_user = get_user_model().objects.create_user(username="synthetic-payroll", email="synthetic-payroll@example.invalid")
        employee = EmployeeProfile.objects.create(user=employee_user, employee_number="SYN-R-1",
            employment_type=EmploymentType.PERMANENT, job_title="Synthetic", employment_start_date=date(2025, 1, 1),
            base_monthly_salary=100, production_percentage=100, administration_percentage=0, selling_percentage=0)
        entry = PayrollEntry.objects.create(employee=employee, accounting_period=self.period, gross_salary=100,
            total_employer_cost=100, production_percentage=100, administration_percentage=0, selling_percentage=0)
        payment = PayrollPayment.objects.create(payroll_entry=entry, amount=100, payment_date=date(2026, 1, 24),
            payment_method="cash", idempotency_key="synthetic-reversal-payroll")
        PayrollPaymentFunding.objects.create(payment=payment, funding_source=self.source, amount=100)
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.assertIn("insufficient_cash", error.exception.detail)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("400.00"))

    @override_settings(FINANCE_SALE_COST_SETTLEMENT=True)
    def test_sale_cost_cash_use_blocks_reversal_without_duplicate_expense(self):
        sale, _ = record_financial_sale(**{**fixtures.sale_payload(self),
            "selling_costs": [{"category": "transport", "amount": "100.00"}]})
        record_sale_cost_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            selling_cost_id=sale.selling_costs.get().pk, payment_date=date(2026, 1, 24),
            funding_allocations=[{"funding_source": self.source.pk, "amount": "100.00"}],
            payee="Synthetic carrier", payment_method="cash")
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.assertIn("insufficient_cash", error.exception.detail)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("400.00"))
        self.assertEqual(FundingReceiptReversal.objects.count(), 0)

    def test_legacy_receipt_is_not_adopted_or_backfilled(self):
        legacy_source = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            legacy = FundingReceipt.objects.create(funding_source=legacy_source, amount="20.00",
                receipt_date=fixtures.instant(), created_by=self.user)
        fields = self.unchanged(legacy)
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self, receipt_id=legacy.pk,
                source_version=funding_receipt_version(legacy)))
        self.assertIn("receipt", error.exception.detail)
        self.assertEqual(self.unchanged(legacy), fields)
        self.no_reversal()

    def test_missing_permanent_anchor_requires_review(self):
        corrupt_fixture(FinancialCommandReceipt, self.original_request["submission_id"], "command", "synthetic.missing")
        with self.assertRaises(ValidationError) as error:
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.assertIn("receipt", error.exception.detail)
        self.no_reversal()

    def test_malformed_or_changed_permanent_evidence_fails_closed(self):
        original = FinancialCommandReceipt.objects.get(pk=self.original_request["submission_id"]).result
        for changed in [[], None, {**original, "amount": "501.00"}, {**original, "counterparty": "Changed"},
                {**original, "journal_id": "not-an-id"}, {**original, "new_field": "unsupported"}]:
            with self.subTest(changed=changed), transaction.atomic():
                corrupt_fixture(FinancialCommandReceipt, self.original_request["submission_id"], "result", json.dumps(changed))
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**reverse_payload(self))
                self.no_reversal()
                transaction.set_rollback(True)

    def test_changed_original_receipt_fields_and_hash_are_not_silently_corrected(self):
        payload = reverse_payload(self)
        for field, value in [("amount", "501.00"), ("reference", "changed"), ("notes", "changed"),
                ("request_fingerprint", "0" * 64), ("status", FundingReceiptStatus.REVERSED),
                ("created_by_id", None), ("receipt_date", fixtures.instant(day=21))]:
            with self.subTest(field=field), transaction.atomic():
                corrupt_fixture(FundingReceipt, self.receipt.pk, field, value)
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**payload)
                row = FundingReceipt.objects.get(pk=self.receipt.pk)
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**{**payload, "source_version": funding_receipt_version(row)})
                self.no_reversal()
                transaction.set_rollback(True)

    def test_changed_source_binding_refuses_even_with_fresh_row_version(self):
        for field, value in [("source_type", FundingSourceType.GRANT), ("batch_id", self.batch.pk)]:
            with self.subTest(field=field), transaction.atomic():
                corrupt_fixture(FundingSource, self.source.pk, field, value)
                row = FundingReceipt.objects.get(pk=self.receipt.pk)
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**reverse_payload(self, source_version=funding_receipt_version(row)))
                self.no_reversal()
                transaction.set_rollback(True)

    def test_changed_journal_date_status_source_and_lines_require_review(self):
        for field, value in [("posting_date", date(2026, 1, 21)), ("status", JournalStatus.REVERSED),
                ("source_identifier", "wrong"), ("idempotency_key", "synthetic-changed")]:
            with self.subTest(field=field), transaction.atomic():
                corrupt_fixture(JournalEntry, self.journal.pk, field, value)
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**reverse_payload(self))
                self.no_reversal()
                transaction.set_rollback(True)
        for field, value in [("debit", "499.00"), ("batch_id", self.batch.pk), ("funding_source_id", None)]:
            with self.subTest(field=field), transaction.atomic():
                line = self.journal.lines.get(account__code="1000")
                corrupt_fixture(JournalLine, line.pk, field, value)
                with self.assertRaises(ValidationError):
                    reverse_financial_funding_receipt(**reverse_payload(self))
                self.no_reversal()
                transaction.set_rollback(True)

    def test_changed_anchor_hash_is_refused(self):
        corrupt_fixture(FinancialCommandReceipt, self.original_request["submission_id"], "request_hash", "0" * 64)
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.no_reversal()

    def test_missing_chart_account_rolls_back_original_and_opposite(self):
        original = self.unchanged(self.receipt)
        ChartOfAccount.objects.filter(code="2200").update(is_active=False)
        with self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**reverse_payload(self))
        self.journal.refresh_from_db()
        self.assertEqual(self.journal.status, JournalStatus.POSTED)
        self.assertEqual(self.unchanged(self.receipt), original)
        self.no_reversal()

    def test_crash_after_opposite_or_source_event_rolls_everything_back(self):
        for target in ["apps.finance.services.funding_reversals.FundingReceiptReversal.objects.create",
                "apps.finance.services.funding_reversals.record_finance_action"]:
            with self.subTest(target=target), patch(target, side_effect=RuntimeError("synthetic interruption")):
                with self.assertRaises(RuntimeError):
                    reverse_financial_funding_receipt(**reverse_payload(self))
            self.journal.refresh_from_db()
            self.assertEqual(self.journal.status, JournalStatus.POSTED)
            self.assertEqual(self.journal.reversal_reason, "")
            self.no_reversal()

    def test_source_only_and_both_journal_only_reversals_stay_blocked(self):
        row, _ = reverse_financial_funding_receipt(**reverse_payload(self))
        with override_settings(FINANCE_FUNDING_RECEIPTS=False, FINANCE_FUNDING_REVERSALS=False):
            for action in [lambda: reverse_funding_receipt(receipt_id=self.receipt.pk, reason="Synthetic", user=self.user),
                    lambda: reverse_journal(self.journal, posting_date=date(2026, 1, 23), reason="Synthetic", user=self.user),
                    lambda: reverse_journal(row.reversal_journal, posting_date=date(2026, 1, 23), reason="Synthetic", user=self.user)]:
                with self.assertRaises(ValidationError):
                    action()
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_append_only_event_cannot_be_forged_edited_or_deleted_normally(self):
        forged = FundingReceiptReversal(receipt=self.receipt, funding_source=self.source,
            original_journal=self.journal, reversal_journal=self.journal, submission_id=uuid.uuid4(),
            source_version="0" * 64, amount=500, reversal_date=date(2026, 1, 22), reason="Synthetic", created_by=self.user)
        for action in [lambda: forged.save(), lambda: forged.save_base(),
                lambda: FundingReceiptReversal.objects.bulk_create([forged])]:
            with self.assertRaises(DjangoValidationError):
                action()
        # The unset context is not permission for an unset original journal.
        forged.original_journal_id = None
        with self.assertRaises(DjangoValidationError):
            forged.save_base()
        row, _ = reverse_financial_funding_receipt(**reverse_payload(self))
        snapshot = FundingReceiptReversal.objects.filter(pk=row.pk).values().get()
        row.reason = "Changed"
        for action in [lambda: row.save(), lambda: row.save_base(), lambda: row.delete(),
                lambda: FundingReceiptReversal.objects.filter(pk=row.pk).update(reason="Changed"),
                lambda: FundingReceiptReversal.objects.bulk_update([row], ["reason"]),
                lambda: FundingReceiptReversal.objects.filter(pk=row.pk).delete(),
                lambda: FundingReceiptReversal.objects.filter(pk=row.pk)._raw_delete("default")]:
            with self.assertRaises(DjangoValidationError):
                action()
        self.assertEqual(FundingReceiptReversal.objects.filter(pk=row.pk).values().get(), snapshot)

    def test_reversal_can_recover_while_new_receipt_capture_is_off(self):
        payload = reverse_payload(self)
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            self.assertTrue(reverse_financial_funding_receipt(**payload)[1])
            self.assertFalse(reverse_financial_funding_receipt(**payload)[1])
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))

    @override_settings(FINANCE_FUNDING_REVERSALS=False)
    def test_gate_off_refuses_before_any_query_and_legacy_reads_skip_new_table(self):
        payload = reverse_payload(self)
        with self.assertNumQueries(0), self.assertRaises(ValidationError):
            reverse_financial_funding_receipt(**payload)
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
            self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("500.00")})
            monthly_profitability_report(self.period)
        self.assertFalse(any("finance_fundingreceiptreversal" in row["sql"] for row in queries))


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_FUNDING_RECEIPTS=True, FINANCE_FUNDING_REVERSALS=True)
class FundingReversalConcurrencyTests(TransactionTestCase):
    race = fixtures.FinancialCaptureConcurrencyTests.race

    def setUp(self):
        reversal_fixture(self)
        self.assertEqual(connection.vendor, "postgresql")

    def test_same_id_race_returns_one_original_reversal(self):
        payload = reverse_payload(self)
        results = self.race([lambda: reverse_financial_funding_receipt(**payload)] * 2)
        self.assertEqual([row[0] for row in results], ["accepted", "accepted"])
        self.assertEqual(sum(row[1][1] for row in results), 1)
        self.assertEqual((FundingReceiptReversal.objects.count(), JournalEntry.objects.count()), (1, 2))

    def test_distinct_ids_cannot_both_reverse_same_receipt(self):
        first, second = reverse_payload(self), reverse_payload(self)
        results = self.race([lambda: reverse_financial_funding_receipt(**first),
            lambda: reverse_financial_funding_receipt(**second)])
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual((FundingReceiptReversal.objects.count(), JournalEntry.objects.count()), (1, 2))

    def test_two_receipts_compete_for_last_available_cash_across_periods(self):
        another, _ = record_financial_funding_receipt(**funding.funding_payload(self, reference="Synthetic second loan"))
        _, payment = pay_service(self, amount="500.00")
        record_financial_supplier_payment(**payment)
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        first = reverse_payload(self)
        second = reverse_payload(self, receipt_id=another.pk, source_version=funding_receipt_version(another),
            reversal_date=date(2026, 2, 2))
        results = self.race([lambda: reverse_financial_funding_receipt(**first),
            lambda: reverse_financial_funding_receipt(**second)])
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual(FundingReceiptReversal.objects.count(), 1)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))
        self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("0.00")})

    def test_reversal_and_supplier_payment_compete_for_last_cash(self):
        _, payment = pay_service(self, amount="500.00")
        payload = reverse_payload(self)
        results = self.race([lambda: reverse_financial_funding_receipt(**payload),
            lambda: record_financial_supplier_payment(**payment)])
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual(FundingReceiptReversal.objects.count() + FundingAllocation.objects.count(), 1)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0.00"))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
