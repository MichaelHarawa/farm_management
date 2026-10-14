"""Bounded original-invoice proof work; real, disposable PostgreSQL only."""
from copy import deepcopy
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
import json
from time import perf_counter
from unittest.mock import patch
import uuid

from django.db import connection, connections, DatabaseError, transaction
from django.core.exceptions import ValidationError as ModelValidationError
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from apps.finance.models import Expenditure, FundingAllocation, FinancialCommandReceipt, JournalEntry, JournalLine
from apps.finance.services import payable_evidence
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_invoice_payments import record_inventory_invoice_payment
from apps.finance.services import inventory_invoice_payments, inventory_invoices
from apps.finance.services.inventory_invoices import locked_invoice_payment_proof, record_inventory_invoice
from . import test_inventory_capture as inventory
from . import test_inventory_invoices as invoices
from . import test_inventory_purchase_proof as proof
from .inventory_corruption import corrupt_inventory


@override_settings(**invoices.SETTINGS)
class InventoryPaymentProofScopeTests(TestCase):
    def setUp(self):
        invoices.invoice_fixture(self)
        self.source = inventory.InventoryCaptureTests.funded_source(self)

    def invoice(self, count, **changes):
        line = {**invoices.invoice_request(self)["lines"][0], "quantity": "1", "total_purchase_cost": "1.00"}
        return record_inventory_invoice(**invoices.invoice_request(self,
            invoice_reference="SYNTHETIC-PROOF-" + uuid.uuid4().hex,
            total_purchase_cost=str(count), lines=[deepcopy(line) for _ in range(count)], **changes))[0]

    def request(self, invoice, **changes):
        return {**dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            invoice_group_id=invoice["invoice_group_id"], invoice_version=invoice["invoice_version"],
            payment_date=date(2026, 1, 12), total_payment_amount=str(Decimal(len(invoice["children"])) / 2),
            lines=[dict(invoice_line_index=index, amount="0.50",
                funding_allocations=[dict(funding_source=self.source.pk, amount="0.50")])
                for index in range(len(invoice["children"]))]), **changes}

    def measure(self, count):
        invoice = self.invoice(count)
        capture = self.request(invoice)
        started = perf_counter()
        with patch.object(payable_evidence, "_version", wraps=payable_evidence._version) as versions:
            # Django's ordinary 9,000-query diagnostic cap truncates the old
            # fifty-line baseline. Increase ONLY this synthetic test's logger,
            # then restore it; never print SQL, references or captured payloads.
            with patch.object(connection, "queries_log", deque(maxlen=100000)):
                with CaptureQueriesContext(connection) as queries:
                    result, created = record_inventory_invoice_payment(**capture)
                query_count = len(queries)
                self.assertLess(query_count, connection.queries_log.maxlen)
        metrics = dict(invoice_lines=count, original_payable_proof_calls=versions.call_count,
            payment_queries=query_count, query_capture_complete=True,
            payment_seconds=round(perf_counter() - started, 6))
        print("INVOICE_PAYMENT_PROOF_METRICS " + json.dumps(metrics, sort_keys=True), flush=True)
        self.assertTrue(created)
        self.assertEqual(len(result["settlements"]), count)
        return metrics, result, capture

    def test_ten_line_payment_original_proof_work_is_linear_and_retains_exact_effects(self):
        metrics, result, capture = self.measure(10)
        self.assertLessEqual(metrics["original_payable_proof_calls"], 30)
        self.assertLessEqual(metrics["payment_queries"], 1500)
        self.assertEqual(FundingAllocation.objects.count(), 10)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("5.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("195.00"))
        self.assertFalse(JournalLine.objects.filter(account__code__in=["5000", "6100"]).exists())
        original = FinancialCommandReceipt.objects.get(pk=capture["invoice_group_id"]).result
        before = proof.snapshot()
        for _ in range(20):
            replay, created = record_inventory_invoice_payment(**capture)
            self.assertFalse(created)
            self.assertEqual(replay, result)
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(FinancialCommandReceipt.objects.get(pk=capture["invoice_group_id"]).result, original)

    def test_fifty_line_payment_original_proof_work_is_linear(self):
        metrics, result, _ = self.measure(50)
        self.assertLessEqual(metrics["original_payable_proof_calls"], 150)
        self.assertLessEqual(metrics["payment_queries"], 7200)
        self.assertEqual(len(result["settlements"]), 50)
        self.assertEqual(FundingAllocation.objects.count(), 50)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("25.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("175.00"))

    def parent(self, invoice):
        return FinancialCommandReceipt.objects.get(pk=invoice["invoice_group_id"])

    def child(self, invoice, index=0):
        return FinancialCommandReceipt.objects.get(pk=invoice["children"][index]["operation_id"])

    def expenditure(self, invoice, index=0):
        return Expenditure.objects.get(pk=invoice["children"][index]["result"]["expenditure_id"])

    def test_membership_reuse_still_checks_each_selected_original_source(self):
        invoice = self.invoice(2)
        with locked_invoice_payment_proof(self.parent(invoice)):
            with patch.object(payable_evidence, "_version", wraps=payable_evidence._version) as versions:
                self.assertTrue(payable_evidence.verified_payable(self.expenditure(invoice)))
                self.assertEqual(versions.call_count, 1)
        self.assertIsNone(inventory_invoices._payment_membership.get())
        with patch.object(payable_evidence, "_version", wraps=payable_evidence._version) as versions:
            self.assertTrue(payable_evidence.verified_payable(self.expenditure(invoice)))
            self.assertEqual(versions.call_count, 3)  # No reuse outside the scope.

    def test_damaged_unselected_sibling_is_refused_before_scope_can_be_reused(self):
        invoice = self.invoice(2)
        line = JournalEntry.objects.get(pk=invoice["children"][1]["result"]["journal_id"]).lines.first()
        corrupt_inventory(JournalLine, line.pk, debit=line.debit + Decimal("1"))
        before = proof.snapshot()
        with self.assertRaises(ValidationError):
            with locked_invoice_payment_proof(self.parent(invoice)):
                self.fail("Damaged original sibling must not grant membership proof.")
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())

    def test_current_selected_source_damage_is_not_hidden_by_membership_reuse(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        with transaction.atomic():
            with locked_invoice_payment_proof(self.parent(invoice)):
                expenditure = self.expenditure(invoice)
                corrupt_inventory(Expenditure, expenditure.pk, amount=Decimal("2"))
                with self.assertRaises(ValidationError):
                    record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user,
                        currency="MWK", expenditure_id=expenditure.pk, payment_date=date(2026, 1, 12),
                        funding_allocations=[dict(funding_source=self.source.pk, amount="0.50")])
                self.assertFalse(FundingAllocation.objects.exists())
            transaction.set_rollback(True)
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())

    def test_cached_child_receipt_content_or_command_cannot_be_substituted(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        with locked_invoice_payment_proof(self.parent(invoice)):
            for command_change in (False, True):
                with self.subTest(command_change=command_change):
                    child = self.child(invoice)
                    if command_change:
                        child.command = "finance.expenditure.create"
                    else:
                        child.result["payable_version"] = "0" * 64
                    with self.assertRaises(ValidationError):
                        inventory_invoices.require_invoice_membership(child)
        self.assertEqual(proof.snapshot(), before)

    def test_other_invoice_never_borrows_this_groups_membership_proof(self):
        invoice, other = self.invoice(2), self.invoice(2)
        with locked_invoice_payment_proof(self.parent(invoice)):
            with patch.object(payable_evidence, "_version", wraps=payable_evidence._version) as versions:
                self.assertTrue(payable_evidence.verified_payable(self.expenditure(other)))
                self.assertEqual(versions.call_count, 3)
            line = JournalEntry.objects.get(pk=other["children"][1]["result"]["journal_id"]).lines.first()
            corrupt_inventory(JournalLine, line.pk, debit=line.debit + Decimal("1"))
            self.assertFalse(payable_evidence.verified_payable(self.expenditure(other)))

    def test_nested_scope_reproves_and_restores_the_outer_scope(self):
        invoice = self.invoice(2)
        parent = self.parent(invoice)
        with locked_invoice_payment_proof(parent):
            original_scope = inventory_invoices._payment_membership.get()
            with patch.object(payable_evidence, "_version", wraps=payable_evidence._version) as versions:
                with locked_invoice_payment_proof(parent):
                    self.assertIsNot(inventory_invoices._payment_membership.get(), original_scope)
                self.assertEqual(versions.call_count, 2)
            self.assertIs(inventory_invoices._payment_membership.get(), original_scope)
            self.assertTrue(payable_evidence.verified_payable(self.expenditure(invoice)))
        self.assertIsNone(inventory_invoices._payment_membership.get())

    def test_normal_writers_cannot_change_original_evidence_inside_scope(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        with locked_invoice_payment_proof(self.parent(invoice)):
            expenditure = self.expenditure(invoice, 1)
            expenditure.amount = Decimal("2")
            with self.assertRaises(ModelValidationError):
                expenditure.save(update_fields=["amount"])
            with self.assertRaises(ModelValidationError):
                Expenditure.objects.filter(pk=expenditure.pk).update(amount=Decimal("2"))
        self.assertEqual(proof.snapshot(), before)

    def test_stale_or_forged_parent_cannot_grant_membership_proof(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        for command_change in (False, True):
            parent = self.parent(invoice)
            if command_change:
                parent.command = "finance.expenditure.create"
            else:
                parent.result["invoice_version"] = "0" * 64
            with self.subTest(command_change=command_change), self.assertRaises(ValidationError):
                with locked_invoice_payment_proof(parent):
                    self.fail("An altered parent must not grant membership proof.")
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())

    def test_failed_later_leaf_rolls_back_effects_and_discards_scope(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        original = inventory_invoice_payments.record_financial_supplier_payment
        calls = []
        def fail_second(**capture):
            calls.append(capture["submission_id"])
            if len(calls) == 2:
                raise RuntimeError("synthetic late payment failure")
            return original(**capture)
        with patch.object(inventory_invoice_payments, "record_financial_supplier_payment", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                record_inventory_invoice_payment(**self.request(invoice))
        self.assertEqual(len(calls), 2)
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())
        self.assertTrue(record_inventory_invoice_payment(**self.request(invoice))[1])

    def test_later_payment_does_not_reuse_the_previous_calls_membership(self):
        invoice = self.invoice(2)
        record_inventory_invoice_payment(**self.request(invoice))
        line = JournalEntry.objects.get(pk=invoice["children"][1]["result"]["journal_id"]).lines.first()
        corrupt_inventory(JournalLine, line.pk, debit=line.debit + Decimal("1"))
        before = proof.snapshot()
        capture = self.request(invoice, total_payment_amount="0.25", lines=[dict(invoice_line_index=0,
            amount="0.25", funding_allocations=[dict(funding_source=self.source.pk, amount="0.25")])])
        with self.assertRaises(ValidationError):
            record_inventory_invoice_payment(**capture)
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())


@override_settings(**invoices.SETTINGS)
class InventoryPaymentProofScopeTransactionTests(TransactionTestCase):
    setUp = InventoryPaymentProofScopeTests.setUp
    invoice = InventoryPaymentProofScopeTests.invoice
    parent = InventoryPaymentProofScopeTests.parent
    child = InventoryPaymentProofScopeTests.child
    expenditure = InventoryPaymentProofScopeTests.expenditure

    def test_scope_cannot_be_entered_without_an_atomic_transaction(self):
        invoice = self.invoice(2)
        before = proof.snapshot()
        self.assertFalse(connection.in_atomic_block)
        with self.assertRaises(ValidationError):
            with locked_invoice_payment_proof(self.parent(invoice)):
                self.fail("Autocommit cannot own reusable row-lock proof.")
        self.assertEqual(proof.snapshot(), before)
        self.assertIsNone(inventory_invoices._payment_membership.get())

    def test_a_prior_postgresql_transaction_cannot_lend_its_proof(self):
        invoice = self.invoice(2)
        with transaction.atomic():
            with locked_invoice_payment_proof(self.parent(invoice)):
                previous = inventory_invoices._payment_membership.get()
        with transaction.atomic():
            token = inventory_invoices._payment_membership.set(previous)
            try:
                with self.assertRaises(ValidationError):
                    inventory_invoices.require_invoice_membership(self.child(invoice))
            finally:
                inventory_invoices._payment_membership.reset(token)

    def test_proof_cannot_outlive_the_savepoint_owning_its_original_locks(self):
        invoice = self.invoice(2)
        with transaction.atomic():
            with transaction.atomic():
                with locked_invoice_payment_proof(self.parent(invoice)):
                    previous = inventory_invoices._payment_membership.get()
                transaction.set_rollback(True)
            token = inventory_invoices._payment_membership.set(previous)
            try:
                with self.assertRaises(ValidationError):
                    inventory_invoices.require_invoice_membership(self.child(invoice))
            finally:
                inventory_invoices._payment_membership.reset(token)

    def test_scope_locks_unselected_payables_and_cannot_be_borrowed_by_another_connection(self):
        invoice = self.invoice(2)
        child_id = self.child(invoice).pk
        unselected_id = self.expenditure(invoice, 1).pk
        def other_connection(scope):
            try:
                with transaction.atomic():
                    self.assertIsNone(inventory_invoices._payment_membership.get())
                    child = FinancialCommandReceipt.objects.get(pk=child_id)
                    inventory_invoices.require_invoice_membership(child)  # Fresh full proof.
                    token = inventory_invoices._payment_membership.set(scope)
                    try:
                        with self.assertRaises(ValidationError):
                            inventory_invoices.require_invoice_membership(child)
                    finally:
                        inventory_invoices._payment_membership.reset(token)
                    Expenditure.objects.select_for_update(nowait=True).get(pk=unselected_id)
            except DatabaseError as error:
                return getattr(error.__cause__, "sqlstate", None) or getattr(error.__cause__, "pgcode", None)
            finally:
                connections["default"].close()
            return "unexpected-unlocked-payable"
        with transaction.atomic():
            with locked_invoice_payment_proof(self.parent(invoice)):
                scope = inventory_invoices._payment_membership.get()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    self.assertEqual(executor.submit(other_connection, scope).result(timeout=15), "55P03")
        self.assertIsNone(inventory_invoices._payment_membership.get())
