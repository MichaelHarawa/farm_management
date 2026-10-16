"""Private reference transport on fresh owned PostgreSQL, no native cache grant."""
from copy import deepcopy
from datetime import timedelta
from threading import Event, Thread
import json
import os
from pathlib import Path
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import RoleChoices
from apps.finance.models import FundingSource, FinancialCommandReceipt
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.finance.services.inventory_invoices import record_inventory_invoice
from apps.finance.tests import test_inventory_invoices as invoice_fixtures
from apps.mobile_sync import reference_pack as packs, schema_reference_pack as wire, financial_references as funding
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import FinancialPublicationBinding, MobileSession, SyncChange, SyncEntity, SyncStreamState
from apps.mobile_sync.projections import canonical, checksum
from apps.mobile_sync.writers import sync_boundary
from .test_reference_publication import PublicationFixture, SETTINGS as PUBLICATION_SETTINGS
from .test_sync import BASE

SETTINGS = {**PUBLICATION_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCE_PACKS": True}


class PackFixture(PublicationFixture):
    def prepare(self):
        self.seed([self.source], [self.invoice["invoice_group_id"], self.second["invoice_group_id"]])

    def begin(self):
        result = packs.begin_reference_pack(self.user, self.session, self.token)
        self.validate(result, wire.MANIFEST)
        return result

    def page(self, manifest, cursor=None):
        result = packs.reference_pack_page(manifest["snapshot_id"], cursor or manifest["next_page_cursor"], self.user, self.session, self.token)
        self.validate(result, wire.PAGE)
        return result

    def pull(self, cursor):
        result = packs.reference_pack_changes(cursor, self.user, self.session, self.token)
        self.validate(result, wire.DELTA)
        return result

    def download(self):
        manifest, values = self.begin(), []
        cursor = manifest["next_page_cursor"]
        while cursor:
            page = self.page(manifest, cursor)
            expected = manifest["manifest"][page["page"]]
            self.assertEqual((checksum(page["entities"]), len(page["entities"])), (expected["sha256"], expected["row_count"]))
            self.assertEqual(page["sha256"], expected["sha256"])
            self.assertEqual(page["expires_at"], manifest["expires_at"])
            values.extend(page["entities"])
            cursor = page["next_page_cursor"]
        self.assertEqual(len(values), manifest["row_count"])
        return manifest, values, page["delta_cursor"]

    def validate(self, value, schema):
        Draft7Validator(schema, format_checker=FormatChecker()).validate(value)

    def signed(self, cursor, **values):
        from django.core import signing
        return packs._save({**signing.loads(cursor, salt=packs.BASIS), **values})


@override_settings(**SETTINGS)
class ReferencePackTests(PackFixture, TestCase):
    def test_complete_pack_is_positive_scoped_metadata_and_no_business_or_sync_mutation(self):
        self.prepare()
        before = self.snapshot()
        manifest, rows, cursor = self.download()
        self.assertEqual(len(rows), 3)
        self.assertEqual((manifest["pack_id"], manifest["offline_cache_seconds"], manifest["financial_uploads"]), (wire.PACK, 0, False))
        self.assertEqual((manifest["deployment_id"], manifest["device_id"], manifest["actor_id"]),
            (str(self.stream.deployment_id), str(self.session.device_id), str(self.user.pk)))
        self.assertEqual({row["entity_type"] for row in rows}, set(packs.publication.TYPES))
        for name in ("source_pk", "owner_id", "notes", "journal_id", "available_balance", "current_outstanding"):
            self.assertNotIn('"' + name + '"', canonical(rows))
        self.assertTrue(self.pull(cursor)["run_complete"])
        self.assertEqual(self.snapshot(), before)
        target = os.environ.get("MOBILE_REFERENCE_PACK_FIXTURE_OUTPUT")
        if target:
            # Explicit generated cross-language evidence from this OWNED DB only.
            root = Path(__file__).resolve().parents[4]
            output = (root / target).resolve()
            self.assertTrue(connection.settings_dict["NAME"].startswith("test_mobile_phase02_"))
            self.assertTrue(output.is_relative_to(root / "docs/mobile/evidence"))
            self.assertTrue(output.name.startswith("phase06-reference-pack-cross-language-"))
            original_finance = self.snapshot()["finance"]
            with patch.object(packs, "PAGE_ROWS", 1):
                generated, pages, point = self.begin(), [], None
                next_cursor = generated["next_page_cursor"]
                while next_cursor:
                    page = self.page(generated, next_cursor)
                    pages.append(page)
                    next_cursor, point = page["next_page_cursor"], page["delta_cursor"]
                with sync_boundary():
                    source = self.extra()
                    source.description = "Synthetic café 🐔 loan"
                    source.save(update_fields=["description"])
                upsert = self.pull(point)
                with sync_boundary():
                    source.delete()
                tombstone = self.pull(upsert["next_cursor"])
                self.assertEqual(len(upsert["changes"]), 1)
                self.assertEqual(len(tombstone["changes"]), 1)
                self.assertEqual(self.snapshot()["finance"], original_finance)
                value = {"owned_database": connection.settings_dict["NAME"], "http_or_native": False,
                    "financial_effects_unchanged": True, "expected": {"identity": {"deploymentId": generated["deployment_id"],
                        "actorId": generated["actor_id"], "deviceId": generated["device_id"]},
                        "epoch": generated["stream_epoch"], "scopeRevision": generated["scope_revision"]},
                    "manifest": generated, "pages": pages, "deltas": [upsert, tombstone]}
            with output.open("x", encoding="utf-8") as destination:
                destination.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    def test_empty_authorized_scope_has_real_complete_empty_page_not_unprepared_fake_empty(self):
        # Only the original actor's invoices are in scope; managers do not see owner capital.
        with sync_boundary():
            other = get_user_model().objects.create_user(username="pack-empty", email="pack-empty@example.invalid")
            other.roles.add(self.user.roles.model.objects.get(slug=RoleChoices.FARM_MANAGER))
        _, _, session, token = self.register(other)
        manifest = packs.begin_reference_pack(other, session, token)
        self.assertEqual((manifest["row_count"], manifest["manifest"][0]["row_count"]), (0, 0))
        page = packs.reference_pack_page(manifest["snapshot_id"], manifest["next_page_cursor"], other, session, token)
        self.assertEqual(page["entities"], [])
        self.assertIsNotNone(page["delta_cursor"])
        self.refused(self.begin, "financial_reference_pack_not_prepared")

    def test_twenty_page_retries_are_identical_except_server_time_and_keep_absolute_expiry(self):
        self.prepare()
        manifest, before = self.begin(), self.snapshot()
        first = self.page(manifest)
        for _ in range(20):
            replay = self.page(manifest)
            for name in ("server_time", "delta_cursor"):
                replay.pop(name)
            expected = {key: value for key, value in first.items() if key not in ("server_time", "delta_cursor")}
            self.assertEqual(replay, expected)
        self.assertEqual(self.snapshot(), before)
        from django.core import signing
        self.assertEqual(signing.loads(first["delta_cursor"], salt=packs.BASIS)["expires"],
            signing.loads(manifest["next_page_cursor"], salt=packs.BASIS)["expires"])

    def test_pagination_is_complete_ordered_and_first_pages_do_not_yield_delta_cursor(self):
        self.prepare()
        with patch.object(packs, "PAGE_ROWS", 1):
            manifest, rows, cursor = self.download()
            self.assertEqual(len(manifest["manifest"]), 3)
            self.assertEqual([(row["entity_type"], row["entity_uuid"]) for row in rows],
                sorted((row["entity_type"], row["entity_uuid"]) for row in rows))
            first = self.page(manifest)
            self.assertIsNone(first["delta_cursor"])
            self.assertIsNotNone(first["next_page_cursor"])
            self.assertTrue(self.pull(cursor)["run_complete"])

    def test_new_process_rebuilds_page_without_server_memory_or_files(self):
        self.prepare()
        manifest = self.begin()
        first = self.page(manifest)
        import importlib
        # Module reload removes any possible module-local page collection/cache.
        importlib.reload(packs)
        second = self.page(manifest)
        self.assertEqual(second["entities"], first["entities"])
        self.assertEqual(second["sha256"], first["sha256"])
        self.assertEqual(second["expires_at"], first["expires_at"])

    def test_changes_during_bootstrap_refuse_old_staging_and_never_replace_it_silently(self):
        self.prepare()
        manifest = self.begin()
        self.extra()
        self.refused(lambda: self.page(manifest), "financial_reference_pack_changed")
        self.assertEqual(self.begin()["row_count"], 4)

    def test_unrelated_operational_write_does_not_invalidate_unchanged_reference_catalog(self):
        self.prepare()
        manifest = self.begin()
        with sync_boundary():
            self.batch.save()
        page = self.page(manifest)
        self.assertEqual(page["watermark"], manifest["watermark"])
        self.assertGreater(SyncStreamState.objects.get().sequence, int(page["watermark"]))
        delta = self.pull(page["delta_cursor"])
        self.assertEqual(delta["changes"], [])
        self.assertTrue(delta["run_complete"])

    def test_current_role_owner_and_other_invoice_actor_filtering(self):
        self.prepare()
        loan = self.extra()
        self.role(RoleChoices.FARM_MANAGER)
        _, rows, _ = self.download()
        self.assertEqual(len(rows), 3)
        self.assertNotIn("owner_capital", canonical(rows))
        with sync_boundary():
            other = get_user_model().objects.create_user(username="pack-admin", email="pack-admin@example.invalid", is_superuser=True)
        _, _, session, token = self.register(other)
        manifest = packs.begin_reference_pack(other, session, token)
        page = packs.reference_pack_page(manifest["snapshot_id"], manifest["next_page_cursor"], other, session, token)
        self.assertEqual(len(page["entities"]), 2)
        self.assertTrue(all(row["entity_type"] == "finance.funding_selection" for row in page["entities"]))
        self.assertNotIn(self.invoice["invoice_group_id"], canonical(page))
        self.assertIn(str(self.entity(loan).entity_uuid), canonical(page))

    def test_role_change_same_actor_new_session_and_device_force_scope_restart(self):
        self.prepare()
        manifest = self.begin()
        _, _, session, token = self.register(self.user)
        self.refused(lambda: packs.reference_pack_page(manifest["snapshot_id"], manifest["next_page_cursor"], self.user, session, token),
            "financial_reference_pack_scope_changed")
        self.role(RoleChoices.FARM_MANAGER)
        self.refused(lambda: self.page(manifest), "financial_reference_pack_scope_changed")

    def test_worker_stakeholder_unbound_foreign_and_revoked_sessions_cannot_download(self):
        self.prepare()
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER):
            self.role(role)
            self.refused(self.begin, "permission_denied")
        self.role(RoleChoices.ADMIN)
        bad = deepcopy(self.token)
        bad["deployment_id"] = str(uuid.uuid4())
        self.refused(lambda: packs.begin_reference_pack(self.user, self.session, bad))
        with sync_boundary():
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        self.refused(self.begin)

    def test_every_missing_gate_refuses_before_any_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_REFERENCE_PACKS", "MOBILE_SYNC_FINANCIAL_PUBLICATION",
                "MOBILE_SYNC_FINANCIAL_REFERENCES", "MOBILE_SYNC_FINANCIAL_READS", "MOBILE_SYNC_CAPTURE", "MOBILE_SYNC_ENABLED"):
            with override_settings(**{flag: False}), self.assertNumQueries(0):
                for action in (self.begin, lambda: packs.reference_pack_page(str(uuid.uuid4()), "not-a-cursor", self.user, self.session, self.token),
                        lambda: self.pull("not-a-cursor")):
                    with self.assertRaises(SyncError):
                        action()

    def test_expiry_clock_rollback_and_cursor_tampering_are_explicit(self):
        self.prepare()
        now = timezone.now()
        with patch.object(packs.timezone, "now", return_value=now):
            manifest = self.begin()
        for value in (now + timedelta(seconds=packs.TTL), now - timedelta(seconds=2)):
            with patch.object(packs.timezone, "now", return_value=value):
                self.refused(lambda: self.page(manifest), "financial_reference_pack_expired")
        self.refused(lambda: self.page(manifest, manifest["next_page_cursor"] + "bad"), "invalid_cursor")
        self.refused(lambda: packs.reference_pack_page(str(uuid.uuid4()), manifest["next_page_cursor"], self.user, self.session, self.token), "invalid_cursor")

    def test_strict_signed_cursor_fields_counters_and_profile_configuration(self):
        self.prepare()
        manifest = self.begin()
        for values in ({"v": True}, {"page": True}, {"watermark": "1"}, {"page": 99999}, {"extra": "field"}, {"catalog": "bad"},
                {"watermark": 9223372036854775807}, {"issued": True}, {"expires": 0}, {"snapshot": str(uuid.uuid4())}):
            self.refused(lambda: self.page(manifest, self.signed(manifest["next_page_cursor"], **values)), "invalid_cursor")
        with patch.object(packs, "PAGE_ROWS", 1):
            self.refused(lambda: self.page(manifest), "financial_reference_pack_scope_changed")

    def test_late_scope_loss_returns_no_pack_and_preserves_all_evidence(self):
        self.prepare()
        original = packs._scope
        calls = []
        def changed(*args):
            calls.append(1)
            return original(*args) if len(calls) == 1 else "0" * 64
        with patch.object(packs, "_scope", side_effect=changed):
            self.refused(self.begin, "financial_reference_pack_scope_changed")

    def test_incomplete_and_stale_capture_is_review_never_fake_empty_or_baseline(self):
        self.refused(self.begin, "financial_reference_pack_not_prepared")
        self.prepare()
        with override_settings(MOBILE_SYNC_FINANCIAL_PUBLICATION=False), sync_boundary():
            FundingSource.objects.filter(pk=self.source.pk).update(description="Flag-off gap")
        self.refused(self.begin, "financial_reference_pack_review_required")

    def test_missing_binding_source_or_corrupted_positive_projection_refuses(self):
        self.prepare()
        entity = self.entity()
        corrupt_inventory(SyncEntity, entity.pk, payload=json.dumps({**entity.payload, "private_balance": "999.00"}))
        self.refused(self.begin, "financial_reference_pack_review_required")

    def test_snapshot_row_byte_and_time_budgets_fail_before_partial_response(self):
        self.prepare()
        for field, value in (("MAX_ROWS", 1), ("MAX_BYTES", 1), ("PAGE_BYTES", 8192)):
            with patch.object(packs, field, value):
                self.refused(self.begin, "financial_reference_pack_limit")
        with patch.object(packs.time, "monotonic", side_effect=[0, 11]):
            self.refused(self.begin, "financial_reference_pack_limit")

    def test_delta_upsert_and_tombstone_retain_original_uuid_and_monotonic_revision(self):
        self.prepare()
        _, _, cursor = self.download()
        source = self.extra()
        first = self.pull(cursor)
        self.assertEqual(len(first["changes"]), 1)
        original = self.entity(source)
        self.assertEqual(first["changes"][0]["entity_uuid"], str(original.entity_uuid))
        with sync_boundary():
            source.delete()
        second = self.pull(first["next_cursor"])
        self.assertEqual([(row["kind"], row["revision"]) for row in second["changes"]], [("tombstone", "2")])
        self.assertNotIn("payload", second["changes"][0])

    def test_hidden_global_and_operational_history_is_sql_redacted_not_returned(self):
        self.prepare()
        self.role(RoleChoices.FARM_MANAGER)
        _, _, cursor = self.download()
        with sync_boundary():
            self.batch.save()
            FundingSource.objects.filter(pk=self.source.pk).update(is_active=False)
        with CaptureQueriesContext(connection) as queries:
            delta = self.pull(cursor)
        self.assertEqual(delta["changes"], [])
        self.assertTrue(delta["run_complete"])
        self.assertTrue(delta["fragments"][-1]["fragment_final"])
        sql = [row["sql"] for row in queries if 'AS "reference_payload"' in row["sql"]]
        self.assertTrue(sql)
        self.assertTrue(all("CASE WHEN" in statement for statement in sql))
        self.assertNotIn("owner_capital", canonical(delta))
        self.assertNotIn("poultry.", canonical(delta))

    def test_partial_mixed_group_finishes_on_hidden_tail_and_watermark_does_not_move(self):
        self.prepare()
        _, _, cursor = self.download()
        with sync_boundary():
            self.batch.save()
            self.extra()
        with patch.object(packs, "SCAN_ROWS", 1):
            first = self.pull(cursor)
            self.assertFalse(first["run_complete"])
            upper = first["run_watermark"]
            self.extra()  # Must wait for NEXT run, not alter the frozen upper.
            rows, fragments, current = [], [], first
            while True:
                rows += current["changes"]
                fragments += current["fragments"]
                if current["run_complete"]:
                    break
                current = self.pull(current["next_cursor"])
                self.assertEqual(current["run_watermark"], upper)
            self.assertEqual(len(rows), 1)
            self.assertTrue(fragments[-1]["fragment_final"])
            self.assertFalse(fragments[0]["fragment_final"])
            self.assertEqual(len(self.pull(current["next_cursor"])["changes"]), 1)

    def test_opaque_hidden_final_fragment_after_visible_partial_group(self):
        self.prepare()
        self.role(RoleChoices.FARM_MANAGER)
        _, _, cursor = self.download()
        with sync_boundary():
            self.extra()
            FundingSource.objects.filter(pk=self.source.pk).update(is_active=False)
        with patch.object(packs, "SCAN_ROWS", 1):
            # Source sort order may put hidden owner first. Both fragments must
            # remain one group, then complete without leaking the hidden type.
            first = self.pull(cursor)
            second = self.pull(first["next_cursor"])
        self.assertFalse(first["run_complete"])
        self.assertTrue(second["run_complete"])
        self.assertEqual(len(first["changes"]) + len(second["changes"]), 1)
        self.assertEqual(first["fragments"][0]["transaction_id"], second["fragments"][0]["transaction_id"])
        self.assertEqual([first["fragments"][0]["fragment_index"], second["fragments"][0]["fragment_index"]], [0, 1])
        self.assertTrue(second["fragments"][0]["fragment_final"])

    def test_pruned_history_restarts_without_changing_business_or_original_commands(self):
        self.prepare()
        manifest, _, cursor = self.download()
        self.extra()
        with sync_boundary():
            SyncStreamState.objects.filter(pk=1).update(minimum_sequence=SyncStreamState.objects.get().sequence)
        self.refused(lambda: self.page(manifest), "resync_required")
        self.refused(lambda: self.pull(cursor), "resync_required")

    def test_foreign_original_invoice_change_is_hidden_even_from_admin(self):
        self.prepare()
        _, _, cursor = self.download()
        with sync_boundary():
            other = get_user_model().objects.create_user(username="pack-foreign-writer", email="pack-foreign-writer@example.invalid", is_superuser=True)
            result, _ = record_inventory_invoice(**invoice_fixtures.invoice_request(self, user=other, invoice_reference="SYNTHETIC-PACK-FOREIGN"))
        before = self.snapshot()
        delta = self.pull(cursor)
        self.assertEqual(delta["changes"], [])
        self.assertTrue(delta["run_complete"])
        self.assertNotIn(result["invoice_group_id"], canonical(delta))
        self.assertEqual(self.snapshot(), before)

    def test_delta_strict_counters_wrong_kinds_and_empty_midgroup_cursors_refuse(self):
        self.prepare()
        manifest, _, cursor = self.download()
        self.extra()
        for values in ({"position": True}, {"upper": -1}, {"upper": "1"}, {"position": 9223372036854775807},
                {"fragment": True}, {"group": str(uuid.uuid4()), "fragment": 0}, {"group": None, "fragment": 1},
                {"group": "not-uuid", "fragment": 1}, {"extra": "field"}):
            self.refused(lambda: self.pull(self.signed(cursor, **values)), "invalid_cursor")
        self.refused(lambda: self.pull(manifest["next_page_cursor"]), "invalid_cursor")

    def test_page_row_limit_and_hidden_descriptor_limit_do_not_stall(self):
        self.prepare()
        with patch.object(packs, "PAGE_ROWS", 1):
            _, _, cursor = self.download()
            self.extra()
            self.extra()
            first = self.pull(cursor)
            second = self.pull(first["next_cursor"])
            self.assertFalse(first["run_complete"])
            self.assertTrue(second["run_complete"])
            self.assertEqual((len(first["changes"]), len(second["changes"])), (1, 1))

    def test_missing_unpruned_change_is_not_reported_as_complete(self):
        self.prepare()
        _, _, cursor = self.download()
        self.extra()
        row = SyncChange.objects.order_by("-sequence").first()
        corrupt_inventory(SyncChange, row.pk, sequence=row.sequence + 1)
        self.refused(lambda: self.pull(cursor), "financial_reference_pack_review_required")

    def test_delta_time_budget_and_schema_never_allow_unsupported_invoice_deletion(self):
        self.prepare()
        _, _, cursor = self.download()
        source = self.extra()
        with patch.object(packs, "_current", return_value=[]), patch.object(packs.time, "monotonic", side_effect=[0, 11]):
            self.refused(lambda: self.pull(cursor), "financial_reference_pack_limit")
        with sync_boundary():
            source.delete()
        value = self.pull(cursor)
        # Last row is the supported funding tombstone, not an invoice deletion.
        changed = deepcopy(value)
        changed["changes"][-1]["entity_type"] = "finance.invoice_reference"
        self.assertFalse(Draft7Validator(wire.DELTA).is_valid(changed))
        changed = deepcopy(value)
        changed["changes"][-1]["revision"] = "1"
        self.assertFalse(Draft7Validator(wire.DELTA).is_valid(changed))

    def test_corrupt_unpruned_sequence_or_group_never_returns_false_run_completion(self):
        self.prepare()
        _, _, cursor = self.download()
        self.extra()
        row = SyncChange.objects.order_by("-sequence").first()
        corrupt_inventory(SyncChange, row.pk, transaction_count=2)
        self.refused(lambda: self.pull(cursor), "financial_reference_pack_review_required")

    def test_current_public_capabilities_and_operational_packs_do_not_expand(self):
        self.prepare()
        caps = self.client.get(BASE + "capabilities")
        self.assertFalse(caps.data["commands"]["finance"]["available"])
        self.assertEqual(self.client.get(BASE + "finance/reference-packs").status_code, 404)
        response = self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": [wire.PACK]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_pack")


@override_settings(**SETTINGS)
class ReferencePackConcurrencyTests(PackFixture, TransactionTestCase):
    def test_role_removed_during_actual_stream_wait_is_denied_before_source_lookup(self):
        self.prepare()
        started, pids, result = Event(), [], []
        original = funding._access
        def authorized(*args):
            value = original(*args)
            if not started.is_set():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                started.set()
            return value
        def run():
            close_old_connections()
            try:
                result.append(packs.begin_reference_pack(self.user, self.session, self.token))
            except SyncError as error:
                result.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(funding, "_access", side_effect=authorized), sync_boundary():
            worker = Thread(target=run)
            worker.start()
            self.assertTrue(started.wait(10))
            deadline, waiting = time.monotonic() + 3, False
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [pids[0]])
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                time.sleep(0.01)
            self.assertTrue(waiting, "Second PostgreSQL connection must actually wait")
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            self.user.roles.clear()
        worker.join(25)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [403])
