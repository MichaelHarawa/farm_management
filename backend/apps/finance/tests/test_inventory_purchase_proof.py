"""Original stock purchase proof before new movements, on disposable PG only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.finance.models import (AccountingPeriod, ChartOfAccount, ConsumableUsage,
    Expenditure, FinanceActionEvent, FinancialCommandReceipt, FundingAllocation,
    InventoryLocation, InventoryLocationStock, InventoryLotBinding,
    InventoryMovementEvidence, InventoryValuePool, JournalEntry, JournalLine,
    PeriodStatus, PoultryStockConsumption, SharedConsumableLot, StockMovement)
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_capture import (PURCHASE_PROOF_MESSAGE,
    record_inventory_issue, record_inventory_purchase)
from apps.finance.services.inventory_corrections import (record_inventory_return, record_inventory_transfer,
    record_inventory_waste, record_inventory_expiry, record_inventory_count_loss)
from apps.finance.services.ledger import trial_balance
from apps.finance.services.poultry_stock_capture import configure_poultry_stock_item, record_stock_backed_feed
from apps.finance.services.reporting import monthly_profitability_report
from apps.poultry.models import FeedUsage, InputCosts
from . import test_expenditure_drafts as drafts
from . import test_inventory_capture as inventory
from . import test_inventory_corrections as corrections
from . import test_poultry_stock_capture as poultry
from .inventory_corruption import corrupt_inventory, corrupt_inventory_insert


SETTINGS = dict(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False,
    FINANCE_POULTRY_STOCK_LINKAGE=False)
MODELS = (Expenditure, FundingAllocation, JournalEntry, JournalLine, FinancialCommandReceipt,
    FinanceActionEvent, SharedConsumableLot, StockMovement, InventoryLotBinding,
    InventoryLocationStock, InventoryValuePool, InventoryMovementEvidence,
    ConsumableUsage, FeedUsage, PoultryStockConsumption, InputCosts)


def snapshot():
    return {model._meta.model_name: list(model.objects.order_by("pk").values()) for model in MODELS}


def setup(test):
    inventory.inventory_fixture(test)
    test.purchase_request = inventory.purchase(test, invoice_reference="SYNTHETIC-ORIGINAL-STOCK")
    test.lot = record_inventory_purchase(**test.purchase_request)[0]
    test.binding = InventoryLotBinding.objects.get(lot=test.lot)
    test.expense = test.binding.expenditure
    test.receipt = FinancialCommandReceipt.objects.get(pk=test.purchase_request["submission_id"])
    test.journal = JournalEntry.objects.get(pk=test.receipt.result["journal_id"])
    test.movement = StockMovement.objects.get(pk=test.receipt.result["movement_id"])
    test.other_location = InventoryLocation.objects.create(code="PROOF-OTHER", name="Synthetic other store")


def erase_receipt(receipt):
    if not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_"):
        raise AssertionError("Privileged damage requires a newly owned disposable test database.")
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM " + connection.ops.quote_name(FinancialCommandReceipt._meta.db_table)
            + " WHERE submission_id=%s", [receipt.pk])


@override_settings(**SETTINGS)
class InventoryPurchaseProofTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, action=None):
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            (action or (lambda: record_inventory_issue(**inventory.issue(self, self.lot))))()
        self.assertIn("inventory_reconciliation", error.exception.detail)
        self.assertEqual(str(error.exception.detail["inventory_reconciliation"]), PURCHASE_PROOF_MESSAGE)
        self.assertEqual(snapshot(), before)

    def damage_result(self, **changes):
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk,
            result=json.dumps({**self.receipt.result, **changes}))

    def test_wrong_but_balanced_purchase_journal_cannot_value_new_issue(self):
        corrupt_inventory(JournalLine, self.journal.lines.get(debit__gt=0).pk,
            account=ChartOfAccount.objects.get(code="6100").pk)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.refused()

    def test_versionless_accepted_purchase_is_not_adopted_on_issue_or_replay(self):
        original = {key: value for key, value in self.receipt.result.items()
            if key not in {"payable_version", "payable_anchor"}}
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk, result=json.dumps(original))
        before = snapshot()
        self.assertFalse(record_inventory_purchase(**self.purchase_request)[1])
        self.refused()
        self.assertEqual(snapshot(), before)

    def test_missing_permanent_purchase_receipt_is_not_recreated(self):
        erase_receipt(self.receipt)
        self.refused()

    def test_ambiguous_purchase_receipt_is_not_selected_arbitrarily(self):
        FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user,
            command=self.receipt.command, request_hash=self.receipt.request_hash,
            result=self.receipt.result, completed_at=self.receipt.completed_at)
        self.refused()

    def test_result_hash_anchor_original_ids_and_versions_are_bound(self):
        results = [{"payable_version": "0" * 64}, {"payable_anchor": "0" * 64},
            {"lot_id": "9223372036854775807"}, {"expenditure_id": "9223372036854775807"},
            {"movement_id": "9223372036854775807"}, {"journal_id": "9223372036854775807"}]
        for changes in results:
            with self.subTest(changes=changes), transaction.atomic():
                self.damage_result(**changes)
                self.refused()
                transaction.set_rollback(True)
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk, request_hash="0" * 64)
        self.refused()

    def test_original_purchase_source_economics_and_capture_are_bound(self):
        for changes in ({"amount": "101.00"}, {"payee": "Altered supplier"},
                {"external_reference": "ALTERED"}, {"created_by": None},
                {"created_at": self.expense.created_at + timedelta(seconds=1)},
                {"idempotency_key": "inventory-purchase:" + str(uuid.uuid4())}, {"status": "draft"}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(Expenditure, self.expense.pk, **changes)
                self.refused()
                transaction.set_rollback(True)

    def test_original_lot_and_receipt_movement_evidence_are_bound(self):
        for model, pk, changes in ((SharedConsumableLot, self.lot.pk, {"supplier": "Altered"}),
                (SharedConsumableLot, self.lot.pk, {"invoice_reference": "Altered"}),
                (SharedConsumableLot, self.lot.pk, {"unit_cost": "9.000000"}),
                (SharedConsumableLot, self.lot.pk, {"unit_of_measurement": "g"}),
                (StockMovement, self.movement.pk, {"reference": "Altered"}),
                (StockMovement, self.movement.pk, {"unit_cost": "9.000000"}),
                (StockMovement, self.movement.pk, {"created_by": None})):
            with self.subTest(model=model.__name__, changes=changes), transaction.atomic():
                corrupt_inventory(model, pk, **changes)
                self.refused()
                transaction.set_rollback(True)

    def test_journal_date_source_actor_and_whole_lines_are_bound(self):
        for changes in ({"posting_date": date(2026, 1, 9)}, {"source_identifier": "999"},
                {"posted_by": None}, {"description": "Altered"}, {"status": "reversed"}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(JournalEntry, self.journal.pk, **changes)
                self.refused()
                transaction.set_rollback(True)
        account = ChartOfAccount.objects.get(code="1000")
        for sides in ({"debit": "1.00"}, {"credit": "1.00"}):
            corrupt_inventory_insert(JournalLine(journal_entry=self.journal, account=account, **sides))
        self.refused()

    def test_damaged_other_lot_in_same_weighted_pool_blocks_selected_lot(self):
        other_request = {**inventory.purchase(self), "total_purchase_cost": "200.00", "invoice_reference": "SYNTHETIC-SECOND"}
        other = record_inventory_purchase(**other_request)[0]
        other_receipt = FinancialCommandReceipt.objects.get(pk=other_request["submission_id"])
        corrupt_inventory(FinancialCommandReceipt, other_receipt.pk,
            result=json.dumps({**other_receipt.result, "payable_anchor": "0" * 64}))
        self.assertNotEqual(other.pk, self.lot.pk)
        self.refused()

    def test_new_purchase_does_not_mix_value_with_an_unproved_existing_pool(self):
        self.damage_result(payable_anchor="0" * 64)
        self.refused(lambda: record_inventory_purchase(**{**inventory.purchase(self), "purchase_date": date(2026, 1, 11)}))

    def test_transfer_and_waste_and_count_require_original_purchase_proof(self):
        self.damage_result(payable_anchor="0" * 64)
        actions = [lambda: record_inventory_transfer(**corrections.transfer(self, self.lot)),
            lambda: record_inventory_waste(**corrections.movement(self, self.lot)),
            lambda: record_inventory_count_loss(submission_id=uuid.uuid4(), user=self.user,
                lot_id=self.lot.pk, location_id=self.location.pk, movement_date=date(2026, 1, 12),
                counted_quantity="9.0000", expected_revision=1, reason="Synthetic physical count")]
        for action in actions:
            with self.subTest(action=action):
                self.refused(action)

    def test_unused_return_cannot_reopen_stock_from_unproved_purchase(self):
        usage = record_inventory_issue(**inventory.issue(self, self.lot))[0]
        original = StockMovement.objects.get(usage=usage)
        self.damage_result(payable_anchor="0" * 64)
        self.refused(lambda: record_inventory_return(**corrections.returned(self, original)))

    def test_expiry_requires_original_purchase_proof_before_recording_loss(self):
        request = inventory.purchase(self, expiry_date=date(2026, 1, 11), invoice_reference="SYNTHETIC-EXPIRY")
        lot = record_inventory_purchase(**request)[0]
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        corrupt_inventory(FinancialCommandReceipt, receipt.pk,
            result=json.dumps({**receipt.result, "payable_anchor": "0" * 64}))
        self.refused(lambda: record_inventory_expiry(**corrections.movement(self, lot)))

    @override_settings(FINANCE_POULTRY_STOCK_LINKAGE=True)
    def test_stock_backed_feed_rolls_back_observation_if_purchase_proof_fails(self):
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user,
            item_id=self.item.pk, kind="feed", reason="Synthetic explicit feed classification")
        self.damage_result(payable_anchor="0" * 64)
        self.refused(lambda: record_stock_backed_feed(**poultry.feed(self)))

    def test_valid_payment_metadata_and_later_issues_preserve_original_purchase(self):
        original = deepcopy(self.receipt.result)
        source = drafts.funded_source(self)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.expense.pk, payment_date=date(2026, 1, 21),
            funding_allocations=[{"funding_source": source.pk, "amount": "40.00"}])
        request = {**inventory.issue(self, self.lot), "usage_date": date(2026, 1, 21)}
        usage = record_inventory_issue(**request)[0]
        after = snapshot()
        for _ in range(20):
            self.assertFalse(record_inventory_issue(**request)[1])
        self.assertEqual(snapshot(), after)
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.result, original)
        self.assertEqual(usage.recognized_cost, Decimal("20.00"))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("8.0000"), Decimal("80.00")))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.assertEqual((FundingAllocation.objects.count(), Expenditure.objects.count()), (1, 1))

    def test_read_reports_and_accepted_replay_do_not_repair_missing_proof(self):
        self.damage_result(payable_anchor="0" * 64)
        before = snapshot()
        monthly_profitability_report(self.period)
        self.assertFalse(record_inventory_purchase(**self.purchase_request)[1])
        self.assertEqual(snapshot(), before)
        self.refused()

    def test_current_issue_from_closed_purchase_period_uses_actual_open_date(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        usage = record_inventory_issue(**{**inventory.issue(self, self.lot), "usage_date": date(2026, 2, 1)})[0]
        self.assertEqual(usage.usage_date, date(2026, 2, 1))
        self.assertEqual(usage.recognized_cost, Decimal("20.00"))
        self.assertEqual(self.movement.movement_date, date(2026, 1, 10))

    def test_proof_scan_bound_refuses_whole_effect_not_partial_history(self):
        record_inventory_purchase(**inventory.purchase(self, invoice_reference="SYNTHETIC-BOUND-SECOND"))
        before = snapshot()
        with patch("apps.finance.services.inventory_capture.MAX_POOL_PURCHASES", 1):
            with self.assertRaises(ValidationError) as error:
                record_inventory_issue(**inventory.issue(self, self.lot))
        self.assertIn("partial history", str(error.exception.detail["inventory_reconciliation"]))
        self.assertEqual(snapshot(), before)

    def test_proof_failure_before_new_purchase_rolls_back_initial_cash_and_all_sources(self):
        source = drafts.funded_source(self)
        self.damage_result(payable_anchor="0" * 64)
        self.refused(lambda: record_inventory_purchase(**{**inventory.purchase(self),
            "purchase_date": date(2026, 1, 21), "payment_date": date(2026, 1, 21),
            "funding_allocations": [{"funding_source": source.pk, "amount": "100.00"}]}))


def race(test, calls):
    barrier, results = Barrier(len(calls)), []
    def run(call):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            results.append(call()[1])
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
class InventoryPurchaseProofConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_same_issue_intent_race_retains_one_original_purchase_and_cost(self):
        original = deepcopy(self.receipt.result)
        request = inventory.issue(self, self.lot)
        self.assertCountEqual(race(self, [lambda: record_inventory_issue(**request)] * 2), [True, False])
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.result, original)
        self.assertEqual((ConsumableUsage.objects.count(), StockMovement.objects.count(), JournalEntry.objects.count()), (1, 2, 2))

    def test_competing_last_stock_uses_proved_purchase_without_overdraw(self):
        self.assertCountEqual(race(self, [lambda: record_inventory_issue(**{
            **inventory.issue(self, self.lot), "quantity": "10.0000"})] * 2), [True, "rejected"])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("0.0000"), Decimal("0.00")))
        self.assertEqual(ConsumableUsage.objects.get().recognized_cost, Decimal("100.00"))
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (2, 2))

    def test_payment_and_issue_preserve_original_proof_and_distinct_cash_cost(self):
        source = drafts.funded_source(self)
        original = deepcopy(self.receipt.result)
        payment = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.expense.pk, payment_date=date(2026, 1, 21),
            funding_allocations=[{"funding_source": source.pk, "amount": "40.00"}])
        issue = {**inventory.issue(self, self.lot), "usage_date": date(2026, 1, 21)}
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**payment),
            lambda: record_inventory_issue(**issue)]), [True, True])
        self.receipt.refresh_from_db()
        self.assertEqual(self.receipt.result, original)
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("8.0000"), Decimal("80.00")))
        self.assertEqual((FundingAllocation.objects.count(), Expenditure.objects.count()), (1, 1))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
