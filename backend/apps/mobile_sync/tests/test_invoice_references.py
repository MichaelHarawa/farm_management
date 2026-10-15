"""Private invoice parents: original evidence, no cash or offline authority."""
from copy import deepcopy
import json
from threading import Event, Thread
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import ConsumableItem, FinancialCommandReceipt, JournalLine, PeriodStatus, SharedConsumableLot
from apps.finance.services.inventory_invoices import _child_id, record_inventory_invoice
from apps.finance.services.inventory_referenced_payments import record_referenced_inventory_payment
from apps.finance.services.inventory_conversion_setup import configure_inventory_unit
from apps.finance.tests import test_inventory_invoices as invoices, test_inventory_referenced_payments as payments
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import invoice_references as references, schema_invoice_references as wire
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import SyncOperationReceipt
from apps.mobile_sync.projections import canonical
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_financial_uuid import UUIDFixture


SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCES": True, "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS": True}


class InvoiceFixture(BridgeFixture):
    def catalog(self, **kwargs):
        result = references.invoice_reference_catalog(self.user, self.session, self.token, **kwargs)
        Draft7Validator(wire.CATALOG, format_checker=FormatChecker()).validate(result)
        return result

    def detail(self, original=None, **kwargs):
        original = original or self.invoice
        result = references.invoice_reference_detail(original["invoice_group_id"], original["invoice_version"],
            self.user, self.session, self.token, **kwargs)
        Draft7Validator(wire.DETAIL, format_checker=FormatChecker()).validate(result)
        return result

    def refused(self, call, code):
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            call()
        self.assertEqual(error.exception.detail["code"], code)
        self.assertEqual(self.snapshot(), before)
        return error.exception


@override_settings(**SETTINGS)
class InvoiceReferenceTests(InvoiceFixture, TestCase):
    def test_catalog_and_detail_twenty_repeats_do_not_write_money_metadata_or_receipts(self):
        before = self.snapshot()
        first = self.catalog()
        detail = self.detail()
        for _ in range(20):
            self.assertEqual(self.catalog()["rows"], first["rows"])
            self.assertEqual(self.detail()["detail_version"], detail["detail_version"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(first["total_authorized_rows"], 2)
        self.assertEqual(detail["invoice"]["original_total_purchase_cost"], "150.00")
        self.assertEqual([row["original_line_cost"] for row in detail["lines"]], ["100.00", "50.00"])
        self.assertEqual([row["invoice_line_index"] for row in detail["lines"]], [0, 1])
        self.assertEqual(detail["lines"][0]["captured_quantity"], "10.0000")
        self.assertEqual(detail["lines"][0]["captured_unit"], "kg")
        for name in ("notes", "actor_id", "item_id", "location_id", "expenditure_id", "lot_id", "journal_id",
                "funding_source", "owner_id", "current_balance", "amount_due", "quantity_available"):
            self.assertNotIn('"' + name + '"', canonical([first, detail]))
        self.assertEqual(detail["payment_authority"], "none_revalidate_payables_and_cash_on_posting")
        self.assertEqual(detail["offline_cache_seconds"], 0)
        self.assertFalse(detail["financial_uploads"])

    def test_payment_does_not_relabel_original_total_as_outstanding_or_change_original_version(self):
        first = self.catalog()
        detail = self.detail()
        with sync_boundary():
            record_referenced_inventory_payment(**payments.request(self))
        self.assertEqual(self.catalog()["catalog_version"], first["catalog_version"])
        self.assertEqual(self.detail()["detail_version"], detail["detail_version"])
        self.assertEqual(self.detail()["invoice"]["original_total_purchase_cost"], "150.00")

    def test_original_labels_survive_current_item_and_location_rename(self):
        detail = self.detail()
        # Ordinary managed-item renames are guarded already. Simulate a later
        # privileged display-name edit only in this owned scratch database.
        corrupt_inventory(ConsumableItem, self.item.pk, name="Renamed current item")
        with sync_boundary():
            self.location.name = "Renamed current location"
            self.location.save(update_fields=["name"])
        self.assertEqual(self.detail()["lines"], detail["lines"])
        self.assertEqual(self.detail()["detail_version"], detail["detail_version"])

    def test_explicit_grams_and_managed_custom_unit_preserve_both_quantities(self):
        with override_settings(FINANCE_INVENTORY_UNIT_CONVERSIONS=True), sync_boundary():
            definition = configure_inventory_unit(submission_id=uuid.uuid4(), user=self.user, item_id=self.item.pk,
                quantity_unit="bag", base_unit="kg", to_base_multiplier="50", reason="Synthetic unit definition")[0]
            request = invoices.invoice_request(self, invoice_reference="SYNTHETIC-CATALOG-UNITS")
            request["lines"][0].update(quantity="2", quantity_unit="bag", unit_conversion_id=definition["configuration_id"])
            request["lines"][1].update(quantity="5000", quantity_unit="g")
            original = record_inventory_invoice(**request)[0]
        detail = self.detail(original)  # Historical proof remains readable with new-capture flag off.
        self.assertEqual([(line["captured_quantity"], line["captured_unit"], line["base_quantity"], line["base_unit"])
            for line in detail["lines"]], [("2.0000", "bag", "100.0000", "kg"), ("5000.0000", "g", "5.0000", "kg")])

    def test_catalog_pages_exact_ids_and_no_partial_page_as_complete_total(self):
        before = self.snapshot()
        with patch.object(references, "PAGE_ROWS", 1):
            first = self.catalog()
            last = self.catalog(cursor=first["next_cursor"])
        self.assertEqual((len(first["rows"]), len(last["rows"])), (1, 1))
        self.assertEqual(first["total_authorized_rows"], 2)
        self.assertIsNone(last["next_cursor"])
        self.assertEqual([row["invoice_group_id"] for row in first["rows"] + last["rows"]],
            sorted([self.invoice["invoice_group_id"], self.second["invoice_group_id"]]))
        self.assertEqual(set(signing.loads(first["next_cursor"], salt=references.BASIS + "-cursor")),
            {"version", "scope", "catalog", "last"})
        self.assertEqual(self.snapshot(), before)

    def test_changed_catalog_requires_restart_without_changing_old_pending_parent(self):
        original = deepcopy(self.invoice)
        with patch.object(references, "PAGE_ROWS", 1):
            cursor = self.catalog()["next_cursor"]
            with sync_boundary():
                record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-CATALOG-THIRD"))
            self.refused(lambda: self.catalog(cursor=cursor), "invoice_catalog_changed")
        self.assertEqual(self.invoice, original)
        self.assertEqual(self.detail()["invoice"]["invoice_version"], original["invoice_version"])

    def test_invalid_expired_or_wrong_profile_cursor_is_refused(self):
        with patch.object(references, "PAGE_ROWS", 1):
            cursor = self.catalog()["next_cursor"]
            for value in (7, "", "x" * 2049, cursor + "tamper", signing.dumps([], salt=references.BASIS + "-cursor")):
                self.refused(lambda: self.catalog(cursor=value), "invoice_catalog_changed")
            with patch.object(signing, "loads", side_effect=signing.SignatureExpired):
                self.refused(lambda: self.catalog(cursor=cursor), "invoice_catalog_changed")

    def test_changed_scope_or_device_invalidates_cursor(self):
        with patch.object(references, "PAGE_ROWS", 1):
            cursor = self.catalog()["next_cursor"]
            self.role(RoleChoices.FARM_MANAGER)
            self.refused(lambda: self.catalog(cursor=cursor), "invoice_catalog_changed")
            cursor = self.catalog()["next_cursor"]
            _, _, self.session, self.token = self.register(self.user)
            self.refused(lambda: self.catalog(cursor=cursor), "invoice_catalog_changed")

    def test_original_actor_other_current_device_can_read_but_scope_is_device_bound(self):
        first = self.detail()
        _, _, self.session, self.token = self.register(self.user)
        second = self.detail()
        self.assertNotEqual(first["scope_revision"], second["scope_revision"])
        self.assertEqual(first["invoice"], second["invoice"])
        self.assertEqual(first["lines"], second["lines"])

    def test_missing_foreign_and_wrong_type_are_same_protected_not_found(self):
        foreign = get_user_model().objects.create_superuser(username="invoice-foreign", email="invoice-foreign@example.invalid", password="Synthetic-only-password")
        owned = deepcopy(self.invoice)
        _, _, self.session, self.token = self.register(foreign)
        original_actor = self.user
        self.user = foreign
        self.assertEqual(self.catalog()["rows"], [])
        candidates = [owned["invoice_group_id"], str(uuid.uuid4()), str(_child_id(owned["invoice_group_id"], 0))]
        errors = []
        for group in candidates:
            errors.append(self.refused(lambda: references.invoice_reference_detail(group, owned["invoice_version"],
                self.user, self.session, self.token), "invoice_reference_unavailable").detail)
        self.assertTrue(all(error == errors[0] for error in errors))
        self.user = original_actor

    def test_incomplete_owned_parent_is_not_listed_or_adopted(self):
        corrupt_inventory(FinancialCommandReceipt, self.invoice["invoice_group_id"], completed_at=None)
        self.assertEqual(self.catalog()["total_authorized_rows"], 1)
        self.refused(self.detail, "invoice_reference_unavailable")

    def test_worker_and_read_only_stakeholder_cannot_select_invoice_money(self):
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER):
            self.role(role)
            self.refused(self.catalog, "permission_denied")
            self.refused(self.detail, "permission_denied")

    def test_current_manager_supervisor_director_and_admin_can_select_only_owned(self):
        for role in (RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR, RoleChoices.DIRECTOR, RoleChoices.ADMIN):
            self.role(role)
            self.assertEqual(self.catalog()["total_authorized_rows"], 2)
            self.detail()

    def test_disabled_reference_operational_or_capture_gate_refuses_before_any_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_REFERENCES", "MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{flag: False}), CaptureQueriesContext(connection) as queries:
                with self.assertRaises(SyncError):
                    references.invoice_reference_catalog(self.user, self.session, self.token)
                with self.assertRaises(SyncError):
                    self.detail()
            self.assertEqual(len(queries), 0)

    def test_malformed_id_and_version_are_not_normalized_or_substituted(self):
        for group, version in (("7", self.invoice["invoice_version"]), (7, self.invoice["invoice_version"]),
                (self.invoice["invoice_group_id"] + "\n", self.invoice["invoice_version"]),
                (self.invoice["invoice_group_id"], self.invoice["invoice_version"] + "\n")):
            self.refused(lambda: references.invoice_reference_detail(group, version, self.user, self.session, self.token), "malformed_request")
        self.refused(lambda: references.invoice_reference_detail(self.invoice["invoice_group_id"], "0" * 64,
            self.user, self.session, self.token), "invoice_reference_changed")

    def test_revoked_session_wrong_principal_and_foreign_deployment_cannot_read(self):
        wrong = dict(self.token.payload)
        wrong["user_id"] = str(uuid.uuid4())
        self.refused(lambda: references.invoice_reference_catalog(self.user, self.session, wrong), "foreign_actor")
        wrong = dict(self.token.payload)
        wrong["deployment_id"] = str(uuid.uuid4())
        self.refused(lambda: references.invoice_reference_catalog(self.user, self.session, wrong), "device_revoked")
        self.session.revoked_at = self.session.created_at
        self.session.save(update_fields=["revoked_at"])
        self.refused(self.catalog, "device_revoked")

    def test_immutable_capture_damage_refuses_catalog_and_detail_without_repair(self):
        parent = FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"])
        damaged = deepcopy(parent.result)
        damaged["capture"]["total_purchase_cost"] = "151.00"
        corrupt_inventory(FinancialCommandReceipt, parent.pk, result=json.dumps(damaged))
        self.refused(self.catalog, "invoice_reference_review_required")
        self.refused(self.detail, "invoice_reference_review_required")

    def test_missing_current_child_keeps_historical_catalog_but_detail_requires_review(self):
        parent = self.catalog()
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM finance_financialcommandreceipt WHERE submission_id=%s', [_child_id(self.invoice["invoice_group_id"], 0)])
        self.assertEqual(self.catalog()["catalog_version"], parent["catalog_version"])
        self.refused(self.detail, "invoice_reference_review_required")

    def test_current_source_or_whole_journal_damage_refuses_detail_not_historical_acceptance(self):
        child = self.invoice["children"][0]["result"]
        journal_line = JournalLine.objects.filter(journal_entry_id=child["journal_id"]).first()
        corrupt_inventory(JournalLine, journal_line.pk, debit="1.00")
        self.assertEqual(self.catalog()["total_authorized_rows"], 2)
        self.refused(self.detail, "invoice_reference_review_required")

    def test_original_lot_name_or_unit_damage_is_not_projected_as_original_evidence(self):
        child = self.invoice["children"][0]["result"]
        corrupt_inventory(SharedConsumableLot, child["lot_id"], item="Damaged original lot label", unit_of_measurement="wrong-unit")
        self.assertEqual(self.catalog()["total_authorized_rows"], 2)
        self.refused(self.detail, "invoice_reference_review_required")

    def test_excess_journal_graph_is_refused_before_existing_proof_materializes_it(self):
        with patch.object(references.JournalLine.objects, "filter") as query, patch.object(references, "_invoice",
                side_effect=AssertionError("Must not materialize excessive graph")):
            query.return_value.count.return_value = 101
            self.refused(self.detail, "invoice_reference_review_required")

    def test_closed_period_and_disabled_new_domain_capture_do_not_erase_original_invoice(self):
        with sync_boundary():
            self.period.status = PeriodStatus.CLOSED
            self.period.save(update_fields=["status"])
        with override_settings(FINANCE_INVENTORY_INVOICES=False, MOBILE_SYNC_FINANCIAL_COMMANDS=False,
                MOBILE_SYNC_FINANCIAL_UUID_COMMANDS=False):
            self.detail()
            self.catalog()

    def test_catalog_row_proof_and_display_budgets_refuse_instead_of_truncating(self):
        for name, value in (("MAX_CATALOG_ROWS", 1), ("MAX_RECEIPT_BYTES", 1), ("MAX_PROOF_BYTES", 1),
                ("MAX_CATALOG_BYTES", 1)):
            with patch.object(references, name, value):
                self.refused(self.catalog, "invoice_reference_limit")
        with patch.object(references, "MAX_DETAIL_BYTES", 1):
            self.refused(self.detail, "invoice_reference_limit")

    def test_oversize_guard_uses_postgres_octet_length_before_fetching_json(self):
        with patch.object(references, "MAX_RECEIPT_BYTES", 1), CaptureQueriesContext(connection) as queries:
            with self.assertRaises(SyncError):
                self.catalog()
        relevant = [query["sql"] for query in queries if "finance_financialcommandreceipt" in query["sql"]]
        self.assertEqual(len(relevant), 1)
        self.assertIn("OCTET_LENGTH", relevant[0])
        self.assertNotIn('"finance_financialcommandreceipt"."result",', relevant[0])

    def test_late_role_change_aborts_release_and_rolls_back_unrelated_test_change(self):
        self.role(RoleChoices.DIRECTOR)
        original = references._row
        changed = []
        def downgrade(receipt):
            row = original(receipt)
            if not changed:
                changed.append(True)
                self.role(RoleChoices.FARM_MANAGER)
            return row
        with patch.object(references, "_row", side_effect=downgrade):
            self.refused(self.catalog, "invoice_reference_scope_changed")

    def test_late_detail_revocation_does_not_release_money_or_write_any_evidence(self):
        original = references._invoice
        def revoke(*args):
            parent = original(*args)
            self.session.revoked_at = self.session.created_at
            self.session.save(update_fields=["revoked_at"])
            return parent
        with patch.object(references, "_invoice", side_effect=revoke):
            self.refused(self.detail, "device_revoked")

    def test_output_schema_refuses_future_fields_balances_and_offline_authority(self):
        detail = self.detail()
        for value in ({**detail, "offline_cache_seconds": 86400}, {**detail, "financial_uploads": True},
                {**detail, "balance": "150.00"}, {**detail, "invoice": {**detail["invoice"], "notes": "Private"}},
                {**detail, "lines": [{**detail["lines"][0], "item_id": "7"}, detail["lines"][1]]}):
            self.assertFalse(Draft7Validator(wire.DETAIL, format_checker=FormatChecker()).is_valid(value))


@override_settings(**SETTINGS)
class InvoiceUUIDIntegrationTests(UUIDFixture, TestCase):
    def test_catalog_and_detail_supply_exact_original_parent_for_uuid_payment(self):
        page = references.invoice_reference_catalog(self.user, self.session, self.token)
        command = self.command()
        versions = {row["invoice_group_id"]: row["invoice_version"] for row in page["rows"]}
        for parent in command["payload"]["invoices"]:
            self.assertEqual(parent["invoice_version"], versions[parent["invoice_group_id"]])
            detail = references.invoice_reference_detail(parent["invoice_group_id"], parent["invoice_version"], self.user, self.session, self.token)
            self.assertEqual([line["invoice_line_index"] for line in parent["lines"]], [line["invoice_line_index"] for line in detail["lines"]])
        result = self.execute(command)
        self.assertEqual(result["outcome"], "accepted")
        original = self.snapshot()
        self.assertEqual(self.execute(command)["outcome"], "replayed")
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)


@override_settings(**SETTINGS)
class InvoiceScopeWaitTests(InvoiceFixture, TransactionTestCase):
    def test_waiting_reader_rechecks_permission_after_real_stream_lock(self):
        started, results, pids = Event(), [], []
        original = references.funding._access
        def observed(*args):
            value = original(*args)
            if not pids:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                started.set()
            return value
        def run():
            close_old_connections()
            try:
                references.invoice_reference_catalog(self.user, self.session, self.token)
                results.append("unexpected_success")
            except SyncError as error:
                results.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(references.funding, "_access", side_effect=observed), sync_boundary():
            thread = Thread(target=run)
            thread.start()
            self.assertTrue(started.wait(10))
            deadline, waiting = time.monotonic() + 3, False
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [pids[0]])
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                time.sleep(0.01)
            self.assertTrue(waiting, "Independent PostgreSQL reader must really wait on stream")
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            role, _ = Role.objects.get_or_create(slug=RoleChoices.GENERAL_WORKER, defaults={"name": "Synthetic worker"})
            self.user.roles.clear()
            self.user.roles.add(role)
        thread.join(25)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [403])
        self.assertFalse(SyncOperationReceipt.objects.exists())
