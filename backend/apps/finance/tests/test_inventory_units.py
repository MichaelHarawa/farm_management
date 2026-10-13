"""Explicit captured units, exact base stock and original replay on owned PG."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace
import json

from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.finance.models import (FinancialCommandReceipt, InventoryLocation, InventoryLocationStock,
    InventoryMovementEvidence, InventoryUnitConversion, InventoryValuePool, JournalEntry, StockMovement)
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase
from apps.finance.services.inventory_corrections import (record_inventory_return, record_inventory_transfer,
    record_inventory_waste, record_inventory_expiry, record_inventory_count_loss)
from apps.finance.services.inventory_units import base_quantity
from apps.finance.services.ledger import trial_balance
from . import test_inventory_capture as inventory
from . import test_inventory_corrections as corrections
from . import test_inventory_purchase_proof as proof
from . import test_expenditure_drafts as drafts
from .inventory_corruption import corrupt_inventory


@override_settings(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False)
class InventoryUnitTests(TestCase):
    def setUp(self):
        inventory.inventory_fixture(self)
        self.other_location = InventoryLocation.objects.create(code="UNIT-OTHER", name="Synthetic other store")

    def purchase(self, **changes):
        return record_inventory_purchase(**{**inventory.purchase(self), **changes})[0]

    def issue(self, lot, **changes):
        return record_inventory_issue(**{**inventory.issue(self, lot), **changes})[0]

    def balance(self, quantity, cost):
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal(quantity), Decimal(cost)))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def refused(self, call):
        before = proof.snapshot()
        with self.assertRaises(ValidationError):
            call()
        self.assertEqual(proof.snapshot(), before)

    def evidence(self, request, quantity, unit, base, multiplier, field="quantity"):
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        self.assertEqual(receipt.result["stock_quantity_evidence"], {
            "input_quantity": format(Decimal(quantity).quantize(Decimal("0.0001")), "f"),
            "input_unit": unit, "base_unit": self.item.base_unit,
            "to_base_multiplier": multiplier, "base_quantity": format(Decimal(base).quantize(Decimal("0.0001")), "f"),
            "quantity_field": field, "conversion_version": "identity-g-kg-v1"})
        return receipt

    def test_purchase_grams_retains_exact_base_quantity_and_cost(self):
        lot, created = record_inventory_purchase(**{**inventory.purchase(self),
            "quantity": "10000", "quantity_unit": "g"})
        self.assertTrue(created)
        self.assertEqual((lot.quantity_purchased, lot.unit_of_measurement, lot.unit_cost),
            (Decimal("10.0000"), "kg", Decimal("10.000000")))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("10"), Decimal("100")))

    def test_issue_grams_costs_once_in_base_stock(self):
        lot = record_inventory_purchase(**inventory.purchase(self))[0]
        usage, created = record_inventory_issue(**{**inventory.issue(self, lot),
            "quantity": "1500", "quantity_unit": "g"})
        self.assertTrue(created)
        self.assertEqual((usage.quantity_used, usage.recognized_cost), (Decimal("1.5000"), Decimal("15.00")))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("8.5"), Decimal("85")))

    def test_twenty_purchase_replays_preserve_original_input_and_base_evidence(self):
        request = {**inventory.purchase(self), "quantity": "10000", "quantity_unit": "g"}
        lot = record_inventory_purchase(**request)[0]
        receipt = self.evidence(request, "10000", "g", "10", "0.001")
        original = deepcopy(receipt.result)
        for _ in range(20):
            result, created = record_inventory_purchase(**request)
            self.assertEqual(result.pk, lot.pk)
            self.assertFalse(created)
        receipt.refresh_from_db()
        self.assertEqual(receipt.result, original)
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (1, 1))
        self.balance("10", "100")

    def test_twenty_issue_replays_preserve_one_cost_and_original_units(self):
        lot = self.purchase()
        request = {**inventory.issue(self, lot), "quantity": "1500", "quantity_unit": "g"}
        usage = record_inventory_issue(**request)[0]
        receipt = self.evidence(request, "1500", "g", "1.5", "0.001")
        original = deepcopy(receipt.result)
        for _ in range(20):
            replay, created = record_inventory_issue(**request)
            self.assertEqual(replay.pk, usage.pk)
            self.assertFalse(created)
        receipt.refresh_from_db()
        self.assertEqual(receipt.result, original)
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (2, 2))
        self.balance("8.5", "85")

    def test_physically_equal_different_unit_is_not_the_same_original_intent(self):
        request = {**inventory.purchase(self), "quantity": "10000", "quantity_unit": "g"}
        lot = record_inventory_purchase(**request)[0]
        self.refused(lambda: record_inventory_purchase(**{**request, "quantity": "10", "quantity_unit": "kg"}))
        issued = {**inventory.issue(self, lot), "quantity": "2000", "quantity_unit": "g"}
        record_inventory_issue(**issued)
        self.refused(lambda: record_inventory_issue(**{**issued, "quantity": "2", "quantity_unit": "kg"}))

    def test_omitted_and_none_units_preserve_existing_hashes_and_result_shapes(self):
        request = inventory.purchase(self)
        lot = record_inventory_purchase(**request)[0]
        before = proof.snapshot()
        self.assertFalse(record_inventory_purchase(**{**request, "quantity_unit": None})[1])
        self.assertEqual(proof.snapshot(), before)
        self.assertNotIn("stock_quantity_evidence", FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result)
        self.refused(lambda: record_inventory_purchase(**{**request, "quantity_unit": "kg"}))
        issued = inventory.issue(self, lot)
        record_inventory_issue(**issued)
        before = proof.snapshot()
        self.assertFalse(record_inventory_issue(**{**issued, "quantity_unit": None})[1])
        self.assertEqual(proof.snapshot(), before)
        self.assertNotIn("stock_quantity_evidence", FinancialCommandReceipt.objects.get(pk=issued["submission_id"]).result)
        self.refused(lambda: record_inventory_issue(**{**issued, "quantity_unit": "kg"}))

    def test_kilograms_convert_to_gram_base_without_client_cost(self):
        self.item.base_unit = "g"
        self.item.save(update_fields=["base_unit"])
        lot = self.purchase(quantity="10", quantity_unit="kg")
        usage = self.issue(lot, quantity="1.5", quantity_unit="kg")
        self.assertEqual((lot.quantity_purchased, usage.quantity_used, usage.recognized_cost),
            (Decimal("10000"), Decimal("1500"), Decimal("15")))
        self.balance("8500", "85")

    def test_identity_preserves_other_explicit_base_units_without_conversion(self):
        self.item.base_unit = "ml"
        self.item.save(update_fields=["base_unit"])
        lot = self.purchase(quantity_unit="ml")
        usage = self.issue(lot, quantity_unit="ml")
        self.assertEqual((usage.quantity_used, usage.recognized_cost), (Decimal("2"), Decimal("20")))
        self.refused(lambda: self.issue(lot, quantity_unit="l"))

    def test_legacy_arbitrary_conversion_rows_do_not_authorize_pack_weights(self):
        InventoryUnitConversion.objects.create(item=self.item, from_unit="bag", to_base_multiplier="50")
        self.refused(lambda: self.purchase(quantity="1", quantity_unit="bag"))
        lot = self.purchase()
        self.refused(lambda: self.issue(lot, quantity="1", quantity_unit="bag"))

    def test_legacy_row_cannot_override_fixed_grams_kilograms(self):
        InventoryUnitConversion.objects.create(item=self.item, from_unit="g", to_base_multiplier="50")
        lot = self.purchase(quantity="10000", quantity_unit="g")
        usage = self.issue(lot, quantity="1000", quantity_unit="g")
        self.assertEqual((lot.quantity_purchased, usage.quantity_used), (Decimal("10"), Decimal("1")))
        self.balance("9", "90")

    def test_sub_base_precision_is_rejected_not_rounded(self):
        self.refused(lambda: self.purchase(quantity="0.01", quantity_unit="g"))
        lot = self.purchase()
        self.refused(lambda: self.issue(lot, quantity="0.01", quantity_unit="g"))
        usage = self.issue(lot, quantity="0.1", quantity_unit="g")
        self.assertEqual((usage.quantity_used, usage.recognized_cost), (Decimal("0.0001"), Decimal("0")))
        self.balance("9.9999", "100")

    def test_converted_overflow_is_rejected_before_stock_creation(self):
        self.item.base_unit = "g"
        self.item.save(update_fields=["base_unit"])
        self.refused(lambda: self.purchase(quantity="10000000", quantity_unit="kg"))

    def test_invalid_units_and_float_inputs_have_no_effect(self):
        for unit in ("", " ", "KG", "bags", "dose", "g" * 41, 1, True):
            with self.subTest(unit=unit):
                self.refused(lambda: self.purchase(quantity_unit=unit))
        for quantity in (1.5, True, "NaN", "Infinity", "-1", "0"):
            with self.subTest(quantity=quantity):
                self.refused(lambda: self.purchase(quantity=quantity, quantity_unit="kg"))

    def test_invalid_paid_purchase_rolls_back_without_consuming_cash(self):
        source = drafts.funded_source(self)
        self.refused(lambda: self.purchase(purchase_date=date(2026, 1, 21), quantity_unit="bag",
            payment_date=date(2026, 1, 21), funding_allocations=[{"funding_source": source.pk, "amount": "100.00"}]))

    def test_converted_quantity_uses_confirmed_limits_not_raw_input(self):
        lot = self.purchase()
        self.refused(lambda: self.issue(lot, quantity="10001", quantity_unit="g"))
        self.issue(lot, quantity="10000", quantity_unit="g")
        self.balance("0", "0")

    def test_return_converts_and_recovers_original_issue_cost_once(self):
        lot = self.purchase()
        usage = self.issue(lot, quantity="2000", quantity_unit="g")
        original = StockMovement.objects.get(usage=usage)
        request = {**corrections.returned(self, original), "quantity": "500", "quantity_unit": "g"}
        returned = record_inventory_return(**request)[0]
        self.assertEqual((returned.quantity, returned.total_cost), (Decimal("0.5"), Decimal("5")))
        receipt = self.evidence(request, "500", "g", "0.5", "0.001")
        original_result = deepcopy(receipt.result)
        for _ in range(20):
            self.assertFalse(record_inventory_return(**request)[1])
        receipt.refresh_from_db()
        self.assertEqual(receipt.result, original_result)
        self.refused(lambda: record_inventory_return(**{**request, "quantity": "0.5", "quantity_unit": "kg"}))
        self.balance("8.5", "85")

    def test_return_limit_uses_original_base_quantity(self):
        lot = self.purchase()
        original = StockMovement.objects.get(usage=self.issue(lot))
        self.refused(lambda: record_inventory_return(**{**corrections.returned(self, original),
            "quantity": "2001", "quantity_unit": "g"}))

    def test_transfer_converts_locations_without_new_expense(self):
        lot = self.purchase()
        request = {**corrections.transfer(self, lot), "quantity": "1500", "quantity_unit": "g"}
        moved = record_inventory_transfer(**request)[0]
        self.assertEqual((moved.quantity, moved.total_cost), (Decimal("1.5"), Decimal("15")))
        self.evidence(request, "1500", "g", "1.5", "0.001")
        self.assertEqual(InventoryLocationStock.objects.get(location=self.other_location).quantity, Decimal("1.5"))
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertFalse(record_inventory_transfer(**request)[1])
        self.issue(lot, quantity="500", quantity_unit="g", location_id=self.other_location.pk,
            usage_date=date(2026, 1, 12))
        self.balance("9.5", "95")

    def test_waste_and_expiry_convert_and_preserve_cost_proof(self):
        lot = self.purchase(expiry_date=date(2026, 1, 13))
        waste = {**corrections.movement(self, lot), "quantity": "500", "quantity_unit": "g"}
        movement = record_inventory_waste(**waste)[0]
        self.assertEqual((movement.quantity, movement.total_cost), (Decimal("0.5"), Decimal("5")))
        self.evidence(waste, "500", "g", "0.5", "0.001")
        expiry = {**corrections.movement(self, lot), "quantity": "1000", "quantity_unit": "g",
            "movement_date": date(2026, 1, 14)}
        movement = record_inventory_expiry(**expiry)[0]
        self.evidence(expiry, "1000", "g", "1", "0.001")
        self.assertEqual((movement.quantity, movement.total_cost), (Decimal("1"), Decimal("10")))
        self.assertFalse(record_inventory_waste(**waste)[1])
        self.assertFalse(record_inventory_expiry(**expiry)[1])
        self.balance("8.5", "85")

    def test_count_preserves_original_count_unit_and_base_difference(self):
        lot = self.purchase()
        request = {**corrections.movement(self, lot), "counted_quantity": "8500", "quantity_unit": "g",
            "expected_revision": InventoryValuePool.objects.get(item=self.item).revision}
        request.pop("quantity")
        moved = record_inventory_count_loss(**request)[0]
        self.evidence(request, "8500", "g", "8.5", "0.001", field="counted_quantity")
        evidence = InventoryMovementEvidence.objects.get(movement=moved)
        self.assertEqual((evidence.expected_quantity, evidence.counted_quantity, moved.quantity, moved.total_cost),
            (Decimal("10"), Decimal("8.5"), Decimal("1.5"), Decimal("15")))
        self.assertFalse(record_inventory_count_loss(**request)[1])
        self.issue(lot, quantity="500", quantity_unit="g", usage_date=date(2026, 1, 12))
        self.balance("8", "80")

    def test_zero_count_is_exact_and_positive_count_remains_unavailable(self):
        lot = self.purchase()
        request = {**corrections.movement(self, lot), "counted_quantity": "10001", "quantity_unit": "g",
            "expected_revision": InventoryValuePool.objects.get(item=self.item).revision}
        request.pop("quantity")
        self.refused(lambda: record_inventory_count_loss(**request))
        movement = record_inventory_count_loss(**{**request, "counted_quantity": "0"})[0]
        self.assertEqual((movement.quantity, movement.total_cost), (Decimal("10"), Decimal("100")))
        self.balance("0", "0")

    def test_changed_purchase_unit_evidence_requires_review_not_read_adoption(self):
        request = {**inventory.purchase(self), "quantity_unit": "kg"}
        lot = record_inventory_purchase(**request)[0]
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        result = deepcopy(receipt.result)
        result["stock_quantity_evidence"]["input_unit"] = "bag"
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(result))
        self.refused(lambda: self.issue(lot))

    def test_changed_issue_unit_evidence_requires_review_before_another_effect(self):
        lot = self.purchase()
        request = {**inventory.issue(self, lot), "quantity_unit": "kg"}
        record_inventory_issue(**request)
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        result = deepcopy(receipt.result)
        result["stock_quantity_evidence"]["to_base_multiplier"] = "2"
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(result))
        self.refused(lambda: self.issue(lot))


class ExactUnitConversionTests(SimpleTestCase):
    def test_fixed_conversion_is_independent_of_decimal_context(self):
        with localcontext() as context:
            context.prec = 6
            result, evidence = base_quantity(Decimal("9876543.2100"), "kg", SimpleNamespace(base_unit="g"))
        self.assertEqual(result, Decimal("9876543210.0000"))
        self.assertEqual(evidence["input_quantity"], "9876543.2100")


@override_settings(**proof.SETTINGS)
class InventoryUnitConcurrencyTests(TransactionTestCase):
    def setUp(self):
        proof.setup(self)

    def test_last_stock_competition_in_different_units_cannot_overdraw(self):
        grams = {**inventory.issue(self, self.lot), "quantity": "10000", "quantity_unit": "g"}
        kilograms = {**inventory.issue(self, self.lot), "quantity": "10", "quantity_unit": "kg"}
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_issue(**grams),
            lambda: record_inventory_issue(**kilograms)]), [True, "rejected"])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("0"), Decimal("0")))
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (2, 2))

    def test_same_captured_unit_intent_race_creates_one_cost(self):
        request = {**inventory.issue(self, self.lot), "quantity": "1500", "quantity_unit": "g"}
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_issue(**request)] * 2), [True, False])
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (2, 2))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("8.5"), Decimal("85")))
