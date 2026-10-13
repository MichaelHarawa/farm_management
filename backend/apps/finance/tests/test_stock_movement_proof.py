"""Original post-purchase movement proof, on newly owned PostgreSQL only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from unittest.mock import patch
import uuid

from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.finance.models import (AccountingPeriod, ChartOfAccount, ConsumableUsage,
    FinancialCommandReceipt, FundingAllocation, InventoryMovementEvidence,
    InventoryValuePool, JournalEntry, JournalLine, PeriodStatus,
    PoultryStockConsumption, PoultryStockItemPolicy, StockMovement)
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase
from apps.finance.services.inventory_corrections import (record_inventory_return, record_inventory_transfer,
    record_inventory_waste, record_inventory_expiry, record_inventory_count_loss)
from apps.finance.services.ledger import trial_balance
from apps.finance.services.poultry_stock_capture import configure_poultry_stock_item, record_stock_backed_feed
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.services.stock_movement_evidence import MESSAGE
from apps.poultry.models import DrugsVaccination, FeedUsage
from . import test_expenditure_drafts as drafts
from . import test_inventory_capture as inventory
from . import test_inventory_corrections as corrections
from . import test_inventory_purchase_proof as purchase_proof
from . import test_poultry_stock_capture as poultry
from .inventory_corruption import corrupt_inventory, corrupt_inventory_insert


def snapshot():
    return {**purchase_proof.snapshot(), **{model._meta.model_name: list(model.objects.order_by("pk").values())
        for model in (DrugsVaccination, PoultryStockItemPolicy)}}


def erase(model, pk):
    if not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_"):
        raise AssertionError("Damage requires a newly owned disposable test database.")
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM " + connection.ops.quote_name(model._meta.db_table)
            + " WHERE " + connection.ops.quote_name(model._meta.pk.column) + "=%s", [pk])


@override_settings(**purchase_proof.SETTINGS)
class StockMovementProofTests(TestCase):
    def setUp(self):
        purchase_proof.setup(self)

    def issue(self, **changes):
        request = {**inventory.issue(self, self.lot), **changes}
        usage = record_inventory_issue(**request)[0]
        movement = StockMovement.objects.get(usage=usage)
        journal = JournalEntry.objects.filter(idempotency_key=movement.idempotency_key).first()
        return request, movement, journal

    def next_issue(self):
        return record_inventory_issue(**{**inventory.issue(self, self.lot),
            "usage_date": date(2026, 1, 12)})

    def refused(self, action=None):
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            (action or self.next_issue)()
        self.assertEqual(str(error.exception.detail["inventory_reconciliation"]), MESSAGE)
        self.assertEqual(snapshot(), before)

    def damage_result(self, request, **changes):
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        corrupt_inventory(FinancialCommandReceipt, receipt.pk,
            result=json.dumps({**receipt.result, **changes}))

    def test_wrong_but_balanced_issue_journal_blocks_new_stock_effect(self):
        _, _, journal = self.issue()
        corrupt_inventory(JournalLine, journal.lines.get(debit__gt=0).pk,
            account=ChartOfAccount.objects.get(code="6100").pk)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        self.refused()

    def test_changed_issue_journal_source_blocks_new_stock_effect(self):
        _, _, journal = self.issue()
        corrupt_inventory(JournalEntry, journal.pk, source_identifier="9223372036854775807")
        self.refused()

    def test_missing_permanent_movement_receipt_is_not_recreated(self):
        request, _, _ = self.issue()
        erase(FinancialCommandReceipt, request["submission_id"])
        self.refused()

    def test_versionless_issue_replays_without_adoption_but_new_effect_requires_review(self):
        request, _, _ = self.issue()
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        original = {key: value for key, value in receipt.result.items() if key not in {"stock_version", "stock_anchor"}}
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(original))
        before = snapshot()
        self.assertFalse(record_inventory_issue(**request)[1])
        monthly_profitability_report(self.period)
        self.assertEqual(snapshot(), before)
        self.refused()

    def test_ambiguous_accepted_movement_receipts_require_review(self):
        request, _, _ = self.issue()
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user,
            command=receipt.command, request_hash=receipt.request_hash,
            result=receipt.result, completed_at=receipt.completed_at)
        self.refused()

    def test_original_result_ids_hash_and_anchors_are_bound(self):
        request, _, _ = self.issue()
        for change in ({"stock_version": "0" * 64}, {"stock_anchor": "0" * 64},
                {"journal_id": "9223372036854775807"}, {"usage_id": "9223372036854775807"},
                {"recognized_cost": "21.00"}, {"movement_id": "9223372036854775807"}):
            with self.subTest(change=change), transaction.atomic():
                self.damage_result(request, **change)
                self.refused()
                transaction.set_rollback(True)
        corrupt_inventory(FinancialCommandReceipt, request["submission_id"], request_hash="0" * 64)
        self.refused()

    def test_original_usage_economics_beneficiary_capture_and_actor_are_bound(self):
        _, movement, _ = self.issue()
        for change in ({"quantity_used": "3.0000"}, {"recognized_cost": "21.00"},
                {"batch": self.other_batch.pk}, {"usage_date": date(2026, 1, 10)},
                {"recorded_by": None}, {"notes": "Altered"}, {"task_or_purpose": "Altered"},
                {"created_at": movement.usage.created_at + timedelta(seconds=1)}):
            with self.subTest(change=change), transaction.atomic():
                corrupt_inventory(ConsumableUsage, movement.usage_id, **change)
                self.refused()
                transaction.set_rollback(True)

    def test_whole_original_movement_capture_unit_cost_and_reference_are_bound(self):
        _, movement, _ = self.issue()
        for change in ({"unit_cost": "9.000000"}, {"reason": "Altered"}, {"reference": "Altered"},
                {"created_by": None}, {"movement_date": date(2026, 1, 10)},
                {"created_at": movement.created_at + timedelta(seconds=1)}):
            with self.subTest(change=change), transaction.atomic():
                corrupt_inventory(StockMovement, movement.pk, **change)
                self.refused()
                transaction.set_rollback(True)

    def test_balanced_wrong_beneficiary_and_extra_journal_lines_are_refused(self):
        _, _, journal = self.issue()
        with transaction.atomic():
            for line in journal.lines.all():
                corrupt_inventory(JournalLine, line.pk, batch=self.other_batch.pk)
            self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
            self.refused()
            transaction.set_rollback(True)
        account = ChartOfAccount.objects.get(code="1000")
        for side in ({"debit": "1.00"}, {"credit": "1.00"}):
            corrupt_inventory_insert(JournalLine(journal_entry=journal, account=account, **side))
        self.refused()

    def test_original_journal_header_date_status_and_actor_are_bound(self):
        _, _, journal = self.issue()
        for change in ({"posting_date": date(2026, 1, 10)}, {"source_model": "finance.StockMovement"},
                {"status": "reversed"}, {"posted_by": None}, {"description": "Altered"}):
            with self.subTest(change=change), transaction.atomic():
                corrupt_inventory(JournalEntry, journal.pk, **change)
                self.refused()
                transaction.set_rollback(True)

    def test_return_journal_and_original_issue_relation_are_bound(self):
        _, original, _ = self.issue()
        request = corrections.returned(self, original)
        returned = record_inventory_return(**request)[0]
        journal = JournalEntry.objects.get(idempotency_key=returned.idempotency_key)
        corrupt_inventory(JournalLine, journal.lines.get(credit__gt=0).pk,
            account=ChartOfAccount.objects.get(code="6100").pk)
        self.refused()

    def test_transfer_without_journal_still_requires_original_movement_proof(self):
        request = corrections.transfer(self, self.lot)
        moved = record_inventory_transfer(**request)[0]
        corrupt_inventory(StockMovement, moved.pk, reason="Altered transfer")
        self.refused()

    def test_waste_expiry_and_count_each_require_original_complete_proof(self):
        actions = [lambda: record_inventory_waste(**corrections.movement(self, self.lot)),
            lambda: record_inventory_count_loss(submission_id=uuid.uuid4(), user=self.user,
                lot_id=self.lot.pk, location_id=self.location.pk, movement_date=date(2026, 1, 12),
                counted_quantity="9.0000", expected_revision=InventoryValuePool.objects.get(item=self.item).revision,
                reason="Synthetic count")]
        for action in actions:
            with self.subTest(action=action), transaction.atomic():
                movement = action()[0]
                journal = JournalEntry.objects.get(idempotency_key=movement.idempotency_key)
                corrupt_inventory(JournalLine, journal.lines.get(debit__gt=0).pk,
                    account=ChartOfAccount.objects.get(code="5000").pk)
                self.refused()
                transaction.set_rollback(True)
        lot = record_inventory_purchase(**inventory.purchase(self, expiry_date=date(2026, 1, 11)))[0]
        request = corrections.movement(self, lot)
        record_inventory_expiry(**request)
        self.damage_result(request, stock_anchor="0" * 64)
        self.refused()

    def test_coherent_changed_count_pair_cannot_replace_original_observation(self):
        movement = record_inventory_count_loss(submission_id=uuid.uuid4(), user=self.user,
            lot_id=self.lot.pk, location_id=self.location.pk, movement_date=date(2026, 1, 12),
            counted_quantity="9.0000", expected_revision=InventoryValuePool.objects.get(item=self.item).revision,
            reason="Synthetic count")[0]
        evidence = InventoryMovementEvidence.objects.get(movement=movement)
        corrupt_inventory(InventoryMovementEvidence, evidence.pk, expected_quantity="11.0000", counted_quantity="10.0000")
        self.refused()

    def test_damaged_movement_of_other_lot_blocks_shared_pool_valuation(self):
        other = record_inventory_purchase(**inventory.purchase(self))[0]
        _, _, journal = self.issue(lot_id=other.pk)
        corrupt_inventory(JournalEntry, journal.pk, description="Altered other-lot journal")
        self.refused()

    def test_bad_movement_proof_refuses_new_paid_purchase_without_partial_cash(self):
        request, _, _ = self.issue()
        self.damage_result(request, stock_anchor="0" * 64)
        source = drafts.funded_source(self)
        self.refused(lambda: record_inventory_purchase(**{**inventory.purchase(self),
            "purchase_date": date(2026, 1, 21), "payment_date": date(2026, 1, 21),
            "funding_allocations": [{"funding_source": source.pk, "amount": "100.00"}]}))

    @override_settings(FINANCE_POULTRY_STOCK_LINKAGE=True)
    def test_bad_movement_proof_rolls_back_linked_poultry_observation(self):
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user,
            item_id=self.item.pk, kind="feed", reason="Synthetic feed classification")
        request, _, _ = self.issue()
        self.damage_result(request, stock_anchor="0" * 64)
        self.refused(lambda: record_stock_backed_feed(**poultry.feed(self)))

    @override_settings(FINANCE_POULTRY_STOCK_LINKAGE=True)
    def test_linked_observation_and_consumption_relation_are_original_proof(self):
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user,
            item_id=self.item.pk, kind="feed", reason="Synthetic feed classification")
        link = record_stock_backed_feed(**poultry.feed(self))[0]
        for change in ({"notes": "Altered original observation"}, {"initial_age": 999}):
            with self.subTest(change=change), transaction.atomic():
                corrupt_inventory(FeedUsage, link.feed_id, **change)
                self.refused()
                transaction.set_rollback(True)

    @override_settings(FINANCE_POULTRY_STOCK_LINKAGE=True)
    def test_derived_feed_population_and_period_locks_do_not_invalidate_proof(self):
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user,
            item_id=self.item.pk, kind="feed", reason="Synthetic feed classification")
        link = record_stock_backed_feed(**poultry.feed(self))[0]
        FeedUsage.objects.filter(pk=link.feed_id).update(current_number_of_birds=80,
            population_calculation_version="dated-flock-events-v1")
        ConsumableUsage.objects.filter(pk=link.usage_id).update(locked=True)
        self.next_issue()
        self.assertEqual(ConsumableUsage.objects.count(), 2)
        self.assertEqual(PoultryStockConsumption.objects.count(), 1)

    def test_zero_cost_issue_and_return_have_proof_without_fabricated_journal(self):
        # An independent legitimately purchased low-value pool, no balance edit.
        self.low_value_pool()
        request, movement, journal = self.issue(quantity="0.0001")
        self.assertIsNone(journal)
        self.assertEqual(movement.total_cost, Decimal("0.00"))
        returned = record_inventory_return(**{**corrections.returned(self, movement), "quantity": "0.0001"})[0]
        self.assertEqual(returned.total_cost, Decimal("0.00"))
        self.next_issue()
        self.assertEqual(len(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result["stock_version"]), 64)

    def low_value_pool(self):
        from apps.finance.models import ConsumableItem
        self.item = ConsumableItem.objects.create(sku="LOW-STOCK", name="Synthetic low-value stock",
            category="Feed", base_unit="kg")
        self.lot = record_inventory_purchase(**{**inventory.purchase(self),
            "quantity": "100.0000", "total_purchase_cost": "0.01"})[0]

    def test_fabricated_journal_on_zero_cost_issue_is_not_accepted(self):
        self.low_value_pool()
        _, movement, journal = self.issue(quantity="0.0001")
        self.assertIsNone(journal)
        corrupt_inventory_insert(JournalEntry(posting_date=movement.movement_date,
            accounting_period=self.period, source_model="finance.ConsumableUsage",
            source_identifier=str(movement.usage_id), idempotency_key=movement.idempotency_key,
            created_by=self.user, status="draft"))
        self.refused()

    def test_fabricated_journal_on_transfer_is_not_accepted(self):
        moved = record_inventory_transfer(**corrections.transfer(self, self.lot))[0]
        corrupt_inventory_insert(JournalEntry(posting_date=moved.movement_date,
            accounting_period=self.period, source_model="finance.StockMovement",
            source_identifier=str(moved.pk), idempotency_key=moved.idempotency_key,
            created_by=self.user, status="draft"))
        self.refused()

    def test_current_period_effect_retains_old_closed_usage_and_journal(self):
        request, movement, _ = self.issue()
        original = deepcopy(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result)
        ConsumableUsage.objects.filter(pk=movement.usage_id).update(locked=True)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        record_inventory_return(**{**corrections.returned(self, movement), "movement_date": date(2026, 2, 1)})
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result, original)
        self.assertEqual(StockMovement.objects.get(pk=movement.pk).movement_date, date(2026, 1, 11))

    def test_twenty_replays_and_valid_return_preserve_original_stock_proof(self):
        request, movement, _ = self.issue()
        original = deepcopy(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result)
        for _ in range(20):
            self.assertFalse(record_inventory_issue(**request)[1])
        record_inventory_return(**corrections.returned(self, movement))
        self.next_issue()
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result, original)
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("7.0000"), Decimal("70.00")))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_later_supplier_payment_preserves_original_movement_proof(self):
        request, _, _ = self.issue()
        original = deepcopy(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result)
        source = drafts.funded_source(self)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.expense.pk, payment_date=date(2026, 1, 21),
            funding_allocations=[{"funding_source": source.pk, "amount": "40.00"}])
        self.issue(usage_date=date(2026, 1, 21))
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result, original)
        self.assertEqual(FundingAllocation.objects.count(), 1)

    def test_movement_scan_bound_refuses_whole_effect_not_partial_history(self):
        self.issue()
        self.next_issue()
        before = snapshot()
        with patch("apps.finance.services.stock_movement_evidence.MAX_POOL_MOVEMENTS", 1):
            with self.assertRaises(ValidationError) as error:
                self.next_issue()
        self.assertIn("partial history", str(error.exception.detail["inventory_reconciliation"]))
        self.assertEqual(snapshot(), before)

    def test_seal_failure_rolls_back_movement_usage_journal_and_receipt(self):
        before = snapshot()
        with patch("apps.finance.services.stock_movement_evidence.seal_stock_result", side_effect=ValidationError("Synthetic seal failure")):
            with self.assertRaises(ValidationError):
                self.issue()
        self.assertEqual(snapshot(), before)

    def test_incomplete_accepted_receipt_does_not_authorize_new_effect(self):
        request, _, _ = self.issue()
        corrupt_inventory(FinancialCommandReceipt, request["submission_id"], completed_at=None)
        self.refused()

    def test_missing_correction_evidence_is_not_recreated(self):
        moved = record_inventory_transfer(**corrections.transfer(self, self.lot))[0]
        evidence = InventoryMovementEvidence.objects.get(movement=moved)
        erase(InventoryMovementEvidence, evidence.pk)
        self.refused()

    def test_return_cannot_be_relinked_to_another_valid_original_issue(self):
        _, first, _ = self.issue()
        _, other, _ = self.issue()
        returned = record_inventory_return(**corrections.returned(self, first))[0]
        evidence = InventoryMovementEvidence.objects.get(movement=returned)
        corrupt_inventory(InventoryMovementEvidence, evidence.pk, original_issue=other.pk)
        self.refused()


@override_settings(**purchase_proof.SETTINGS)
class StockMovementProofConcurrencyTests(TransactionTestCase):
    def setUp(self):
        purchase_proof.setup(self)
        usage = record_inventory_issue(**inventory.issue(self, self.lot))[0]
        self.original = StockMovement.objects.get(usage=usage)

    def test_same_new_issue_intent_with_existing_proof_commits_once(self):
        request = inventory.issue(self, self.lot)
        self.assertCountEqual(purchase_proof.race(self, [lambda: record_inventory_issue(**request)] * 2), [True, False])
        self.assertEqual((ConsumableUsage.objects.count(), StockMovement.objects.count(), JournalEntry.objects.count()), (2, 3, 3))

    def test_two_last_stock_issues_cannot_overdraw_proved_existing_movements(self):
        self.assertCountEqual(purchase_proof.race(self, [lambda: record_inventory_issue(**{
            **inventory.issue(self, self.lot), "quantity": "8.0000"})] * 2), [True, "rejected"])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("0.0000"), Decimal("0.00")))

    def test_two_full_returns_cannot_restore_more_than_original_issue(self):
        self.assertCountEqual(purchase_proof.race(self, [lambda: record_inventory_return(**{
            **corrections.returned(self, self.original), "quantity": "2.0000"})] * 2), [True, "rejected"])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("10.0000"), Decimal("100.00")))
        self.assertEqual(InventoryMovementEvidence.objects.count(), 1)
