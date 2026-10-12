from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.finance.models import (AccountingPeriod, ChartOfAccount, CostAllocation, Expenditure,
    FinanceActionEvent, FinancialCommandReceipt, FundingAllocation, InventoryLotBinding,
    InventoryLocationStock, InventoryValuePool, JournalEntry, JournalLine, PeriodStatus,
    SharedConsumableLot, StockMovement)
from apps.finance.services.expenditure_drafts import post_financial_expenditure_draft, update_financial_expenditure_draft
from apps.finance.services.financial_capture import record_financial_expenditure, record_financial_supplier_payment
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase
from apps.finance.services.ledger import trial_balance
from apps.finance.services.payable_evidence import verified_payable
from apps.finance.services.profitability import available_batch_cash, available_funding_source_cash
from . import test_expenditure_drafts as drafts
from . import test_financial_capture as fixtures
from . import test_inventory_capture as inventory
from .inventory_corruption import corrupt_inventory, corrupt_inventory_insert


SETTINGS = dict(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False)
MODELS = [Expenditure, CostAllocation, FundingAllocation, JournalEntry, JournalLine,
    FinancialCommandReceipt, FinanceActionEvent, SharedConsumableLot, StockMovement,
    InventoryLotBinding, InventoryLocationStock, InventoryValuePool]


def snapshot():
    return {model._meta.model_name: list(model.objects.order_by("pk").values()) for model in MODELS}


def payment(test, amount="10.00", **extra):
    return {"submission_id": uuid.uuid4(), "user": test.user, "currency": "MWK", "expenditure_id": test.expense.pk,
        "payment_date": date(2026, 1, 23), "funding_allocations": [{"funding_source": test.source.pk, "amount": amount}], **extra}


def spending_setup(test):
    fixtures.fixture(test)
    test.source = drafts.funded_source(test)
    test.create = dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        expenditure_date=date(2026, 1, 21), amount="100.00", category_id=test.category.pk,
        accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
        cost_allocations=[{"batch": test.other_batch.pk, "amount": "100.00"}], post=True,
        funding_allocations=[{"funding_source": test.source.pk, "amount": "40.00"}], payment_date=date(2026, 1, 22))
    test.expense = record_financial_expenditure(**test.create)[0]
    test.receipt = FinancialCommandReceipt.objects.get(pk=test.create["submission_id"])
    test.journal = JournalEntry.objects.get(pk=test.receipt.result["journal_id"])
    test.cost = CostAllocation.objects.get(expenditure=test.expense)


class CorruptionAssertions:
    def refused(self):
        self.expense.refresh_from_db()
        before = snapshot()
        self.assertFalse(verified_payable(self.expense))
        with self.assertRaises(ValidationError) as error:
            record_financial_supplier_payment(**payment(self))
        self.assertIn("expenditure", error.exception.detail)
        self.assertEqual(snapshot(), before)

    def changed(self, model, pk, changes):
        for change in changes:
            with self.subTest(model=model.__name__, change=change), transaction.atomic():
                corrupt_inventory(model, pk, **change)
                self.refused()
                transaction.set_rollback(True)

    def changed_receipt(self, receipt, results):
        self.changed(FinancialCommandReceipt, receipt.pk, [{"result": json.dumps(result)} for result in results])


@override_settings(**SETTINGS)
class PayableEvidenceTests(CorruptionAssertions, TestCase):
    def setUp(self):
        spending_setup(self)

    def test_twenty_payment_retries_preserve_original_proof_cost_and_cash_origin(self):
        original = deepcopy(self.receipt.result)
        command = payment(self)
        for index in range(21):
            expense, created = record_financial_supplier_payment(**command)
            self.assertEqual(created, index == 0)
            self.assertEqual(expense.pk, self.expense.pk)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.result, original)
        self.assertRegex(original["payable_version"], r"^[0-9a-f]{64}$")
        self.assertRegex(original["payable_anchor"], r"^[0-9a-f]{64}$")
        self.assertTrue(verified_payable(expense))
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), FundingAllocation.objects.count()), (1, 1, 2))
        self.assertEqual((available_funding_source_cash(self.source), available_batch_cash(self.other_batch)), (Decimal("150"), Decimal("0")))
        self.assertEqual(self.cost.allocated_amount, Decimal("100"))
        totals = trial_balance()
        self.assertEqual((totals["debits"], totals["credits"]), (Decimal("550"), Decimal("550")))
        payable = sum((line.credit - line.debit for line in JournalLine.objects.filter(account__code="2000")), Decimal("0"))
        self.assertEqual(payable, Decimal("50"))

    def test_distinct_later_partial_payments_do_not_invalidate_original_proof(self):
        record_financial_supplier_payment(**payment(self, "10"))
        expense, _ = record_financial_supplier_payment(**payment(self, "20"))
        self.assertTrue(verified_payable(expense))
        self.assertEqual((expense.payment_status, available_funding_source_cash(self.source)), ("partial", Decimal("130")))
        record_financial_supplier_payment(**payment(self, "30"))
        before = snapshot()
        with self.assertRaises(ValidationError):
            record_financial_supplier_payment(**payment(self))
        self.assertEqual(snapshot(), before)

    def test_current_payment_against_closed_original_period_retains_original_proof(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        CostAllocation.objects.filter(pk=self.cost.pk).update(locked=True)
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        command = payment(self, payment_date=date(2026, 2, 2))
        record_financial_supplier_payment(**command)
        self.expense.refresh_from_db()
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual(self.expense.expenditure_date, date(2026, 1, 21))
        funding = FundingAllocation.objects.get(payment_group_key=f"financial-payment:{command['submission_id']}")
        journal = JournalEntry.objects.get(source_model="finance.FundingAllocation", source_identifier=str(funding.pk))
        self.assertEqual(journal.posting_date, date(2026, 2, 2))
        before = snapshot()
        with self.assertRaises(ValidationError):
            record_financial_supplier_payment(**payment(self))
        self.assertEqual(snapshot(), before)

    def test_earlier_versionless_receipt_is_not_backfilled_even_after_create_replay(self):
        result = {key: value for key, value in self.receipt.result.items() if key not in {"payable_version", "payable_anchor"}}
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk, result=json.dumps(result))
        before = snapshot()
        self.assertFalse(record_financial_expenditure(**self.create)[1])
        self.refused()
        self.assertEqual(snapshot(), before)

    def test_whole_original_source_including_reference_and_capture_identity_is_bound(self):
        self.changed(Expenditure, self.expense.pk, [{"description": "Altered"}, {"payee": "Other"},
            {"external_reference": "Altered"}, {"notes": "Altered"}, {"expenditure_reference": "ALTERED-REFERENCE"},
            {"reference_number": "ALTERED"}, {"created_at": self.expense.created_at + timedelta(seconds=1)},
            {"created_by": None}, {"idempotency_key": f"financial-expense:{uuid.uuid4()}"},
            {"beneficiary_type": "general_admin"}, {"farm_module": "changed"}, {"posted_at": None},
            {"origin": "batch_cost"}, {"status": "void"}, {"reversal_reason": "Changed"},
            {"cost_allocation_plan": json.dumps([{"batch": self.batch.pk, "amount": "100.00"}])}])

    def test_wrong_debit_account_cannot_pass_a_correct_payable_credit(self):
        debit = self.journal.lines.get(debit__gt=0)
        corrupt_inventory(JournalLine, debit.pk, account=ChartOfAccount.objects.get(code="6100").pk)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.refused()

    def test_wrong_journal_beneficiary_or_funding_scope_requires_review(self):
        self.changed(JournalLine, self.journal.lines.get(debit__gt=0).pk,
            [{"batch": self.batch.pk}, {"funding_source": self.source.pk}, {"memo": "Altered original evidence"}])
        self.changed(JournalLine, self.journal.lines.get(credit__gt=0).pk,
            [{"batch": self.batch.pk}, {"funding_source": self.source.pk}])

    def test_balanced_extra_lines_cannot_authorize_payment(self):
        account = ChartOfAccount.objects.get(code="1000")
        for sides in [{"debit": "1.00"}, {"credit": "1.00"}]:
            corrupt_inventory_insert(JournalLine(journal_entry=self.journal, account=account, **sides))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.refused()

    def test_original_journal_actor_date_source_and_posting_identity_are_bound(self):
        self.changed(JournalEntry, self.journal.pk, [{"description": "Altered"}, {"reference": "ALTERED-JOURNAL"},
            {"source_model": "legacy.Expenditure"}, {"source_identifier": "999"},
            {"posting_date": date(2026, 1, 22)}, {"created_by": None}, {"posted_by": None},
            {"posted_at": None}, {"status": "reversed"}, {"reversal_reason": "Altered"}])

    def test_opposite_journal_refuses_settlement_even_if_original_status_stayed_posted(self):
        corrupt_inventory_insert(JournalEntry(reference="PRIVILEGED-OPPOSITE", posting_date=date(2026, 1, 22),
            accounting_period=self.period, description="Privileged incomplete correction", source_model="finance.Expenditure",
            source_identifier=str(self.expense.pk), idempotency_key="privileged-opposite", reversal_of=self.journal,
            status="posted", created_by=self.user, posted_by=self.user))
        self.refused()

    def test_cost_beneficiary_amount_driver_actor_and_reason_are_bound(self):
        self.changed(CostAllocation, self.cost.pk, [{"batch": self.batch.pk}, {"allocated_amount": "99.00"},
            {"driver_quantity": "99.0000"}, {"allocation_percentage": "99.0000"},
            {"generated_by": None}, {"manual_reason": "Altered"}, {"calculation_version": "changed"}])

    def test_missing_original_cost_is_not_recreated_by_payment(self):
        other = drafts.draft(self)
        corrupt_inventory(CostAllocation, self.cost.pk, expenditure=other.pk)
        self.refused()

    def test_extra_original_cost_requires_review(self):
        corrupt_inventory_insert(CostAllocation(accounting_period=self.period, batch=self.batch,
            source_type="expenditure", expenditure=self.expense, allocation_method="direct", allocated_amount="100",
            generated_by=self.user))
        self.refused()

    def test_modified_receipt_result_version_or_request_hash_is_not_adopted(self):
        result = self.receipt.result
        self.changed_receipt(self.receipt, [{**result, "payable_version": "0" * 64},
            {**result, "payable_anchor": "0" * 64}, {**result, "extra_evidence": "Altered"},
            {**result, "journal_id": "999"}])
        self.changed(FinancialCommandReceipt, self.receipt.pk, [{"request_hash": "0" * 64},
            {"command": "finance.expenditure.post"}, {"completed_at": None}])

    def test_ambiguous_additional_posting_receipt_is_not_chosen_as_authority(self):
        FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user,
            command=self.receipt.command, request_hash=self.receipt.request_hash,
            result=self.receipt.result, completed_at=self.receipt.completed_at)
        self.refused()

    def test_changed_content_or_revoked_current_actor_cannot_replay_payment(self):
        command = payment(self)
        record_financial_supplier_payment(**command)
        before = snapshot()
        with self.assertRaises(ValidationError):
            record_financial_supplier_payment(**{**command, "payment_date": date(2026, 1, 24)})
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            record_financial_supplier_payment(**command)
        self.assertEqual(snapshot(), before)

    def test_failed_new_proof_rolls_back_source_initial_cash_gl_audit_and_receipt(self):
        from apps.finance.services.financial_capture import post_journal
        def damaged_posting(**kwargs):
            journal = post_journal(**kwargs)
            corrupt_inventory(JournalLine, journal.lines.get(debit__gt=0).pk,
                account=ChartOfAccount.objects.get(code="6100").pk)
            return journal
        before = snapshot()
        with patch("apps.finance.services.financial_capture.post_journal", side_effect=damaged_posting):
            with self.assertRaises(ValidationError):
                record_financial_expenditure(**{**self.create, "submission_id": uuid.uuid4()})
        self.assertEqual(snapshot(), before)
        self.assertTrue(verified_payable(self.expense))

    def test_versioned_draft_post_binds_creation_and_last_edit_lineage(self):
        expense = drafts.draft(self)
        creation = FinancialCommandReceipt.objects.get(result__expenditure_id=str(expense.pk))
        edit = drafts.editing(self, expense, {"notes": "Actual reviewed draft evidence"})
        updated = update_financial_expenditure_draft(**edit)[0]
        command = drafts.posting(self, updated)
        self.expense = post_financial_expenditure_draft(**command)[0]
        self.assertTrue(verified_payable(self.expense))
        for _ in range(20):
            self.assertFalse(post_financial_expenditure_draft(**command)[1])
        record_financial_supplier_payment(**payment(self))
        for receipt in [creation, FinancialCommandReceipt.objects.get(pk=edit["submission_id"])]:
            self.changed(FinancialCommandReceipt, receipt.pk, [{"request_hash": "0" * 64},
                {"result": json.dumps({**receipt.result, "draft_version": "0" * 64})}])

    def test_administration_posts_admin_expense_without_batch_beneficiary(self):
        self.expense = drafts.draft(self, post=True, accounting_nature="indirect_operating_expense", cost_allocations=[])
        self.assertTrue(verified_payable(self.expense))
        record_financial_supplier_payment(**payment(self))
        journal = JournalEntry.objects.get(source_model="finance.Expenditure", source_identifier=str(self.expense.pk))
        self.assertEqual(list(journal.lines.values_list("account__code", flat=True).order_by("account__code")), ["2000", "6100"])
        self.assertFalse(self.expense.cost_allocations.exists())


def stock_setup(test):
    inventory.inventory_fixture(test)
    test.source = drafts.funded_source(test)
    test.create = inventory.purchase(test, invoice_reference="SYNTHETIC-INVOICE")
    test.lot = record_inventory_purchase(**test.create)[0]
    test.binding = InventoryLotBinding.objects.get(lot=test.lot)
    test.expense = test.binding.expenditure
    test.receipt = FinancialCommandReceipt.objects.get(pk=test.create["submission_id"])
    test.movement = StockMovement.objects.get(pk=test.receipt.result["movement_id"])
    test.journal = JournalEntry.objects.get(pk=test.receipt.result["journal_id"])


@override_settings(**SETTINGS)
class StockPayableEvidenceTests(CorruptionAssertions, TestCase):
    def setUp(self):
        stock_setup(self)

    def test_legitimate_issue_then_two_payments_preserve_original_purchase_proof(self):
        original = deepcopy(self.receipt.result)
        record_inventory_issue(**inventory.issue(self, self.lot))
        for amount in ["30", "20"]:
            record_financial_supplier_payment(**payment(self, amount))
        self.expense.refresh_from_db()
        self.lot.refresh_from_db()
        self.receipt.refresh_from_db()
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual(self.receipt.result, original)
        self.assertEqual((self.lot.quantity_available, pool.quantity, pool.carrying_value),
            (Decimal("8"), Decimal("8"), Decimal("80")))
        self.assertEqual((self.lot.payment_status, available_funding_source_cash(self.source)), ("partial", Decimal("150")))
        self.assertEqual(CostAllocation.objects.count(), 0)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_original_stock_purchase_details_not_current_available_quantity_are_bound(self):
        self.changed(SharedConsumableLot, self.lot.pk, [{"quantity_purchased": "11.0000"},
            {"unit_of_measurement": "grams"}, {"unit_cost": "9.000000"}, {"supplier": "Altered"},
            {"invoice_reference": "Changed"}, {"notes": "Altered"}, {"purchase_date": date(2026, 1, 11)}])

    def test_original_stock_receipt_movement_is_required(self):
        self.changed(StockMovement, self.movement.pk, [{"quantity": "11.0000"}, {"total_cost": "99.00"},
            {"movement_date": date(2026, 1, 11)}, {"reference": "Changed"}, {"unit_cost": "9.000000"},
            {"created_by": None}, {"to_location": None}, {"idempotency_key": "inventory-receipt:altered"}])

    def test_changed_invoice_binding_or_receipt_result_requires_review(self):
        self.changed(InventoryLotBinding, self.binding.pk, [{"invoice_key": "0" * 64}])
        self.changed_receipt(self.receipt, [{**self.receipt.result, "movement_id": "999"},
            {**self.receipt.result, "lot_id": "999"}])

    def test_balanced_purchase_reclassified_as_immediate_expense_is_refused(self):
        corrupt_inventory(JournalLine, self.journal.lines.get(debit__gt=0).pk,
            account=ChartOfAccount.objects.get(code="6100").pk)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.refused()

    def test_earlier_stock_receipt_is_not_backfilled_on_purchase_replay(self):
        result = {key: value for key, value in self.receipt.result.items() if key not in {"payable_version", "payable_anchor"}}
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk, result=json.dumps(result))
        before = snapshot()
        self.assertFalse(record_inventory_purchase(**self.create)[1])
        self.refused()
        self.assertEqual(snapshot(), before)

    def test_string_uuid_identity_retains_original_purchase_and_movement_keys(self):
        payload = {**inventory.purchase(self), "submission_id": str(uuid.uuid4()).upper()}
        lot = record_inventory_purchase(**payload)[0]
        self.assertTrue(verified_payable(InventoryLotBinding.objects.get(lot=lot).expenditure))
        self.assertFalse(record_inventory_purchase(**payload)[1])


def race(test, calls):
    barrier, results = Barrier(len(calls)), []
    def run(call):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            _, created = call()
            results.append(created)
        except ValidationError:
            results.append("rejected")
        except Exception as error:
            results.append(type(error).__name__)
        finally:
            close_old_connections()
    threads = [Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=25)
        test.assertFalse(thread.is_alive())
    return results


@override_settings(**SETTINGS)
class PayableEvidenceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        spending_setup(self)

    def test_same_payment_intent_race_replays_one_exact_effect(self):
        command = payment(self)
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**command)] * 2), [True, False])
        self.expense.refresh_from_db()
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual((FundingAllocation.objects.count(), available_funding_source_cash(self.source)), (2, Decimal("150")))

    def test_last_payable_balance_cannot_be_settled_twice(self):
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**payment(self, "60"))] * 2), [True, "rejected"])
        self.expense.refresh_from_db()
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual((self.expense.payment_status, FundingAllocation.objects.count(), available_funding_source_cash(self.source)),
            ("paid", 2, Decimal("100")))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_new_proof_and_payment_do_not_publish_financial_data_to_operational_profiles(self):
        from apps.mobile_sync.models import SyncChange, SyncStreamState
        from apps.mobile_sync.writers import sync_boundary
        SyncStreamState.objects.get_or_create(pk=1)
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary():
            record_financial_expenditure(**{**self.create, "submission_id": uuid.uuid4(), "funding_allocations": [], "payment_date": None})
            record_financial_supplier_payment(**payment(self))
        self.assertEqual(SyncChange.objects.count(), 0)
        self.assertEqual(Expenditure.objects.count(), 2)


@override_settings(**SETTINGS)
class StockPayableEvidenceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        stock_setup(self)

    def test_stock_issue_and_supplier_payment_both_retain_original_purchase_proof(self):
        self.assertCountEqual(race(self, [lambda: record_inventory_issue(**inventory.issue(self, self.lot)),
            lambda: record_financial_supplier_payment(**payment(self, "50"))]), [True, True])
        self.expense.refresh_from_db()
        self.assertTrue(verified_payable(self.expense))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value, available_funding_source_cash(self.source)),
            (Decimal("8"), Decimal("80"), Decimal("150")))
        self.assertEqual((FundingAllocation.objects.count(), StockMovement.objects.count()), (1, 2))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
