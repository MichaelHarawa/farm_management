from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.finance.models import (AccountingPeriod, ChartOfAccount, CostAllocation, Expenditure,
    FinanceActionEvent, FinancialCommandReceipt, FundingReceipt, FundingReceiptStatus, FundingSource,
    FundingSourceType, JournalEntry, PeriodStatus)
from apps.finance.services.financial_capture import record_financial_expenditure, record_financial_supplier_payment
from apps.finance.services.funding_capture import funding_source_version, record_financial_funding_receipt
from apps.finance.services.ledger import reverse_journal, trial_balance
from apps.finance.services.owner_capital import reverse_funding_receipt
from apps.finance.services.profitability import available_batch_cash, available_funding_source_cash, funding_source_available_balances
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.tests import test_financial_capture as fixtures


def funding_fixture(test):
    fixtures.fixture(test)
    test.source = FundingSource.objects.create(source_type=FundingSourceType.LOAN, description="Synthetic lender account")


def funding_payload(test, **changes):
    return {**dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", funding_source_id=test.source.pk,
        source_version=funding_source_version(test.source), amount="500.00", receipt_date=fixtures.instant(),
        counterparty="Synthetic lender", payment_method="bank_transfer", reference="SYNTHETIC-LOAN-001",
        notes="Original physical receipt evidence, not farm records"), **changes}


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_FUNDING_RECEIPTS=True)
class FundingCaptureTests(TestCase):
    def setUp(self):
        funding_fixture(self)

    def no_effects(self):
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(),
            FinancialCommandReceipt.objects.count(), FinanceActionEvent.objects.count()), (0, 0, 0, 0))

    def test_twenty_retries_preserve_exact_cash_liability_and_original_evidence(self):
        payload = funding_payload(self)
        original, created = record_financial_funding_receipt(**payload)
        self.assertTrue(created)
        evidence = FinancialCommandReceipt.objects.get(pk=payload["submission_id"])
        saved = (evidence.request_hash, evidence.result, evidence.completed_at)
        original_fields = FundingReceipt.objects.filter(pk=original.pk).values().get()
        for _ in range(20):
            row, created = record_financial_funding_receipt(**payload)
            self.assertEqual(row.pk, original.pk)
            self.assertFalse(created)
        evidence.refresh_from_db()
        self.assertEqual((evidence.request_hash, evidence.result, evidence.completed_at), saved)
        self.assertEqual(FundingReceipt.objects.filter(pk=original.pk).values().get(), original_fields)
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(), FinanceActionEvent.objects.count()), (1, 1, 1))
        self.assertEqual(evidence.result["payment_method"], "bank_transfer")
        self.assertEqual(evidence.result["counterparty"], "Synthetic lender")
        self.assertEqual(len(original.request_fingerprint), 64)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count()), (0, 0))
        journal = JournalEntry.objects.get()
        self.assertEqual(journal.posting_date, date(2026, 1, 20))
        self.assertEqual(list(journal.lines.order_by("account__code").values_list(
            "account__code", "debit", "credit", "batch_id", "funding_source_id")),
            [("1000", Decimal("500.00"), Decimal("0.00"), None, self.source.pk),
             ("2200", Decimal("0.00"), Decimal("500.00"), None, self.source.pk)])
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("500.00"), Decimal("500.00")))

    def test_changed_content_cannot_reuse_id(self):
        payload = funding_payload(self)
        record_financial_funding_receipt(**payload)
        other = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        for change in [{"amount": "501.00"}, {"receipt_date": fixtures.instant(day=21)},
                {"counterparty": "Other lender"}, {"payment_method": "cash"}, {"reference": "Changed"},
                {"notes": "Changed"}, {"source_version": "0" * 64},
                {"funding_source_id": other.pk, "source_version": funding_source_version(other)}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**{**payload, **change})
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count()), (1, 1))

    def test_replay_works_after_closed_period_or_source_deactivation_without_new_effect(self):
        payload = funding_payload(self)
        original, _ = record_financial_funding_receipt(**payload)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])
        row, created = record_financial_funding_receipt(**payload)
        self.assertEqual(row.pk, original.pk)
        self.assertFalse(created)
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**{**payload, "submission_id": uuid.uuid4(), "reference": "Another"})

    def test_current_role_and_activity_are_rechecked_on_replay(self):
        payload = funding_payload(self)
        record_financial_funding_receipt(**payload)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            record_financial_funding_receipt(**payload)
        self.assertEqual(FundingReceipt.objects.count(), 1)

    def test_worker_and_stakeholder_cannot_capture_but_supervisor_can(self):
        for slug in ["general_worker", "stake_holder", "farm_supervisor"]:
            actor = get_user_model().objects.create_user(username=slug, email=slug + "@example.invalid", password="synthetic")
            role, _ = Role.objects.get_or_create(slug=slug, defaults={"name": slug})
            actor.roles.add(role)
            payload = funding_payload(self, user=actor, reference=slug)
            if slug == "farm_supervisor":
                self.assertTrue(record_financial_funding_receipt(**payload)[1])
                actor.roles.clear()
                with self.assertRaises(PermissionDenied):
                    record_financial_funding_receipt(**payload)
            else:
                with self.assertRaises(PermissionDenied):
                    record_financial_funding_receipt(**payload)
        self.assertEqual(FundingReceipt.objects.count(), 1)

    def test_missing_inactive_and_stale_source_are_refused(self):
        for change in [{"funding_source_id": 999999}, {"source_version": "0" * 64}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**funding_payload(self, **change))
        self.source.is_active = False
        self.source.save()
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**funding_payload(self))
        self.no_effects()

    def test_source_rebinding_before_capture_requires_review(self):
        payload = funding_payload(self)
        self.source.source_type = FundingSourceType.OTHER_INCOME
        self.source.save()
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**payload)
        self.assertIn("source_version", error.exception.detail)
        self.no_effects()

    def test_owner_batch_grant_income_and_general_cash_are_not_invented_templates(self):
        for kind in FundingSourceType.values:
            if kind == FundingSourceType.LOAN:
                continue
            source = FundingSource.objects.create(source_type=kind,
                batch=self.batch if kind == FundingSourceType.BATCH_COLLECTION else None)
            with self.subTest(kind=kind), self.assertRaises(ValidationError) as error:
                record_financial_funding_receipt(**funding_payload(self, funding_source_id=source.pk,
                    source_version=funding_source_version(source)))
            self.assertIn("capability_unavailable", error.exception.detail)
        self.source.batch = self.batch
        self.source.save()
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**funding_payload(self))
        self.no_effects()

    def test_money_currency_and_identifier_validation_is_exact(self):
        for value in [True, 1.1, None, "NaN", "Infinity", "0", "-1", "1.001", "1000000000000.00"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**funding_payload(self, amount=value))
        for value in [True, 1.9, "1.0", "-1", None, "9223372036854775808"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**funding_payload(self, funding_source_id=value))
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**funding_payload(self, currency="USD"))
        self.no_effects()

    def test_evidence_limits_methods_and_version_validation(self):
        for change in [{"counterparty": " "}, {"counterparty": "x" * 201}, {"counterparty": {}},
                {"reference": " "}, {"reference": "x" * 121}, {"reference": None},
                {"notes": "x" * 4001}, {"notes": []}, {"payment_method": "credit"},
                {"payment_method": "loan"}, {"payment_method": []}, {"payment_method": {}},
                {"payment_method": None}, {"source_version": "G" * 64}, {"source_version": None}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**funding_payload(self, **change))
        self.no_effects()

    def test_actual_aware_instant_and_existing_open_period_required(self):
        for value in [date(2026, 1, 20), "2026-01-20", datetime(2026, 1, 20),
                timezone.now() + timedelta(days=1), fixtures.instant(month=2)]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                record_financial_funding_receipt(**funding_payload(self, receipt_date=value))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self))
        self.assertIn("period_locked", error.exception.detail)
        self.no_effects()

    def test_offset_instant_locks_and_posts_same_utc_day(self):
        at = datetime(2026, 2, 1, 0, 30, tzinfo=datetime_timezone(timedelta(hours=2)))
        row, _ = record_financial_funding_receipt(**funding_payload(self, receipt_date=at))
        self.assertEqual(row.receipt_date, at.astimezone(datetime_timezone.utc))
        self.assertEqual(JournalEntry.objects.get().posting_date, date(2026, 1, 31))

    def test_duplicate_reference_is_source_scoped_trimmed_case_insensitive(self):
        original, _ = record_financial_funding_receipt(**funding_payload(self))
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self, reference=" synthetic-loan-001 ", amount="100.00",
                receipt_date=fixtures.instant(day=21)))
        self.assertIn("duplicate_reference", error.exception.detail)
        self.assertEqual(FundingReceipt.objects.get().pk, original.pk)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_legacy_reference_reserves_identity_without_adopting_or_backfilling(self):
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            legacy = FundingReceipt.objects.create(funding_source=self.source, amount="10.00",
                receipt_date=fixtures.instant(), reference=" Synthetic-Loan-001 ")
        fields = FundingReceipt.objects.filter(pk=legacy.pk).values().get()
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self))
        self.assertIn("duplicate_reference", error.exception.detail)
        self.assertEqual(FundingReceipt.objects.filter(pk=legacy.pk).values().get(), fields)
        self.assertEqual((JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (0, 0))

    def test_reversed_legacy_reference_stays_reserved(self):
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            FundingReceipt.objects.create(funding_source=self.source, amount="10.00",
                receipt_date=fixtures.instant(), reference="SYNTHETIC-LOAN-001", status=FundingReceiptStatus.REVERSED)
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self))
        self.assertIn("duplicate_reference", error.exception.detail)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_source_with_other_legacy_receipts_is_not_silently_adopted(self):
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            legacy = FundingReceipt.objects.create(funding_source=self.source, amount="10.00", reference="Legacy-other")
        before = FundingReceipt.objects.filter(pk=legacy.pk).values().get()
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self))
        self.assertIn("source_review_required", error.exception.detail)
        self.assertEqual(FundingReceipt.objects.filter(pk=legacy.pk).values().get(), before)
        self.assertEqual((JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (0, 0))

    def test_matching_other_source_evidence_goes_to_review_not_fake_replay(self):
        record_financial_funding_receipt(**funding_payload(self))
        other = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        with self.assertRaises(ValidationError) as error:
            record_financial_funding_receipt(**funding_payload(self, funding_source_id=other.pk,
                source_version=funding_source_version(other), reference="synthetic-loan-001"))
        self.assertIn("possible_duplicate", error.exception.detail)
        self.assertEqual(available_funding_source_cash(other), Decimal("0.00"))
        self.assertEqual(FundingReceipt.objects.count(), 1)

    def test_different_reference_allows_legitimate_same_amount_and_time(self):
        record_financial_funding_receipt(**funding_payload(self))
        record_financial_funding_receipt(**funding_payload(self, reference="SYNTHETIC-LOAN-002"))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("1000.00"))
        self.assertEqual(FundingReceipt.objects.count(), 2)

    def test_missing_chart_or_crash_after_journal_rolls_back_every_effect(self):
        ChartOfAccount.objects.filter(code="2200").update(is_active=False)
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**funding_payload(self))
        self.no_effects()
        ChartOfAccount.objects.filter(code="2200").update(is_active=True)
        with patch("apps.finance.services.funding_capture.record_finance_action", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaises(RuntimeError):
                record_financial_funding_receipt(**funding_payload(self))
        self.no_effects()

    def test_managed_source_and_receipt_are_not_editable_or_deletable(self):
        row, _ = record_financial_funding_receipt(**funding_payload(self))
        original = FundingReceipt.objects.filter(pk=row.pk).values().get()
        for action in [lambda: row.save(), lambda: row.save_base(raw=True), lambda: row.delete(),
                lambda: FundingReceipt.objects.filter(pk=row.pk).update(amount="1.00"),
                lambda: FundingReceipt.objects.bulk_update([row], ["amount"]),
                lambda: FundingReceipt.objects.filter(pk=row.pk).delete(),
                lambda: FundingReceipt.objects.filter(pk=row.pk)._raw_delete("default")]:
            with self.assertRaises(DjangoValidationError):
                action()
        row.idempotency_key = None
        with self.assertRaises(DjangoValidationError):
            row.save()
        for change in [{"source_type": FundingSourceType.GRANT}, {"batch_id": self.batch.pk}]:
            with self.subTest(change=change), self.assertRaises(DjangoValidationError):
                FundingSource.objects.filter(pk=self.source.pk).update(**change)
        self.source.source_type = FundingSourceType.GRANT
        with self.assertRaises(DjangoValidationError):
            self.source.save()
        with self.assertRaises(DjangoValidationError):
            self.source.save_base(raw=True)
        with self.assertRaises(DjangoValidationError):
            FundingSource.objects.bulk_update([self.source], ["source_type"])
        with self.assertRaises(DjangoValidationError):
            self.source.delete()
        self.assertEqual(FundingReceipt.objects.filter(pk=row.pk).values().get(), original)

    def test_metadata_can_change_without_rebinding_money_or_authorizing_capture(self):
        record_financial_funding_receipt(**funding_payload(self))
        before = funding_source_version(self.source)
        self.source.description = "New display label"
        self.source.notes = "Metadata only"
        self.source.is_active = False
        self.source.save(update_fields=["description", "notes", "is_active"])
        self.assertEqual(funding_source_version(self.source), before)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        with self.assertRaises(ValidationError):
            record_financial_funding_receipt(**funding_payload(self, reference="Another"))

    def test_guard_survives_capture_gate_off_and_reversal_cannot_hide_cash(self):
        row, _ = record_financial_funding_receipt(**funding_payload(self))
        journal = JournalEntry.objects.get()
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            for action in [lambda: row.save(), lambda: FundingReceipt.objects.filter(pk=row.pk).delete(),
                    lambda: reverse_funding_receipt(receipt_id=row.pk, reason="Synthetic", user=self.user),
                    lambda: reverse_journal(journal, posting_date=date(2026, 1, 21), reason="Synthetic", user=self.user),
                    lambda: FundingReceipt.objects.create(funding_source=self.source, amount="1.00", reference="Unjournaled"),
                    lambda: FundingReceipt.objects.bulk_create([FundingReceipt(funding_source=self.source, amount="1.00")])]:
                with self.assertRaises((DjangoValidationError, ValidationError)):
                    action()
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        self.assertEqual(FundingReceipt.objects.get().status, FundingReceiptStatus.POSTED)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_reserved_namespace_and_ordinary_loan_bypass_are_refused(self):
        for action in [lambda: FundingReceipt.objects.create(funding_source=self.source, amount="500.00"),
                lambda: FundingReceipt.objects.bulk_create([FundingReceipt(funding_source=self.source, amount="500.00")]),
                lambda: FundingReceipt.objects.create(funding_source=self.source, amount="500.00", idempotency_key="financial-funding:forged")]:
            with self.assertRaises(DjangoValidationError):
                action()
        self.no_effects()

    def test_ordinary_rest_bypasses_return_clear_rejections_not_server_errors(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post("/api/v1/finance/funding-receipts", {
            "funding_source": self.source.pk, "amount": "500.00", "receipt_date": fixtures.instant().isoformat()}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.no_effects()
        row, _ = record_financial_funding_receipt(**funding_payload(self))
        for method, path, data in [
                (client.patch, f"/api/v1/finance/funding-sources/{self.source.pk}", {"source_type": "grant"}),
                (client.delete, f"/api/v1/finance/funding-sources/{self.source.pk}", None),
                (client.post, f"/api/v1/finance/funding-receipts/{row.pk}/reverse", {"reason": "Synthetic"}),
                (client.post, "/api/v1/finance/funding-receipts", {"funding_source": self.source.pk, "amount": "1.00"})]:
            with self.subTest(path=path, data=data):
                response = method(path, data, format="json")
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        self.assertEqual(JournalEntry.objects.count(), 1)
        response = client.patch(f"/api/v1/finance/funding-sources/{self.source.pk}", {"notes": "Metadata only"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_legacy_receipts_and_sources_remain_editable_when_no_managed_evidence(self):
        with override_settings(FINANCE_FUNDING_RECEIPTS=False):
            row = FundingReceipt.objects.create(funding_source=self.source, amount="1.00")
            row.notes = "Legacy metadata"
            row.save()
            self.assertEqual(FundingReceipt.objects.filter(pk=row.pk).update(amount="2.00"), 1)
            self.assertEqual(FundingSource.objects.filter(pk=self.source.pk).update(source_type=FundingSourceType.GRANT), 1)
            row.delete()
            self.source.delete()
        self.assertEqual(FundingReceipt.objects.count(), 0)

    def test_monthly_cash_loan_and_profit_are_distinct_with_next_month_opening(self):
        record_financial_funding_receipt(**funding_payload(self))
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        jan = monthly_profitability_report(self.period)
        nxt = monthly_profitability_report(feb)
        self.assertEqual(jan["cash_flow"]["financing"]["inflows"], Decimal("500.00"))
        self.assertEqual(jan["cash_flow"]["operating"]["inflows"], Decimal("0.00"))
        self.assertEqual(jan["cash_flow"]["closing_cash"], Decimal("500.00"))
        self.assertEqual(nxt["cash_flow"]["opening_cash"], Decimal("500.00"))
        self.assertEqual(jan["statement_of_financial_position"]["loans"], Decimal("500.00"))
        self.assertEqual(jan["revenue"]["total_revenue"], Decimal("0.00"))
        self.assertEqual(jan["other_costs"]["net_profit_after_recorded_tax"], Decimal("0.00"))

    def test_confirmed_loan_cash_can_pay_service_without_becoming_batch_revenue(self):
        record_financial_funding_receipt(**funding_payload(self))
        expense, _ = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.batch.pk, "amount": "100.00"}], post=True)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=expense.pk, payment_date=date(2026, 1, 22),
            funding_allocations=[{"funding_source": self.source.pk, "amount": "100.00"}])
        self.assertEqual(available_funding_source_cash(self.source), Decimal("400.00"))
        self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("400.00")})
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
        self.assertEqual(sum(CostAllocation.objects.values_list("allocated_amount", flat=True)), Decimal("100.00"))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    @override_settings(FINANCE_FUNDING_RECEIPTS=False)
    def test_capture_gate_is_off_before_any_query(self):
        payload = funding_payload(self)
        with self.assertNumQueries(0), self.assertRaises(ValidationError):
            record_financial_funding_receipt(**payload)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_FUNDING_RECEIPTS=True)
class FundingCaptureConcurrencyTests(TransactionTestCase):
    race = fixtures.FinancialCaptureConcurrencyTests.race

    def setUp(self):
        funding_fixture(self)
        self.assertEqual(connection.vendor, "postgresql")

    def test_same_submission_races_accept_one_and_replay_original(self):
        payload = funding_payload(self)
        outcomes = self.race([lambda: record_financial_funding_receipt(**payload)] * 2)
        self.assertEqual([row[0] for row in outcomes], ["accepted", "accepted"])
        self.assertEqual(sum(row[1][1] for row in outcomes), 1)
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (1, 1, 1))

    def test_different_ids_compete_for_same_reference_even_across_periods(self):
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        first = funding_payload(self)
        second = funding_payload(self, receipt_date=fixtures.instant(month=2), reference="synthetic-loan-001")
        outcomes = self.race([lambda: record_financial_funding_receipt(**first), lambda: record_financial_funding_receipt(**second)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(FundingReceipt.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_cross_source_alias_evidence_race_goes_to_review(self):
        other = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        first = funding_payload(self)
        second = funding_payload(self, funding_source_id=other.pk, source_version=funding_source_version(other),
            reference="synthetic-loan-001")
        outcomes = self.race([lambda: record_financial_funding_receipt(**first), lambda: record_financial_funding_receipt(**second)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(FundingReceipt.objects.count(), 1)
        self.assertEqual(sum(funding_source_available_balances([self.source, other]).values()), Decimal("500.00"))

    def test_source_rebind_race_cannot_change_accepted_cash_into_income(self):
        payload = funding_payload(self)
        outcomes = self.race([lambda: record_financial_funding_receipt(**payload),
            lambda: FundingSource.objects.filter(pk=self.source.pk).update(source_type=FundingSourceType.GRANT)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.source.refresh_from_db()
        if FundingReceipt.objects.exists():
            self.assertEqual(self.source.source_type, FundingSourceType.LOAN)
            self.assertEqual(JournalEntry.objects.count(), 1)
        else:
            self.assertEqual(self.source.source_type, FundingSourceType.GRANT)
            self.assertEqual(JournalEntry.objects.count(), 0)
