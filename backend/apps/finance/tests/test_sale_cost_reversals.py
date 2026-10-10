"""Actual selling-cost payment refunds, using disposable synthetic records only."""
from datetime import date, timedelta
from decimal import Decimal
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role
from apps.finance.models import (AccountingPeriod, ChartOfAccount, FinanceActionEvent, FinancialCommandReceipt,
    FundingReceipt, FundingSource, FundingSourceType, JournalEntry, JournalLine, JournalStatus,
    PeriodStatus, SaleCostPayment, SaleCostPaymentReversal)
from apps.finance.services.financial_capture import record_financial_sale
from apps.finance.services.funding_capture import funding_source_version, record_financial_funding_receipt
from apps.finance.services.ledger import reverse_journal, trial_balance
from apps.finance.services.profitability import (available_batch_cash, available_funding_source_cash,
    batch_revenue_utilization, funding_source_available_balances, portfolio_expenditure_funding_mix, selling_cost_total)
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.services.sale_cost_reversal_guards import sale_cost_reversal_allowed
from apps.finance.services.sale_cost_reversals import refund_sale_cost_payment, sale_cost_payment_group_version
from apps.finance.services.selling_cost_settlement import (record_sale_cost_payment,
    sale_cost_payment_total, sale_cost_payable_summary)
from apps.finance.tests import test_financial_capture as fixtures
from apps.finance.tests.test_funding_reversals import corrupt_fixture
from apps.finance.tests.test_selling_cost_settlement import settlement_fixture, payment_payload
from apps.poultry.models import SaleSellingCost, Sales


def refund_fixture(test, cash="200.00"):
    settlement_fixture(test, cash)
    test.original_request = payment_payload(test)
    test.payments, _ = record_sale_cost_payment(**test.original_request)
    test.anchor = FinancialCommandReceipt.objects.get(pk=test.original_request["submission_id"])
    test.original_journal = JournalEntry.objects.get(pk=test.anchor.result["journal_ids"][0])


def refund_payload(test, **changes):
    return {**dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        original_submission_id=test.original_request["submission_id"],
        source_version=sale_cost_payment_group_version(test.anchor, test.payments), refund_date=date(2026, 1, 23),
        refund_method="bank_transfer", external_reference="SYNTHETIC-REFUND", reason="Actual synthetic payee refund"), **changes}


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_SALE_COST_SETTLEMENT=True, FINANCE_SALE_COST_REVERSALS=True)
class SaleCostRefundTests(TestCase):
    def setUp(self):
        refund_fixture(self)

    def counts(self):
        return tuple(model.objects.count() for model in [SaleCostPaymentReversal, JournalEntry,
            FinancialCommandReceipt, FinanceActionEvent])

    def test_twenty_retries_preserve_original_payment_request_hash_cost_and_one_refund(self):
        payment = SaleCostPayment.objects.filter(pk=self.payments[0].pk).values().get()
        anchor = FinancialCommandReceipt.objects.filter(pk=self.anchor.pk).values().get()
        cost = SaleSellingCost.objects.filter(pk=self.cost.pk).values().get()
        request = refund_payload(self)
        refunds, created = refund_sale_cost_payment(**request)
        self.assertTrue(created)
        permanent = FinancialCommandReceipt.objects.filter(pk=request["submission_id"]).values().get()
        for _ in range(20):
            replay, created = refund_sale_cost_payment(**request)
            self.assertFalse(created)
            self.assertEqual([row.pk for row in replay], [row.pk for row in refunds])
        self.assertEqual(SaleCostPayment.objects.filter(pk=self.payments[0].pk).values().get(), payment)
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=self.anchor.pk).values().get(), anchor)
        self.assertEqual(SaleSellingCost.objects.filter(pk=self.cost.pk).values().get(), cost)
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=request["submission_id"]).values().get(), permanent)
        self.assertEqual(self.counts(), (1, 6, 4, 2))
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0.00"))
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("0.00"))
        self.assertEqual(selling_cost_total(self.other_batch), Decimal("100.00"))
        self.assertEqual(sale_cost_payable_summary(date(2026, 1, 31))["total"], Decimal("100.00"))
        self.original_journal.refresh_from_db()
        self.assertEqual(self.original_journal.status, JournalStatus.REVERSED)
        self.assertEqual(list(refunds[0].reversal_journal.lines.order_by("account__code").values_list(
            "account__code", "debit", "credit", "batch_id", "funding_source_id")),
            [("1000", Decimal("60.00"), Decimal("0.00"), None, self.source.pk),
             ("2000", Decimal("0.00"), Decimal("60.00"), self.other_batch.pk, self.source.pk)])
        self.assertFalse(record_sale_cost_payment(**self.original_request)[1])
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
        balance = trial_balance()
        self.assertEqual(balance["debits"], balance["credits"])

    def test_closed_original_month_preserved_refund_date_reopens_payable_without_profit(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        march = AccountingPeriod.objects.create(period_start=date(2026, 3, 1), period_end=date(2026, 3, 31))
        refund_sale_cost_payment(**refund_payload(self, refund_date=date(2026, 2, 2)))
        jan, nxt, later = [monthly_profitability_report(row) for row in [self.period, feb, march]]
        self.assertEqual((jan["cash_flow"]["closing_cash"], jan["sale_cost_settlement"]["verified_payables"]),
            (Decimal("140.00"), Decimal("40.00")))
        self.assertEqual((nxt["cash_flow"]["opening_cash"], nxt["cash_flow"]["operating"]["inflows"],
            nxt["cash_flow"]["closing_cash"], nxt["sale_cost_settlement"]["verified_payables"]),
            (Decimal("140.00"), Decimal("60.00"), Decimal("200.00"), Decimal("100.00")))
        self.assertEqual(later["cash_flow"]["opening_cash"], Decimal("200.00"))
        self.assertEqual(nxt["revenue"]["total_revenue"], Decimal("0.00"))
        self.assertEqual(nxt["other_costs"]["net_profit_after_recorded_tax"], Decimal("0.00"))
        self.assertEqual(nxt["cash_flow"]["financing"]["inflows"], Decimal("0.00"))
        self.assertEqual(jan["sale_cost_settlement"]["cash_paid_in_period"], Decimal("60.00"))
        self.assertEqual(nxt["sale_cost_settlement"]["cash_refunded_in_period"], Decimal("60.00"))
        self.assertEqual(sale_cost_payment_total(self.cost, cutoff=date(2026, 1, 31)), Decimal("60.00"))
        self.assertEqual(sale_cost_payment_total(self.cost, cutoff=feb.period_end), Decimal("0.00"))
        self.assertEqual(trial_balance(cutoff=feb.period_end)["debits"], trial_balance(cutoff=feb.period_end)["credits"])

    def test_full_split_group_returns_each_original_source_atomically(self):
        other = FundingSource.objects.create(source_type="general_farm_cash")
        FundingReceipt.objects.create(funding_source=other, amount="30.00", receipt_date=fixtures.instant(), created_by=self.user)
        request = {**payment_payload(self, "40.00"), "funding_allocations": [
            {"funding_source": self.source.pk, "amount": "20.00", "classification": None},
            {"funding_source": other.pk, "amount": "20.00", "classification": ""}]}
        self.payments, _ = record_sale_cost_payment(**request)
        self.original_request = request
        self.anchor = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        refunds, _ = refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual([(row.funding_source_id, row.amount) for row in refunds],
            [(self.source.pk, Decimal("20.00")), (other.pk, Decimal("20.00"))])
        self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
        self.assertEqual(available_funding_source_cash(other), Decimal("30.00"))
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("60.00"))

    def test_changed_refund_evidence_and_cross_command_uuid_cannot_reuse_intent(self):
        request = refund_payload(self)
        refund_sale_cost_payment(**request)
        for change in [{"reason": "Different"}, {"external_reference": "Other"}, {"refund_method": "cash"},
                {"refund_date": date(2026, 1, 24)}, {"source_version": "0" * 64},
                {"original_submission_id": uuid.uuid4()}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                refund_sale_cost_payment(**{**request, **change})
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self, submission_id=self.original_request["submission_id"]))
        self.assertEqual(self.counts(), (1, 6, 4, 2))

    def test_new_uuid_cannot_refund_same_group_again(self):
        request = refund_payload(self)
        refund_sale_cost_payment(**request)
        with self.assertRaises(ValidationError) as error:
            refund_sale_cost_payment(**{**request, "submission_id": uuid.uuid4(), "external_reference": "OTHER-REFUND"})
        self.assertIn("already_refunded", error.exception.detail)

    def test_reopened_payable_can_be_paid_once_not_overpaid(self):
        refund_sale_cost_payment(**refund_payload(self))
        record_sale_cost_payment(**{**payment_payload(self, "100.00"), "payment_date": date(2026, 1, 24)})
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self, "0.01"))
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("100.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("100.00"))

    def test_management_current_role_applies_to_new_effect_and_replay(self):
        User = get_user_model()
        request = refund_payload(self)
        for role in ["farm_supervisor", "general_worker", "stake_holder"]:
            actor = User.objects.create_user(username=role, email=f"{role}@refund.invalid")
            actor.roles.add(Role.objects.get(slug=role))
            with self.subTest(role=role), self.assertRaises(PermissionDenied):
                refund_sale_cost_payment(**{**request, "user": actor})
        refund_sale_cost_payment(**request)
        self.user.roles.clear()
        User.objects.filter(pk=self.user.pk).update(is_superuser=False)
        with self.assertRaises(PermissionDenied):
            refund_sale_cost_payment(**request)

    def test_inactive_actor_cannot_replay(self):
        request = refund_payload(self)
        refund_sale_cost_payment(**request)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            refund_sale_cost_payment(**request)

    def test_manager_and_director_can_refund(self):
        # First exact group uses manager, second uses director; neither gains owner authority.
        for index, role in enumerate(["farm_manager", "director"]):
            actor = get_user_model().objects.create_user(username=role, email=f"{role}@refund.invalid")
            actor.roles.add(Role.objects.get(slug=role))
            if index:
                self.original_request = {**payment_payload(self), "payment_date": date(2026, 1, 24)}
                self.payments, _ = record_sale_cost_payment(**self.original_request)
                self.anchor = FinancialCommandReceipt.objects.get(pk=self.original_request["submission_id"])
            refunds, _ = refund_sale_cost_payment(**refund_payload(self, user=actor, external_reference=role,
                refund_date=date(2026, 1, 25 if index else 23)))
            self.assertEqual(refunds[0].created_by, actor)

    def test_invalid_actual_date_evidence_version_method_currency_or_ids_have_no_effect(self):
        before = self.counts()
        for change in [{"currency": "USD"}, {"original_submission_id": True}, {"original_submission_id": uuid.uuid4()},
                {"submission_id": "bad"}, {"refund_date": timezone.localdate() + timedelta(days=1)},
                {"refund_date": date(2026, 1, 21)}, {"refund_date": fixtures.instant()}, {"refund_date": "2026-01-23"},
                {"source_version": "x" * 64}, {"source_version": {}}, {"refund_method": []}, {"refund_method": "credit"},
                {"external_reference": " "}, {"external_reference": "x" * 121}, {"reason": " "}, {"reason": "x" * 2001}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                refund_sale_cost_payment(**refund_payload(self, **change))
            self.assertEqual(self.counts(), before)

    def test_missing_closed_or_overlapping_refund_period_refused(self):
        for day in [date(2025, 12, 31), date(2026, 2, 1)]:
            with self.assertRaises(ValidationError):
                refund_sale_cost_payment(**refund_payload(self, refund_date=day))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))
        self.period.status = PeriodStatus.OPEN
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 1, 2), period_end=date(2026, 1, 25))
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_older_accepted_payment_result_is_recoverable_but_never_adopted_for_refund(self):
        old = {key: value for key, value in self.anchor.result.items() if key not in {"original_request", "payment_versions"}}
        corrupt_fixture(FinancialCommandReceipt, self.anchor.pk, "result", json.dumps(old))
        self.anchor.refresh_from_db()
        self.assertFalse(record_sale_cost_payment(**self.original_request)[1])
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=self.anchor.pk).result, old)

    def test_stale_payment_or_original_cost_version_refused(self):
        request = refund_payload(self)
        corrupt_fixture(SaleCostPayment, self.payments[0].pk, "payee", "Tampered")
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**request)
        corrupt_fixture(SaleCostPayment, self.payments[0].pk, "payee", "Synthetic transporter")
        with self.assertRaises(DjangoValidationError):
            SaleSellingCost.objects.filter(pk=self.cost.pk).update(notes="Changed original economic evidence")
        corrupt_fixture(SaleSellingCost, self.cost.pk, "notes", "Changed original economic evidence")
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**request)

    def test_original_request_hash_or_payment_version_tamper_refused(self):
        corrupt_fixture(FinancialCommandReceipt, self.anchor.pk, "request_hash", "0" * 64)
        self.anchor.refresh_from_db()
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_missing_anchor_or_changed_split_order_or_actor_requires_review(self):
        request = refund_payload(self)
        corrupt_fixture(SaleCostPayment, self.payments[0].pk, "split_index", 1)
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**request)
        corrupt_fixture(SaleCostPayment, self.payments[0].pk, "split_index", 0)
        corrupt_fixture(FinancialCommandReceipt, self.anchor.pk, "completed_at", None)
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**request)

    def test_original_full_journal_mismatch_refused(self):
        line = self.original_journal.lines.get(account__code="1000")
        corrupt_fixture(JournalLine, line.pk, "credit", "59.00")
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_source_binding_tamper_requires_review_even_with_new_current_snapshot(self):
        corrupt_fixture(FundingSource, self.source.pk, "batch_id", self.other_batch.pk)
        self.payments = list(SaleCostPayment.objects.filter(submission_id=self.original_request["submission_id"]).order_by("split_index"))
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_sale_cancellation_refused(self):
        with self.assertRaises(DjangoValidationError):
            Sales.objects.filter(pk=self.sale.pk).update(payment_status="cancelled")
        corrupt_fixture(Sales, self.sale.pk, "payment_status", "cancelled")
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_original_payable_full_journal_mismatch_refused(self):
        line = self.payments[0].payable_journal.lines.get(account__code="2000")
        corrupt_fixture(JournalLine, line.pk, "credit", "99.00")
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))

    def test_inactive_source_can_receive_actual_refund_but_cannot_be_spent(self):
        self.source.description = "New display label"
        self.source.is_active = False
        self.source.save()
        refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))

    def test_source_economic_binding_is_protected_on_all_normal_save_paths_even_gates_off(self):
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False, FINANCE_SALE_COST_REVERSALS=False):
            for action in [lambda: FundingSource.objects.filter(pk=self.source.pk).update(batch=self.other_batch),
                    lambda: FundingSource.objects.filter(pk=self.source.pk).delete(),
                    lambda: FundingSource.objects.filter(pk=self.source.pk)._raw_delete("default")]:
                with self.assertRaises(DjangoValidationError):
                    action()
            self.source.batch = self.other_batch
            with self.assertRaises(DjangoValidationError):
                self.source.save()
            with self.assertRaises(DjangoValidationError):
                self.source.save_base()
            with self.assertRaises(DjangoValidationError):
                FundingSource.objects.bulk_update([self.source], ["batch"])

    def test_original_payable_payment_and_opposite_gl_only_reversal_refused_even_flags_off(self):
        refunds, _ = refund_sale_cost_payment(**refund_payload(self))
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False, FINANCE_SALE_COST_REVERSALS=False):
            for journal in [self.original_journal, self.payments[0].payable_journal, refunds[0].reversal_journal]:
                with self.assertRaises(ValidationError):
                    reverse_journal(journal, posting_date=date(2026, 1, 24), reason="Synthetic GL-only attempt", user=self.user)

    def test_refund_model_is_immutable_and_forged_creation_or_context_none_refused(self):
        refund = refund_sale_cost_payment(**refund_payload(self))[0][0]
        for action in [lambda: refund.save(), lambda: refund.save_base(), lambda: refund.delete(),
                lambda: SaleCostPaymentReversal.objects.filter(pk=refund.pk).update(reason="Changed"),
                lambda: SaleCostPaymentReversal.objects.bulk_update([refund], ["reason"]),
                lambda: SaleCostPaymentReversal.objects.filter(pk=refund.pk).delete(),
                lambda: SaleCostPaymentReversal.objects.filter(pk=refund.pk)._raw_delete("default"),
                lambda: SaleCostPaymentReversal.objects.bulk_create([refund]),
                lambda: SaleCostPaymentReversal(payment=self.payments[0]).save(),
                lambda: SaleCostPaymentReversal(payment=self.payments[0]).save_base(raw=True)]:
            with self.assertRaises(DjangoValidationError):
                action()
        self.assertFalse(sale_cost_reversal_allowed(None))
        self.assertFalse(sale_cost_reversal_allowed(self.original_journal.pk))

    def test_missing_chart_or_interruption_rolls_back_source_journals_audit_receipt(self):
        before = self.counts()
        ChartOfAccount.objects.filter(code="1000").update(is_active=False)
        with self.assertRaises(ValidationError):
            refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual(self.counts(), before)
        ChartOfAccount.objects.filter(code="1000").update(is_active=True)
        for target in ["apps.finance.services.sale_cost_reversals.SaleCostPaymentReversal.objects.create",
                       "apps.finance.services.sale_cost_reversals.record_finance_action"]:
            with patch(target, side_effect=ValueError("Synthetic interruption")), self.assertRaises(ValueError):
                refund_sale_cost_payment(**refund_payload(self))
            self.assertEqual(self.counts(), before)
            self.original_journal.refresh_from_db()
            self.assertEqual(self.original_journal.status, JournalStatus.POSTED)
            self.assertFalse(sale_cost_reversal_allowed(self.original_journal.pk))

    def test_full_split_group_last_row_failure_rolls_back_earlier_split(self):
        request = {**payment_payload(self, "40.00"), "funding_allocations": [
            {"funding_source": self.source.pk, "amount": "20.00"}, {"funding_source": self.source.pk, "amount": "20.00"}]}
        self.payments, _ = record_sale_cost_payment(**request)
        self.original_request = request
        self.anchor = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        before = self.counts()
        create = SaleCostPaymentReversal.objects.create
        def interrupted(**kwargs):
            if kwargs["split_index"] == 1:
                raise ValueError("Synthetic second split failure")
            return create(**kwargs)
        with patch("apps.finance.services.sale_cost_reversals.SaleCostPaymentReversal.objects.create", side_effect=interrupted), self.assertRaises(ValueError):
            refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual(self.counts(), before)
        self.assertTrue(all(row.status == JournalStatus.POSTED for row in JournalEntry.objects.filter(pk__in=self.anchor.result["journal_ids"])))
        self.assertEqual(available_batch_cash(self.batch), Decimal("100.00"))

    def test_dated_refund_cannot_fund_backdated_payment(self):
        # Only60 confirmed cash originally; no future refund can fundJan22 again.
        # Remove unused original cash by another actual accepted payment to this cost.
        record_sale_cost_payment(**payment_payload(self, "40.00"))
        refund_sale_cost_payment(**refund_payload(self, refund_date=date(2026, 1, 25)))
        # Existing100 unspent cash +60 future refund: refuse spending160 beforeJan25.
        data = {**fixtures.sale_payload(self), "batch_id": self.other_batch.pk,
            "selling_costs": [{"category": "transport", "amount": "160.00"}]}
        sale, _ = record_financial_sale(**data)
        pay = {**payment_payload(self, "160.00"), "selling_cost_id": sale.selling_costs.get().pk}
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**pay)
        record_sale_cost_payment(**{**pay, "payment_date": date(2026, 1, 25)})
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))

    def test_future_refund_cannot_reopen_backdated_payable_even_with_ample_cash(self):
        record_sale_cost_payment(**payment_payload(self, "40.00"))
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        refund_sale_cost_payment(**refund_payload(self, refund_date=date(2026, 2, 2)))
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**{**payment_payload(self), "payment_date": date(2026, 1, 24)})
        record_sale_cost_payment(**{**payment_payload(self), "payment_date": date(2026, 2, 2)})
        self.assertEqual(sale_cost_payment_total(self.cost, cutoff=date(2026, 1, 31)), Decimal("100.00"))
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("100.00"))

    def test_batch_source_alias_net_cash_utilization_and_funding_mix(self):
        alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch)
        refund_sale_cost_payment(**refund_payload(self))
        self.assertEqual(funding_source_available_balances([self.source, alias]),
            {self.source.pk: Decimal("200.00"), alias.pk: Decimal("200.00")})
        usage = batch_revenue_utilization(self.batch)
        self.assertEqual((usage["cash_used"], usage["available_cash"]), (Decimal("0.00"), Decimal("200.00")))
        self.assertEqual(usage["by_category"]["Sale-specific selling costs"], Decimal("0.00"))
        self.assertEqual([row["amount"] for row in usage["transactions"]], [Decimal("60.00"), Decimal("-60.00")])
        mix = portfolio_expenditure_funding_mix([self.other_batch])
        self.assertEqual(mix["total_paid_for_batches"], Decimal("0.00"))
        self.assertEqual(mix["total_batch_expenditure"], Decimal("100.00"))

    def test_normalized_reference_already_received_as_funding_requires_review(self):
        FundingReceipt.objects.create(funding_source=self.source, amount="60.00", receipt_date=fixtures.instant(),
            reference="  SyNtHeTiC-ReFuNd  ", created_by=self.user)
        with self.assertRaises(ValidationError) as error:
            refund_sale_cost_payment(**refund_payload(self))
        self.assertIn("possible_duplicate", error.exception.detail)

    def test_normalized_refund_reference_cannot_add_loan_cash(self):
        refund_sale_cost_payment(**refund_payload(self))
        loan = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        with override_settings(FINANCE_FUNDING_RECEIPTS=True), self.assertRaises(ValidationError):
            record_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                funding_source_id=loan.pk, source_version=funding_source_version(loan), amount="60.00",
                receipt_date=fixtures.instant(), counterparty="Synthetic lender", payment_method="cash", reference=" synthetic-REFUND ")
        self.assertEqual(available_funding_source_cash(loan), Decimal("0.00"))

    def test_read_gate_preserves_effective_cash_with_new_capture_disabled(self):
        refund_sale_cost_payment(**refund_payload(self))
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False):
            self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
            self.assertEqual(monthly_profitability_report(self.period)["sale_cost_settlement"]["verified_payables"], Decimal("100.00"))
            with self.assertRaises(ValidationError):
                record_sale_cost_payment(**payment_payload(self))

    def test_disabled_refund_gate_has_zero_queries_and_old_reads_avoid_new_tables(self):
        request = refund_payload(self)
        with override_settings(FINANCE_SALE_COST_REVERSALS=False):
            with self.assertNumQueries(0), self.assertRaises(ValidationError):
                refund_sale_cost_payment(**request)
            with connection.execute_wrapper(self.no_new_table):
                self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
                monthly_profitability_report(self.period)

    def no_new_table(self, execute, sql, params, many, context):
        self.assertNotIn(SaleCostPaymentReversal._meta.db_table, sql)
        return execute(sql, params, many, context)

    def test_full_reason_retained_without_exceeding_journal_caption(self):
        reason = "Synthetic refund reason " * 80
        refund = refund_sale_cost_payment(**refund_payload(self, reason=reason))[0][0]
        self.assertEqual(refund.reason, reason.strip())
        self.assertLessEqual(len(refund.reversal_journal.description), 255)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_SALE_COST_SETTLEMENT=True, FINANCE_SALE_COST_REVERSALS=True)
class SaleCostRefundConcurrencyTests(TransactionTestCase):
    race = fixtures.FinancialCaptureConcurrencyTests.race

    def setUp(self):
        refund_fixture(self)

    def test_same_intent_race_has_one_effect_and_one_replay(self):
        request = refund_payload(self)
        outcomes = self.race([lambda: refund_sale_cost_payment(**request)] * 2)
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "accepted"])
        self.assertEqual(sum(row[1][1] for row in outcomes), 1)
        self.assertEqual(SaleCostPaymentReversal.objects.count(), 1)

    def test_different_intents_race_same_group_only_one_refund(self):
        first, second = refund_payload(self), refund_payload(self, external_reference="OTHER-REFUND")
        outcomes = self.race([lambda: refund_sale_cost_payment(**first), lambda: refund_sale_cost_payment(**second)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))

    def test_competing_payments_cannot_overpay_reopened_payable(self):
        refund_sale_cost_payment(**refund_payload(self))
        request = {**payment_payload(self, "100.00"), "payment_date": date(2026, 1, 24)}
        outcomes = self.race([lambda: record_sale_cost_payment(**{**request, "submission_id": uuid.uuid4()})] * 2)
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("100.00"))

    def test_same_normalized_refund_reference_across_original_groups_only_one_cash_effect(self):
        first = refund_payload(self)
        self.original_request = payment_payload(self, "40.00")
        self.payments, _ = record_sale_cost_payment(**self.original_request)
        self.anchor = FinancialCommandReceipt.objects.get(pk=self.original_request["submission_id"])
        second = refund_payload(self, external_reference=" synthetic-REFUND ")
        outcomes = self.race([lambda: refund_sale_cost_payment(**first), lambda: refund_sale_cost_payment(**second)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(SaleCostPaymentReversal.objects.count(), 1)

    @override_settings(FINANCE_FUNDING_RECEIPTS=True)
    def test_refund_and_loan_same_reference_race_cannot_double_record_incoming_cash(self):
        request = refund_payload(self)
        loan = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        incoming = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", funding_source_id=loan.pk,
            source_version=funding_source_version(loan), amount="60.00", receipt_date=fixtures.instant(),
            counterparty="Synthetic lender", payment_method="bank_transfer", reference=" synthetic-REFUND ")
        outcomes = self.race([lambda: refund_sale_cost_payment(**request),
            lambda: record_financial_funding_receipt(**incoming)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(SaleCostPaymentReversal.objects.count() + FundingReceipt.objects.filter(funding_source=loan).count(), 1)
