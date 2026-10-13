"""Multi-item invoice capture on disposable PostgreSQL, never the farm DB."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (AccountingPeriod, ChartOfAccount, ConsumableItem, Expenditure,
    FinancialCommandReceipt, FundingAllocation, InventoryLotBinding, InventoryValuePool,
    JournalEntry, JournalLine, PeriodStatus, SharedConsumableLot, StockMovement)
from apps.finance.services.inventory_capture import record_inventory_purchase, record_inventory_issue
from apps.finance.services.inventory_conversion_setup import configure_inventory_unit
from apps.finance.services.inventory_corrections import record_inventory_return
from apps.finance.services.inventory_invoices import COMMAND, _anchor, _child_id, _version, record_inventory_invoice
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.ledger import trial_balance
from apps.finance.services.payable_evidence import _anchor as payable_anchor
from .inventory_corruption import corrupt_inventory
from . import test_inventory_capture as inventory
from . import test_inventory_corrections as corrections
from . import test_inventory_purchase_proof as proof


SETTINGS = {**proof.SETTINGS, "FINANCE_INVENTORY_INVOICES": True}


def invoice_fixture(test):
    inventory.inventory_fixture(test)
    test.other_item = ConsumableItem.objects.create(sku="INVOICE-OTHER", name="Other synthetic stock",
        category="Feed", base_unit="kg")


def invoice_request(test, **changes):
    return {**dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        supplier="Synthetic multi-item supplier", invoice_reference="SYNTHETIC-MULTI-1",
        purchase_date=test.period.period_start, total_purchase_cost="150.00", lines=[
            dict(item_id=test.item.pk, location_id=test.location.pk, category_id=test.stock_category.pk,
                quantity="10", total_purchase_cost="100.00"),
            dict(item_id=test.other_item.pk, location_id=test.location.pk, category_id=test.stock_category.pk,
                quantity="5", total_purchase_cost="50.00")]), **changes}


@override_settings(**SETTINGS)
class InventoryInvoiceTests(TestCase):
    def setUp(self):
        invoice_fixture(self)

    def request(self, **changes):
        return invoice_request(self, **changes)

    def capture(self, **changes):
        return record_inventory_invoice(**self.request(**changes))[0]

    def lots(self, result):
        return [SharedConsumableLot.objects.get(pk=child["result"]["lot_id"]) for child in result["children"]]

    def refused(self, action, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception):
            action()
        self.assertEqual(proof.snapshot(), before)

    def issue(self, lot, **changes):
        return record_inventory_issue(**{**inventory.issue(self, lot), **changes})

    def parent(self, result):
        return FinancialCommandReceipt.objects.get(pk=result["invoice_group_id"])

    def assert_balanced(self):
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_two_item_invoice_commits_two_lots_and_payables_without_cash_or_expense(self):
        result, created = record_inventory_invoice(**self.request())
        self.assertTrue(created)
        self.assertEqual(len(result["children"]), 2)
        self.assertEqual((SharedConsumableLot.objects.count(), Expenditure.objects.count(), JournalEntry.objects.count()), (2, 2, 2))
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("150.00"))
        self.assertFalse(FundingAllocation.objects.exists())
        self.assertEqual(FinancialCommandReceipt.objects.count(), 3)
        self.assertEqual(sum(JournalLine.objects.filter(account__code="1200").values_list("debit", flat=True)), Decimal("150.00"))
        self.assertEqual(sum(JournalLine.objects.filter(account__code="2000").values_list("credit", flat=True)), Decimal("150.00"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=["1000", "5000", "6100"]).exists())
        self.assertEqual([lot.invoice_reference for lot in self.lots(result)], ["SYNTHETIC-MULTI-1"] * 2)
        self.assertEqual(InventoryLotBinding.objects.filter(invoice_key__isnull=False).count(), 1)
        self.assert_balanced()

    def test_same_item_multiple_lines_keep_separate_lots_and_one_value_pool(self):
        request = self.request()
        request["lines"][1]["item_id"] = self.item.pk
        result = record_inventory_invoice(**request)[0]
        self.assertEqual(len(self.lots(result)), 2)
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("15"), Decimal("150")))
        self.issue(self.lots(result)[1])
        pool.refresh_from_db()
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("13"), Decimal("130")))

    def test_custom_and_fixed_unit_lines_preserve_original_capture(self):
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=True):
            definition = configure_inventory_unit(submission_id=uuid.uuid4(), user=self.user, item_id=self.item.pk,
                quantity_unit="bag", base_unit="kg", to_base_multiplier="50", reason="Synthetic 50 kg supplier pack.")[0]
            request = self.request()
            request["lines"][0].update(quantity="2", quantity_unit="bag", unit_conversion_id=definition["configuration_id"])
            request["lines"][1].update(quantity="5000", quantity_unit="g")
            result = record_inventory_invoice(**request)[0]
            self.assertEqual([lot.quantity_purchased for lot in self.lots(result)], [Decimal("100"), Decimal("5")])
            self.assertEqual(result["capture"]["lines"][0]["quantity"], "2.0000")
            self.assertEqual(result["children"][0]["result"]["stock_quantity_evidence"]["input_unit"], "bag")
            self.issue(self.lots(result)[0], quantity="5")

    def test_twenty_parent_replays_preserve_all_child_ids_payloads_hashes_and_effects(self):
        request = self.request()
        original = record_inventory_invoice(**request)[0]
        before = proof.snapshot()
        for _ in range(20):
            result, created = record_inventory_invoice(**request)
            self.assertFalse(created)
            self.assertEqual(result, original)
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 3)

    def test_same_parent_id_changed_invoice_or_line_content_has_no_effect(self):
        request = self.request()
        record_inventory_invoice(**request)
        for changes in ({"supplier": "Changed supplier"}, {"invoice_reference": "Changed reference"},
                {"purchase_date": date(2026, 1, 2)}, {"notes": "Different header evidence"},
                {"lines": list(reversed(request["lines"]))}):
            with self.subTest(changes=changes):
                self.refused(lambda: record_inventory_invoice(**{**request, **changes}))
        changed = deepcopy(request["lines"])
        changed[0]["quantity"] = "11"
        self.refused(lambda: record_inventory_invoice(**{**request, "lines": changed}))

    def test_uuid_case_and_exact_decimal_representations_normalize_without_new_effect(self):
        request = self.request()
        original = record_inventory_invoice(**request)[0]
        changed = deepcopy(request["lines"])
        changed[0].update(quantity="10.0000", total_purchase_cost="100.00")
        result, created = record_inventory_invoice(**{**request, "submission_id": str(request["submission_id"]).upper(),
            "lines": changed, "total_purchase_cost": "150"})
        self.assertFalse(created)
        self.assertEqual(result, original)

    def test_different_invoice_same_supplier_keeps_independent_groups(self):
        first = self.capture()
        second = self.capture(invoice_reference="SYNTHETIC-MULTI-2")
        self.assertNotEqual(first["invoice_group_id"], second["invoice_group_id"])
        self.assertEqual(SharedConsumableLot.objects.count(), 4)
        self.issue(self.lots(second)[0])
        self.assert_balanced()

    def test_duplicate_supplier_reference_casefold_requires_review(self):
        self.capture()
        before = proof.snapshot()
        with self.assertRaises(ValidationError) as error:
            self.capture(supplier="synthetic multi-item supplier", invoice_reference="synthetic-multi-1")
        self.assertIn("possible_duplicate", error.exception.detail)
        self.assertEqual(proof.snapshot(), before)

    def test_independent_purchase_and_invoice_cannot_reuse_reference_even_flag_off(self):
        request = self.request()
        with transaction.atomic():
            record_inventory_purchase(**{**inventory.purchase(self), "supplier": request["supplier"],
                "invoice_reference": request["invoice_reference"]})
            self.refused(lambda: record_inventory_invoice(**request))
            transaction.set_rollback(True)
        record_inventory_invoice(**request)
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            self.refused(lambda: record_inventory_purchase(**{**inventory.purchase(self), "supplier": request["supplier"],
                "invoice_reference": request["invoice_reference"]}))

    def test_preexisting_deterministic_child_is_not_adopted(self):
        request = self.request()
        record_inventory_purchase(**{**inventory.purchase(self), "submission_id": _child_id(request["submission_id"], 1)})
        self.refused(lambda: record_inventory_invoice(**request))
        self.assertEqual(FinancialCommandReceipt.objects.count(), 1)

    def test_later_invalid_line_rolls_back_every_earlier_stock_payable_gl_receipt(self):
        for changes in ({"quantity_unit": "unsupported-bag"}, {"expiry_date": date(2025, 12, 31)},
                {"category_id": 9223372036854775807}):
            request = self.request()
            request["lines"][1].update(**changes)
            with self.subTest(changes=changes):
                self.refused(lambda: record_inventory_invoice(**request))
        self.assertFalse(FinancialCommandReceipt.objects.exists())
        self.capture()  # A failure never leaks the private construction context.

    def test_missing_gl_account_has_no_partial_invoice(self):
        ChartOfAccount.objects.filter(code="1200").update(is_active=False)
        self.refused(self.capture)

    def test_parent_receipt_insert_failure_rolls_back_all_lines(self):
        create = FinancialCommandReceipt.objects.create
        def interrupted(**kwargs):
            if kwargs["command"] == COMMAND:
                raise RuntimeError("synthetic parent receipt insertion interruption")
            return create(**kwargs)
        with patch("apps.finance.services.financial_capture.FinancialCommandReceipt.objects.create", side_effect=interrupted):
            self.refused(self.capture, RuntimeError)
        self.capture()

    def test_second_child_receipt_failure_has_no_orphan_first_line(self):
        create, calls = FinancialCommandReceipt.objects.create, []
        def interrupted(**kwargs):
            calls.append(kwargs["submission_id"])
            if len(calls) == 2:
                raise RuntimeError("synthetic second child insertion interruption")
            return create(**kwargs)
        with patch("apps.finance.services.financial_capture.FinancialCommandReceipt.objects.create", side_effect=interrupted):
            self.refused(self.capture, RuntimeError)
        self.assertEqual(len(calls), 2)

    def test_closed_period_refuses_original_invoice_date(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        request = self.request()
        self.refused(lambda: record_inventory_invoice(**request))
        self.assertEqual(request["purchase_date"], date(2026, 1, 1))

    def test_current_six_role_matrix_for_unpaid_capture(self):
        for slug in RoleChoices.values:
            with self.subTest(role=slug), transaction.atomic():
                actor = get_user_model().objects.create_user(username="invoice-" + slug,
                    email="invoice-" + slug + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=slug, defaults={"name": slug})[0])
                if slug in {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR}:
                    self.capture(user=actor)
                else:
                    self.refused(lambda: self.capture(user=actor), PermissionDenied)
                transaction.set_rollback(True)

    def test_stale_cached_active_user_is_rejected(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(self.capture, PermissionDenied)

    def test_invalid_header_line_types_money_or_implicit_apportionment_have_no_effect(self):
        for changes in ({"supplier": ""}, {"invoice_reference": ""}, {"currency": "USD"},
                {"total_purchase_cost": "149.99"}, {"total_purchase_cost": 150.0},
                {"total_purchase_cost": "NaN"}, {"purchase_date": "2099-01-01"}, {"submission_id": "invalid"}):
            with self.subTest(changes=changes):
                self.refused(lambda: self.capture(**changes))
        for changes in ({"quantity": 1.5}, {"total_purchase_cost": "100.001"}, {"item_id": True},
                {"funding_allocations": []}, {"journal_lines": []}, {"supplier": "hidden override"}):
            request = self.request()
            request["lines"][0].update(**changes)
            with self.subTest(changes=changes):
                self.refused(lambda: record_inventory_invoice(**request))

    def test_line_count_and_strict_object_limits(self):
        line = self.request()["lines"][0]
        for rows in ([], [line], [line] * 51, "not lines", [line, None]):
            with self.subTest(rows=type(rows).__name__):
                self.refused(lambda: self.capture(lines=rows))

    def test_fifty_distinct_lines_have_exact_total_and_no_extra_cash_expense(self):
        rows = []
        for position in range(50):
            item = ConsumableItem.objects.create(sku="LIMIT-" + str(position), name="Synthetic limit item " + str(position),
                category="Feed", base_unit="kg")
            rows.append(dict(item_id=item.pk, location_id=self.location.pk, category_id=self.stock_category.pk,
                quantity="1", total_purchase_cost="0.10"))
        result = self.capture(lines=rows, total_purchase_cost="5.00")
        self.assertEqual(len(result["children"]), 50)
        self.assertEqual((SharedConsumableLot.objects.count(), Expenditure.objects.count(), JournalEntry.objects.count()), (50, 50, 50))
        self.assertEqual(FinancialCommandReceipt.objects.count(), 51)
        self.assertFalse(FundingAllocation.objects.exists())
        self.assert_balanced()

    def test_flag_off_new_capture_does_not_query_receipt_schema(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                self.capture()

    def test_flag_off_preserves_original_invoice_and_allows_proved_base_issue(self):
        result = self.capture()
        original = deepcopy(self.parent(result).result)
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            self.issue(self.lots(result)[1])
            self.refused(self.capture)
        self.assertEqual(self.parent(result).result, original)

    def test_later_payment_after_original_period_close_changes_cash_not_purchase_expense(self):
        result = self.capture()
        source = inventory.InventoryCaptureTests.funded_source(self)
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        lot = self.lots(result)[1]
        request = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=InventoryLotBinding.objects.get(lot=lot).expenditure_id, payment_date=date(2026, 2, 2),
            funding_allocations=[{"funding_source": source.pk, "amount": "50.00"}])
        record_financial_supplier_payment(**request)
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**request)[1])
        self.assertEqual(Expenditure.objects.count(), 2)
        self.assertEqual(FundingAllocation.objects.count(), 1)
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("150"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=["5000", "6100"]).exists())
        self.assert_balanced()

    def test_missing_parent_blocks_stock_and_payment_without_erasing_work(self):
        result = self.capture()
        source = inventory.InventoryCaptureTests.funded_source(self)
        lot = self.lots(result)[1]
        proof.erase_receipt(self.parent(result))
        self.refused(lambda: self.issue(lot))
        self.refused(lambda: record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=InventoryLotBinding.objects.get(lot=lot).expenditure_id, payment_date=date(2026, 1, 12),
            funding_allocations=[{"funding_source": source.pk, "amount": "50"}]))

    def test_missing_sibling_receipt_blocks_other_items_new_effect(self):
        result = self.capture()
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=result["children"][0]["operation_id"]))
        self.refused(lambda: self.issue(self.lots(result)[1]))

    def test_parent_result_hash_completion_command_damage_requires_whole_invoice_review(self):
        result = self.capture()
        parent = self.parent(result)
        for changes in ({"invoice_version": "0" * 64}, {"invoice_anchor": "0" * 64},
                {"children": list(reversed(result["children"]))}, {"capture": {**result["capture"], "total_purchase_cost": "500.00"}}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, parent.pk, result=json.dumps({**result, **changes}))
                self.refused(lambda: self.issue(self.lots(result)[1]))
                transaction.set_rollback(True)
        for changes in ({"request_hash": "0" * 64}, {"completed_at": None}, {"command": "inventory.unknown"}, {"result": json.dumps("bad")}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, parent.pk, **changes)
                self.refused(lambda: self.issue(self.lots(result)[0]))
                transaction.set_rollback(True)

    def test_ambiguous_parent_reference_is_not_repaired_or_adopted(self):
        result = self.capture()
        parent = self.parent(result)
        FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), command=COMMAND, actor=self.user,
            request_hash=parent.request_hash, result=result, completed_at=parent.completed_at)
        self.refused(lambda: self.issue(self.lots(result)[0]))

    def test_sibling_wrong_but_balanced_journal_blocks_untouched_items_stock(self):
        result = self.capture()
        journal = JournalEntry.objects.get(pk=result["children"][0]["result"]["journal_id"])
        line = journal.lines.get(account__code="1200")
        corrupt_inventory(JournalLine, line.pk, account_id=ChartOfAccount.objects.get(code="6100").pk)
        self.refused(lambda: self.issue(self.lots(result)[1]))

    def test_changed_first_invoice_key_or_sibling_key_blocks_entire_group(self):
        result = self.capture()
        for position, key in ((0, None), (1, "f" * 64)):
            with self.subTest(position=position), transaction.atomic():
                binding = InventoryLotBinding.objects.get(lot=self.lots(result)[position])
                corrupt_inventory(InventoryLotBinding, binding.pk, invoice_key=key)
                self.refused(lambda: self.issue(self.lots(result)[1 - position]))
                transaction.set_rollback(True)

    def test_reanchored_wrong_invoice_total_or_line_cannot_match_child_evidence(self):
        result = self.capture()
        parent = self.parent(result)
        for mutate in (lambda row: row["capture"].update(total_purchase_cost="500.00"),
                lambda row: row["capture"]["lines"][0].update(quantity="11.0000")):
            with transaction.atomic():
                damaged = deepcopy(result)
                mutate(damaged)
                from apps.mobile_sync.projections import checksum
                request_hash = checksum({"actor": str(parent.actor_id), "command": COMMAND, "payload": damaged["capture"]})
                damaged["invoice_version"] = _version(damaged)
                damaged["invoice_anchor"] = _anchor(damaged, parent.pk, parent.actor_id, request_hash)
                corrupt_inventory(FinancialCommandReceipt, parent.pk, request_hash=request_hash, result=json.dumps(damaged))
                self.refused(lambda: self.issue(self.lots(result)[1]))
                transaction.set_rollback(True)

    def test_reanchored_child_cannot_discard_original_invoice_membership(self):
        result = self.capture()
        child = FinancialCommandReceipt.objects.get(pk=result["children"][1]["operation_id"])
        damaged = {key: value for key, value in child.result.items() if key not in {"invoice_group_id", "invoice_line_index"}}
        damaged["payable_anchor"] = payable_anchor(damaged, submission_id=child.pk, command=child.command,
            actor_id=child.actor_id, request_hash=child.request_hash)
        corrupt_inventory(FinancialCommandReceipt, child.pk, result=json.dumps(damaged))
        self.refused(lambda: self.issue(self.lots(result)[1]))

    def test_return_after_issue_keeps_original_group_source_proof(self):
        result = self.capture()
        lot = self.lots(result)[0]
        usage = self.issue(lot)[0]
        original = StockMovement.objects.get(usage=usage)
        record_inventory_return(**{**corrections.returned(self, original), "quantity": "1"})
        self.issue(lot, usage_date=date(2026, 1, 13), quantity="1")
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal("8"), Decimal("80")))
        self.assert_balanced()

    def test_child_operation_cannot_be_replayed_as_an_independent_purchase(self):
        request = self.request()
        result = record_inventory_invoice(**request)[0]
        row = request["lines"][1]
        self.refused(lambda: record_inventory_purchase(submission_id=result["children"][1]["operation_id"],
            user=self.user, currency="MWK", supplier=request["supplier"], invoice_reference=request["invoice_reference"],
            purchase_date=request["purchase_date"], **row))


@override_settings(**SETTINGS)
class InventoryInvoiceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        invoice_fixture(self)

    def test_same_parent_intent_race_commits_one_invoice_with_two_lines(self):
        request = invoice_request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice(**request)] * 2), [True, False])
        self.assertEqual((SharedConsumableLot.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (2, 2, 3))

    def test_competing_parent_ids_same_invoice_accept_only_one_whole_group(self):
        first, second = invoice_request(self), invoice_request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice(**first),
            lambda: record_inventory_invoice(**second)]), [True, "rejected"])
        self.assertEqual((SharedConsumableLot.objects.count(), Expenditure.objects.count(), JournalEntry.objects.count()), (2, 2, 2))

    def test_group_and_single_purchase_compete_for_same_supplier_reference(self):
        group = invoice_request(self)
        single = {**inventory.purchase(self), "supplier": group["supplier"],
            "invoice_reference": group["invoice_reference"], "purchase_date": group["purchase_date"]}
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice(**group),
            lambda: record_inventory_purchase(**single)]), [True, "rejected"])
        self.assertIn(SharedConsumableLot.objects.count(), [1, 2])

    def test_different_invoices_with_reversed_item_order_use_sorted_locks(self):
        first = invoice_request(self)
        second = invoice_request(self, invoice_reference="SYNTHETIC-MULTI-2", lines=list(reversed(first["lines"])))
        self.assertEqual(proof.race(self, [lambda: record_inventory_invoice(**first),
            lambda: record_inventory_invoice(**second)]), [True, True])
        self.assertEqual((SharedConsumableLot.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (4, 4, 6))
