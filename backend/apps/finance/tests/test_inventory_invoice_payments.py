"""Atomic explicit invoice settlements on newly owned PostgreSQL databases."""
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
from apps.finance.models import (AccountingPeriod, ChartOfAccount, Expenditure, FinancialCommandReceipt,
    FundingAllocation, FundingSource, FundingSourceType, JournalEntry, JournalLine, PeriodStatus, SharedConsumableLot)
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_capture import record_inventory_issue
from apps.finance.services.inventory_invoices import record_inventory_invoice
from apps.finance.services.inventory_invoice_payments import COMMAND, _child_id, record_inventory_invoice_payment
from apps.finance.services.ledger import trial_balance
from . import test_inventory_capture as inventory
from . import test_inventory_invoices as invoices
from . import test_inventory_purchase_proof as proof
from . import test_expenditure_drafts as drafts
from .inventory_corruption import corrupt_inventory


def setup(test):
    invoices.invoice_fixture(test)
    test.invoice = record_inventory_invoice(**invoices.invoice_request(test))[0]
    test.source = inventory.InventoryCaptureTests.funded_source(test)


def request(test, **changes):
    return {**dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        invoice_group_id=test.invoice["invoice_group_id"], invoice_version=test.invoice["invoice_version"],
        payment_date=date(2026, 1, 12), total_payment_amount="75.00", lines=[
            dict(invoice_line_index=0, amount="50.00", funding_allocations=[dict(funding_source=test.source.pk, amount="50.00")]),
            dict(invoice_line_index=1, amount="25.00", funding_allocations=[dict(funding_source=test.source.pk, amount="25.00")])]), **changes}


@override_settings(**invoices.SETTINGS)
class InventoryInvoicePaymentTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, capture=None, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception):
            record_inventory_invoice_payment(**(capture or request(self)))
        self.assertEqual(proof.snapshot(), before)

    def expenditure(self, index):
        return Expenditure.objects.get(pk=self.invoice["children"][index]["result"]["expenditure_id"])

    def assert_balanced(self):
        totals = trial_balance()
        self.assertEqual(totals["debits"], totals["credits"])

    def test_atomic_two_line_partial_payment_clears_ap_and_cash_without_extra_expense_stock(self):
        original = deepcopy(FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"]).result)
        before_journals = JournalEntry.objects.count()
        result, created = record_inventory_invoice_payment(**request(self))
        self.assertTrue(created)
        self.assertEqual((FundingAllocation.objects.count(), JournalEntry.objects.count() - before_journals), (2, 2))
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("75"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("125"))
        self.assertEqual([self.expenditure(i).payment_status for i in (0, 1)], ["partial", "partial"])
        self.assertEqual((Expenditure.objects.count(), SharedConsumableLot.objects.count()), (2, 2))
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("150"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=["5000", "6100"]).exists())
        self.assertEqual(len(result["settlements"]), 2)
        for settlement in result["settlements"]:
            self.assertEqual(len(settlement["effects"]), 1)
            self.assertEqual(len(settlement["effects"][0]["journal_lines"]), 2)
            self.assertEqual(settlement["receipt"]["result"]["expenditure_id"],
                str(self.expenditure(settlement["invoice_line_index"]).pk))
        self.assertEqual(FinancialCommandReceipt.objects.filter(command=COMMAND).count(), 1)
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"]).result, original)
        self.assert_balanced()

    def test_twenty_lost_response_replays_retain_exact_original_ids_hashes_and_effects(self):
        capture = request(self)
        result, _ = record_inventory_invoice_payment(**capture)
        before = proof.snapshot()
        for _ in range(20):
            replay, created = record_inventory_invoice_payment(**capture)
            self.assertFalse(created)
            self.assertEqual(replay, result)
        self.assertEqual(proof.snapshot(), before)

    def test_full_settlement_after_partial_uses_only_remaining_line_balances(self):
        record_inventory_invoice_payment(**request(self))
        record_inventory_invoice_payment(**request(self))
        self.assertEqual([self.expenditure(i).payment_status for i in (0, 1)], ["paid", "paid"])
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50"))
        self.refused()
        self.assert_balanced()

    def test_single_selected_line_does_not_pay_unselected_sibling(self):
        capture = request(self)
        capture.update(total_payment_amount="25", lines=capture["lines"][1:])
        result, _ = record_inventory_invoice_payment(**capture)
        self.assertEqual([self.expenditure(i).payment_status for i in (0, 1)], ["unpaid", "partial"])
        self.assertEqual([entry["invoice_line_index"] for entry in result["settlements"]], [1])

    def test_multiple_sources_per_line_are_explicit_and_original_splits_retained(self):
        other = inventory.InventoryCaptureTests.funded_source(self)
        capture = request(self)
        capture["lines"][0]["funding_allocations"] = [dict(funding_source=self.source.pk, amount="30.00"),
            dict(funding_source=other.pk, amount="20.00")]
        result, _ = record_inventory_invoice_payment(**capture)
        self.assertEqual(FundingAllocation.objects.count(), 3)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("145"))
        self.assertEqual(dated_source_cash(other, date(2026, 1, 12)), Decimal("180"))
        self.assertEqual(len(result["settlements"][0]["effects"]), 2)
        self.assert_balanced()

    def test_fifty_line_boundary_settles_exact_small_amounts_without_header_journal(self):
        invoice_request = invoices.invoice_request(self, invoice_reference="SYNTHETIC-FIFTY-PAY", total_purchase_cost="5")
        invoice_request["lines"] = [dict(invoice_request["lines"][0], total_purchase_cost="0.10", quantity="0.01") for _ in range(50)]
        invoice = record_inventory_invoice(**invoice_request)[0]
        capture = request(self, invoice_group_id=invoice["invoice_group_id"], invoice_version=invoice["invoice_version"],
            total_payment_amount="2.50", lines=[dict(invoice_line_index=index, amount="0.05",
                funding_allocations=[dict(funding_source=self.source.pk, amount="0.05")]) for index in range(50)])
        before_journals = JournalEntry.objects.count()
        result, _ = record_inventory_invoice_payment(**capture)
        self.assertEqual((len(result["settlements"]), FundingAllocation.objects.count(),
            JournalEntry.objects.count() - before_journals), (50, 50, 50))
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("2.50"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("197.50"))
        self.assert_balanced()

    def test_two_batch_funding_aliases_cannot_double_spend_one_cash_pool(self):
        source = drafts.funded_source(self, "75")
        alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch,
            description="Synthetic label, NOT additional cash")
        capture = request(self, payment_date=date(2026, 1, 20), total_payment_amount="100")
        for line, selected, amount in zip(capture["lines"], (source, alias), ("60", "40")):
            line.update(amount=amount, funding_allocations=[dict(funding_source=selected.pk, amount=amount)])
        self.refused(capture)

    def test_all_four_finance_write_roles_can_use_non_owner_confirmed_cash(self):
        source = drafts.funded_source(self, "200")
        for role in (RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR):
            with self.subTest(role=role), transaction.atomic():
                actor = get_user_model().objects.create_user(username="invoice-non-owner-" + role,
                    email="non-owner-" + role + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=role, defaults={"name": role})[0])
                capture = request(self, user=actor, payment_date=date(2026, 1, 20))
                for line in capture["lines"]:
                    line["funding_allocations"][0]["funding_source"] = source.pk
                self.assertTrue(record_inventory_invoice_payment(**capture)[1])
                transaction.set_rollback(True)

    def test_changed_amount_date_source_line_order_note_or_invoice_cannot_replay(self):
        capture = request(self)
        record_inventory_invoice_payment(**capture)
        changed_amount = deepcopy(capture)
        changed_amount.update(total_payment_amount="76")
        changed_amount["lines"][0].update(amount="51", funding_allocations=[dict(funding_source=self.source.pk, amount="51")])
        changed_source = deepcopy(capture)
        changed_source["lines"][0]["funding_allocations"][0]["funding_source"] = 9223372036854775807
        for change in (changed_amount, changed_source, {**capture, "payment_date": date(2026, 1, 13)},
                {**capture, "lines": list(reversed(capture["lines"]))}, {**capture, "notes": "Changed evidence"},
                {**capture, "invoice_group_id": uuid.uuid4()}, {**capture, "invoice_version": "0" * 64}):
            with self.subTest(change=change):
                self.refused(change)

    def test_exact_decimal_representations_uuid_case_and_string_source_ids_replay(self):
        capture = request(self)
        result, _ = record_inventory_invoice_payment(**capture)
        retry = deepcopy(capture)
        retry.update(submission_id=str(capture["submission_id"]).upper(),
            invoice_group_id=capture["invoice_group_id"].upper(), total_payment_amount="75.0")
        for line in retry["lines"]:
            line["amount"] = line["amount"].replace(".00", ".0")
            line["funding_allocations"][0]["funding_source"] = str(self.source.pk)
        self.assertEqual(record_inventory_invoice_payment(**retry), (result, False))

    def test_current_payment_after_original_purchase_period_close_is_allowed(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        record_inventory_invoice_payment(**request(self, payment_date=date(2026, 2, 2)))
        self.assertEqual(set(FundingAllocation.objects.values_list("allocation_date", flat=True)), {date(2026, 2, 2)})
        self.assertEqual(set(Expenditure.objects.values_list("expenditure_date", flat=True)), {date(2026, 1, 1)})

    def test_closed_actual_payment_period_refuses_and_does_not_move_date(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        self.refused()

    def test_before_purchase_or_before_confirmed_cash_date_refuses(self):
        self.refused(request(self, payment_date=date(2026, 1, 1)))
        AccountingPeriod.objects.create(period_start=date(2025, 12, 1), period_end=date(2025, 12, 31))
        self.refused(request(self, payment_date=date(2025, 12, 31)))

    def test_later_line_overpayment_rolls_back_prior_line(self):
        capture = request(self)
        capture.update(total_payment_amount="101.00")
        capture["lines"][1].update(amount="51.00", funding_allocations=[dict(funding_source=self.source.pk, amount="51.00")])
        self.refused(capture)

    def test_combined_cash_limit_refuses_even_if_each_line_fits_separately(self):
        # Existing valid consumption leaves 60: each 50 fits, both do not.
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.expenditure(0).pk, payment_date=date(2026, 1, 12),
            funding_allocations=[dict(funding_source=self.source.pk, amount="90")])
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.expenditure(1).pk, payment_date=date(2026, 1, 12),
            funding_allocations=[dict(funding_source=self.source.pk, amount="50")])
        # A different original invoice has two 100 payables.
        capture_invoice = invoices.invoice_request(self, invoice_reference="SYNTHETIC-CASH-LIMIT", total_purchase_cost="200")
        for line in capture_invoice["lines"]:
            line["total_purchase_cost"] = "100"
        other = record_inventory_invoice(**capture_invoice)[0]
        capture = request(self, invoice_group_id=other["invoice_group_id"], invoice_version=other["invoice_version"], total_payment_amount="100")
        for line in capture["lines"]:
            line.update(amount="50", funding_allocations=[dict(funding_source=self.source.pk, amount="50")])
        self.refused(capture)

    def test_missing_inactive_source_or_damaged_incoming_cash_refuses(self):
        capture = request(self)
        capture["lines"][1]["funding_allocations"][0]["funding_source"] = 9223372036854775807
        self.refused(capture)
        with transaction.atomic():
            self.source.is_active = False
            self.source.save(update_fields=["is_active"])
            self.refused()
            transaction.set_rollback(True)
        receipt = FinancialCommandReceipt.objects.get(command="finance.owner_contribution.record")
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, request_hash="0" * 64)
        self.refused()

    def test_missing_version_changed_or_ambiguous_original_invoice_refuses(self):
        parent = FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"])
        for change in ({"invoice_version": "0" * 64}, {"invoice_anchor": "0" * 64}, {"children": []}):
            with self.subTest(change=change), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, parent.pk, result=json.dumps({**parent.result, **change}))
                self.refused()
                transaction.set_rollback(True)
        with transaction.atomic():
            FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), actor=self.user, command=parent.command,
                request_hash=parent.request_hash, result=parent.result, completed_at=parent.completed_at)
            self.refused()
            transaction.set_rollback(True)
        proof.erase_receipt(parent)
        self.refused()

    def test_missing_unselected_sibling_receipt_blocks_selected_line(self):
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=self.invoice["children"][1]["operation_id"]))
        capture = request(self)
        capture.update(total_payment_amount="50", lines=capture["lines"][:1])
        self.refused(capture)

    def test_wrong_balanced_unselected_purchase_gl_refuses_whole_invoice(self):
        journal = JournalEntry.objects.get(pk=self.invoice["children"][1]["result"]["journal_id"])
        corrupt_inventory(JournalLine, journal.lines.get(debit__gt=0).pk, account=ChartOfAccount.objects.get(code="6100").pk)
        self.assert_balanced()
        capture = request(self)
        capture.update(total_payment_amount="50", lines=capture["lines"][:1])
        self.refused(capture)

    def test_missing_second_payment_account_rolls_back_first_payment(self):
        from apps.finance.services import expenditures
        original = expenditures.post_journal
        count = 0
        def interrupted(**kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise ValidationError({"journal": "Synthetic second-line posting failure."})
            return original(**kwargs)
        with patch.object(expenditures, "post_journal", side_effect=interrupted):
            self.refused()

    def test_interrupted_parent_receipt_insert_rolls_back_all_cash_and_children(self):
        original = FinancialCommandReceipt.objects.create
        def interrupted(**kwargs):
            if kwargs.get("command") == COMMAND:
                raise RuntimeError("Synthetic parent receipt crash")
            return original(**kwargs)
        with patch.object(FinancialCommandReceipt.objects, "create", side_effect=interrupted):
            self.refused(exception=RuntimeError)

    def test_interrupted_second_child_receipt_rolls_back_first_child_and_all_funding(self):
        original = FinancialCommandReceipt.objects.create
        count = 0
        def interrupted(**kwargs):
            nonlocal count
            if kwargs.get("command") == "finance.expenditure.pay":
                count += 1
                if count == 2:
                    raise RuntimeError("Synthetic second child receipt crash")
            return original(**kwargs)
        with patch.object(FinancialCommandReceipt.objects, "create", side_effect=interrupted):
            self.refused(exception=RuntimeError)

    def test_preexisting_deterministic_child_is_never_adopted(self):
        capture = request(self)
        record_financial_supplier_payment(submission_id=_child_id(capture["submission_id"], 0), user=self.user, currency="MWK",
            expenditure_id=self.expenditure(0).pk, payment_date=capture["payment_date"],
            funding_allocations=capture["lines"][0]["funding_allocations"])
        self.refused(capture)

    def test_missing_accepted_parent_refuses_retry_instead_of_recreating_header(self):
        capture = request(self)
        record_inventory_invoice_payment(**capture)
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=capture["submission_id"]))
        self.refused(capture)

    def test_replay_remains_read_only_after_purchase_changes_and_payment_period_close(self):
        capture = request(self)
        result, _ = record_inventory_invoice_payment(**capture)
        lot = SharedConsumableLot.objects.get(pk=self.invoice["children"][0]["result"]["lot_id"])
        record_inventory_issue(**inventory.issue(self, lot))
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        before = proof.snapshot()
        self.assertEqual(record_inventory_invoice_payment(**capture), (result, False))
        self.assertEqual(proof.snapshot(), before)

    def test_flag_off_refuses_new_header_with_zero_queries_and_keeps_existing_per_line_service(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            with self.assertNumQueries(0), self.assertRaises(ValidationError):
                record_inventory_invoice_payment(**request(self))
            record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                expenditure_id=self.expenditure(0).pk, payment_date=date(2026, 1, 12),
                funding_allocations=[dict(funding_source=self.source.pk, amount="10")])
        self.assertEqual(FundingAllocation.objects.count(), 1)

    def test_invalid_inputs_never_create_partial_payment_or_guess_allocations(self):
        base = request(self)
        invalid = [{**base, field: value} for field, values in {
            "submission_id": [None, "bad"], "invoice_group_id": [None, "bad"],
            "invoice_version": [None, "bad"], "currency": ["USD"], "payment_date": ["bad", date(2099, 1, 1)],
            "total_payment_amount": [75.0, True, "75.001", "NaN", "0", "76"],
            "lines": [[], None, {}, [None], base["lines"] * 26], "notes": [None, "x" * 4001],
        }.items() for value in values]
        for index in (True, "0", 0.5, -1, 2, 50):
            value = deepcopy(base)
            value["lines"][0]["invoice_line_index"] = index
            invalid.append(value)
        for field, value in (("amount", "49"), ("amount", 50.0), ("funding_allocations", []),
                ("funding_allocations", [dict(funding_source=self.source.pk, amount="50", journal_lines=[])]),
                ("expenditure_id", self.expenditure(0).pk), ("paid", True)):
            capture = deepcopy(base)
            capture["lines"][0][field] = value
            invalid.append(capture)
        duplicate = deepcopy(base)
        duplicate["lines"][1]["invoice_line_index"] = 0
        invalid.append(duplicate)
        for capture in invalid:
            with self.subTest(capture=capture):
                self.refused(capture)

    def test_current_role_and_owner_cash_permission_not_cached_authority(self):
        for role in RoleChoices.values:
            with self.subTest(role=role), transaction.atomic():
                actor = get_user_model().objects.create_user(username="invoice-pay-" + role, email=role + "@synthetic.invalid",
                    password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=role, defaults={"name": role})[0])
                if role in {RoleChoices.ADMIN, RoleChoices.DIRECTOR}:
                    self.assertTrue(record_inventory_invoice_payment(**request(self, user=actor))[1])
                else:
                    self.refused(request(self, user=actor), exception=PermissionDenied)
                transaction.set_rollback(True)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(exception=PermissionDenied)


@override_settings(**invoices.SETTINGS)
class InventoryInvoicePaymentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_same_parent_race_posts_one_payment_composite(self):
        capture = request(self)
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_payment(**capture)] * 2), [True, False])
        self.assertEqual((FundingAllocation.objects.count(), FinancialCommandReceipt.objects.filter(command=COMMAND).count()), (2, 1))

    def test_competing_full_invoice_payments_cannot_overpay_last_balances(self):
        first, second = request(self, total_payment_amount="150"), request(self, total_payment_amount="150")
        for capture in (first, second):
            for line, amount in zip(capture["lines"], ("100", "50")):
                line.update(amount=amount, funding_allocations=[dict(funding_source=self.source.pk, amount=amount)])
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_payment(**first),
            lambda: record_inventory_invoice_payment(**second)]), [True, "rejected"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_composite_and_standalone_compete_for_same_last_payable(self):
        capture = request(self, total_payment_amount="100")
        capture["lines"] = [dict(invoice_line_index=0, amount="100",
            funding_allocations=[dict(funding_source=self.source.pk, amount="100")])]
        standalone = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.invoice["children"][0]["result"]["expenditure_id"], payment_date=date(2026, 1, 12),
            funding_allocations=capture["lines"][0]["funding_allocations"])
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_payment(**capture),
            lambda: record_financial_supplier_payment(**standalone)]), [True, "rejected"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("100"))

    def test_different_invoice_composites_compete_for_shared_last_cash(self):
        other = record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-OTHER-CASH"))[0]
        first, second = request(self, total_payment_amount="150"), request(self,
            invoice_group_id=other["invoice_group_id"], invoice_version=other["invoice_version"], total_payment_amount="150")
        for capture in (first, second):
            for line, amount in zip(capture["lines"], ("100", "50")):
                line.update(amount=amount, funding_allocations=[dict(funding_source=self.source.pk, amount=amount)])
        self.assertCountEqual(proof.race(self, [lambda: record_inventory_invoice_payment(**first),
            lambda: record_inventory_invoice_payment(**second)]), [True, "rejected"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_reversed_line_order_distinct_partial_payments_commit_without_inverted_locks(self):
        first, second = request(self), request(self)
        second["lines"].reverse()
        self.assertEqual(proof.race(self, [lambda: record_inventory_invoice_payment(**first),
            lambda: record_inventory_invoice_payment(**second)]), [True, True])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_independent_planned_child_race_never_adopts_effect_or_deadlocks(self):
        capture = request(self)
        standalone = dict(submission_id=_child_id(capture["submission_id"], 0), user=self.user, currency="MWK",
            expenditure_id=self.invoice["children"][0]["result"]["expenditure_id"], payment_date=capture["payment_date"],
            funding_allocations=capture["lines"][0]["funding_allocations"])
        result = proof.race(self, [lambda: record_inventory_invoice_payment(**capture),
            lambda: record_financial_supplier_payment(**standalone)])
        if sorted(str(value) for value in result) == ["False", "True"]:
            self.assertEqual(FundingAllocation.objects.count(), 2)
            self.assertEqual(FinancialCommandReceipt.objects.filter(command=COMMAND).count(), 1)
        else:
            self.assertCountEqual(result, [True, "rejected"])
            self.assertEqual(FundingAllocation.objects.count(), 1)
            self.assertFalse(FinancialCommandReceipt.objects.filter(command=COMMAND).exists())
