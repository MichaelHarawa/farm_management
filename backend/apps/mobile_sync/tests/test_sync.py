from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Event, Thread
from unittest.mock import patch
import time
import uuid

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Role
from apps.finance.models import AccountingPeriod, JournalEntry
from apps.poultry.models import Batch, FeedUsage, Mortality, Sales
from apps.poultry.services.batch_lifecycle import create_mortality_with_lifecycle
from apps.mobile_sync.models import (MobileDevice, SyncBootstrap, SyncChange, SyncEntity,
                                     SyncOperationReceipt, SyncStreamState)
from apps.mobile_sync.projections import CURRENT_PACK, checksum, json_value
from apps.mobile_sync.transport import decode
from apps.mobile_sync.writers import sync_boundary, UnsafeSyncWrite

BASE = "/api/v1/mobile-sync/"
TEST_SETTINGS = {"MOBILE_SYNC_CAPTURE": True, "MOBILE_SYNC_ENABLED": True,
                 "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
                 "REST_FRAMEWORK": {"DEFAULT_AUTHENTICATION_CLASSES": ["apps.mobile_sync.authentication.FarmJWTAuthentication"],
                     "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
                     "DEFAULT_THROTTLE_RATES": {"mobile_sync": "10000/min", "mobile_registration": "10000/hour"}}}


class FixtureMixin:
    def make_fixture(self):
        self.arrival = timezone.now() - timedelta(days=4)
        self.users = {}
        with sync_boundary():
            for slug in ["general_worker", "farm_supervisor", "farm_manager", "director", "stake_holder", "admin"]:
                user = get_user_model().objects.create_user(username=f"sync-{slug}", email=f"{slug}@example.invalid", password="mobile-password")
                user.roles.add(Role.objects.get(slug=slug))
                self.users[slug] = user
            self.worker = self.users["general_worker"]
            self.batch = Batch.objects.create(batch_id="SYNC-BATCH", quantity=100, entry_date=self.arrival,
                expected_maturity_date=self.arrival + timedelta(days=35), created_by=self.worker, target_selling_price="5000.00")
            self.feed = FeedUsage.objects.create(batch=self.batch, initial_age=2, feeding_start_date=self.arrival + timedelta(days=2),
                feeding_end_date=self.arrival + timedelta(days=3), feed_type="starter", feed_source="cp_feed", quantity_given=10,
                unit_of_measurement="kg", current_number_of_birds=100, notes="Feed evidence", reported_by_name="Worker")
        stream = SyncStreamState.objects.get(pk=1)
        stream.ready = True
        stream.save(update_fields=["ready"])
        self.batch_uuid = str(SyncEntity.objects.get(entity_type="poultry.batch", source_pk=str(self.batch.pk)).entity_uuid)
        self.client, self.registration = self.register(self.worker)

    def register(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        response = client.post(BASE + "devices", {"installation_id": str(uuid.uuid4()), "app_version": "test-1",
            "platform": "android", "protocol_version": 1, "device_label": "Disposable test phone"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client, response.data

    def command(self, quantity=1):
        return {"operation_id": str(uuid.uuid4()), "entity_type": "poultry.mortality", "entity_uuid": str(uuid.uuid4()),
            "action": "record", "payload_version": 1, "base_version": None, "captured_at": json_value(timezone.now()), "depends_on": [],
            "payload": {"batch_uuid": self.batch_uuid, "mortality_date": json_value(self.arrival + timedelta(days=1)),
                        "quantity_dead": quantity, "suspected_cause": "Unknown", "description": "Morning check",
                        "action_taken": "Reported", "reported_by_name": "Observed reporter"}}

    def push(self, command, client=None, registration=None):
        client = client or self.client
        registration = registration or self.registration
        return client.post(BASE + "push", {"protocol_version": 1, "device_id": registration["device_id"], "operations": [command]}, format="json")

    def snapshot(self, client=None, packs=None):
        client = client or self.client
        response = client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": packs or [CURRENT_PACK]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        manifest = response.data
        cursor, rows = manifest["next_page_cursor"], []
        while cursor:
            page = client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": cursor})
            self.assertEqual(page.status_code, 200, page.data)
            self.assertEqual(checksum(page.data["entities"]), page.data["sha256"])
            rows += page.data["entities"]
            cursor = page.data["next_page_cursor"]
        return manifest, rows, page.data["delta_cursor"]


@override_settings(**TEST_SETTINGS)
class SyncAPITests(FixtureMixin, TestCase):
    def setUp(self):
        self.make_fixture()

    def test_lost_response_twenty_retries_and_status_have_one_effect(self):
        command = self.command(2)
        first = self.push(command)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["results"][0]["outcome"], "accepted")
        for _ in range(20):
            retry = self.push(command)
            self.assertEqual(retry.data["results"][0]["outcome"], "replayed")
            self.assertEqual(retry.data["results"][0]["transaction_id"], first.data["results"][0]["transaction_id"])
        self.assertEqual(Mortality.objects.count(), 1)
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)
        record = Mortality.objects.get()
        self.assertEqual(record.age_in_days, 1)
        self.assertEqual(record.created_by, self.worker)
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.current_number_of_birds, 98)
        self.assertEqual(JournalEntry.objects.count(), 0)
        mapping = SyncEntity.objects.get(entity_type="poultry.mortality")
        self.assertEqual(str(mapping.entity_uuid), command["entity_uuid"])
        self.assertEqual(SyncChange.objects.filter(origin_operation_id=command["operation_id"]).count(), 3)
        status = self.client.get(BASE + f"operations/{command['operation_id']}")
        self.assertEqual(status.data, first.data["results"][0])

    def test_changed_quantity_target_date_or_capture_is_not_reexecuted(self):
        command = self.command()
        self.assertEqual(self.push(command).data["results"][0]["outcome"], "accepted")
        for mutate in [lambda c: c["payload"].update(quantity_dead=2),
                       lambda c: c["payload"].update(batch_uuid=str(uuid.uuid4())),
                       lambda c: c["payload"].update(mortality_date=json_value(self.arrival + timedelta(hours=3))),
                       lambda c: c.update(captured_at=json_value(timezone.now()))]:
            changed = deepcopy(command)
            mutate(changed)
            self.assertEqual(self.push(changed).data["results"][0]["code"], "idempotency_mismatch")
        self.assertEqual(Mortality.objects.count(), 1)

    def test_rejection_durable_without_source_or_stream_effect_then_superseded(self):
        command = self.command(101)
        sequence = SyncStreamState.objects.get().sequence
        rejected = self.push(command).data["results"][0]
        self.assertEqual(rejected["outcome"], "conflict")
        self.assertEqual(rejected["code"], "insufficient_birds")
        self.assertEqual(self.push(command).data["results"][0], rejected)
        self.assertEqual(SyncStreamState.objects.get().sequence, sequence)
        self.assertEqual(Mortality.objects.count(), 0)
        corrected = self.command(1)
        corrected["supersedes_operation_id"] = command["operation_id"]
        self.assertEqual(self.push(corrected).data["results"][0]["outcome"], "accepted")
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)

    def test_future_invalid_schema_unknown_fields_and_integer_coercion(self):
        for mutate in [lambda c: c["payload"].update(age_in_days=1), lambda c: c["payload"].update(quantity_dead=True),
                       lambda c: c["payload"].update(quantity_dead="1"), lambda c: c["payload"].update(batch_uuid=1),
                       lambda c: c["payload"].update(description=1), lambda c: c["payload"].update(reported_by_name=1.5),
                       lambda c: c["payload"].update(mortality_date="2026-99-99T00:00:00Z"),
                       lambda c: c["payload"].update(reported_by_name="   "), lambda c: c.update(base_version="1")]:
            command = self.command()
            mutate(command)
            self.assertEqual(self.push(command).status_code, 400)
        future = self.command()
        future["payload"]["mortality_date"] = json_value(timezone.now() + timedelta(hours=1))
        self.assertEqual(self.push(future).data["results"][0]["outcome"], "validation_failed")
        self.assertEqual(Mortality.objects.count(), 0)

    def test_existing_web_mortality_rejects_dates_flock_and_period_without_500_or_mutation(self):
        web = APIClient()
        web.force_authenticate(self.worker)
        sequence = SyncStreamState.objects.get().sequence
        body = deepcopy(self.command()["payload"])
        body.pop("batch_uuid")
        body["age_in_days"] = 999
        for invalid in [{"quantity_dead": 101}, {"mortality_date": json_value(timezone.now()+timedelta(hours=1))}]:
            response = web.post(f"/api/v1/poultry-management/{self.batch.pk}/mortality", {**body, **invalid}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        AccountingPeriod.objects.create(period_start=self.arrival.date(), period_end=timezone.now().date(), status="closed")
        response = web.post(f"/api/v1/poultry-management/{self.batch.pk}/mortality", body, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(Mortality.objects.exists())
        self.assertEqual(SyncStreamState.objects.get().sequence, sequence)

    def test_backdated_mortality_rejects_later_negative_history_even_if_total_positive(self):
        from apps.poultry.models import FlockAdjustment
        with sync_boundary():
            Sales.objects.create(batch=self.batch, sale_date=self.arrival + timedelta(days=2), product_type="live_chicken",
                quantity_sold=99, unit_price=Decimal("1.00"), amount_paid=Decimal("99.00"), buyer_name="Buyer", buyer_type="retail", sold_by_name="Manager")
            FlockAdjustment.objects.create(batch=self.batch, effective_at=self.arrival + timedelta(days=3), quantity_change=50, reason="Later arrivals", approved_by=self.worker)
        response = self.push(self.command(2))
        self.assertEqual(response.data["results"][0]["code"], "insufficient_birds")
        self.assertEqual(Mortality.objects.count(), 0)

    def test_closed_period_and_finalized_batch_preserve_original_date(self):
        AccountingPeriod.objects.create(period_start=self.arrival.date(), period_end=timezone.now().date(), status="closed")
        command = self.command()
        result = self.push(command).data["results"][0]
        self.assertEqual(result["outcome"], "period_locked")
        self.assertEqual(Mortality.objects.count(), 0)
        self.assertEqual(SyncOperationReceipt.objects.get().command["payload"]["mortality_date"], command["payload"]["mortality_date"])

    def test_dependencies_block_missing_reject_cycles_and_process_parent_first(self):
        parent, child = self.command(), self.command()
        child["depends_on"] = [parent["operation_id"]]
        self.assertEqual(self.push(child).data["results"][0]["outcome"], "dependency_blocked")
        self.assertFalse(SyncOperationReceipt.objects.exists())
        parent["depends_on"] = [child["operation_id"]]
        body = {"protocol_version": 1, "device_id": self.registration["device_id"], "operations": [parent, child]}
        self.assertEqual(self.client.post(BASE + "push", body, format="json").status_code, 400)
        parent["depends_on"] = []
        body["operations"] = [child, parent]
        response = self.client.post(BASE + "push", body, format="json")
        self.assertEqual([result["outcome"] for result in response.data["results"]], ["accepted", "accepted"])

    def test_all_six_roles_have_projected_reads_and_stakeholder_cannot_write(self):
        for role, user in self.users.items():
            client, registration = self.register(user)
            capabilities = client.get(BASE + "capabilities")
            self.assertEqual(capabilities.status_code, 200)
            self.assertEqual(capabilities.data["commands"]["poultry.mortality.record"]["available"], role != "stake_holder")
            _, rows, _ = self.snapshot(client)
            batch = next(row["payload"] for row in rows if row["entity_type"] == "poultry.batch")
            for forbidden in ["target_selling_price", "base_monthly_salary", "created_by", "owner", "password", "email"]:
                self.assertNotIn(forbidden, batch)
            web = APIClient()
            web.force_authenticate(user)
            payload = deepcopy(self.command()["payload"])
            payload.pop("batch_uuid")
            payload["age_in_days"] = 999
            response = web.post(f"/api/v1/poultry-management/{self.batch.pk}/mortality", payload, format="json")
            self.assertEqual(response.status_code, 403 if role == "stake_holder" else 201, response.data)
            if role == "stake_holder":
                self.assertEqual(self.push(self.command(), client, registration).data["results"][0]["outcome"], "permission_denied")

    def test_revoked_device_denies_rest_refresh_push_and_receipt_replay(self):
        command = self.command()
        self.push(command)
        self.assertEqual(self.client.post(BASE + f"devices/{self.registration['device_id']}/revoke", {"reason": "Lost test phone"}, format="json").status_code, 200)
        for path in [BASE + "capabilities", BASE + f"operations/{command['operation_id']}", "/api/v1/auth/me", f"/api/v1/poultry-management/{self.batch.pk}"]:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.push(command).status_code, 403)
        refresh = APIClient().post("/api/v1/auth/refresh", {"refresh": self.registration["refresh"]}, format="json")
        self.assertEqual(refresh.status_code, 403)
        public = APIClient()
        self.assertEqual(public.post("/api/v1/auth/verify", {"token": self.registration["access"]}, format="json").status_code, 403)
        self.assertEqual(public.post("/api/v1/auth/logout", {"refresh": self.registration["refresh"]}, format="json").status_code, 403)
        self.assertEqual(Mortality.objects.count(), 1)

    def test_cross_actor_device_snapshot_and_cursor_access_fail(self):
        command = self.command()
        self.push(command)
        other, registration = self.register(self.users["farm_manager"])
        self.assertEqual(other.get(BASE + f"operations/{command['operation_id']}").status_code, 404)
        same_actor, same_actor_registration = self.register(self.worker)
        self.assertEqual(self.push(command, same_actor, same_actor_registration).status_code, 403)
        manifest, _, cursor = self.snapshot()
        self.assertEqual(other.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": manifest["next_page_cursor"]}).status_code, 404)
        self.assertEqual(other.get(BASE + "changes", {"cursor": cursor}).status_code, 409)
        self.assertEqual(self.client.get(BASE + "changes", {"cursor": cursor + "tamper"}).status_code, 400)

    def test_role_loss_scope_revision_resets_existing_cursors(self):
        _, _, cursor = self.snapshot()
        self.worker.roles.set([Role.objects.get(slug="stake_holder")])
        self.assertEqual(self.client.get(BASE + "changes", {"cursor": cursor}).status_code, 409)
        self.assertFalse(self.client.get(BASE + "capabilities").data["commands"]["poultry.mortality.record"]["available"])

    def test_mobile_cannot_bypass_registry_through_direct_rest(self):
        self.assertEqual(self.client.get("/api/v1/finance/dashboard").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/poultry-management/{self.batch.pk}/mortality", {}, format="json").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        ordinary = APIClient()
        ordinary.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.worker).access_token}")
        self.assertEqual(ordinary.get(BASE + "capabilities").status_code, 403)
        self.assertEqual(ordinary.get("/api/v1/auth/me").status_code, 200)

    def test_frozen_bootstrap_web_delta_update_delete_and_new_batch_entry(self):
        manifest, rows, cursor = self.snapshot()
        before = deepcopy(rows)
        self.push(self.command())
        # Frozen pages still equal their original bytes/checksums after mutation.
        first = self.client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": manifest["next_page_cursor"]})
        self.assertEqual(first.data["entities"], before)
        delta = self.client.get(BASE + "changes", {"cursor": cursor})
        self.assertEqual(len(delta.data["changes"]), 3)
        cursor = delta.data["next_cursor"]
        with sync_boundary():
            Mortality.objects.all().delete()
            new_batch = Batch.objects.create(batch_id="NEW-ENTRY", quantity=10, entry_date=self.arrival, expected_maturity_date=timezone.now()+timedelta(days=5))
        delta = self.client.get(BASE + "changes", {"cursor": cursor})
        self.assertTrue(any(change["kind"] == "tombstone" for change in delta.data["changes"]))
        self.assertTrue(any(change.get("payload", {}).get("batch_id") == new_batch.batch_id for change in delta.data["changes"]))

    @override_settings(MOBILE_SYNC_PAGE_ROWS=1)
    def test_snapshot_pagination_resume_expiry_and_no_partial_activation(self):
        manifest, rows, _ = self.snapshot()
        self.assertEqual(len(manifest["manifest"]), 2)
        self.assertEqual(len(rows), 2)
        resumed = self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": [CURRENT_PACK], "resume_snapshot_id": manifest["snapshot_id"]}, format="json")
        self.assertEqual(resumed.data["snapshot_id"], manifest["snapshot_id"])
        SyncBootstrap.objects.filter(pk=manifest["snapshot_id"]).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": manifest["next_page_cursor"]}).status_code, 410)

    def test_large_transaction_fragments_fixed_watermark_and_hidden_progress(self):
        _, _, cursor = self.snapshot()
        self.push(self.command())  # Batch, mortality, feed in one transaction.
        first = self.client.get(BASE + "changes", {"cursor": cursor, "limit": 1}).data
        self.assertFalse(first["run_complete"])
        self.assertFalse(first["changes"][0]["fragment_final"])
        self.push(self.command())  # Must not enter the existing fixed-watermark run.
        all_changes = list(first["changes"])
        next_cursor = first["next_cursor"]
        while not first["run_complete"]:
            first = self.client.get(BASE + "changes", {"cursor": next_cursor, "limit": 1}).data
            all_changes += first["changes"]
            next_cursor = first["next_cursor"]
        self.assertEqual(len(all_changes), 3)
        self.assertEqual([change["fragment_index"] for change in all_changes], [0, 1, 2])
        self.assertTrue(all_changes[-1]["fragment_final"])
        self.assertEqual(len(self.client.get(BASE + "changes", {"cursor": next_cursor}).data["changes"]), 3)
        # An archive cursor scanning changes for a different batch progresses
        # over hidden-only pages without exposing another batch's payload.
        _, _, archive_cursor = self.snapshot(packs=[f"batch:{self.batch_uuid}"])
        with sync_boundary():
            Batch.objects.create(batch_id="HIDDEN", quantity=5, entry_date=self.arrival, expected_maturity_date=timezone.now()+timedelta(days=5))
        hidden = self.client.get(BASE + "changes", {"cursor": archive_cursor}).data
        self.assertEqual(hidden["changes"], [])
        self.assertTrue(hidden["run_complete"])
        self.assertNotEqual(hidden["next_cursor"], archive_cursor)

    def test_dynamic_pack_exit_is_eviction_not_deletion_and_archive_retains_rows(self):
        _, _, current_cursor = self.snapshot()
        _, _, archive_cursor = self.snapshot(packs=[f"batch:{self.batch_uuid}"])
        # Last mortality is after all recorded feed, so dated feed remains valid.
        command = self.command(100)
        command["payload"]["mortality_date"] = json_value(timezone.now()-timedelta(seconds=5))
        self.assertEqual(self.push(command).data["results"][0]["outcome"], "accepted")
        current = self.client.get(BASE + "changes", {"cursor": current_cursor}).data["changes"]
        self.assertTrue(any(change["kind"] == "evict_from_pack" for change in current))
        self.assertFalse(any(change["kind"] == "tombstone" for change in current))
        archive = self.client.get(BASE + "changes", {"cursor": archive_cursor}).data["changes"]
        self.assertTrue(any(change["kind"] == "upsert" for change in archive))
        self.assertFalse(any(change["kind"] == "evict_from_pack" for change in archive))

    def test_unknown_bulk_writers_fail_closed_guarded_update_and_cascade_publish(self):
        with self.assertRaises(UnsafeSyncWrite):
            Batch.objects.filter(pk=self.batch.pk).update(quantity=90)
        with self.assertRaises(UnsafeSyncWrite):
            create_mortality_with_lifecycle(batch_id=self.batch.pk, created_by=self.worker, **{
                key: value for key, value in self.command()["payload"].items() if key != "batch_uuid"})
        with self.assertRaises(UnsafeSyncWrite):
            Batch.objects.bulk_create([Batch(quantity=2, entry_date=self.arrival, expected_maturity_date=timezone.now())])
        with sync_boundary():
            Batch.objects.filter(pk=self.batch.pk).update(quantity=90, actual_quantity_received=90)
        self.assertEqual(SyncEntity.objects.get(entity_type="poultry.batch", source_pk=str(self.batch.pk)).payload["remaining_birds"], 90)
        with sync_boundary():
            self.batch.delete()
        self.assertEqual(SyncEntity.objects.filter(deleted=True).count(), 2)
        self.assertEqual(SyncChange.objects.filter(kind="tombstone").count(), 2)

    def test_entity_collision_inactive_account_and_request_budget(self):
        command = self.command()
        command["entity_uuid"] = self.batch_uuid
        self.assertEqual(self.push(command).data["results"][0]["code"], "entity_uuid_conflict")
        with override_settings(MOBILE_SYNC_PAGE_BYTES=64):
            self.assertEqual(self.push(self.command()).status_code, 413)
        with override_settings(MOBILE_SYNC_SNAPSHOT_BYTES=1):
            self.assertEqual(self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": [CURRENT_PACK]}, format="json").status_code, 413)
        self.assertFalse(SyncBootstrap.objects.exists())
        self.worker.is_active = False
        self.worker.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(BASE + "capabilities").status_code, 401)

    def test_cleanup_dry_run_retains_receipts_and_identity(self):
        self.push(self.command())
        receipt_count, entity_count = SyncOperationReceipt.objects.count(), SyncEntity.objects.count()
        stream = SyncStreamState.objects.get()
        sequence = stream.sequence
        call_command("cleanup_sync", database_name=connections["default"].settings_dict["NAME"], verbosity=0)
        stream.refresh_from_db()
        self.assertEqual(stream.sequence, sequence)
        self.assertEqual(SyncOperationReceipt.objects.count(), receipt_count)
        self.assertEqual(SyncEntity.objects.count(), entity_count)

    def test_publication_failure_rolls_back_source_versions_changes_and_acceptance(self):
        sequence = SyncStreamState.objects.get().sequence
        revisions = list(SyncEntity.objects.values_list("pk", "revision"))
        with override_settings(MOBILE_SYNC_GROUP_BYTES=1):
            result = self.push(self.command()).data["results"][0]
        self.assertEqual(result["outcome"], "validation_failed")
        self.assertFalse(Mortality.objects.exists())
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.current_number_of_birds, 100)
        self.assertEqual(SyncStreamState.objects.get().sequence, sequence)
        self.assertEqual(list(SyncEntity.objects.values_list("pk", "revision")), revisions)
        self.assertEqual(SyncOperationReceipt.objects.get().outcome, "validation_failed")

    def test_generic_admin_writers_are_explicitly_disabled_and_worker_rest_is_projected(self):
        from django.contrib import admin
        from django.test import RequestFactory
        request = RequestFactory().post("/admin/")
        request.user = get_user_model()(is_superuser=True, is_staff=True, is_active=True)
        for model in [Batch, Mortality, FeedUsage, Sales]:
            editor = admin.site._registry[model]
            self.assertFalse(editor.has_add_permission(request))
            self.assertFalse(editor.has_change_permission(request))
            self.assertFalse(editor.has_delete_permission(request))
        web = APIClient()
        web.force_authenticate(self.worker)
        response = web.get(f"/api/v1/poultry-management/{self.batch.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("target_selling_price", response.data)
        self.assertNotIn("created_by", response.data)
        self.assertEqual(web.get(f"/api/v1/poultry-management/{self.batch.pk}/sales").status_code, 403)
        for path in ["input_costs", "feed_input_costs", "sell-by-recommendation"]:
            self.assertEqual(web.get(f"/api/v1/poultry-management/{self.batch.pk}/{path}").status_code, 403)

    def test_employee_login_routes_cannot_escalate_or_disable_accounts_as_supervisor(self):
        from apps.finance.models import EmployeeProfile
        profile = EmployeeProfile.objects.create(user=self.worker, employee_number="SYNC-EMP", job_title="Worker",
            employment_start_date=self.arrival.date(), base_monthly_salary=Decimal("100.00"))
        web = APIClient()
        web.force_authenticate(self.users["farm_supervisor"])
        path = f"/api/v1/finance/employees/{profile.pk}"
        for fields in [{"role_slugs": ["admin"]}, {"user_id": self.users["admin"].pk}, {"username": "stolen-login"}]:
            self.assertEqual(web.patch(path, fields, format="json").status_code, 403)
        self.assertEqual(web.post(path + "/deactivate", {}, format="json").status_code, 400)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.role_slugs, {"general_worker"})
        self.assertTrue(self.worker.is_active)
        self.assertEqual(web.patch(path, {"first_name": "Employee record name"}, format="json").status_code, 200)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.first_name, "")

    def test_operational_wire_schemas_match_actual_payloads_and_envelopes(self):
        from jsonschema import Draft7Validator, FormatChecker
        from apps.mobile_sync import schema

        def json_schema(value):
            if isinstance(value, list):
                return [json_schema(item) for item in value]
            if not isinstance(value, dict):
                return value
            converted = {key: json_schema(item) for key, item in value.items() if key != "nullable"}
            if value.get("nullable"):
                return {"anyOf": [converted, {"type": "null"}]}
            return converted

        def validate(value, definition):
            Draft7Validator(json_schema(definition), format_checker=FormatChecker()).validate(value)

        validate(self.registration, schema.REGISTER)
        validate(self.client.get(BASE + "capabilities").data, schema.CAPABILITIES)
        manifest, _, cursor = self.snapshot()
        validate(manifest, schema.BOOTSTRAP)
        page = self.client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": manifest["next_page_cursor"]}).data
        validate(page, schema.PAGE)
        self.push(self.command())
        validate(self.client.get(BASE + "changes", {"cursor": cursor}).data, schema.CHANGES)

    def test_snapshot_storage_quota_and_post_lock_policy_recheck(self):
        body = {"protocol_version": 1, "packs": [CURRENT_PACK]}
        for _ in range(4):
            self.assertEqual(self.client.post(BASE + "bootstrap", body, format="json").status_code, 200)
        limited = self.client.post(BASE + "bootstrap", body, format="json")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.data["code"], "snapshot_limit")
        with patch("apps.mobile_sync.views.permits", side_effect=[True, False]):
            self.assertEqual(self.client.post(BASE + "bootstrap", body, format="json").status_code, 403)
        self.assertEqual(SyncBootstrap.objects.count(), 4)

    def test_active_refresh_preserves_binding_and_ordinary_verify_is_unchanged(self):
        public = APIClient()
        refresh = public.post("/api/v1/auth/refresh", {"refresh": self.registration["refresh"]}, format="json")
        self.assertEqual(refresh.status_code, 200, refresh.data)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.data['access']}")
        self.assertEqual(client.get(BASE + "capabilities").data["device_id"], self.registration["device_id"])
        web_token = str(RefreshToken.for_user(self.worker).access_token)
        self.assertEqual(public.post("/api/v1/auth/verify", {"token": web_token}, format="json").status_code, 200)

    def test_finalization_and_sales_adjustment_services_publish_operational_only(self):
        from apps.finance.services.profitability import create_final_snapshot
        from apps.poultry.services.feed_metrics import create_flock_adjustment
        from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle
        sequence = SyncStreamState.objects.get().sequence
        with sync_boundary():
            create_flock_adjustment(batch_id=self.batch.pk,
                effective_at=timezone.now()-timedelta(minutes=2), quantity_change=10, reason="Verified arrivals",
                approved_by=self.users["farm_manager"])
            create_sale_with_lifecycle(batch_id=self.batch.pk, created_by=self.users["farm_manager"],
                sale_date=timezone.now()-timedelta(minutes=1), product_type="live_chicken", quantity_sold=2,
                unit_price=Decimal("5.00"), amount_paid=Decimal("10.00"), buyer_name="Buyer", buyer_type="retail",
                sold_by_name="Manager", payment_status="paid", payment_method="cash", notes="Sync writer test")
        self.assertEqual(SyncEntity.objects.get(entity_type="poultry.batch").payload["remaining_birds"], 108)
        period = AccountingPeriod.objects.create(period_start=self.arrival.date(), period_end=timezone.now().date())
        with sync_boundary():
            create_final_snapshot(self.batch, accounting_period=period, generated_by=self.users["farm_manager"])
        self.assertGreater(SyncStreamState.objects.get().sequence, sequence)
        result = self.push(self.command()).data["results"][0]
        self.assertEqual(result["outcome"], "period_locked")
        for change in SyncChange.objects.filter(sequence__gt=sequence):
            for forbidden in ["unit_price", "amount_paid", "management_net_position", "buyer_name", "profitability_snapshots"]:
                self.assertNotIn(forbidden, change.payload)

    def test_existing_period_close_reopen_bulk_writer_under_capture(self):
        command = self.command(100)
        command["payload"]["mortality_date"] = json_value(timezone.now()-timedelta(seconds=5))
        self.assertEqual(self.push(command).data["results"][0]["outcome"], "accepted")
        period = AccountingPeriod.objects.create(period_start=self.arrival.date(), period_end=timezone.now().date())
        sequence = SyncStreamState.objects.get().sequence
        web = APIClient()
        web.force_authenticate(self.users["farm_manager"])
        path = f"/api/v1/finance/accounting-periods/{period.pk}"
        response = web.post(path + "/close", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.batch.refresh_from_db()
        self.assertIsNotNone(self.batch.profitability_finalized_at)
        self.assertGreater(SyncStreamState.objects.get().sequence, sequence)
        for change in SyncChange.objects.filter(sequence__gt=sequence):
            self.assertNotIn("profitability_finalized_at", change.payload)
        response = web.post(path + "/reopen", {"reason": "Owned database writer test"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.batch.refresh_from_db()
        self.assertIsNone(self.batch.profitability_finalized_at)

    @override_settings(MOBILE_SYNC_SCAN_ROWS=1)
    def test_hidden_only_scan_pages_progress_and_signal_final_fragment(self):
        _, _, cursor = self.snapshot(packs=[f"batch:{self.batch_uuid}"])
        with sync_boundary():
            hidden = Batch.objects.create(batch_id="HIDDEN-ONLY", quantity=5, entry_date=self.arrival,
                expected_maturity_date=timezone.now()+timedelta(days=5))
            FeedUsage.objects.create(batch=hidden, initial_age=2, feeding_start_date=self.arrival+timedelta(days=2),
                feeding_end_date=self.arrival+timedelta(days=3), feed_type="starter", feed_source="cp_feed", quantity_given=1,
                unit_of_measurement="kg", current_number_of_birds=5, reported_by_name="Hidden")
        first = self.client.get(BASE + "changes", {"cursor": cursor}).data
        self.assertEqual(first["changes"], [])
        self.assertFalse(first["run_complete"])
        self.assertFalse(first["fragments"][0]["fragment_final"])
        last = self.client.get(BASE + "changes", {"cursor": first["next_cursor"]}).data
        self.assertTrue(last["run_complete"])
        self.assertEqual(last["changes"], [])
        self.assertEqual(last["fragments"][0]["fragment_index"], 1)
        self.assertTrue(last["fragments"][0]["fragment_final"])

    def test_receipts_and_changes_immutable_cleanup_prunes_only_whole_old_groups(self):
        from apps.mobile_sync.models import SyncBootstrapPage
        from django.db import connection
        _, _, cursor = self.snapshot()
        self.push(self.command())
        with self.assertRaises(ValueError):
            SyncOperationReceipt.objects.update(result={})
        with self.assertRaises(ValueError):
            SyncChange.objects.all().delete()
        # Test-only ageing via SQL: production has no mutable metadata endpoint.
        with connection.cursor() as sql:
            sql.execute("UPDATE mobile_sync_syncchange SET created_at=%s", [timezone.now()-timedelta(days=91)])
        expected_minimum = SyncStreamState.objects.get().sequence
        SyncBootstrap.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        call_command("cleanup_sync", database_name=connection.settings_dict["NAME"], apply=True, limit=100, verbosity=0)
        self.assertEqual(SyncStreamState.objects.get().minimum_sequence, expected_minimum)
        self.assertFalse(SyncChange.objects.exists())
        self.assertFalse(SyncBootstrapPage.objects.exists())
        self.assertTrue(SyncOperationReceipt.objects.exists())
        self.assertEqual(self.client.get(BASE + "changes", {"cursor": cursor}).status_code, 410)


@override_settings(**TEST_SETTINGS)
class PostgreSQLConcurrencyTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        # TransactionTestCase flush removes data-migration seeds after each test.
        SyncStreamState.objects.get_or_create(pk=1)
        for slug in ["general_worker", "farm_supervisor", "farm_manager", "director", "stake_holder", "admin"]:
            Role.objects.get_or_create(slug=slug, defaults={"name": slug})
        self.make_fixture()

    def test_racing_identical_commands_one_committed_business_effect(self):
        gate = Event()
        results, errors = [], []
        command = self.command()

        def worker():
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.registration['access']}")
                gate.wait(5)
                response = self.push(command, client=client)
                results.append((response.status_code, response.data))
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        threads = [Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        gate.set()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(result[1]["results"][0]["outcome"] for result in results), ["accepted", "replayed"])
        self.assertEqual(Mortality.objects.count(), 1)
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)

    def test_delayed_lower_sequence_cannot_commit_behind_advanced_cursor(self):
        _, _, cursor = self.snapshot()
        locked, release, completed = Event(), Event(), Event()
        errors = []

        def delayed_writer():
            try:
                with sync_boundary():
                    Batch.objects.filter(pk=self.batch.pk).update(quantity=110, actual_quantity_received=110)
                    locked.set()
                    release.wait(5)
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        def later_writer():
            try:
                with sync_boundary():
                    Batch.objects.filter(pk=self.batch.pk).update(quantity=120, actual_quantity_received=120)
                completed.set()
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        first = Thread(target=delayed_writer)
        first.start()
        self.assertTrue(locked.wait(5))
        second = Thread(target=later_writer)
        second.start()
        time.sleep(0.1)
        self.assertFalse(completed.is_set())
        before_commit = self.client.get(BASE + "changes", {"cursor": cursor})
        self.assertEqual(before_commit.data["changes"], [])
        release.set()
        first.join(10)
        second.join(10)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        pulled = self.client.get(BASE + "changes", {"cursor": before_commit.data["next_cursor"]})
        self.assertEqual([change["payload"]["remaining_birds"] for change in pulled.data["changes"]], [110, 120])

    def test_bootstrap_concurrent_web_create_update_guarded_delete_converges_after_delta(self):
        from apps.mobile_sync.projections import wire_entity
        frozen, release, writer_done = Event(), Event(), Event()
        results, errors = [], []

        def freeze(entity):
            frozen.set()
            release.wait(5)
            return wire_entity(entity)

        def bootstrap():
            try:
                results.append(self.snapshot())
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        def web_writer():
            try:
                web = APIClient()
                web.force_authenticate(self.users["farm_manager"])
                payload = deepcopy(self.command(2)["payload"])
                payload.pop("batch_uuid")
                payload["age_in_days"] = 999
                response = web.post(f"/api/v1/poultry-management/{self.batch.pk}/mortality", payload, format="json")
                self.assertEqual(response.status_code, 201, response.data)
                response = web.patch(f"/api/v1/poultry-management/{self.batch.pk}/forecast-assumptions",
                    {"target_selling_price": "5100.00"}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                # There is no generic web delete route. Test the supported
                # guarded deletion, not an invented endpoint or unsafe admin.
                with sync_boundary():
                    Batch.objects.get(pk=self.batch.pk).delete()
                writer_done.set()
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()

        with patch("apps.mobile_sync.transport.wire_entity", side_effect=freeze):
            first = Thread(target=bootstrap)
            first.start()
            self.assertTrue(frozen.wait(5))
            second = Thread(target=web_writer)
            second.start()
            time.sleep(0.1)
            self.assertFalse(writer_done.is_set())
            release.set()
            first.join(10)
            second.join(10)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        _, rows, cursor = results[0]
        confirmed = {row["entity_uuid"]: row for row in rows}
        self.assertEqual(len(confirmed), 2)
        self.assertEqual(next(row["payload"]["remaining_birds"] for row in rows if row["entity_type"] == "poultry.batch"), 100)
        changes = self.client.get(BASE + "changes", {"cursor": cursor}).data["changes"]
        self.assertTrue(any(change["entity_type"] == "poultry.mortality" and change["kind"] == "upsert" for change in changes))
        self.assertTrue(any(change.get("payload", {}).get("remaining_birds") == 98 for change in changes))
        for change in changes:
            if change["kind"] == "upsert":
                confirmed[change["entity_uuid"]] = change
            else:
                confirmed.pop(change["entity_uuid"], None)
        self.assertEqual(confirmed, {})
        self.assertFalse(SyncEntity.objects.filter(deleted=False).exists())

    def test_two_devices_competing_for_last_birds_cannot_overdraw(self):
        _, second_registration = self.register(self.worker)
        gate, results, errors = Event(), [], []
        commands = [self.command(60), self.command(60)]
        for command in commands:
            command["payload"]["mortality_date"] = json_value(timezone.now()-timedelta(seconds=5))

        def worker(command, registration):
            try:
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {registration['access']}")
                gate.wait(5)
                results.append(self.push(command, client, registration).data["results"][0]["outcome"])
            except Exception as error:
                errors.append(error)
            finally:
                connections.close_all()
        threads = [Thread(target=worker, args=(command, registration)) for command, registration in
                   zip(commands, [self.registration, second_registration])]
        for thread in threads:
            thread.start()
        gate.set()
        for thread in threads:
            thread.join(10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), ["accepted", "conflict"])
        self.assertEqual(Mortality.objects.get().quantity_dead, 60)
        self.assertEqual(SyncEntity.objects.get(entity_type="poultry.batch").payload["remaining_birds"], 40)
