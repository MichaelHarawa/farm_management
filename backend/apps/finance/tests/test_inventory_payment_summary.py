"""Private positive summary/evidence checks on owned PostgreSQL only."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, override_settings
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import FinancialCommandReceipt, FundingAllocation, JournalEntry, JournalLine, PeriodStatus
from apps.finance.services import inventory_payment_summary as summaries
from apps.finance.services.inventory_payment_summary_schema import supplier_payment_summary_schema
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.inventory_invoices import _snapshot, record_inventory_invoice
from apps.finance.services.inventory_referenced_payments import record_referenced_inventory_payment
from apps.finance.services.ledger import trial_balance
from apps.mobile_sync.projections import canonical, checksum
from . import test_inventory_referenced_payments as references
from . import test_inventory_invoices as invoices
from . import test_inventory_capture as inventory
from . import test_inventory_payment_proof_scope as scoped
from . import test_inventory_purchase_proof as proof
from .inventory_corruption import corrupt_inventory


SCHEMA = Path(__file__).resolve().parents[4] / "docs/mobile/contracts/supplier-payment-summary-candidate-v1.schema.json"


@override_settings(**invoices.SETTINGS)
class InventoryPaymentSummaryTests(TestCase):
    def setUp(self):
        references.setup(self)

    def record(self, **changes):
        capture = references.request(self, **changes)
        result, _ = record_referenced_inventory_payment(**capture)
        return FinancialCommandReceipt.objects.get(pk=capture["submission_id"]), result

    def summary(self, receipt, user=None):
        return summaries.supplier_payment_summary(operation_id=receipt.pk, user=user or self.user)

    def validate(self, summary):
        schema = supplier_payment_summary_schema()
        # /docs is user-ignored. Core verification must work from tracked
        # source alone; also check the generated local mirror when present.
        if SCHEMA.is_file():
            self.assertEqual(json.loads(SCHEMA.read_text(encoding="utf-8")), schema)
        Draft7Validator.check_schema(schema)
        Draft7Validator(schema, format_checker=FormatChecker()).validate(summary)
        self.assertLessEqual(len(canonical(summary).encode("utf-8")), summaries.MAX_SUMMARY_BYTES)

    def refused(self, receipt):
        before = proof.snapshot()
        with self.assertRaises(ValidationError) as error:
            self.summary(receipt)
        self.assertEqual(str(error.exception.detail["payment_summary"]), summaries.MESSAGE)
        self.assertEqual(proof.snapshot(), before)

    def reseal(self, receipt, prefix, result):
        # Explicit privileged corruption in the owned test database only. It
        # tests independent effects/semantics, not a production repair API.
        result = deepcopy(result)
        result.pop("payment_version", None)
        result.pop("payment_anchor", None)
        request_hash = checksum({"actor": str(receipt.actor_id), "command": receipt.command, "payload": result["capture"]})
        result["payment_version"] = checksum({"basis": prefix + "-v1", "result": result})
        result["payment_anchor"] = checksum({"basis": prefix + "-receipt-v1", "operation_id": str(receipt.pk),
            "actor_id": str(receipt.actor_id), "command": receipt.command, "request_hash": request_hash, "result": result})
        corrupt_inventory(FinancialCommandReceipt, receipt.pk, request_hash=request_hash, result=json.dumps(result))

    def test_positive_summary_is_accurate_bounded_and_read_only(self):
        receipt, original = self.record(notes="SYNTHETIC-PRIVATE-NOTE-OWNER-DETAIL")
        before = proof.snapshot()
        summary = self.summary(receipt)
        self.validate(summary)
        self.assertEqual(summary["amount"], "150.00")
        self.assertEqual(summary["payment_date"], "2026-01-12")
        self.assertEqual(summary["payment_version"], original["payment_version"])
        self.assertEqual(summary["operation_id"], str(receipt.pk))
        self.assertEqual(summary["evidence_status"], "accepted_original_payment")
        self.assertEqual(summary["balance_semantics"], "historical_payment_not_current_balance")
        self.assertTrue(summary["note_available"])
        self.assertEqual([row["invoice_id"] for row in summary["invoices"]], sorted([self.invoice["invoice_group_id"], self.second["invoice_group_id"]]))
        for row in summary["invoices"]:
            self.assertEqual(row["amount"], "75.00")
            self.assertEqual(row["lines"], [dict(line_index=0, amount="50.00"), dict(line_index=1, amount="25.00")])
        self.assertNotIn("SYNTHETIC-PRIVATE-NOTE", canonical(summary))
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_five_finance_read_roles_receive_the_same_positive_common_fields(self):
        receipt, _ = self.record()
        baseline = self.summary(receipt)
        for role in (RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER,
                     RoleChoices.FARM_SUPERVISOR, RoleChoices.STAKE_HOLDER):
            with self.subTest(role=role):
                reader = get_user_model().objects.create_user(username="summary-" + role,
                    email="summary-" + role + "@synthetic.invalid", password="Synthetic-only-pass")
                reader.roles.add(Role.objects.get(slug=role))
                summary = self.summary(receipt, reader)
                self.validate(summary)
                self.assertEqual(summary, baseline)
        encoded = canonical(baseline)
        for field in ("funding_source", "owner", "journal", "request_hash", "actor_id", "classification", "expenditure_id", '"notes"'):
            self.assertNotIn(field, encoded)

    def test_worker_roleless_or_missing_principal_is_denied_before_financial_lookup(self):
        receipt, _ = self.record()
        for role in (RoleChoices.GENERAL_WORKER, None):
            reader = get_user_model().objects.create_user(username="denied-summary-" + str(role),
                email="denied-summary-" + str(role) + "@synthetic.invalid", password="Synthetic-only-pass")
            if role:
                reader.roles.add(Role.objects.get(slug=role))
            with patch.object(FinancialCommandReceipt.objects, "get", side_effect=AssertionError("financial lookup must not occur")):
                with self.assertRaises(PermissionDenied):
                    self.summary(receipt, reader)
        with self.assertRaises(PermissionDenied):
            summaries.supplier_payment_summary(operation_id=receipt.pk, user=None)

    def test_stale_cached_role_or_inactive_user_does_not_grant_access(self):
        receipt, _ = self.record()
        reader = get_user_model().objects.create_user(username="summary-stale-reader",
            email="summary-stale-reader@synthetic.invalid", password="Synthetic-only-pass")
        reader.roles.add(Role.objects.get(slug=RoleChoices.ADMIN))
        self.assertIn(RoleChoices.ADMIN, reader.role_slugs)
        reader.roles.clear()
        with self.assertRaises(PermissionDenied):
            self.summary(receipt, reader)
        reader.roles.add(Role.objects.get(slug=RoleChoices.ADMIN))
        get_user_model().objects.filter(pk=reader.pk).update(is_active=False)
        self.assertTrue(reader.is_active)
        with self.assertRaises(PermissionDenied):
            self.summary(receipt, reader)

    def test_access_is_rechecked_after_proof_reads(self):
        receipt, _ = self.record()
        original = summaries._summary
        def revoke_after_proof(receipt):
            result = original(receipt)
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
            return result
        with patch.object(summaries, "_summary", side_effect=revoke_after_proof):
            with self.assertRaises(PermissionDenied):
                self.summary(receipt)

    def test_flag_off_and_unsupported_database_refuse_without_queries(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                summaries.supplier_payment_summary(operation_id=uuid.uuid4(), user=self.user)
        with patch.object(connection, "vendor", "sqlite"), self.assertNumQueries(0):
            with self.assertRaises(ValidationError):
                summaries.supplier_payment_summary(operation_id=uuid.uuid4(), user=self.user)

    def test_missing_incomplete_or_wrong_command_cannot_be_presented_as_accepted(self):
        receipt, _ = self.record()
        with self.assertRaises(ValidationError):
            summaries.supplier_payment_summary(operation_id=uuid.uuid4(), user=self.user)
        for fields in (dict(completed_at=None), dict(command="finance.expenditure.pay")):
            with self.subTest(fields=fields), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, **fields)
                self.refused(receipt)
                transaction.set_rollback(True)

    def test_changed_root_hash_version_anchor_or_reference_key_is_refused(self):
        receipt, result = self.record()
        changes = [dict(request_hash="0" * 64)] + [dict(result=json.dumps({**result, key: "0" * 64}))
            for key in ("payment_version", "payment_anchor", "reference_key")]
        for fields in changes:
            with self.subTest(fields=list(fields)), transaction.atomic():
                corrupt_inventory(FinancialCommandReceipt, receipt.pk, **fields)
                self.refused(receipt)
                transaction.set_rollback(True)

    def test_missing_nested_leaf_or_original_invoice_receipt_is_refused(self):
        receipt, result = self.record()
        nested = result["payments"][0]["receipt"]
        identities = [nested["operation_id"], nested["result"]["settlements"][0]["receipt"]["operation_id"],
            nested["result"]["original_invoice"]["operation_id"]]
        for identifier in identities:
            with self.subTest(identifier=identifier), transaction.atomic():
                proof.erase_receipt(FinancialCommandReceipt.objects.get(pk=identifier))
                self.refused(receipt)
                transaction.set_rollback(True)

    def test_changed_actual_allocation_or_journal_is_refused_without_repair(self):
        receipt, _ = self.record()
        allocation = FundingAllocation.objects.first()
        journal = JournalEntry.objects.get(idempotency_key=f"expenditure-payment:{allocation.pk}")
        for model, pk, fields in [(FundingAllocation, allocation.pk, dict(amount=allocation.amount + Decimal("1"))),
                                  (JournalEntry, journal.pk, dict(posting_date=date(2026, 1, 13)))]:
            with self.subTest(model=model.__name__), transaction.atomic():
                corrupt_inventory(model, pk, **fields)
                self.refused(receipt)
                transaction.set_rollback(True)

    def test_resealed_balanced_but_wrong_payment_gl_does_not_pass_semantic_proof(self):
        receipt, result = self.record()
        observed_parent = result["payments"][0]["receipt"]
        parent = FinancialCommandReceipt.objects.get(pk=observed_parent["operation_id"])
        parent_result = deepcopy(parent.result)
        settled = parent_result["settlements"][0]
        expenditure_id = settled["receipt"]["result"]["expenditure_id"]
        allocation = FundingAllocation.objects.get(expenditure_id=expenditure_id,
            payment_group_key="financial-payment:" + settled["receipt"]["operation_id"])
        journal = JournalEntry.objects.get(idempotency_key=f"expenditure-payment:{allocation.pk}")
        for line in journal.lines.all():
            values = {"debit": line.debit + Decimal("1")} if line.debit else {"credit": line.credit + Decimal("1")}
            corrupt_inventory(JournalLine, line.pk, **values)
        settled["effects"] = summaries.settlements._effects(expenditure_id, settled["receipt"]["operation_id"])
        self.reseal(parent, "phase6-inventory-invoice-payment", parent_result)
        result["payments"][0]["receipt"] = _snapshot(FinancialCommandReceipt.objects.get(pk=parent.pk))
        self.reseal(receipt, "phase6-inventory-referenced-payment", result)
        self.refused(receipt)

    def test_damaged_unselected_invoice_source_is_not_hidden_by_positive_summary(self):
        receipt, _ = self.record(invoices=[references.invoice_payment(self, amounts=("50",))], total_payment_amount="50")
        journal = JournalEntry.objects.get(pk=self.invoice["children"][1]["result"]["journal_id"])
        line = journal.lines.first()
        corrupt_inventory(JournalLine, line.pk, debit=line.debit + Decimal("1"))
        self.refused(receipt)

    def test_later_cash_spending_stock_issue_and_period_close_do_not_rewrite_historical_summary(self):
        receipt, _ = self.record()
        original = self.summary(receipt)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=self.invoice["children"][0]["result"]["expenditure_id"], payment_date=date(2026, 1, 12),
            funding_allocations=[dict(funding_source=self.source.pk, amount="50")])
        lot = inventory.SharedConsumableLot.objects.get(pk=self.invoice["children"][0]["result"]["lot_id"])
        inventory.record_inventory_issue(**inventory.issue(self, lot))
        self.period.status = PeriodStatus.CLOSED
        self.period.save(update_fields=["status"])
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("0.00"))
        before = proof.snapshot()
        self.assertEqual(self.summary(receipt), original)
        self.assertEqual(proof.snapshot(), before)

    def test_utc_instant_dates_and_exact_money_do_not_depend_on_display_timezone(self):
        receipt, _ = self.record()
        original = self.summary(receipt)
        for zone in ("Africa/Blantyre", "Pacific/Auckland", "America/Los_Angeles"):
            with override_settings(TIME_ZONE=zone):
                self.assertEqual(self.summary(receipt), original)
        self.assertTrue(original["recorded_at"].endswith("+00:00"))
        self.assertIsInstance(original["amount"], str)

    def test_historical_accepted_payment_is_not_redated_or_rejected_by_new_capture_clock_rule(self):
        receipt, _ = self.record()
        original = self.summary(receipt)
        with patch.object(summaries.settlements.timezone, "localdate", return_value=date(2026, 1, 3)):
            self.assertEqual(self.summary(receipt), original)
        self.assertEqual(original["payment_date"], "2026-01-12")

    def test_executable_schema_does_not_require_ignored_documentation(self):
        receipt, _ = self.record()
        with patch.object(Path, "is_file", return_value=False):
            self.validate(self.summary(receipt))

    def test_exactly_one_hundred_explicit_funding_rows_can_be_verified_without_truncation(self):
        capture = references.request(self)
        for invoice in capture["invoices"]:
            for line in invoice["lines"]:
                amount = format(Decimal(line["amount"]) / 25, ".2f")
                line["funding_allocations"] = [dict(funding_source=self.source.pk, amount=amount) for _ in range(25)]
        record_referenced_inventory_payment(**capture)
        receipt = FinancialCommandReceipt.objects.get(pk=capture["submission_id"])
        before = proof.snapshot()
        summary = self.summary(receipt)
        self.validate(summary)
        self.assertEqual(FundingAllocation.objects.count(), 100)
        self.assertEqual(summary["amount"], "150.00")
        self.assertEqual(sum(len(invoice["lines"]) for invoice in summary["invoices"]), 4)
        self.assertEqual(proof.snapshot(), before)

    def test_large_unicode_notes_are_not_leaked_or_silently_truncated_into_summary(self):
        supplier = "🐔" * 160
        original = record_inventory_invoice(**invoices.invoice_request(self,
            supplier=supplier, invoice_reference="SYNTHETIC-UNICODE-INVOICE"))[0]
        receipt, _ = self.record(payee=supplier, external_reference="💵" * 120, notes="🔒" * 4000,
            invoices=[references.invoice_payment(self, original)], total_payment_amount="75")
        summary = self.summary(receipt)
        self.validate(summary)
        self.assertEqual(summary["payee"], supplier)
        self.assertEqual(summary["external_reference"], "💵" * 120)
        self.assertTrue(summary["note_available"])
        self.assertNotIn("🔒", canonical(summary))

    def test_oversized_summary_refuses_instead_of_truncating_evidence(self):
        receipt, _ = self.record()
        before = proof.snapshot()
        with patch.object(summaries, "MAX_SUMMARY_BYTES", 100):
            with self.assertRaises(ValidationError) as error:
                self.summary(receipt)
        self.assertIn("payment_summary_limit", error.exception.detail)
        self.assertEqual(proof.snapshot(), before)

    def test_excessive_verification_graph_refuses_before_deep_domain_scan(self):
        receipt, result = self.record()
        for invoice in result["capture"]["invoices"]:
            for line in invoice["lines"]:
                line["funding_allocations"] = [dict(funding_source=self.source.pk, amount="1.00")
                    for _ in range(int(Decimal(line["amount"])))]
        self.reseal(receipt, "phase6-inventory-referenced-payment", result)
        before = proof.snapshot()
        with patch.object(summaries.settlements, "_invoice", side_effect=AssertionError("bounded read must refuse before invoice scan")):
            with self.assertRaises(ValidationError) as error:
                self.summary(receipt)
        self.assertIn("payment_summary_limit", error.exception.detail)
        self.assertEqual(proof.snapshot(), before)

    def test_mutating_returned_summary_cannot_change_original_permanent_receipt(self):
        receipt, _ = self.record()
        before = proof.snapshot()
        summary = self.summary(receipt)
        summary["invoices"][0]["lines"][0]["amount"] = "999.00"
        summary["notes"] = "not allowed"
        with self.assertRaises(SchemaError):
            self.validate(summary)
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(self.summary(receipt)["amount"], "150.00")

    def test_fifty_selected_lines_have_a_complete_bounded_positive_summary(self):
        invoice = scoped.InventoryPaymentProofScopeTests.invoice(self, 50)
        selected = [dict(invoice_line_index=index, amount="0.50",
            funding_allocations=[dict(funding_source=self.source.pk, amount="0.50")]) for index in range(50)]
        receipt, _ = self.record(invoices=[dict(invoice_group_id=invoice["invoice_group_id"],
            invoice_version=invoice["invoice_version"], total_payment_amount="25.00", lines=selected)], total_payment_amount="25.00")
        before = proof.snapshot()
        summary = self.summary(receipt)
        self.validate(summary)
        self.assertEqual(len(summary["invoices"][0]["lines"]), 50)
        self.assertEqual(summary["invoices"][0]["lines"][-1], dict(line_index=49, amount="0.50"))
        self.assertEqual(summary["amount"], "25.00")
        self.assertEqual(proof.snapshot(), before)
