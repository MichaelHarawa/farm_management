"""Controlled item-specific unit definitions on disposable PostgreSQL only."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DomainValidationError
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (ConsumableItem, FinancialCommandReceipt, InventoryLocation,
    InventoryMovementEvidence, InventoryUnitConversion, InventoryValuePool, JournalEntry, PeriodStatus, StockMovement)
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase
from apps.finance.services.inventory_conversion_setup import COMMAND, configure_inventory_unit
from apps.finance.services.inventory_corrections import (record_inventory_return, record_inventory_transfer,
    record_inventory_waste, record_inventory_expiry, record_inventory_count_loss)
from apps.finance.services.ledger import trial_balance
from apps.finance.services.stock_movement_evidence import _anchor as stock_anchor
from apps.finance.services.payable_evidence import _anchor as payable_anchor
from .inventory_corruption import corrupt_inventory
from . import test_inventory_purchase_proof as proof
from . import test_inventory_corrections as corrections

from . import test_inventory_capture as inventory


SETTINGS = {**proof.SETTINGS, "FINANCE_INVENTORY_UNIT_CONVERSIONS": True}


def setup_request(test, **changes):
    return {"submission_id": uuid.uuid4(), "user": test.user, "item_id": test.item.pk,
        "quantity_unit": "bag", "base_unit": "kg", "to_base_multiplier": "50",
        "reason": "Synthetic supplier label: each sealed bag contains 50 kg.", **changes}


@override_settings(**SETTINGS)
class InventoryConversionSetupTests(TestCase):
    def setUp(self):
        inventory.inventory_fixture(self)
        self.other_location = InventoryLocation.objects.create(code="CONVERT-OTHER", name="Other synthetic store")

    def configure(self, **changes):
        return configure_inventory_unit(**setup_request(self, **changes))[0]

    def purchase(self, definition=None, **changes):
        units = {"quantity_unit": "bag", "unit_conversion_id": definition["configuration_id"]} if definition else {}
        return record_inventory_purchase(**{**inventory.purchase(self), **units, **changes})[0]

    def issue(self, lot, definition=None, **changes):
        units = {"quantity_unit": "bag", "unit_conversion_id": definition["configuration_id"]} if definition else {}
        return record_inventory_issue(**{**inventory.issue(self, lot), **units, **changes})[0]

    def refused(self, call, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception):
            call()
        self.assertEqual(proof.snapshot(), before)

    def balance(self, quantity, value):
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal(quantity), Decimal(value)))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_explicit_management_definition_can_back_a_bag_purchase(self):
        definition, created = configure_inventory_unit(submission_id=uuid.uuid4(), user=self.user,
            item_id=self.item.pk, quantity_unit="bag", base_unit="kg", to_base_multiplier="50",
            reason="Synthetic supplier label: each sealed bag contains 50 kg.")
        self.assertTrue(created)
        lot, _ = record_inventory_purchase(**{**inventory.purchase(self), "quantity": "2",
            "quantity_unit": "bag", "unit_conversion_id": definition["configuration_id"]})
        self.assertEqual(str(lot.quantity_purchased), "100.0000")

    def test_twenty_setup_replays_have_one_definition_and_no_stock_cash_gl(self):
        request = setup_request(self)
        definition, created = configure_inventory_unit(**request)
        self.assertTrue(created)
        before = proof.snapshot()
        for _ in range(20):
            result, created = configure_inventory_unit(**request)
            self.assertFalse(created)
            self.assertEqual(result, definition)
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 1)
        self.assertFalse(InventoryUnitConversion.objects.exists())
        self.assertFalse(InventoryValuePool.objects.exists())
        self.assertFalse(JournalEntry.objects.exists())
        self.assertFalse(StockMovement.objects.exists())

    def test_same_setup_id_changed_definition_is_rejected(self):
        request = setup_request(self)
        configure_inventory_unit(**request)
        for changes in ({"to_base_multiplier": "25"}, {"quantity_unit": "box"},
                {"base_unit": "g"}, {"reason": "Changed physical evidence"}, {"item_id": self.item.pk + 1}):
            with self.subTest(changes=changes):
                self.refused(lambda: configure_inventory_unit(**{**request, **changes}))

    def test_same_item_unit_cannot_be_redefined_by_another_operation(self):
        original = self.configure()
        self.refused(lambda: self.configure(to_base_multiplier="25"))
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=original["configuration_id"]).result, original)

    def test_different_items_have_independent_explicit_pack_definitions(self):
        first = self.configure()
        other = ConsumableItem.objects.create(sku="OTHER-PACK", name="Other synthetic item", category="Feed", base_unit="kg")
        second = self.configure(item_id=other.pk, to_base_multiplier="25")
        self.assertNotEqual(first["configuration_id"], second["configuration_id"])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)

    def test_current_role_matrix_for_management_setup(self):
        for slug in RoleChoices.values:
            with self.subTest(role=slug), transaction.atomic():
                actor = get_user_model().objects.create_user(username="unit-" + slug,
                    email="unit-" + slug + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=slug, defaults={"name": slug})[0])
                if slug in {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER}:
                    self.configure(user=actor)
                else:
                    self.refused(lambda: self.configure(user=actor), PermissionDenied)
                transaction.set_rollback(True)

    def test_stale_cached_active_user_cannot_configure(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(self.configure, PermissionDenied)

    def test_supervisor_can_use_management_definition_but_cannot_configure_it(self):
        definition = self.configure()
        actor = get_user_model().objects.create_user(username="unit-stock-supervisor",
            email="unit-stock-supervisor@synthetic.invalid", password="synthetic-only")
        actor.roles.add(Role.objects.get(slug=RoleChoices.FARM_SUPERVISOR))
        self.refused(lambda: self.configure(user=actor), PermissionDenied)
        lot = self.purchase(definition, user=actor, quantity="2")
        self.issue(lot, definition, user=actor, quantity="0.1")
        self.balance("95", "95")

    def test_definition_does_not_bypass_closed_financial_period(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        self.refused(lambda: self.purchase(definition, quantity="1"))
        self.refused(lambda: self.issue(lot, definition, quantity="0.1"))
        self.balance("100", "100")

    def test_flag_off_setup_does_not_query_new_receipt_schema(self):
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=False), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                self.configure()

    def test_base_and_fixed_si_units_cannot_be_overridden(self):
        for unit in ("kg", "g"):
            with self.subTest(unit=unit):
                self.refused(lambda: self.configure(quantity_unit=unit))

    def test_setup_preserves_explicit_expected_base_unit(self):
        self.refused(lambda: self.configure(base_unit="g"))

    def test_invalid_multiplier_and_missing_physical_evidence_have_no_effect(self):
        for factor in (0, "-1", "NaN", "Infinity", True, 50.0, "50.0000001", "1000000000000"):
            with self.subTest(factor=factor):
                self.refused(lambda: self.configure(to_base_multiplier=factor))
        for changes in ({"reason": ""}, {"quantity_unit": ""}, {"base_unit": ""}, {"reason": "x" * 256}):
            with self.subTest(changes=changes):
                self.refused(lambda: self.configure(**changes))

    def test_legacy_conversion_row_is_not_adopted_or_changed(self):
        legacy = InventoryUnitConversion.objects.create(item=self.item, from_unit="bag", to_base_multiplier="2")
        original = list(InventoryUnitConversion.objects.values())
        self.refused(lambda: self.purchase(quantity_unit="bag"))
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        self.assertEqual(list(InventoryUnitConversion.objects.values()), original)
        InventoryUnitConversion.objects.filter(pk=legacy.pk).update(to_base_multiplier="999")
        usage = self.issue(lot, definition, quantity="0.1")
        self.assertEqual((usage.quantity_used, usage.recognized_cost), (Decimal("5"), Decimal("5")))
        self.balance("95", "95")

    def test_definition_reference_cannot_bind_another_item_or_unit(self):
        definition = self.configure()
        self.refused(lambda: self.purchase(definition, quantity_unit="box"))
        other = ConsumableItem.objects.create(sku="OTHER-REF", name="Other reference item", category="Feed", base_unit="kg")
        self.refused(lambda: self.purchase(definition, item_id=other.pk))
        self.refused(lambda: self.purchase(definition, quantity_unit="kg"))

    def test_custom_unit_must_explicitly_reference_original_definition(self):
        self.configure()
        self.refused(lambda: self.purchase(quantity_unit="bag"))
        for reference in ("", "invalid", True, 1, str(uuid.uuid4())):
            with self.subTest(reference=reference):
                self.refused(lambda: self.purchase(quantity_unit="bag", unit_conversion_id=reference))
        self.refused(lambda: self.purchase(unit_conversion_id=str(uuid.uuid4())))

    def test_changed_item_base_or_sku_obsoletes_definition_without_reinterpretation(self):
        definition = self.configure()
        for field, value in (("base_unit", "g"), ("sku", "CHANGED-SKU")):
            with self.subTest(field=field), transaction.atomic():
                ConsumableItem.objects.filter(pk=self.item.pk).update(**{field: value})
                self.refused(lambda: self.purchase(definition))
                transaction.set_rollback(True)

    def test_original_input_definition_and_base_result_are_sealed(self):
        definition = self.configure()
        request = {**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"]}
        record_inventory_purchase(**request)
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        self.assertEqual(receipt.result["stock_quantity_evidence"], {"input_quantity": "2.0000", "input_unit": "bag",
            "base_unit": "kg", "to_base_multiplier": "50.000000", "base_quantity": "100.0000",
            "quantity_field": "quantity", "conversion_version": "configured-unit-v1",
            "unit_conversion_id": definition["configuration_id"], "unit_conversion_version": definition["definition_version"]})
        original = deepcopy(receipt.result)
        for _ in range(20):
            self.assertFalse(record_inventory_purchase(**request)[1])
        receipt.refresh_from_db()
        self.assertEqual(receipt.result, original)
        self.refused(lambda: record_inventory_purchase(**{**request, "quantity": "100", "quantity_unit": "kg", "unit_conversion_id": None}))

    def test_custom_conversion_overprecision_and_overflow_are_not_rounded(self):
        tiny = self.configure(quantity_unit="tiny-pack", to_base_multiplier="0.000001")
        self.refused(lambda: self.purchase(tiny, quantity_unit="tiny-pack", quantity="0.0001"))
        huge = self.configure(quantity_unit="huge-pack", to_base_multiplier="999999999999.999999")
        self.refused(lambda: self.purchase(huge, quantity_unit="huge-pack", quantity="2"))
        lot = self.purchase(tiny, quantity_unit="tiny-pack", quantity="1000")
        self.assertEqual(lot.quantity_purchased, Decimal("0.0010"))

    def test_last_stock_limit_uses_normalized_pack_quantity(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        self.issue(lot, definition, quantity="1.5")
        self.refused(lambda: self.issue(lot, definition, quantity="0.5001"))
        self.issue(lot, definition, quantity="0.5")
        self.balance("0", "0")

    def test_returns_recover_original_cost_with_original_pack_evidence(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        original = StockMovement.objects.get(usage=self.issue(lot, definition, quantity="1.5"))
        request = {**corrections.returned(self, original), "quantity": "0.5", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"]}
        result = record_inventory_return(**request)[0]
        self.assertEqual((result.quantity, result.total_cost), (Decimal("25"), Decimal("25")))
        for _ in range(20):
            self.assertFalse(record_inventory_return(**request)[1])
        record_inventory_return(**{**request, "submission_id": uuid.uuid4(), "quantity": "1"})
        self.balance("100", "100")

    def test_transfer_and_losses_keep_stock_costing_and_cash_separate(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2", expiry_date=date(2026, 1, 13))
        units = {"quantity": "0.1", "quantity_unit": "bag", "unit_conversion_id": definition["configuration_id"]}
        transferred = record_inventory_transfer(**{**corrections.transfer(self, lot), **units})[0]
        self.assertEqual(transferred.quantity, Decimal("5"))
        self.assertEqual(JournalEntry.objects.count(), 1)
        record_inventory_waste(**{**corrections.movement(self, lot), **units})
        record_inventory_expiry(**{**corrections.movement(self, lot), **units, "movement_date": date(2026, 1, 14)})
        self.balance("90", "90")

    def test_physical_count_retains_pack_count_and_base_difference(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        request = {**corrections.movement(self, lot), "counted_quantity": "1.5", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"],
            "expected_revision": InventoryValuePool.objects.get(item=self.item).revision}
        request.pop("quantity")
        result = record_inventory_count_loss(**request)[0]
        evidence = InventoryMovementEvidence.objects.get(movement=result)
        self.assertEqual((evidence.expected_quantity, evidence.counted_quantity, result.quantity, result.total_cost),
            (Decimal("100"), Decimal("75"), Decimal("25"), Decimal("25")))
        record = FinancialCommandReceipt.objects.get(pk=request["submission_id"]).result["stock_quantity_evidence"]
        self.assertEqual((record["input_quantity"], record["base_quantity"], record["quantity_field"]),
            ("1.5000", "75.0000", "counted_quantity"))
        self.issue(lot, quantity="5", usage_date=date(2026, 1, 12))
        self.balance("70", "70")

    def test_missing_setup_after_custom_purchase_blocks_even_base_unit_issue(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=definition["configuration_id"]))
        self.refused(lambda: self.issue(lot))

    def test_missing_setup_after_custom_issue_blocks_later_base_only_effect(self):
        definition = self.configure()
        lot = self.purchase()
        self.issue(lot, definition, quantity="0.1")
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=definition["configuration_id"]))
        self.refused(lambda: self.issue(lot))

    def test_damaged_definition_result_hash_actor_or_completion_requires_review(self):
        definition = self.configure()
        receipt = FinancialCommandReceipt.objects.get(pk=definition["configuration_id"])
        other_actor = get_user_model().objects.create_user(username="unit-different-actor",
            email="unit-different-actor@synthetic.invalid", password="synthetic-only")
        result_changes = ({"to_base_multiplier": "25.000000"}, {"quantity_unit": "box"},
            {"base_unit": "g"}, {"configuration_id": str(uuid.uuid4())}, {"definition_version": "0" * 64},
            {"definition_anchor": "0" * 64}, {"item_sku": "Altered"}, {"reason": "Altered evidence"})
        for changes in result_changes:
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps({**definition, **changes}))
                self.refused(lambda: self.purchase(definition))
                transaction.set_rollback(True)
        for changes in ({"request_hash": "0" * 64}, {"actor_id": other_actor.pk},
                {"completed_at": None}, {"command": "inventory.unit.unknown"},
                {"result": json.dumps("not a definition")}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, **changes)
                self.refused(lambda: self.purchase(definition))
                transaction.set_rollback(True)

    def test_ambiguous_or_versionless_definitions_are_not_adopted(self):
        definition = self.configure()
        receipt = FinancialCommandReceipt.objects.get(pk=definition["configuration_id"])
        with transaction.atomic():
            FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user,
                command=COMMAND, request_hash=receipt.request_hash, result=definition, completed_at=receipt.completed_at)
            self.refused(lambda: self.purchase(definition))
            transaction.set_rollback(True)
        corrupt_inventory(FinancialCommandReceipt, receipt.pk,
            result=json.dumps({key: value for key, value in definition.items() if not key.startswith("definition_")}))
        self.refused(lambda: self.purchase(definition))

    def test_reanchored_wrong_custom_input_cannot_match_original_purchase(self):
        definition = self.configure()
        lot = self.purchase(definition, quantity="2")
        receipt = FinancialCommandReceipt.objects.get(command="inventory.receipt.record")
        result = deepcopy(receipt.result)
        result["stock_quantity_evidence"]["input_quantity"] = "4.0000"
        result["stock_quantity_evidence"]["base_quantity"] = "200.0000"
        result["payable_anchor"] = payable_anchor(result, submission_id=receipt.pk, command=receipt.command,
            actor_id=receipt.actor_id, request_hash=receipt.request_hash)
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(result))
        self.refused(lambda: self.issue(lot))

    def test_reanchored_wrong_custom_input_cannot_match_original_issue(self):
        definition = self.configure()
        lot = self.purchase()
        self.issue(lot, definition, quantity="0.1")
        receipt = FinancialCommandReceipt.objects.get(command="inventory.issue.record")
        result = deepcopy(receipt.result)
        result["stock_quantity_evidence"]["input_quantity"] = "0.2"
        result["stock_quantity_evidence"]["base_quantity"] = "10.0000"
        result["stock_anchor"] = stock_anchor(result, submission_id=receipt.pk, command=receipt.command,
            actor_id=receipt.actor_id, request_hash=receipt.request_hash)
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(result))
        self.refused(lambda: self.issue(lot))

    def test_retained_definition_is_immutable_through_ordinary_receipt_paths(self):
        definition = self.configure()
        receipt = FinancialCommandReceipt.objects.get(pk=definition["configuration_id"])
        receipt.result = {"changed": True}
        calls = [lambda: receipt.save(), lambda: receipt.save_base(), lambda: receipt.save_base(raw=True),
            lambda: receipt.delete(), lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk).update(result={"changed": True}),
            lambda: FinancialCommandReceipt.objects.bulk_update([receipt], ["result"]),
            lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk).delete(),
            lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk)._raw_delete("default")]
        for call in calls:
            self.refused(call, DomainValidationError)

    def test_raw_or_incomplete_receipt_import_cannot_create_definition(self):
        for raw, completed in ((True, self.period.created_at), (False, None)):
            fake = FinancialCommandReceipt(submission_id=uuid.uuid4(), actor=self.user, command=COMMAND,
                request_hash="0" * 64, result={"fake": True}, completed_at=completed)
            self.refused(lambda: fake.save_base(raw=raw), DomainValidationError)
            if raw:
                self.refused(lambda: fake.save_base(True), DomainValidationError)

    def test_flag_off_retains_old_custom_proof_and_replays_but_blocks_new_custom_use(self):
        definition = self.configure()
        request = {**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"]}
        lot = record_inventory_purchase(**request)[0]
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=False):
            self.assertFalse(record_inventory_purchase(**request)[1])
            self.refused(lambda: self.issue(lot, definition, quantity="0.1"))
            self.issue(lot, quantity="5")
        self.balance("95", "95")

    def test_new_definition_receipt_failure_has_no_placeholder_or_other_effect(self):
        with patch("apps.finance.services.financial_capture.FinancialCommandReceipt.objects.create",
                side_effect=RuntimeError("synthetic receipt insert interruption")):
            self.refused(self.configure, RuntimeError)


@override_settings(**SETTINGS)
class InventoryConversionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        inventory.inventory_fixture(self)

    def test_same_setup_intent_commits_one_definition(self):
        request = setup_request(self)
        self.assertCountEqual(proof.race(self, [lambda: configure_inventory_unit(**request)] * 2), [True, False])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 1)
        self.assertFalse(JournalEntry.objects.exists())

    def test_competing_same_item_unit_setup_accepts_only_one_factor(self):
        first, second = setup_request(self), setup_request(self, to_base_multiplier="25")
        self.assertCountEqual(proof.race(self, [lambda: configure_inventory_unit(**first),
            lambda: configure_inventory_unit(**second)]), [True, "rejected"])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 1)

    def test_custom_pack_and_base_requests_compete_for_same_last_stock(self):
        definition = configure_inventory_unit(**setup_request(self))[0]
        lot = record_inventory_purchase(**{**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"]})[0]
        pack = {**inventory.issue(self, lot), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"]}
        base = {**inventory.issue(self, lot), "quantity": "100", "quantity_unit": "kg"}
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_issue(**pack),
            lambda: record_inventory_issue(**base)]), [True, "rejected"])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("0"), Decimal("0")))
        self.assertEqual(JournalEntry.objects.count(), 2)
