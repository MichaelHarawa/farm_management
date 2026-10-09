from copy import deepcopy
from datetime import date
from decimal import Decimal
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role
from apps.finance.models import (AccountingPeriod, ChartOfAccount, CostAllocation, Expenditure,
    ExpenditureCategory, FinanceActionEvent, FinancialCommandReceipt, FundingAllocation, FundingSource,
    FundingSourceType, JournalEntry, JournalLine, PeriodStatus)
from apps.finance.services.expenditure_drafts import (expenditure_draft_version,
    post_financial_expenditure_draft, update_financial_expenditure_draft)
from apps.finance.services.expenditures import post_expenditure
from apps.finance.services.financial_capture import (record_financial_expenditure,
    record_financial_sale, record_financial_supplier_payment)
from apps.finance.services.ledger import trial_balance
from apps.finance.services.profitability import available_batch_cash, available_funding_source_cash
from apps.finance.services.reporting import monthly_profitability_report
from apps.poultry.models import InputCosts
from .test_financial_capture import fixture, instant, sale_payload


SETTINGS = dict(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)


def draft(test, **extra):
    return record_financial_expenditure(**{"submission_id": uuid.uuid4(), "user": test.user, "currency": "MWK",
        "expenditure_date": date(2026, 1, 21), "amount": "100.00", "category_id": test.category.pk,
        "accounting_nature": "direct_cost", "description": "Synthetic cleaning service", "payee": "Synthetic supplier",
        "cost_allocations": [{"batch": test.other_batch.pk, "amount": "100.00"}], **extra})[0]


def posting(test, expenditure, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", expenditure_id=expenditure.pk,
        expected_version=expenditure_draft_version(expenditure), **extra)


def editing(test, expenditure, changes=None, **extra):
    return {**posting(test, expenditure), "changes": changes or {"notes": "Observed corrected evidence"},
            "reason": "Synthetic draft correction", **extra}


def funded_source(test, amount="200.00"):
    payload = sale_payload(test)
    payload["initial_receipt"] = {"amount": amount, "payment_date": instant(), "payment_method": "cash"}
    record_financial_sale(**payload)
    return FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=test.batch)


@override_settings(**SETTINGS)
class ExpenditureDraftTests(TestCase):
    def setUp(self):
        fixture(self)

    def effects(self):
        return tuple(model.objects.count() for model in [Expenditure, CostAllocation, FundingAllocation,
            JournalEntry, JournalLine, FinancialCommandReceipt, FinanceActionEvent, InputCosts])

    def test_create_and_update_remain_drafts_with_zero_financial_effects(self):
        expense = draft(self)
        original_reference = expense.expenditure_reference
        original_actor, original_time = expense.created_by_id, expense.created_at
        creation = FinancialCommandReceipt.objects.get(result__expenditure_id=str(expense.pk))
        self.assertEqual(creation.result["draft_version"], expenditure_draft_version(expense))
        command = editing(self, expense, {"amount": "130.00", "description": "Corrected cleaning service",
            "payee": "Observed payee", "external_reference": "SYNTHETIC-INVOICE",
            "cost_allocations": [{"batch": self.batch.pk, "amount": "30.00"},
                                 {"batch": self.other_batch.pk, "amount": "100.00"}]})
        updated, created = update_financial_expenditure_draft(**command)
        self.assertTrue(created)
        self.assertEqual((updated.pk, updated.expenditure_reference, updated.created_by_id, updated.created_at),
            (expense.pk, original_reference, original_actor, original_time))
        self.assertEqual((updated.status, updated.payment_status, updated.amount), ("draft", "unpaid", Decimal("130.00")))
        self.assertNotEqual(expenditure_draft_version(updated), command["expected_version"])
        self.assertEqual(self.effects(), (1, 0, 0, 0, 0, 2, 1, 0))
        self.assertEqual(monthly_profitability_report(self.period)["production"]["direct_batch_costs"], Decimal("0.00"))

    def test_twenty_identical_edits_replay_original_receipt_even_after_another_edit(self):
        expense = draft(self)
        command = editing(self, expense)
        updated, _ = update_financial_expenditure_draft(**command)
        accepted = FinancialCommandReceipt.objects.get(pk=command["submission_id"])
        original = deepcopy((accepted.request_hash, accepted.result))
        update_financial_expenditure_draft(**editing(self, updated, {"notes": "Later explicit correction"}))
        for _ in range(20):
            self.assertFalse(update_financial_expenditure_draft(**command)[1])
        accepted.refresh_from_db()
        expense.refresh_from_db()
        self.assertEqual((accepted.request_hash, accepted.result), original)
        self.assertEqual(expense.notes, "Later explicit correction")
        self.assertEqual((FinanceActionEvent.objects.count(), FinancialCommandReceipt.objects.count()), (2, 3))
        for change in [{"changes": {"notes": "Changed repeat"}}, {"reason": "Changed repeat reason"},
                       {"expected_version": "0" * 64}]:
            with self.assertRaises(ValidationError):
                update_financial_expenditure_draft(**{**command, **change})

    def test_stale_edit_or_post_never_overwrites_current_draft(self):
        expense = draft(self)
        stale_edit, stale_post = editing(self, expense), posting(self, expense)
        updated, _ = update_financial_expenditure_draft(**editing(self, expense, {"notes": "Current evidence"}))
        before = self.effects(), expenditure_draft_version(updated)
        for call, command in [(update_financial_expenditure_draft, stale_edit), (post_financial_expenditure_draft, stale_post)]:
            with self.assertRaises(ValidationError) as error:
                call(**command)
            self.assertIn("revision_conflict", error.exception.detail)
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense)), before)

    def test_twenty_posts_reuse_original_source_one_payable_and_cost_without_payment(self):
        expense = draft(self)
        command = posting(self, expense)
        posted, created = post_financial_expenditure_draft(**command)
        self.assertTrue(created)
        receipt = FinancialCommandReceipt.objects.get(pk=command["submission_id"])
        original = deepcopy((receipt.request_hash, receipt.result))
        for _ in range(20):
            replay, created = post_financial_expenditure_draft(**command)
            self.assertEqual(replay.pk, expense.pk)
            self.assertFalse(created)
        self.assertEqual((posted.status, posted.payment_status), ("posted", "unpaid"))
        self.assertEqual(self.effects(), (1, 1, 0, 1, 2, 2, 1, 0))
        lines = list(JournalLine.objects.order_by("account__code").values_list("account__code", "debit", "credit", "batch_id"))
        self.assertEqual(lines, [("2000", Decimal("0.00"), Decimal("100.00"), None),
                                ("5000", Decimal("100.00"), Decimal("0.00"), self.other_batch.pk)])
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0.00"))
        receipt.refresh_from_db()
        self.assertEqual((receipt.request_hash, receipt.result), original)
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**{**command, "submission_id": uuid.uuid4()})
        with self.assertRaises(ValidationError):
            update_financial_expenditure_draft(**editing(self, posted))

    def test_edit_then_partial_post_and_later_settlement_charge_beneficiary_once(self):
        source = funded_source(self)
        expense = draft(self)
        expense, _ = update_financial_expenditure_draft(**editing(self, expense, {"amount": "130.00",
            "cost_allocations": [{"batch": self.other_batch.pk, "amount": "130.00"}]}))
        command = posting(self, expense, payment_date=date(2026, 1, 22),
            funding_allocations=[{"funding_source": source.pk, "amount": "60.00"}])
        expense, _ = post_financial_expenditure_draft(**command)
        for _ in range(20):
            self.assertFalse(post_financial_expenditure_draft(**command)[1])
        self.assertEqual((expense.payment_status, expense.amount), ("partial", Decimal("130.00")))
        self.assertEqual(available_funding_source_cash(source), Decimal("140.00"))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0.00"))
        self.assertEqual(CostAllocation.objects.get(expenditure=expense).allocated_amount, Decimal("130.00"))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        payment = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
            payment_date=date(2026, 2, 1), funding_allocations=[{"funding_source": source.pk, "amount": "70.00"}])
        record_financial_supplier_payment(**payment)
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**payment)[1])
        expense.refresh_from_db()
        self.assertEqual(expense.payment_status, "paid")
        self.assertEqual(available_funding_source_cash(source), Decimal("70.00"))
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), FundingAllocation.objects.count(), InputCosts.objects.count()), (1, 1, 2, 0))
        self.assertEqual(JournalEntry.objects.filter(source_model="finance.Expenditure").count(), 1)
        balance = trial_balance()
        self.assertEqual(balance["debits"], balance["credits"])

    def test_admin_draft_posts_without_batch_mirror(self):
        expense = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="50.00", category_id=self.category.pk,
            accounting_nature="indirect_operating_expense", description="Synthetic administration", payee="Synthetic")[0]
        posted, _ = post_financial_expenditure_draft(**posting(self, expense))
        self.assertEqual(posted.beneficiary_type, "general_admin")
        self.assertEqual(CostAllocation.objects.count(), 0)
        self.assertEqual(JournalLine.objects.get(account__code="6100").debit, Decimal("50.00"))

    def test_insufficient_funding_overpayment_or_missing_account_roll_back_entire_post(self):
        source = funded_source(self, "50.00")
        expense = draft(self)
        command = posting(self, expense, payment_date=date(2026, 1, 22))
        before = self.effects(), expenditure_draft_version(expense), available_funding_source_cash(source)
        for amount in ["51.00", "101.00"]:
            with self.assertRaises(ValidationError):
                post_financial_expenditure_draft(**{**command,
                    "funding_allocations": [{"funding_source": source.pk, "amount": amount}]})
            expense.refresh_from_db()
            self.assertEqual((self.effects(), expenditure_draft_version(expense), available_funding_source_cash(source)), before)
        ChartOfAccount.objects.filter(code="2000").update(is_active=False)
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense), available_funding_source_cash(source)), before)

    def test_failure_after_post_journal_rolls_back_status_cost_journal_receipt_and_audit(self):
        expense = draft(self)
        before = self.effects(), expenditure_draft_version(expense)
        with patch("apps.finance.services.expenditure_drafts.record_finance_action", side_effect=RuntimeError("Synthetic post-journal crash")):
            with self.assertRaises(RuntimeError):
                post_financial_expenditure_draft(**posting(self, expense))
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense)), before)

    def test_invalid_patch_rejects_before_hash_or_write_and_keeps_original(self):
        expense = draft(self)
        before = self.effects(), expenditure_draft_version(expense)
        for changes in [{"amount": 1.1}, {"amount": float("nan")}, {"amount": "1.001"},
                {"amount": "NaN"}, {"amount": True}, {"amount": "-1.00"}, {"posted_by": str(self.user.pk)},
                {"status": "posted"}, {"journal_lines": []}, {"description": ""}, {"notes": {}},
                {"category_id": True}, {"accounting_nature": "inventory_purchase"},
                {"cost_allocations": [{"batch": self.batch.pk, "amount": "99.00"}]},
                {"cost_allocations": [{"batch": self.batch.pk, "amount": "50.00"}] * 2},
                {"expenditure_date": date(2099, 1, 1)}]:
            with self.subTest(changes=changes), self.assertRaises((ValidationError, DjangoValidationError)):
                update_financial_expenditure_draft(**editing(self, expense, changes))
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense)), before)

    def test_closed_original_period_cannot_be_evaded_by_editing_date_or_posting(self):
        expense = draft(self)
        command = posting(self, expense)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        before = self.effects(), expenditure_draft_version(expense)
        for call, payload in [(post_financial_expenditure_draft, command), (update_financial_expenditure_draft,
                editing(self, expense, {"expenditure_date": date(2026, 2, 1)}))]:
            with self.assertRaises(ValidationError) as error:
                call(**payload)
            self.assertIn("period_locked", error.exception.detail)
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense)), before)

    def test_explicit_open_period_date_edit_preserves_original_reference_and_actor(self):
        expense = draft(self)
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        changed, _ = update_financial_expenditure_draft(**editing(self, expense, {"expenditure_date": date(2026, 2, 1)}))
        self.assertEqual((changed.expenditure_reference, changed.created_by_id), (expense.expenditure_reference, expense.created_by_id))
        post_financial_expenditure_draft(**posting(self, changed))
        self.assertEqual(JournalEntry.objects.get(source_model="finance.Expenditure").posting_date, date(2026, 2, 1))

    def test_accepted_post_replays_after_period_close_but_changed_date_or_funding_does_not(self):
        source = funded_source(self)
        expense = draft(self)
        command = posting(self, expense, payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": source.pk, "amount": "60.00"}])
        post_financial_expenditure_draft(**command)
        before = self.effects()
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        self.assertFalse(post_financial_expenditure_draft(**command)[1])
        for change in [{"payment_date": date(2026, 1, 23)}, {"expected_version": "0" * 64},
                       {"funding_allocations": [{"funding_source": source.pk, "amount": "59.00"}]}]:
            with self.assertRaises(ValidationError):
                post_financial_expenditure_draft(**{**command, **change})
        self.assertEqual(self.effects(), before)

    def test_legacy_and_externally_edited_drafts_are_not_silently_adopted(self):
        expense = draft(self)
        Expenditure.objects.filter(pk=expense.pk).update(notes="External unsupported edit")
        expense.refresh_from_db()
        with self.assertRaises(ValidationError) as error:
            post_financial_expenditure_draft(**posting(self, expense))
        self.assertIn("legacy_reconciliation", error.exception.detail)
        legacy = Expenditure.objects.create(expenditure_date=expense.expenditure_date, accounting_period=self.period,
            amount=expense.amount, category=self.category, description="Historical unverified draft", accounting_nature="direct_cost",
            cost_allocation_plan=expense.cost_allocation_plan, created_by=self.user)
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, legacy))
        old_version = draft(self)
        # Simulate an earlier accepted draft without fabricating a new token.
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("UPDATE finance_financialcommandreceipt SET result=result-'draft_version' WHERE result->>'expenditure_id'=%s", [str(old_version.pk)])
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, old_version))
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_draft_creation_receipt_plus_legacy_post_is_not_a_verified_payable(self):
        source = funded_source(self)
        expense = draft(self)
        post_expenditure(expenditure_id=expense.pk, user=self.user, funding_rows=[], allow_unpaid=True)
        with self.assertRaises(ValidationError):
            record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
                payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": source.pk, "amount": "10.00"}])
        self.assertEqual(FundingAllocation.objects.count(), 0)
        self.assertEqual(available_funding_source_cash(source), Decimal("200.00"))

    def test_payment_date_requires_real_split_not_paid_dropdown_or_pre_expense_deposit(self):
        source = funded_source(self)
        expense = draft(self)
        for changes in [{"payment_date": date(2026, 1, 22)}, {"funding_allocations": [{"funding_source": source.pk, "amount": "10.00"}]},
                {"payment_date": date(2026, 1, 20), "funding_allocations": [{"funding_source": source.pk, "amount": "10.00"}]},
                {"payment_date": date(2099, 1, 1), "funding_allocations": [{"funding_source": source.pk, "amount": "10.00"}]}]:
            with self.assertRaises(ValidationError):
                post_financial_expenditure_draft(**posting(self, expense, **changes))
        self.assertEqual(FundingAllocation.objects.count(), 0)
        self.assertEqual(CostAllocation.objects.count(), 0)

    def test_closed_finalized_or_inactive_category_requires_review_and_keeps_draft(self):
        expense = draft(self)
        self.other_batch.closed_at = instant(day=22)
        self.other_batch.save()
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        self.other_batch.closed_at = None
        self.other_batch.profitability_finalized_at = instant(day=22)
        self.other_batch.save()
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        self.other_batch.profitability_finalized_at = None
        self.other_batch.save()
        self.category.is_active = False
        self.category.save()
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        self.assertEqual((JournalEntry.objects.count(), CostAllocation.objects.count()), (0, 0))

    def test_posted_model_validation_is_not_bypassed_by_draft_state(self):
        other, _ = ExpenditureCategory.objects.get_or_create(name="Other", defaults={"code": "synthetic_other"})
        # Isolate posted-state detail validation from this seed's independent
        # itemized-purchase gate; modify only the disposable fixture category.
        other.requires_item_details = False
        other.save()
        expense = draft(self, category_id=other.pk)
        with self.assertRaises(DjangoValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        expense.refresh_from_db()
        self.assertEqual(expense.status, "draft")
        self.assertEqual(CostAllocation.objects.count(), 0)

    def test_current_write_role_required_on_new_post_edit_and_accepted_replay(self):
        expense = draft(self)
        for slug in ["general_worker", "stake_holder"]:
            user = get_user_model().objects.create_user(username=slug, email=slug + "@example.invalid")
            role, _ = Role.objects.get_or_create(slug=slug, defaults={"name": slug})
            user.roles.add(role)
            for call, command in [(post_financial_expenditure_draft, posting(self, expense)),
                    (update_financial_expenditure_draft, editing(self, expense))]:
                with self.assertRaises(PermissionDenied):
                    call(**{**command, "user": user})
        command = posting(self, expense)
        post_financial_expenditure_draft(**command)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            post_financial_expenditure_draft(**command)

    def test_missing_version_reason_or_invalid_identity_cannot_mutate_draft(self):
        expense = draft(self)
        before = self.effects(), expenditure_draft_version(expense)
        for change in [{"expected_version": None}, {"expected_version": "bad"}, {"expected_version": "A" * 64},
                       {"reason": ""}, {"reason": {}}, {"changes": {}}, {"changes": []},
                       {"expenditure_id": True}, {"currency": "USD"}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                update_financial_expenditure_draft(**{**editing(self, expense), **change})
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense)), before)

    def test_existing_draft_funding_is_refused_without_deleting_or_spending_it(self):
        source = funded_source(self)
        expense = draft(self)
        FundingAllocation.objects.create(expenditure=expense, funding_source=source, amount=Decimal("10.00"),
            allocation_date=expense.expenditure_date, created_by=self.user)
        before = self.effects(), expenditure_draft_version(expense), available_funding_source_cash(source)
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**posting(self, expense))
        expense.refresh_from_db()
        self.assertEqual((self.effects(), expenditure_draft_version(expense), available_funding_source_cash(source)), before)

    def test_payable_amount_or_date_mutation_does_not_authorize_unjournaled_settlement(self):
        source = funded_source(self)
        expense = draft(self)
        post_financial_expenditure_draft(**posting(self, expense))
        original_day, original_amount = expense.expenditure_date, expense.amount
        before = self.effects(), available_funding_source_cash(source)
        for change in [{"amount": Decimal("101.00")}, {"expenditure_date": date(2026, 1, 22)}]:
            Expenditure.objects.filter(pk=expense.pk).update(**change)
            with self.assertRaises(ValidationError):
                record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
                    payment_date=date(2026, 1, 23), funding_allocations=[{"funding_source": source.pk, "amount": "10.00"}])
            Expenditure.objects.filter(pk=expense.pk).update(amount=original_amount, expenditure_date=original_day)
        self.assertEqual((self.effects(), available_funding_source_cash(source)), before)

    def test_pre_expense_supplier_payment_is_not_a_guessed_deposit(self):
        source = funded_source(self)
        expense = draft(self)
        post_financial_expenditure_draft(**posting(self, expense))
        with self.assertRaises(ValidationError) as error:
            record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
                payment_date=date(2026, 1, 20), funding_allocations=[{"funding_source": source.pk, "amount": "10.00"}])
        self.assertIn("payment_date", error.exception.detail)
        self.assertEqual(FundingAllocation.objects.count(), 0)

    def test_valid_future_period_does_not_authorize_future_expense_or_payment(self):
        AccountingPeriod.objects.create(period_start=date(2099, 1, 1), period_end=date(2099, 1, 31))
        expense = draft(self, expenditure_date=date(2099, 1, 1))
        with self.assertRaises(ValidationError) as error:
            post_financial_expenditure_draft(**posting(self, expense))
        self.assertIn("expenditure_date", error.exception.detail)
        with self.assertRaises(ValidationError):
            draft(self, expenditure_date=date(2099, 1, 1), post=True)
        self.assertEqual((Expenditure.objects.count(), JournalEntry.objects.count()), (1, 0))
        source = funded_source(self)
        current = draft(self)
        with self.assertRaises(ValidationError) as error:
            post_financial_expenditure_draft(**posting(self, current, payment_date=date(2099, 1, 1),
                funding_allocations=[{"funding_source": source.pk, "amount": "10.00"}]))
        self.assertIn("payment_date", error.exception.detail)

    def test_funding_classification_is_strict_before_hashing_or_side_effects(self):
        expense = draft(self)
        for value in [{}, [], True, "arbitrary"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                post_financial_expenditure_draft(**posting(self, expense, payment_date=date(2026, 1, 22),
                    funding_allocations=[{"funding_source": 1, "amount": "10.00", "classification": value}]))
        self.assertEqual((CostAllocation.objects.count(), FundingAllocation.objects.count(), JournalEntry.objects.count()), (0, 0, 0))

    def test_legacy_null_blank_funding_defaults_keep_original_hash_and_replay(self):
        source = funded_source(self)
        expense = draft(self)
        post_financial_expenditure_draft(**posting(self, expense))
        for classification in [None, ""]:
            command = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
                payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": source.pk,
                    "amount": "10.00", "classification": classification}])
            record_financial_supplier_payment(**command)
            receipt = FinancialCommandReceipt.objects.get(pk=command["submission_id"])
            original = deepcopy((receipt.request_hash, receipt.result))
            for _ in range(20):
                self.assertFalse(record_financial_supplier_payment(**command)[1])
            receipt.refresh_from_db()
            self.assertEqual((receipt.request_hash, receipt.result), original)
        self.assertEqual(list(FundingAllocation.objects.values_list("classification", flat=True)), ["reinvestment", "reinvestment"])
        self.assertEqual(available_funding_source_cash(source), Decimal("180.00"))


@override_settings(**SETTINGS)
class ExpenditureDraftConcurrencyTests(TransactionTestCase):
    def setUp(self):
        fixture(self)

    def race(self, calls):
        barrier = Barrier(2)
        results = []
        def run(call, payload):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                _, created = call(**payload)
                results.append(("accepted", created))
            except ValidationError:
                results.append(("rejected", False))
            except Exception as error:
                results.append((type(error).__name__, False))
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=row) for row in calls]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        return sorted(results)

    def test_same_post_id_races_create_one_source_payable_receipt_and_audit(self):
        expense = draft(self)
        command = posting(self, expense)
        self.assertEqual(self.race([(post_financial_expenditure_draft, command)] * 2), [("accepted", False), ("accepted", True)])
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), JournalEntry.objects.count(),
            FinancialCommandReceipt.objects.count(), FinanceActionEvent.objects.count()), (1, 1, 1, 2, 1))

    def test_distinct_post_ids_for_same_version_accept_only_one_payable(self):
        expense = draft(self)
        self.assertEqual(self.race([(post_financial_expenditure_draft, posting(self, expense)) for _ in range(2)]),
            [("accepted", True), ("rejected", False)])
        self.assertEqual((CostAllocation.objects.count(), JournalEntry.objects.count()), (1, 1))

    def test_two_edits_same_version_accept_one_without_lost_update(self):
        expense = draft(self)
        calls = [(update_financial_expenditure_draft, editing(self, expense, {"notes": notes})) for notes in ["Proposal A", "Proposal B"]]
        self.assertEqual(self.race(calls), [("accepted", True), ("rejected", False)])
        expense.refresh_from_db()
        self.assertIn(expense.notes, {"Proposal A", "Proposal B"})
        self.assertEqual((FinancialCommandReceipt.objects.count(), FinanceActionEvent.objects.count(), JournalEntry.objects.count()), (2, 1, 0))

    def test_edit_and_post_same_version_cannot_both_change_source(self):
        expense = draft(self)
        self.assertEqual(self.race([(update_financial_expenditure_draft, editing(self, expense)),
            (post_financial_expenditure_draft, posting(self, expense))]), [("accepted", True), ("rejected", False)])
        expense.refresh_from_db()
        self.assertEqual(JournalEntry.objects.count(), 1 if expense.status == "posted" else 0)

    def test_same_edit_id_races_create_one_revision_receipt_and_audit(self):
        expense = draft(self)
        command = editing(self, expense)
        self.assertEqual(self.race([(update_financial_expenditure_draft, command)] * 2), [("accepted", False), ("accepted", True)])
        self.assertEqual((FinancialCommandReceipt.objects.count(), FinanceActionEvent.objects.count(), JournalEntry.objects.count()), (2, 1, 0))

    def test_two_drafts_competing_for_last_cash_roll_back_losing_post(self):
        source = funded_source(self, "50.00")
        expenses = [draft(self) for _ in range(2)]
        originals = {expense.pk: expenditure_draft_version(expense) for expense in expenses}
        commands = [(post_financial_expenditure_draft, posting(self, expense, payment_date=date(2026, 1, 22),
            funding_allocations=[{"funding_source": source.pk, "amount": "50.00"}])) for expense in expenses]
        self.assertEqual(self.race(commands), [("accepted", True), ("rejected", False)])
        self.assertEqual(available_funding_source_cash(source), Decimal("0.00"))
        self.assertEqual((CostAllocation.objects.count(), FundingAllocation.objects.count(),
            JournalEntry.objects.filter(source_model="finance.Expenditure").count()), (1, 1, 1))
        for expense in expenses:
            expense.refresh_from_db()
            if expense.status == "draft":
                self.assertEqual(expenditure_draft_version(expense), originals[expense.pk])
