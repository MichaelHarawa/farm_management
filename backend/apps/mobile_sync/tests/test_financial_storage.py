"""Private evidence grants on owned PostgreSQL; never live farm configuration."""
from datetime import timedelta
import json
import os
from pathlib import Path
from threading import Event, Thread
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.test import TransactionTestCase
from django.db import connection, close_old_connections
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import RoleChoices
from apps.mobile_sync import financial_storage as storage, schema_financial_storage as wire
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import MobileSession, MobileDevice, SyncStreamState
from apps.mobile_sync.commands import financial_uuid
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_sync import BASE

SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS": True, "MOBILE_SYNC_FINANCIAL_STORAGE": True}


@override_settings(**SETTINGS)
class FinancialStorageTests(BridgeFixture, TestCase):
    def grant(self):
        return storage.financial_storage_grant(self.user, self.session, self.token)

    def refused(self, code=None):
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            self.grant()
        if code:
            self.assertEqual(error.exception.detail["code"], code)
        self.assertEqual(self.snapshot(), before)

    def test_bound_grant_does_not_read_or_change_money_or_grant_reference_cache(self):
        before = self.snapshot()
        result = self.grant()
        Draft7Validator.check_schema(wire.GRANT)
        Draft7Validator(wire.GRANT, format_checker=FormatChecker()).validate(result)
        self.assertEqual(result["actor_id"], str(self.user.pk))
        self.assertEqual(result["device_id"], str(self.session.device_id))
        self.assertEqual(result["session_id"], str(self.session.pk))
        self.assertEqual(result["deployment_id"], str(self.stream.deployment_id))
        self.assertEqual(result["stream_epoch"], str(self.stream.epoch))
        self.assertFalse(result["financial_uploads"])
        self.assertEqual(result["reference_cache_seconds"], 0)
        with self.assertNumQueries(0):
            # Positive validation cannot accept a financial pack/role/balance.
            self.assertFalse(storage.VALID.is_valid({**result, "cash_balance": "100.00"}))
        self.assertEqual(self.snapshot(), before)

    def test_24_hour_window_and_shorter_session_expiry(self):
        now = timezone.now()
        for seconds in (60, 86400, 172800):
            expiry = now + timedelta(seconds=seconds)
            MobileSession.objects.filter(pk=self.session.pk).update(expires_at=expiry)
            with patch.object(storage.timezone, "now", return_value=now):
                result = self.grant()
            self.assertEqual(result["expires_at"], (min(expiry, now + timedelta(days=1))).isoformat().replace("+00:00", "Z"))

    def test_every_disabled_gate_refuses_before_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_STORAGE", "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS", "MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{flag: False}), self.assertNumQueries(0), self.assertRaises(SyncError):
                self.grant()

    def test_current_write_role_required_not_operational_sensitive_policy(self):
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER, None):
            self.role(role)
            self.refused("permission_denied")

    def test_stale_actor_object_and_revoked_or_expired_session_refuse(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.refused()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=True)
        for changes in ({"revoked_at": timezone.now()}, {"expires_at": timezone.now() - timedelta(seconds=1)}):
            MobileSession.objects.filter(pk=self.session.pk).update(**changes)
            self.refused("device_revoked")
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=None, expires_at=timezone.now() + timedelta(days=3))
        MobileDevice.objects.filter(pk=self.session.device_id).update(revoked_at=timezone.now())
        self.refused("device_revoked")

    def test_foreign_actor_deployment_and_session_refuse(self):
        original = dict(self.token.payload)
        for key in ("user_id", "deployment_id", "mobile_session_id", "mobile_device_id"):
            self.token.payload = {**original, key: str(uuid.uuid4())}
            self.refused()
        self.token.payload = original

    def test_scope_changes_with_session_epoch_role_and_expiry(self):
        first = self.grant()["scope_revision"]
        SyncStreamState.objects.filter(pk=1).update(epoch=uuid.uuid4())
        self.assertNotEqual(first, self.grant()["scope_revision"])
        second = self.grant()["scope_revision"]
        MobileSession.objects.filter(pk=self.session.pk).update(expires_at=timezone.now() + timedelta(hours=3))
        self.assertNotEqual(second, self.grant()["scope_revision"])
        third = self.grant()["scope_revision"]
        self.role(RoleChoices.FARM_MANAGER)
        self.assertNotEqual(third, self.grant()["scope_revision"])

    def test_late_scope_loss_refuses_and_retains_every_original(self):
        original = storage._scope
        calls = []
        def changed(*args):
            calls.append(1)
            return original(*args) if len(calls) == 1 else "0" * 64
        with patch.object(storage, "_scope", side_effect=changed):
            self.refused("financial_storage_scope_changed")

    def test_rechecks_current_actor_after_wait_and_at_release(self):
        original = storage.references._access
        for target in (2, 3):
            calls = []
            def denied(*args):
                calls.append(1)
                if len(calls) == target:
                    raise SyncError("permission_denied", "Synthetic late denial.", 403)
                return original(*args)
            with patch.object(storage.references, "_access", side_effect=denied):
                self.refused("permission_denied")

    def test_public_financial_capability_and_routes_stay_unavailable(self):
        self.assertFalse(self.client.get(BASE + "capabilities").data["commands"]["finance"]["available"])
        self.assertEqual(self.client.get(BASE + "finance/storage-grant").status_code, 404)

    def test_actual_grant_and_uuid_command_hash_cross_language_fixture(self):
        result = self.grant()
        command = self.command()
        command["financial_command_version"] = 2
        command["captured_at"] = "2026-10-15T15:59:59.123456Z"
        command["payload"]["payee"] = "Synthetic café 🐔 supplier"
        for invoice in command["payload"]["invoices"]:
            invoice["invoice_version"] = "b" * 64
            for line in invoice["lines"]:
                for row in line["funding_allocations"]:
                    row["funding_source"] = str(uuid.uuid4())
                    row["funding_version"] = "c" * 64
        financial_uuid._validate(command, financial_uuid.OPERATIONS)
        evidence = {"grant": result, "operation": command,
            "command_hash": financial_uuid.command_hash(self.stream, self.user, self.session.device, command),
            "provenance": "owned_postgresql_private_grant_and_pure_uuid_hash_no_upload"}
        output = os.environ.get("MOBILE_FINANCIAL_STORAGE_FIXTURE_OUTPUT")
        if output:
            root = Path(__file__).resolve().parents[4]
            target = (root / output).resolve()
            if not connection.settings_dict["NAME"].startswith("test_mobile_phase02_") or not target.is_relative_to(root / "docs/mobile/evidence"):
                raise AssertionError("Refuse non-owned fixture export")
            with target.open("x", encoding="utf-8") as stream:
                json.dump(evidence, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        self.assertEqual(result["reference_cache_seconds"], 0)


@override_settings(**SETTINGS)
class FinancialStorageConcurrencyTests(BridgeFixture, TransactionTestCase):
    def test_revocation_during_actual_postgresql_stream_wait_refuses_grant(self):
        before = self.snapshot()
        started, pids, result = Event(), [], []
        original = storage.references._access
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
                result.append(storage.financial_storage_grant(self.user, self.session, self.token))
            except SyncError as error:
                result.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(storage.references, "_access", side_effect=authorized), sync_boundary():
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
            self.assertTrue(waiting, "Must prove actual contention on another PostgreSQL connection")
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        worker.join(25)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [403])
        self.assertEqual(self.snapshot(), before)
