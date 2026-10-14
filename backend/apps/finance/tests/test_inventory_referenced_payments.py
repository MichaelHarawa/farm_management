"""Observed multi-invoice payments on newly owned PostgreSQL only."""
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
from apps.finance.models import (AccountingPeriod, Expenditure, FinancialCommandReceipt,
    FundingAllocation, FundingSource, FundingSourceType, JournalEntry, JournalLine,
    PeriodStatus, SharedConsumableLot, StockMovement)
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_capture import record_inventory_issue
from apps.finance.services.inventory_invoice_payments import record_inventory_invoice_payment, _child_id
from apps.finance.services.inventory_invoices import record_inventory_invoice
from apps.finance.services import inventory_referenced_payments as payments
from apps.finance.services.ledger import trial_balance
from .inventory_corruption import corrupt_inventory
from . import test_inventory_capture as inventory
from . import test_inventory_invoices as invoices
from . import test_inventory_invoice_payments as settlements
from . import test_inventory_purchase_proof as proof
from . import test_expenditure_drafts as drafts


def setup(test):
    settlements.setup(test)
    test.second = record_inventory_invoice(**invoices.invoice_request(test, invoice_reference="SYNTHETIC-REFERENCE-SECOND"))[0]


def invoice_payment(test, original=None, amounts=("50", "25")):
    original = original or test.invoice
    return dict(invoice_group_id=original["invoice_group_id"], invoice_version=original["invoice_version"],
        total_payment_amount=format(sum(map(Decimal, amounts)), "f"), lines=[dict(invoice_line_index=index, amount=amount,
            funding_allocations=[dict(funding_source=test.source.pk, amount=amount)]) for index, amount in enumerate(amounts)])


def request(test, **changes):
    return {"submission_id": uuid.uuid4(), "user": test.user, "currency": "MWK",
        "payee": "Synthetic multi-item supplier", "payment_method": "bank_transfer",
        "external_reference": "SYNTHETIC-OBSERVED-TRANSFER-001", "payment_date": date(2026, 1, 12),
        "total_payment_amount": "150", "invoices": [invoice_payment(test), invoice_payment(test, test.second)],
        "notes": "Synthetic bank evidence; one actual transfer covers two invoices.", **changes}


@override_settings(**invoices.SETTINGS)
class InventoryReferencedPaymentTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, capture=None, exception=ValidationError):
        before = proof.snapshot()
        with self.assertRaises(exception) as error:
            payments.record_referenced_inventory_payment(**(capture or request(self)))
        self.assertEqual(proof.snapshot(), before)
        return error.exception

    def expense(self, original, index):
        return Expenditure.objects.get(pk=original["children"][index]["result"]["expenditure_id"])

    def test_one_observed_transfer_settles_two_invoices_without_extra_stock_or_expense(self):
        original = proof.snapshot()
        result, created = payments.record_referenced_inventory_payment(**request(self))
        self.assertTrue(created)
        self.assertEqual(len(result["payments"]), 2)
        self.assertEqual((Expenditure.objects.count(), SharedConsumableLot.objects.count(), StockMovement.objects.count()), (4, 4, 4))
        self.assertEqual(FundingAllocation.objects.count(), 4)
        self.assertEqual(JournalEntry.objects.count() - len(original["journalentry"]), 4)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50"))
        self.assertEqual([self.expense(invoice, index).payment_status for invoice in (self.invoice, self.second) for index in (0, 1)], ["partial"] * 4)
        self.assertEqual(sum(SharedConsumableLot.objects.values_list("total_purchase_cost", flat=True)), Decimal("300"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=("5000", "6100")).exists())
        self.assertEqual(FinancialCommandReceipt.objects.count() - len(original["financialcommandreceipt"]), 7)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])
        for row in original["financialcommandreceipt"]:
            self.assertIn(row, proof.snapshot()["financialcommandreceipt"])

    def test_twenty_response_loss_replays_retain_exact_ids_hashes_and_payment_effects(self):
        capture = request(self)
        result, created = payments.record_referenced_inventory_payment(**capture)
        self.assertTrue(created)
        before = proof.snapshot()
        for _ in range(20):
            self.assertEqual(payments.record_referenced_inventory_payment(**capture), (result, False))
        self.assertEqual(proof.snapshot(), before)

    def test_changed_id_same_trim_case_reference_requires_review_not_fake_replay(self):
        payments.record_referenced_inventory_payment(**request(self))
        for reference in ("SYNTHETIC-OBSERVED-TRANSFER-001", "  synthetic-observed-transfer-001  "):
            with self.subTest(reference=reference):
                error = self.refused(request(self, external_reference=reference))
                self.assertIn("possible_duplicate", error.detail)

    def test_changed_method_date_amount_supplier_or_invoice_cannot_bypass_same_reference(self):
        payments.record_referenced_inventory_payment(**request(self))
        other = record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-REF-OTHER",
            supplier="Another actual synthetic supplier"))[0]
        for changes in ({"payment_method": "cash"}, {"payment_date": date(2026, 1, 13)},
                {"payee": "Another actual synthetic supplier", "invoices": [invoice_payment(self, other)], "total_payment_amount": "75"},
                {"invoices": [invoice_payment(self)], "total_payment_amount": "75"}):
            with self.subTest(changes=changes):
                self.assertIn("possible_duplicate", self.refused(request(self, **changes)).detail)

    def test_postgresql_unicode_normalization_matches_duplicate_query(self):
        payments.record_referenced_inventory_payment(**request(self, external_reference="SYNTHETIC-Ä-TRANSFER"))
        self.assertIn("possible_duplicate", self.refused(request(self, external_reference="synthetic-ä-transfer")).detail)

    def test_new_actual_reference_can_pay_a_separate_remaining_amount(self):
        payments.record_referenced_inventory_payment(**request(self, total_payment_amount="75", invoices=[invoice_payment(self)]))
        payments.record_referenced_inventory_payment(**request(self, total_payment_amount="75", invoices=[invoice_payment(self)],
            external_reference="SYNTHETIC-OBSERVED-TRANSFER-002"))
        self.assertEqual([self.expense(self.invoice, index).payment_status for index in (0, 1)], ["paid", "paid"])
        self.assertEqual([self.expense(self.second, index).payment_status for index in (0, 1)], ["unpaid", "unpaid"])
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50"))

    def test_one_invoice_and_selected_line_leave_other_payables_unchanged(self):
        group = invoice_payment(self, amounts=("25",))
        result, _ = payments.record_referenced_inventory_payment(**request(self, invoices=[group], total_payment_amount="25"))
        self.assertEqual(len(result["payments"]), 1)
        self.assertEqual([self.expense(self.invoice, index).payment_status for index in (0, 1)], ["partial", "unpaid"])
        self.assertEqual([self.expense(self.second, index).payment_status for index in (0, 1)], ["unpaid", "unpaid"])

    def test_same_id_changed_capture_is_rejected_without_new_effect(self):
        capture = request(self)
        payments.record_referenced_inventory_payment(**capture)
        for changes in ({"external_reference": "SYNTHETIC-DIFFERENT-REFERENCE"}, {"payment_method": "cash"},
                {"payment_date": date(2026, 1, 13)}, {"payee": "SYNTHETIC MULTI-ITEM SUPPLIER"},
                {"notes": "Changed bank evidence"}, {"invoices": list(reversed(capture["invoices"]))},
                {"invoices": [capture["invoices"][0]], "total_payment_amount": "75"}):
            with self.subTest(changes=changes):
                self.assertIn("idempotency_key", self.refused({**capture, **changes}).detail)

    def test_equivalent_exact_decimals_uuid_and_funding_ids_replay(self):
        capture = request(self)
        result = payments.record_referenced_inventory_payment(**capture)[0]
        equivalent = deepcopy(capture)
        equivalent.update(submission_id=str(capture["submission_id"]).upper(), total_payment_amount="150.00")
        for invoice in equivalent["invoices"]:
            invoice["invoice_group_id"] = invoice["invoice_group_id"].upper()
            invoice["total_payment_amount"] = "75.00"
            for line in invoice["lines"]:
                line["amount"] = format(Decimal(line["amount"]), ".2f")
                line["funding_allocations"][0]["funding_source"] = str(self.source.pk)
                line["funding_allocations"][0]["amount"] = line["amount"]
        self.assertEqual(payments.record_referenced_inventory_payment(**equivalent), (result, False))

    def test_payee_must_match_each_original_supplier_without_fuzzy_aliases(self):
        self.refused(request(self, payee="Wrong actual counterparty"))
        other = record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-DIFFERENT-SUPPLIER",
            supplier="Another actual supplier"))[0]
        self.refused(request(self, invoices=[invoice_payment(self), invoice_payment(self, other)]))
        self.assertTrue(payments.record_referenced_inventory_payment(**request(self, payee="  SYNTHETIC MULTI-ITEM SUPPLIER  "))[1])

    def test_late_invoice_overpayment_rolls_back_prior_settlement_and_reference(self):
        bad = request(self)
        ordered = sorted((self.invoice, self.second), key=lambda value: value["invoice_group_id"])
        bad["invoices"] = [invoice_payment(self, ordered[0]), invoice_payment(self, ordered[1], amounts=("101", "25"))]
        bad["total_payment_amount"] = "201"
        # Extra confirmed cash makes this specifically the late payable failure.
        other_source = inventory.InventoryCaptureTests.funded_source(self)
        for line in bad["invoices"][1]["lines"]:
            line["funding_allocations"][0]["funding_source"] = other_source.pk
        with patch.object(payments, "record_inventory_invoice_payment", wraps=record_inventory_invoice_payment) as posted:
            self.refused(bad)
        self.assertEqual(posted.call_count, 2)
        self.assertTrue(payments.record_referenced_inventory_payment(**request(self))[1])

    def test_combined_cash_shortfall_across_invoices_rolls_back_everything(self):
        bad = request(self, total_payment_amount="300",
            invoices=[invoice_payment(self, amounts=("100", "50")), invoice_payment(self, self.second, amounts=("100", "50"))])
        self.refused(bad)
        self.assertFalse(FinancialCommandReceipt.objects.filter(command=payments.COMMAND).exists())

    def test_batch_cash_aliases_across_invoices_are_one_cash_pool(self):
        source = drafts.funded_source(self, "100")
        alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch,
            description="Synthetic alias, not more cash")
        bad = request(self, payment_date=date(2026, 1, 20))
        for group, selected in zip(bad["invoices"], (source, alias)):
            for line in group["lines"]:
                line["funding_allocations"][0]["funding_source"] = selected.pk
        self.refused(bad)

    def test_funding_sources_and_explicit_splits_are_independent_of_supplier_costs(self):
        other = inventory.InventoryCaptureTests.funded_source(self)
        capture = request(self)
        capture["invoices"][0]["lines"][0]["funding_allocations"] = [dict(funding_source=self.source.pk, amount="30"),
            dict(funding_source=other.pk, amount="20")]
        payments.record_referenced_inventory_payment(**capture)
        self.assertEqual(FundingAllocation.objects.count(), 5)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("70"))
        self.assertEqual(dated_source_cash(other, date(2026, 1, 12)), Decimal("180"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=("5000", "6100")).exists())

    def test_closed_purchase_period_allows_actual_later_payment_without_reopening(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        payments.record_referenced_inventory_payment(**request(self, payment_date=date(2026, 2, 2)))
        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PeriodStatus.CLOSED)
        self.assertEqual(set(FundingAllocation.objects.values_list("allocation_date", flat=True)), {date(2026, 2, 2)})
        self.assertEqual({row.expenditure_date for row in Expenditure.objects.all()}, {date(2026, 1, 1)})

    def test_closed_actual_payment_period_rejects_unchanged_date_and_evidence(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        capture = request(self)
        original = deepcopy(capture)
        self.refused(capture)
        self.assertEqual(capture, original)

    def test_payment_before_purchase_or_confirmed_cash_date_requires_review(self):
        self.refused(request(self, payment_date=date(2025, 12, 31)))
        source = drafts.funded_source(self, "200")
        capture = request(self)
        for group in capture["invoices"]:
            for line in group["lines"]:
                line["funding_allocations"][0]["funding_source"] = source.pk
        self.refused(capture)

    def test_whole_original_invoice_and_unselected_siblings_need_intact_proof(self):
        receipt = FinancialCommandReceipt.objects.get(pk=self.second["children"][1]["operation_id"])
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, request_hash="0" * 64)
        capture = request(self, total_payment_amount="100", invoices=[invoice_payment(self, amounts=("50",)),
            invoice_payment(self, self.second, amounts=("50",))])
        self.refused(capture)

    def test_missing_or_changed_original_invoice_version_is_not_adopted(self):
        for changes in ({"invoice_group_id": str(uuid.uuid4())}, {"invoice_version": "0" * 64}):
            capture = request(self)
            capture["invoices"][1].update(changes)
            self.refused(capture)

    def test_preexisting_nested_settlement_is_refused_not_adopted(self):
        capture = request(self)
        group = capture["invoices"][0]
        nested_id = payments._settlement_id(capture["submission_id"], group["invoice_group_id"])
        record_inventory_invoice_payment(submission_id=nested_id, user=self.user, currency="MWK",
            payment_date=capture["payment_date"], **group)
        self.refused(capture)

    def test_preexisting_planned_leaf_is_refused_not_adopted(self):
        capture = request(self)
        group = capture["invoices"][0]
        nested_id = payments._settlement_id(capture["submission_id"], group["invoice_group_id"])
        record_financial_supplier_payment(submission_id=_child_id(nested_id, 0), user=self.user,
            currency="MWK", expenditure_id=self.expense(self.invoice, 0).pk, payment_date=capture["payment_date"],
            funding_allocations=group["lines"][0]["funding_allocations"])
        self.refused(capture)

    def test_outer_receipt_insert_failure_rolls_back_all_nested_receipts_and_cash(self):
        capture = request(self)
        manager = FinancialCommandReceipt.objects
        create = manager.create
        def fail_outer(**kwargs):
            if kwargs.get("command") == payments.COMMAND:
                raise RuntimeError("synthetic referenced parent insert interruption")
            return create(**kwargs)
        with patch.object(manager, "create", side_effect=fail_outer):
            self.refused(capture, RuntimeError)
        self.assertTrue(payments.record_referenced_inventory_payment(**capture)[1])

    def test_later_nested_receipt_failure_rolls_back_earlier_payments(self):
        capture = request(self)
        manager, original = FinancialCommandReceipt.objects, FinancialCommandReceipt.objects.create
        calls = []
        def fail_later(**kwargs):
            if kwargs.get("command") == "inventory.invoice.pay":
                calls.append(kwargs["submission_id"])
                if len(calls) == 2:
                    raise RuntimeError("synthetic later invoice payment interruption")
            return original(**kwargs)
        with patch.object(manager, "create", side_effect=fail_later):
            self.refused(capture, RuntimeError)
        self.assertEqual(len(calls), 2)

    def test_missing_outer_receipt_cannot_recreate_or_adopt_original_children(self):
        capture = request(self)
        payments.record_referenced_inventory_payment(**capture)
        proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=capture["submission_id"]))
        self.refused(capture)

    def test_reference_remains_reserved_with_partial_damage_or_incomplete_evidence(self):
        capture = request(self)
        result = payments.record_referenced_inventory_payment(**capture)[0]
        receipt = FinancialCommandReceipt.objects.get(pk=capture["submission_id"])
        for changes in ({"completed_at": None}, {"result": json.dumps({**result, "reference_key": "0" * 64})},
                {"result": json.dumps({**result, "capture": {**result["capture"], "external_reference": "DAMAGED-CAPTURE"}})}):
            with self.subTest(changes=changes), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, **changes)
                self.assertIn("possible_duplicate", self.refused().detail)
                transaction.set_rollback(True)

    def test_retained_reference_parent_is_immutable_through_ordinary_writes(self):
        capture = request(self)
        payments.record_referenced_inventory_payment(**capture)
        receipt = FinancialCommandReceipt.objects.get(pk=capture["submission_id"])
        receipt.result = {"changed": True}
        for call in (lambda: receipt.save(), lambda: receipt.save_base(raw=True), lambda: receipt.delete(),
                lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk).update(result={}),
                lambda: FinancialCommandReceipt.objects.filter(pk=receipt.pk)._raw_delete("default")):
            before = proof.snapshot()
            with self.assertRaises(DomainValidationError):
                call()
            self.assertEqual(proof.snapshot(), before)

    def test_reference_and_replay_survive_later_stock_use_and_period_close(self):
        capture = request(self)
        result = payments.record_referenced_inventory_payment(**capture)[0]
        lot = SharedConsumableLot.objects.get(pk=self.invoice["children"][0]["result"]["lot_id"])
        record_inventory_issue(**inventory.issue(self, lot))
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        before = proof.snapshot()
        self.assertEqual(payments.record_referenced_inventory_payment(**capture), (result, False))
        self.assertEqual(proof.snapshot(), before)

    def test_current_finance_roles_and_owner_source_authority_are_enforced(self):
        source = drafts.funded_source(self, "200")
        for slug in RoleChoices.values:
            with self.subTest(role=slug), transaction.atomic():
                actor = get_user_model().objects.create_user(username="reference-" + slug,
                    email="reference-" + slug + "@synthetic.invalid", password="synthetic-only")
                actor.roles.add(Role.objects.get_or_create(slug=slug, defaults={"name": slug})[0])
                capture = request(self, user=actor, payment_date=date(2026, 1, 20))
                if slug in {RoleChoices.ADMIN, RoleChoices.DIRECTOR}:
                    self.assertTrue(payments.record_referenced_inventory_payment(**capture)[1])
                else:
                    self.refused(capture, PermissionDenied)
                for group in capture["invoices"]:
                    for line in group["lines"]:
                        line["funding_allocations"][0]["funding_source"] = source.pk
                if slug in {RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR}:
                    # Use a distinct actual reference for this separate attempted payment.
                    capture.update(submission_id=uuid.uuid4(), external_reference="SYNTHETIC-NON-OWNER-" + slug,
                        total_payment_amount="30")
                    capture["invoices"] = [invoice_payment(self, amounts=("20", "10"))]
                    for line in capture["invoices"][0]["lines"]:
                        line["funding_allocations"][0]["funding_source"] = source.pk
                    self.assertTrue(payments.record_referenced_inventory_payment(**capture)[1])
                else:
                    self.refused(capture, PermissionDenied)
                transaction.set_rollback(True)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)
        self.refused(exception=PermissionDenied)

    def test_flag_off_refuses_before_any_schema_or_database_query(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                payments.record_referenced_inventory_payment(**request(self))

    def test_required_actual_method_reference_payee_and_exact_amounts_are_strict(self):
        for changes in ({"payment_method": "credit"}, {"payment_method": True}, {"payment_method": "card"},
                {"external_reference": ""}, {"external_reference": "x" * 121}, {"payee": ""},
                {"payee": "x" * 161}, {"notes": "x" * 4001}, {"currency": "USD"},
                {"payment_date": date(2099, 1, 1)}, {"total_payment_amount": "149.99"},
                {"total_payment_amount": 150.0}):
            with self.subTest(changes=changes):
                self.refused(request(self, **changes))

    def test_invoices_lines_and_funding_cannot_inject_parent_journal_or_paid_flags(self):
        for field in ("paid", "journal_lines", "submission_id", "supplier", "notes", "payment_method"):
            capture = request(self)
            capture["invoices"][0][field] = True
            self.refused(capture)
        for value in (None, {}, [], ["not an invoice"]):
            self.refused(request(self, invoices=value))
        capture = request(self)
        capture["invoices"][0]["lines"][0]["funding_allocations"][0]["funding_source"] = True
        self.refused(capture)

    def test_duplicate_invoice_or_line_does_not_infer_an_allocation(self):
        group = invoice_payment(self)
        self.refused(request(self, invoices=[group, deepcopy(group)]))
        capture = request(self)
        capture["invoices"][0]["lines"].append(deepcopy(capture["invoices"][0]["lines"][0]))
        self.refused(capture)

    def test_invoice_and_total_selected_line_bounds_refuse_before_posting(self):
        capture = request(self)
        capture["invoices"] *= 6
        self.refused(capture)
        capture = request(self, total_payment_amount="51")
        for group, count in zip(capture["invoices"], (26, 25)):
            group["total_payment_amount"] = str(count)
            group["lines"] = [dict(invoice_line_index=index, amount="1", funding_allocations=[
                dict(funding_source=self.source.pk, amount="1")]) for index in range(count)]
        with self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                payments.record_referenced_inventory_payment(**capture)

    def test_ten_invoice_boundary_can_capture_one_observed_payment(self):
        originals = [self.invoice, self.second]
        for index in range(8):
            originals.append(record_inventory_invoice(**invoices.invoice_request(self, invoice_reference=f"SYNTHETIC-BOUNDARY-{index}"))[0])
        groups = [invoice_payment(self, original, amounts=("1", "1")) for original in originals]
        result, created = payments.record_referenced_inventory_payment(**request(self, total_payment_amount="20", invoices=groups))
        self.assertTrue(created)
        self.assertEqual(len(result["payments"]), 10)
        self.assertEqual(FundingAllocation.objects.count(), 20)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("180"))

    def test_fifty_selected_lines_across_two_invoices_can_settle_exactly(self):
        originals = []
        for index in range(2):
            invoice = invoices.invoice_request(self, invoice_reference=f"SYNTHETIC-FIFTY-LINES-{index}",
                total_purchase_cost="25")
            invoice["lines"] = [dict(item_id=self.item.pk, location_id=self.location.pk,
                category_id=self.stock_category.pk, quantity="1", total_purchase_cost="1") for _ in range(25)]
            originals.append(record_inventory_invoice(**invoice)[0])
        groups = [invoice_payment(self, original, amounts=("1",) * 25) for original in originals]
        result, created = payments.record_referenced_inventory_payment(**request(self, total_payment_amount="50", invoices=groups))
        self.assertTrue(created)
        self.assertEqual(len(result["payments"]), 2)
        self.assertEqual(FundingAllocation.objects.count(), 50)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("150"))
        self.assertTrue(all(self.expense(original, index).payment_status == "paid" for original in originals for index in range(25)))

    def test_same_submission_id_from_another_authorized_actor_is_not_replayed(self):
        capture = request(self)
        payments.record_referenced_inventory_payment(**capture)
        actor = get_user_model().objects.create_user(username="referenced-payment-other-director",
            email="referenced-payment-other-director@synthetic.invalid", password="synthetic-only")
        actor.roles.add(Role.objects.get(slug=RoleChoices.DIRECTOR))
        self.assertIn("idempotency_key", self.refused({**capture, "user": actor}).detail)


@override_settings(**invoices.SETTINGS)
class InventoryReferencedPaymentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_same_parent_intent_posts_once(self):
        capture = request(self)
        self.assertCountEqual(proof.race(self, [lambda: payments.record_referenced_inventory_payment(**capture)] * 2), [True, False])
        self.assertEqual(FundingAllocation.objects.count(), 4)

    def test_different_ids_same_actual_reference_do_not_duplicate_payment(self):
        first, second = request(self), request(self, external_reference=" synthetic-observed-transfer-001 ")
        self.assertCountEqual(proof.race(self, [lambda: payments.record_referenced_inventory_payment(**first),
            lambda: payments.record_referenced_inventory_payment(**second)]), [True, "rejected"])
        self.assertEqual(FinancialCommandReceipt.objects.filter(command=payments.COMMAND).count(), 1)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_same_reference_across_actual_payment_periods_is_serialized(self):
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        first, second = request(self), request(self, payment_date=date(2026, 2, 2))
        self.assertCountEqual(proof.race(self, [lambda: payments.record_referenced_inventory_payment(**first),
            lambda: payments.record_referenced_inventory_payment(**second)]), [True, "rejected"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_distinct_references_cannot_double_spend_shared_cash(self):
        first, second = request(self), request(self, external_reference="SYNTHETIC-DIFFERENT-ACTUAL-TRANSFER")
        self.assertCountEqual(proof.race(self, [lambda: payments.record_referenced_inventory_payment(**first),
            lambda: payments.record_referenced_inventory_payment(**second)]), [True, "rejected"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))

    def test_reversed_invoice_order_distinct_small_payments_do_not_invert_payable_locks(self):
        groups = [invoice_payment(self, amounts=("10", "5")), invoice_payment(self, self.second, amounts=("10", "5"))]
        first = request(self, invoices=groups, total_payment_amount="30")
        second = request(self, invoices=list(reversed(groups)), total_payment_amount="30", external_reference="SYNTHETIC-SECOND-SMALL-PAYMENT")
        self.assertEqual(proof.race(self, [lambda: payments.record_referenced_inventory_payment(**first),
            lambda: payments.record_referenced_inventory_payment(**second)]), [True, True])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("60"))

    def test_independent_planned_settlement_parent_cannot_invert_leaf_locks_or_be_adopted(self):
        capture = request(self)
        group = capture["invoices"][0]
        nested_id = payments._settlement_id(capture["submission_id"], group["invoice_group_id"])
        standalone = dict(submission_id=nested_id, user=self.user, currency="MWK", payment_date=capture["payment_date"], **group)
        results = proof.race(self, [lambda: payments.record_referenced_inventory_payment(**capture),
            lambda: record_inventory_invoice_payment(**standalone)])
        if "rejected" in results:
            self.assertCountEqual(results, [True, "rejected"])
            self.assertEqual(FundingAllocation.objects.count(), 2)
            self.assertFalse(FinancialCommandReceipt.objects.filter(command=payments.COMMAND).exists())
        else:
            self.assertCountEqual(results, [True, False])
            self.assertEqual(FundingAllocation.objects.count(), 4)

    def test_independent_planned_leaf_is_never_attached_as_this_payment(self):
        capture = request(self)
        group = capture["invoices"][0]
        nested_id = payments._settlement_id(capture["submission_id"], group["invoice_group_id"])
        leaf = dict(submission_id=_child_id(nested_id, 0), user=self.user, currency="MWK",
            expenditure_id=int(self.invoice["children"][0]["result"]["expenditure_id"]),
            payment_date=capture["payment_date"], funding_allocations=group["lines"][0]["funding_allocations"])
        results = proof.race(self, [lambda: payments.record_referenced_inventory_payment(**capture),
            lambda: record_financial_supplier_payment(**leaf)])
        if "rejected" in results:
            self.assertCountEqual(results, [True, "rejected"])
            self.assertEqual(FundingAllocation.objects.count(), 1)
            self.assertFalse(FinancialCommandReceipt.objects.filter(command=payments.COMMAND).exists())
        else:
            self.assertCountEqual(results, [True, False])
            self.assertEqual(FundingAllocation.objects.count(), 4)
