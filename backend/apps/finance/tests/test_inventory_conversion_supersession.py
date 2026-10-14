"""Prospective unit corrections and historical proof on owned PostgreSQL only."""
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
from apps.finance.models import (ConsumableItem, FinancialCommandReceipt, InventoryValuePool,
    JournalEntry, PeriodStatus, StockMovement)
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase, _item
from apps.finance.services.inventory_conversion_setup import configure_inventory_unit, read_inventory_unit
from apps.finance.services import inventory_conversion_supersession as supersession
from apps.finance.services.inventory_corrections import record_inventory_return
from apps.finance.services.ledger import trial_balance
from .inventory_corruption import corrupt_inventory
from . import test_inventory_capture as inventory
from . import test_inventory_corrections as corrections
from . import test_inventory_conversion_setup as setup
from . import test_inventory_purchase_proof as proof


def replacement_request(test, previous, **changes):
    return {"submission_id": uuid.uuid4(), "user": test.user, "item_id": test.item.pk,
        "previous_definition_id": previous["configuration_id"], "previous_definition_version": previous["definition_version"],
        "to_base_multiplier": "25", "reason": "Synthetic verified supplier label: future bags contain 25 kg.", **changes}


@override_settings(**setup.SETTINGS)
class InventoryConversionSupersessionTests(TestCase):
    def setUp(self):
        inventory.inventory_fixture(self)
        self.original_request = setup.setup_request(self)
        self.original = configure_inventory_unit(**self.original_request)[0]

    def replace(self, previous=None, **changes):
        return supersession.supersede_inventory_unit(**replacement_request(self, previous or self.original, **changes))[0]

    def purchase(self, definition=None, **changes):
        definition = definition or self.original
        return record_inventory_purchase(**{**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": definition["configuration_id"], **changes})[0]

    def issue(self, lot, definition=None, **changes):
        units = dict(quantity_unit="bag", unit_conversion_id=definition["configuration_id"]) if definition else {}
        return record_inventory_issue(**{**inventory.issue(self, lot), **units, **changes})[0]

    def refused(self, call, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception):
            call()
        self.assertEqual(proof.snapshot(), before)

    def read(self, definition, **kwargs):
        return read_inventory_unit(definition["configuration_id"], _item(self.item.pk), "bag", **kwargs)

    def test_replacement_changes_only_future_definition_not_original_sources(self):
        lot = self.purchase()
        before = proof.snapshot()
        new = self.replace()
        after = proof.snapshot()
        for model in before:
            if model != "financialcommandreceipt":
                self.assertEqual(before[model], after[model])
        for row in before["financialcommandreceipt"]:
            self.assertIn(row, after["financialcommandreceipt"])
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=self.original["configuration_id"]).result, self.original)
        self.assertEqual(self.read(self.original), (self.original, Decimal("50")))
        self.assertEqual(self.read(new, require_current=True), (new, Decimal("25")))
        next_lot = self.purchase(new)
        self.assertEqual((lot.quantity_purchased, next_lot.quantity_purchased), (Decimal("100"), Decimal("50")))
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal("150"))
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_twenty_lost_response_replays_retain_one_replacement(self):
        request = replacement_request(self, self.original)
        new, created = supersession.supersede_inventory_unit(**request)
        self.assertTrue(created)
        before = proof.snapshot()
        for _ in range(20):
            self.assertEqual(supersession.supersede_inventory_unit(**request), (new, False))
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)
        self.assertFalse(JournalEntry.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(InventoryValuePool.objects.exists())

    def test_same_operation_with_changed_capture_is_not_a_replay(self):
        request = replacement_request(self, self.original)
        supersession.supersede_inventory_unit(**request)
        for changes in ({"to_base_multiplier": "20"}, {"reason": "Different physical evidence"},
                {"previous_definition_version": "0" * 64}, {"previous_definition_id": str(uuid.uuid4())},
                {"item_id": self.item.pk + 1}):
            with self.subTest(changes=changes):
                self.refused(lambda: supersession.supersede_inventory_unit(**{**request, **changes}))

    def test_exact_equivalent_decimal_uuid_and_identifier_replay(self):
        request = replacement_request(self, self.original)
        new = supersession.supersede_inventory_unit(**request)[0]
        self.assertEqual(supersession.supersede_inventory_unit(**{**request,
            "submission_id": str(request["submission_id"]).upper(), "item_id": str(self.item.pk),
            "previous_definition_id": request["previous_definition_id"].upper(),
            "to_base_multiplier": "25.000000"}), (new, False))

    def test_accepted_old_capture_replays_with_exact_original_quantity_after_replacement(self):
        request = {**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": self.original["configuration_id"]}
        lot = record_inventory_purchase(**request)[0]
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        original_row = deepcopy(proof.snapshot()["financialcommandreceipt"])
        self.replace()
        for _ in range(20):
            self.assertFalse(record_inventory_purchase(**request)[1])
        receipt.refresh_from_db()
        self.assertEqual(receipt.result["stock_quantity_evidence"]["to_base_multiplier"], "50.000000")
        self.assertEqual(lot.quantity_purchased, Decimal("100"))
        for row in original_row:
            self.assertIn(row, proof.snapshot()["financialcommandreceipt"])

    def test_old_unsubmitted_quantity_cannot_be_silently_reinterpreted(self):
        request = {**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": self.original["configuration_id"]}
        capture = deepcopy(request)
        self.replace()
        self.refused(lambda: record_inventory_purchase(**request))
        self.assertEqual(request, capture)
        self.assertFalse(FinancialCommandReceipt.objects.filter(pk=request["submission_id"]).exists())

    def test_new_custom_issue_requires_current_explicit_definition(self):
        lot = self.purchase()
        new = self.replace()
        self.refused(lambda: self.issue(lot, self.original, quantity="1"))
        used = self.issue(lot, new, quantity="1")
        self.assertEqual((used.quantity_used, used.recognized_cost), (Decimal("25"), Decimal("25")))
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal("75"))

    def test_old_issue_proof_and_base_unit_return_keep_original_cost(self):
        lot = self.purchase()
        used = self.issue(lot, self.original, quantity="1")
        original = StockMovement.objects.get(usage=used)
        original_row = deepcopy(proof.snapshot()["financialcommandreceipt"])
        new = self.replace()
        result = record_inventory_return(**{**corrections.returned(self, original), "quantity": "10"})[0]
        self.assertEqual((result.quantity, result.total_cost), (Decimal("10"), Decimal("10")))
        result = record_inventory_return(**{**corrections.returned(self, original), "quantity": "0.4",
            "quantity_unit": "bag", "unit_conversion_id": new["configuration_id"]})[0]
        self.assertEqual((result.quantity, result.total_cost), (Decimal("10"), Decimal("10")))
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal("70"))
        for row in original_row:
            self.assertIn(row, proof.snapshot()["financialcommandreceipt"])

    def test_multiple_replacements_preserve_every_version_and_require_only_tip_for_new_use(self):
        first = self.replace()
        lot = self.purchase(first)
        second = self.replace(first, to_base_multiplier="10")
        for definition, factor in ((self.original, "50"), (first, "25"), (second, "10")):
            self.assertEqual(self.read(definition), (definition, Decimal(factor)))
        self.refused(lambda: self.purchase(first))
        self.refused(lambda: self.replace(self.original, to_base_multiplier="20"))
        self.issue(lot, quantity="5")
        self.assertEqual(self.purchase(second, purchase_date=date(2026, 1, 12)).quantity_purchased, Decimal("20"))

    def test_stale_or_changed_previous_version_cannot_replace_the_tip(self):
        self.refused(lambda: self.replace(previous_definition_version="0" * 64))
        self.replace()
        self.refused(lambda: self.replace(to_base_multiplier="20"))

    def test_setup_cannot_reset_the_original_unit_after_replacement(self):
        self.replace()
        self.refused(lambda: configure_inventory_unit(**setup.setup_request(self, to_base_multiplier="10")))

    def test_definition_from_another_item_or_unit_cannot_be_replaced_here(self):
        other = ConsumableItem.objects.create(sku="SUPERSEDE-OTHER", name="Other synthetic item", base_unit="kg")
        foreign = configure_inventory_unit(**setup.setup_request(self, item_id=other.pk))[0]
        self.refused(lambda: self.replace(foreign))
        box = configure_inventory_unit(**setup.setup_request(self, quantity_unit="box"))[0]
        new_box = self.replace(box, to_base_multiplier="10")
        self.refused(lambda: self.purchase(new_box))
        self.assertEqual(self.read(self.original, require_current=True)[0], self.original)

    def test_current_management_roles_only_no_cached_permission_authority(self):
        for slug in RoleChoices.values:
            with self.subTest(role=slug), transaction.atomic():
                actor = get_user_model().objects.create_user(username="replace-" + slug,
                    email="replace-" + slug + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=slug, defaults={"name": slug})[0])
                if slug in {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER}:
                    self.replace(user=actor)
                else:
                    self.refused(lambda: self.replace(user=actor), PermissionDenied)
                transaction.set_rollback(True)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(self.replace, PermissionDenied)

    def test_flag_off_replacement_refuses_before_any_database_query(self):
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=False), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                self.replace()

    def test_flag_off_preserves_old_and_replacement_source_proof(self):
        old_lot = self.purchase()
        new = self.replace()
        new_lot = self.purchase(new)
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=False):
            self.issue(old_lot, quantity="5")
            self.issue(new_lot, quantity="5")
            self.assertEqual(self.read(self.original)[1], Decimal("50"))
            self.assertEqual(self.read(new)[1], Decimal("25"))
            self.refused(lambda: self.issue(new_lot, new, quantity="1"))

    def test_invalid_multiplier_reason_version_or_reference_has_no_effect(self):
        for factor in ("50", "0", "-1", "NaN", "Infinity", True, 25.0, "25.0000001", "1000000000000"):
            with self.subTest(factor=factor):
                self.refused(lambda: self.replace(to_base_multiplier=factor))
        for changes in ({"reason": ""}, {"reason": "x" * 256}, {"previous_definition_version": True},
                {"previous_definition_version": "missing"}, {"previous_definition_id": None},
                {"previous_definition_id": True}, {"previous_definition_id": "invalid"},
                {"previous_definition_id": str(uuid.uuid4())}, {"item_id": True}):
            with self.subTest(changes=changes):
                self.refused(lambda: self.replace(**changes))

    def test_changed_item_identity_base_or_active_state_requires_review(self):
        for fields in ({"sku": "CHANGED"}, {"base_unit": "g"}, {"is_active": False}):
            with self.subTest(fields=fields), transaction.atomic():
                ConsumableItem.objects.filter(pk=self.item.pk).update(**fields)
                self.refused(self.replace)
                transaction.set_rollback(True)

    def test_missing_original_definition_blocks_replacement_and_later_stock_effect(self):
        lot = self.purchase()
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=self.original["configuration_id"]))
        self.refused(self.replace)
        self.refused(lambda: self.issue(lot))

    def test_replacement_exact_previous_identity_hash_completion_and_version_are_required(self):
        new = self.replace()
        receipt = FinancialCommandReceipt.objects.get(pk=new["configuration_id"])
        for field in supersession.PREVIOUS_KEYS:
            with self.subTest(field=field), transaction.atomic():
                changed = deepcopy(new)
                changed["previous_definition"][field] = "altered"
                # Reanchoring a changed snapshot does not recreate original proof.
                changed["definition_anchor"] = supersession._anchor(changed, receipt.pk, receipt.actor_id, receipt.request_hash)
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps(changed))
                self.refused(lambda: self.purchase(new))
                transaction.set_rollback(True)

    def test_damaged_replacement_definition_or_receipt_requires_review(self):
        lot = self.purchase()
        new = self.replace()
        receipt = FinancialCommandReceipt.objects.get(pk=new["configuration_id"])
        other_actor = get_user_model().objects.create_user(username="replacement-corruption-actor",
            email="replacement-corruption-actor@synthetic.invalid", password="synthetic-only")
        for changes in ({"to_base_multiplier": "10.000000"}, {"definition_version": "0" * 64},
                {"definition_anchor": "0" * 64}, {"quantity_unit": "box"}, {"item_id": "999999"},
                {"reason": "Changed"}, {"configuration_id": str(uuid.uuid4())},
                {"previous_definition": None}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, result=json.dumps({**new, **changes}))
                self.refused(lambda: self.purchase(new))
                self.refused(lambda: self.issue(lot))
                transaction.set_rollback(True)
        for changes in ({"request_hash": "0" * 64}, {"actor_id": other_actor.pk},
                {"completed_at": None}, {"command": "inventory.unit.unknown"}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, **changes)
                self.refused(lambda: self.purchase(new))
                transaction.set_rollback(True)

    def test_branch_or_orphan_is_not_last_write_wins(self):
        new = self.replace()
        receipt = FinancialCommandReceipt.objects.get(pk=new["configuration_id"])
        for orphan in (False, True):
            with self.subTest(orphan=orphan), transaction.atomic():
                result = deepcopy(new)
                if orphan:
                    result["previous_definition"]["operation_id"] = str(uuid.uuid4())
                FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user,
                    command=supersession.COMMAND, request_hash=receipt.request_hash, result=result,
                    completed_at=receipt.completed_at)
                self.refused(lambda: self.purchase(new))
                self.refused(lambda: self.replace(new, to_base_multiplier="10"))
                transaction.set_rollback(True)

    def test_replacement_receipt_is_immutable_through_ordinary_writes(self):
        new = self.replace()
        receipt = FinancialCommandReceipt.objects.get(pk=new["configuration_id"])
        receipt.result = {"changed": True}
        for call in (lambda: receipt.save(), lambda: receipt.save_base(raw=True), lambda: receipt.delete(),
                lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk).update(result={}),
                lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk)._raw_delete("default")):
            self.refused(call, DomainValidationError)

    def test_receipt_failure_does_not_retire_original_or_commit_a_placeholder(self):
        request = replacement_request(self, self.original)
        with patch("apps.finance.services.financial_capture.FinancialCommandReceipt.objects.create",
                side_effect=RuntimeError("synthetic replacement insert interruption")):
            self.refused(lambda: supersession.supersede_inventory_unit(**request), RuntimeError)
        self.assertEqual(self.read(self.original, require_current=True)[0], self.original)
        self.assertTrue(supersession.supersede_inventory_unit(**request)[1])

    def test_master_correction_does_not_reopen_closed_period_or_bypass_stock_period_guard(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        new = self.replace()
        self.refused(lambda: self.purchase(new))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PeriodStatus.CLOSED)
        self.assertFalse(JournalEntry.objects.exists())

    def test_fifty_replacements_have_bounded_reads_and_next_requires_review(self):
        previous = self.original
        retained = []
        for index in range(supersession.MAX_REPLACEMENTS):
            previous = self.replace(previous, to_base_multiplier=str(index + 1))
            retained.append(previous)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 51)
        item = _item(self.item.pk)
        with self.assertNumQueries(4):
            self.assertEqual(read_inventory_unit(previous["configuration_id"], item, "bag", require_current=True)[0], previous)
        self.assertEqual(self.read(retained[0])[1], Decimal("1"))
        self.assertEqual(self.read(self.original)[1], Decimal("50"))
        self.refused(lambda: self.replace(previous, to_base_multiplier="51"))
        self.assertEqual(FinancialCommandReceipt.objects.count(), 51)


@override_settings(**setup.SETTINGS)
class InventoryConversionSupersessionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        inventory.inventory_fixture(self)
        self.original = configure_inventory_unit(**setup.setup_request(self))[0]

    def test_same_replacement_intent_commits_once(self):
        request = replacement_request(self, self.original)
        self.assertCountEqual(proof.race(self, [lambda: supersession.supersede_inventory_unit(**request)] * 2), [True, False])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)
        self.assertFalse(JournalEntry.objects.exists())

    def test_competing_replacements_cannot_branch_the_same_definition(self):
        first, second = replacement_request(self, self.original), replacement_request(self, self.original, to_base_multiplier="10")
        self.assertCountEqual(proof.race(self, [lambda: supersession.supersede_inventory_unit(**first),
            lambda: supersession.supersede_inventory_unit(**second)]), [True, "rejected"])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)

    def test_old_pending_pack_capture_vs_replacement_never_uses_the_new_factor(self):
        request = replacement_request(self, self.original)
        purchase = {**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": self.original["configuration_id"]}
        results = proof.race(self, [lambda: supersession.supersede_inventory_unit(**request),
            lambda: record_inventory_purchase(**purchase)])
        self.assertIn(results.count(True), (1, 2))
        self.assertEqual(results.count("rejected"), 2 - results.count(True))
        pools = list(InventoryValuePool.objects.filter(item=self.item))
        if pools:
            self.assertEqual((pools[0].quantity, pools[0].carrying_value), (Decimal("100"), Decimal("100")))
            self.assertEqual(JournalEntry.objects.count(), 1)
        else:
            self.assertFalse(JournalEntry.objects.exists())

    def test_existing_base_stock_effect_and_replacement_both_retain_original_proof(self):
        lot = record_inventory_purchase(**{**inventory.purchase(self), "quantity": "2", "quantity_unit": "bag",
            "unit_conversion_id": self.original["configuration_id"]})[0]
        request = replacement_request(self, self.original)
        issue = {**inventory.issue(self, lot), "quantity": "50"}
        self.assertEqual(proof.race(self, [lambda: supersession.supersede_inventory_unit(**request),
            lambda: record_inventory_issue(**issue)]), [True, True])
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("50"), Decimal("50")))
        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_replacement_and_duplicate_setup_do_not_reset_the_root(self):
        request = replacement_request(self, self.original)
        duplicate = setup.setup_request(self, to_base_multiplier="10")
        self.assertCountEqual(proof.race(self, [lambda: supersession.supersede_inventory_unit(**request),
            lambda: configure_inventory_unit(**duplicate)]), [True, "rejected"])
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)
