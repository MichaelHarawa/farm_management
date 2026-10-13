"""New invoice plus initial payment on owned disposable PostgreSQL only."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (AccountingPeriod, Expenditure, FinancialCommandReceipt, FundingAllocation,
    FundingSource, FundingSourceType, InventoryLotBinding, JournalEntry, JournalLine, PeriodStatus, SharedConsumableLot, StockMovement)
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_capture import record_inventory_issue, record_inventory_purchase
from apps.finance.services.inventory_invoices import record_inventory_invoice
from apps.finance.services.inventory_conversion_setup import configure_inventory_unit
from apps.finance.services.inventory_invoice_payments import record_inventory_invoice_payment
from apps.finance.services.inventory_invoice_composites import (COMMAND, _invoice_id, _payment_id,
    record_inventory_invoice_with_payment)
from apps.finance.services.ledger import trial_balance
from . import test_inventory_capture as inventory
from . import test_inventory_invoices as invoices
from . import test_inventory_purchase_proof as proof
from . import test_expenditure_drafts as drafts


def setup(test):
    invoices.invoice_fixture(test)
    test.source = inventory.InventoryCaptureTests.funded_source(test)


def request(test, **changes):
    invoice = invoices.invoice_request(test)
    return {**invoice, "initial_payment": dict(payment_date=date(2026, 1, 12), total_payment_amount="75.00", lines=[
        dict(invoice_line_index=0, amount="50.00", funding_allocations=[dict(funding_source=test.source.pk, amount="50.00")]),
        dict(invoice_line_index=1, amount="25.00", funding_allocations=[dict(funding_source=test.source.pk, amount="25.00")])]), **changes}


def full(capture):
    capture = deepcopy(capture)
    capture["initial_payment"]["total_payment_amount"] = "150.00"
    for line, amount in zip(capture["initial_payment"]["lines"], ("100.00", "50.00")):
        line["amount"] = amount
        line["funding_allocations"][0]["amount"] = amount
    return capture


@override_settings(**invoices.SETTINGS)
class InventoryInvoiceCompositeTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, capture=None, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception):
            record_inventory_invoice_with_payment(**(capture or request(self)))
        self.assertEqual(proof.snapshot(), before)

    def test_partial_initial_payment_commits_one_invoice_stock_ap_cash_and_seven_receipts(self):
        before_journals, before_receipts = JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()
        capture = request(self)
        result, created = record_inventory_invoice_with_payment(**capture)
        self.assertTrue(created)
        self.assertEqual((Expenditure.objects.count(), SharedConsumableLot.objects.count(), StockMovement.objects.count()), (2, 2, 2))
        self.assertEqual((FundingAllocation.objects.count(), JournalEntry.objects.count() - before_journals,
            FinancialCommandReceipt.objects.count() - before_receipts), (2, 4, 7))
        self.assertEqual(result["invoice"]["operation_id"], str(_invoice_id(capture["submission_id"])))
        self.assertEqual(result["initial_payment"]["operation_id"], str(_payment_id(capture["submission_id"])))
        self.assertEqual(result["initial_payment"]["result"]["original_invoice"], result["invoice"])
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("150"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("125"))
        self.assertEqual(list(Expenditure.objects.order_by("pk").values_list("payment_status", flat=True)), ["partial", "partial"])
        self.assertFalse(JournalLine.objects.filter(account__code__in=["5000", "6100"]).exists())
        self.assertEqual(InventoryLotBinding.objects.filter(invoice_key__isnull=False).count(), 1)
        self.assertEqual(sum(JournalLine.objects.filter(account__code="1200").values_list("debit", flat=True)), Decimal("150"))
        self.assertEqual(sum(JournalLine.objects.filter(account__code="2000").values_list("debit", flat=True)), Decimal("75"))
        self.assertEqual(sum(JournalLine.objects.filter(account__code="1000").values_list("credit", flat=True)), Decimal("75"))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_full_initial_payment_clears_payables_but_does_not_recognize_expense(self):
        record_inventory_invoice_with_payment(**full(request(self)))
        self.assertEqual(set(Expenditure.objects.values_list("payment_status", flat=True)), {"paid"})
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=["5000", "6100"]).exists())

    def test_custom_pack_and_fixed_units_preserve_original_input_in_composite(self):
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=True):
            definition = configure_inventory_unit(submission_id=uuid.uuid4(), user=self.user, item_id=self.item.pk,
                quantity_unit="bag", base_unit="kg", to_base_multiplier="50", reason="Synthetic 50 kg observed supplier pack")[0]
            capture = request(self)
            capture["lines"][0].update(quantity="2", quantity_unit="bag", unit_conversion_id=definition["configuration_id"])
            capture["lines"][1].update(quantity="5000", quantity_unit="g")
            result, _ = record_inventory_invoice_with_payment(**capture)
            self.assertEqual(list(SharedConsumableLot.objects.order_by("pk").values_list("quantity_purchased", flat=True)),
                [Decimal("100"), Decimal("5")])
            self.assertEqual([line["quantity_unit"] for line in result["capture"]["invoice"]["lines"]], ["bag", "g"])
        self.assertEqual(record_inventory_invoice_with_payment(**capture), (result, False))

    def test_explicit_multiple_source_split_keeps_funding_separate_from_stock_cost(self):
        other = inventory.InventoryCaptureTests.funded_source(self)
        capture = request(self)
        capture["initial_payment"]["lines"][0]["funding_allocations"] = [dict(funding_source=self.source.pk, amount="30"),
            dict(funding_source=other.pk, amount="20")]
        record_inventory_invoice_with_payment(**capture)
        self.assertEqual(FundingAllocation.objects.count(), 3)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("145"))
        self.assertEqual(dated_source_cash(other, date(2026, 1, 12)), Decimal("180"))
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("150"))

    def test_shared_batch_cash_alias_failure_rolls_back_whole_initial_invoice(self):
        source = drafts.funded_source(self, "75")
        alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch,
            description="Synthetic second label, no extra cash")
        capture = request(self)
        capture["initial_payment"].update(payment_date=date(2026, 1, 20), total_payment_amount="100")
        for line, selected, amount in zip(capture["initial_payment"]["lines"], (source, alias), ("60", "40")):
            line.update(amount=amount, funding_allocations=[dict(funding_source=selected.pk, amount=amount)])
        self.refused(capture)
        self.assertFalse(Expenditure.objects.exists())

    def test_initial_payment_for_one_line_keeps_other_line_unpaid(self):
        capture = request(self)
        capture["initial_payment"].update(total_payment_amount="25", lines=capture["initial_payment"]["lines"][1:])
        record_inventory_invoice_with_payment(**capture)
        self.assertEqual(list(Expenditure.objects.order_by("pk").values_list("payment_status", flat=True)), ["unpaid", "partial"])

    def test_twenty_lost_response_retries_keep_exact_outer_and_all_nested_evidence(self):
        capture = request(self)
        result, _ = record_inventory_invoice_with_payment(**capture)
        before = proof.snapshot()
        for _ in range(20):
            self.assertEqual(record_inventory_invoice_with_payment(**capture), (result, False))
        self.assertEqual(proof.snapshot(), before)

    def test_changed_invoice_or_payment_content_cannot_reuse_original_id(self):
        capture = request(self)
        record_inventory_invoice_with_payment(**capture)
        variants = [{**capture, "supplier": "Changed supplier"}, {**capture, "notes": "Changed invoice evidence"},
            {**capture, "invoice_reference": "Changed physical reference"},
            {**capture, "purchase_date": date(2026, 1, 2)}, {**capture, "lines": list(reversed(capture["lines"]))}]
        for changes in ({"payment_date": date(2026, 1, 13)}, {"notes": "Changed payment evidence"},
                {"lines": list(reversed(capture["initial_payment"]["lines"]))}):
            variants.append({**capture, "initial_payment": {**capture["initial_payment"], **changes}})
        source_change = deepcopy(capture)
        source_change["initial_payment"]["lines"][0]["funding_allocations"][0]["funding_source"] = 9223372036854775807
        variants.extend([source_change, full(capture)])
        for value in variants:
            with self.subTest(value=value):
                self.refused(value)

    def test_exact_money_representations_and_uuid_case_replay_same_canonical_intent(self):
        capture = request(self)
        result, _ = record_inventory_invoice_with_payment(**capture)
        retry = deepcopy(capture)
        retry.update(submission_id=str(capture["submission_id"]).upper(), total_purchase_cost="150.0")
        retry["initial_payment"]["total_payment_amount"] = "75.0"
        for line in retry["initial_payment"]["lines"]:
            line["amount"] = line["amount"].replace(".00", ".0")
            line["funding_allocations"][0]["funding_source"] = str(self.source.pk)
        self.assertEqual(record_inventory_invoice_with_payment(**retry), (result, False))

    def test_payment_failure_after_purchase_rolls_back_all_stock_payables_and_receipts(self):
        capture = full(request(self))
        capture["initial_payment"]["total_payment_amount"] = "201"
        capture["initial_payment"]["lines"][1].update(amount="101", funding_allocations=[dict(funding_source=self.source.pk, amount="101")])
        self.refused(capture)
        self.assertFalse(Expenditure.objects.exists())

    def test_second_line_overpayment_rolls_back_first_payment_and_entire_invoice(self):
        capture = request(self)
        capture["initial_payment"].update(total_payment_amount="101")
        capture["initial_payment"]["lines"][1].update(amount="51", funding_allocations=[dict(funding_source=self.source.pk, amount="51")])
        from apps.finance.services import inventory_invoice_payments
        original = inventory_invoice_payments.record_financial_supplier_payment
        with patch.object(inventory_invoice_payments, "record_financial_supplier_payment", wraps=original) as payments:
            self.refused(capture)
            self.assertEqual(payments.call_count, 2)

    def test_later_invalid_purchase_line_leaves_no_invoice_or_initial_payment(self):
        capture = request(self)
        capture["lines"][1]["location_id"] = 9223372036854775807
        self.refused(capture)

    def test_closed_either_actual_period_preserves_both_dates_and_no_effect(self):
        other = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        capture = request(self)
        capture["initial_payment"]["payment_date"] = date(2026, 2, 2)
        for period in (self.period, other):
            with self.subTest(period=period.pk), transaction.atomic():
                period.status = PeriodStatus.CLOSED
                period.save(update_fields=["status"])
                self.refused(capture)
                transaction.set_rollback(True)
        self.assertEqual(capture["purchase_date"], date(2026, 1, 1))
        self.assertEqual(capture["initial_payment"]["payment_date"], date(2026, 2, 2))

    def test_different_open_purchase_and_payment_periods_use_original_dates(self):
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        capture = request(self)
        capture["initial_payment"]["payment_date"] = date(2026, 2, 2)
        record_inventory_invoice_with_payment(**capture)
        self.assertEqual(set(Expenditure.objects.values_list("expenditure_date", flat=True)), {date(2026, 1, 1)})
        self.assertEqual(set(FundingAllocation.objects.values_list("allocation_date", flat=True)), {date(2026, 2, 2)})

    def test_before_purchase_deposit_and_before_confirmed_cash_refuse(self):
        capture = request(self, purchase_date=date(2026, 1, 10))
        capture["initial_payment"]["payment_date"] = date(2026, 1, 9)
        self.refused(capture)
        capture = request(self)
        capture["initial_payment"]["payment_date"] = date(2026, 1, 1)
        self.refused(capture)

    def test_preexisting_planned_unpaid_invoice_is_not_adopted(self):
        capture = request(self)
        invoice = {key: value for key, value in capture.items() if key != "initial_payment"}
        invoice["submission_id"] = _invoice_id(capture["submission_id"])
        record_inventory_invoice(**invoice)
        self.refused(capture)

    def test_preexisting_planned_payment_intent_on_other_payable_is_not_adopted(self):
        capture = request(self)
        invoice = record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-INDEPENDENT"))[0]
        record_financial_supplier_payment(submission_id=_payment_id(capture["submission_id"]), user=self.user,
            currency="MWK", expenditure_id=invoice["children"][0]["result"]["expenditure_id"],
            payment_date=date(2026, 1, 12), funding_allocations=[dict(funding_source=self.source.pk, amount="10")])
        self.refused(capture)

    def test_interrupted_outer_receipt_rolls_back_both_nested_parents_and_all_effects(self):
        original = FinancialCommandReceipt.objects.create
        def interrupted(**kwargs):
            if kwargs.get("command") == COMMAND:
                raise RuntimeError("Synthetic outer receipt interruption")
            return original(**kwargs)
        with patch.object(FinancialCommandReceipt.objects, "create", side_effect=interrupted):
            self.refused(exception=RuntimeError)

    def test_interrupted_payment_parent_rolls_back_new_invoice_and_its_children(self):
        original = FinancialCommandReceipt.objects.create
        def interrupted(**kwargs):
            if kwargs.get("command") == "inventory.invoice.pay":
                raise RuntimeError("Synthetic payment parent interruption")
            return original(**kwargs)
        with patch.object(FinancialCommandReceipt.objects, "create", side_effect=interrupted):
            self.refused(exception=RuntimeError)

    def test_missing_accepted_outer_parent_cannot_recreate_children_or_cash(self):
        capture = request(self)
        record_inventory_invoice_with_payment(**capture)
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=capture["submission_id"]))
        self.refused(capture)

    def test_failed_attempt_can_retry_original_intent_after_payment_problem_is_resolved(self):
        capture = request(self)
        from apps.finance.services import inventory_invoice_composites
        with patch.object(inventory_invoice_composites, "record_inventory_invoice_payment",
                side_effect=ValidationError({"initial_payment": "Synthetic transient payment validation failure"})):
            self.refused(capture)
        self.assertTrue(record_inventory_invoice_with_payment(**capture)[1])
        self.assertEqual(FinancialCommandReceipt.objects.filter(command=COMMAND).count(), 1)

    def test_initial_receipts_remain_exact_after_later_supplier_payment_stock_issue_and_close(self):
        capture = request(self)
        result, _ = record_inventory_invoice_with_payment(**capture)
        invoice = result["invoice"]["result"]
        record_inventory_invoice_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            invoice_group_id=invoice["invoice_group_id"], invoice_version=invoice["invoice_version"],
            **capture["initial_payment"])
        lot = SharedConsumableLot.objects.get(pk=invoice["children"][0]["result"]["lot_id"])
        record_inventory_issue(**inventory.issue(self, lot))
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        before = proof.snapshot()
        self.assertEqual(record_inventory_invoice_with_payment(**capture), (result, False))
        self.assertEqual(proof.snapshot(), before)

    def test_flag_off_refuses_new_composite_before_queries_without_altering_prior_services(self):
        capture = request(self)
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            with self.assertNumQueries(0), self.assertRaises(ValidationError):
                record_inventory_invoice_with_payment(**capture)
        self.assertFalse(Expenditure.objects.exists())

    def test_strict_initial_payment_inputs_no_paid_dropdown_guess_or_supplied_parent(self):
        capture = request(self)
        variants = [{**capture, "initial_payment": value} for value in (None, [], {},
            {**capture["initial_payment"], "paid": True}, {**capture["initial_payment"], "currency": "USD"},
            {**capture["initial_payment"], "invoice_group_id": str(uuid.uuid4())},
            {**capture["initial_payment"], "journal_lines": []},
            {**capture["initial_payment"], "payment_date": "2099-01-01"},
            {**capture["initial_payment"], "total_payment_amount": 75.0},
            {**capture["initial_payment"], "total_payment_amount": "75.001"},
            {**capture["initial_payment"], "total_payment_amount": "76"})]
        for value in (True, "0", -1, 2, 50):
            changed = deepcopy(capture)
            changed["initial_payment"]["lines"][0]["invoice_line_index"] = value
            variants.append(changed)
        for value in variants:
            with self.subTest(value=value):
                self.refused(value)

    def test_current_roles_and_owner_source_restrictions_cover_all_six_roles(self):
        for role in RoleChoices.values:
            with self.subTest(role=role), transaction.atomic():
                actor = get_user_model().objects.create_user(username="initial-invoice-" + role,
                    email="initial-invoice-" + role + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=role, defaults={"name": role})[0])
                if role in {RoleChoices.ADMIN, RoleChoices.DIRECTOR}:
                    self.assertTrue(record_inventory_invoice_with_payment(**request(self, user=actor))[1])
                else:
                    self.refused(request(self, user=actor), exception=PermissionDenied)
                transaction.set_rollback(True)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(exception=PermissionDenied)

    def test_four_finance_write_roles_can_use_non_owner_confirmed_cash(self):
        source = drafts.funded_source(self, "200")
        for role in (RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR):
            with self.subTest(role=role), transaction.atomic():
                actor = get_user_model().objects.create_user(username="initial-invoice-batch-" + role,
                    email="initial-invoice-batch-" + role + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=role, defaults={"name": role})[0])
                capture = request(self, user=actor)
                capture["initial_payment"]["payment_date"] = date(2026, 1, 20)
                for line in capture["initial_payment"]["lines"]:
                    line["funding_allocations"][0]["funding_source"] = source.pk
                self.assertTrue(record_inventory_invoice_with_payment(**capture)[1])
                transaction.set_rollback(True)


@override_settings(**invoices.SETTINGS)
class InventoryInvoiceCompositeConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_same_outer_intent_race_commits_one_complete_initial_invoice(self):
        capture = request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**capture)] * 2), [True, False])
        self.assertEqual((Expenditure.objects.count(), FundingAllocation.objects.count()), (2, 2))

    def test_different_ids_same_supplier_invoice_cannot_duplicate_stock_or_cash(self):
        first, second = request(self), request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**first),
            lambda: record_inventory_invoice_with_payment(**second)]), [True, "rejected"])
        self.assertEqual((Expenditure.objects.count(), FundingAllocation.objects.count()), (2, 2))

    def test_initial_composite_and_unpaid_invoice_share_reference_guard(self):
        capture = request(self)
        unpaid = invoices.invoice_request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**capture),
            lambda: record_inventory_invoice(**unpaid)]), [True, "rejected"])
        self.assertEqual(Expenditure.objects.count(), 2)
        self.assertIn(FundingAllocation.objects.count(), (0, 2))

    def test_initial_composite_and_standalone_purchase_share_reference_guard(self):
        capture = request(self)
        standalone = {**inventory.purchase(self), "supplier": capture["supplier"],
            "invoice_reference": capture["invoice_reference"], "purchase_date": capture["purchase_date"]}
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**capture),
            lambda: record_inventory_purchase(**standalone)]), [True, "rejected"])
        self.assertIn(Expenditure.objects.count(), (1, 2))

    def test_competing_initial_invoices_cannot_spend_same_last_cash(self):
        first = full(request(self))
        second = full(request(self, invoice_reference="SYNTHETIC-OTHER-INITIAL"))
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**first),
            lambda: record_inventory_invoice_with_payment(**second)]), [True, "rejected"])
        self.assertEqual((Expenditure.objects.count(), FundingAllocation.objects.count()), (2, 2))
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_two_initial_invoices_reversed_item_order_commit_with_sufficient_cash(self):
        first = request(self)
        second = request(self, invoice_reference="SYNTHETIC-REVERSED-INITIAL")
        second["lines"].reverse()
        self.assertEqual(proof.race(self, [lambda: record_inventory_invoice_with_payment(**first),
            lambda: record_inventory_invoice_with_payment(**second)]), [True, True])
        self.assertEqual((Expenditure.objects.count(), FundingAllocation.objects.count()), (4, 4))
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_independent_planned_invoice_parent_race_cannot_invert_child_locks_or_adopt(self):
        capture = request(self)
        unpaid = {key: value for key, value in capture.items() if key != "initial_payment"}
        unpaid["submission_id"] = _invoice_id(capture["submission_id"])
        outcomes = proof.race(self, [lambda: record_inventory_invoice_with_payment(**capture),
            lambda: record_inventory_invoice(**unpaid)])
        if sorted(str(value) for value in outcomes) == ["False", "True"]:
            self.assertEqual(FundingAllocation.objects.count(), 2)
            self.assertEqual(FinancialCommandReceipt.objects.filter(command=COMMAND).count(), 1)
        else:
            self.assertCountEqual(outcomes, [True, "rejected"])
            self.assertFalse(FundingAllocation.objects.exists())
            self.assertFalse(FinancialCommandReceipt.objects.filter(command=COMMAND).exists())
        self.assertEqual(Expenditure.objects.count(), 2)
