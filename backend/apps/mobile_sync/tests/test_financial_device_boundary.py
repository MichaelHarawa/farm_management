"""Real TCP device revocation on a newly owned PostgreSQL test database only.

These tests never revoke retained emulator devices. They exercise the actual
login/register/revoke/refresh/grant views, not a direct revoked_at update, and
retain non-zero financial source/journal fixtures for the no-business-effect
comparison. They are backend evidence, not native restart/isolation acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
import json
import re
from threading import Barrier
from urllib.parse import urlsplit
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import LiveServerTestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Role
from apps.mobile_sync.models import MobileDevice, MobileDeviceAudit, MobileSession
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture
from .test_financial_storage import SETTINGS
from .test_sync import BASE


@override_settings(**SETTINGS)
class FinancialDeviceBoundaryHTTPTests(BridgeFixture, LiveServerTestCase):
    def setUp(self):
        if connection.vendor != "postgresql" or re.fullmatch(r"test_mobile_phase02_[0-9a-f]{12}", connection.settings_dict["NAME"]) is None:
            self.fail("Run through the newly owned PostgreSQL test runner, never a retained/source database")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            self.assertEqual(cursor.fetchone()[0], connection.settings_dict["NAME"])
        super().setUp()
        self.role("farm_manager")  # Current role, not a fixture superuser shortcut.
        self.password = uuid.uuid4().hex + "-SyntheticOnly!"
        with sync_boundary():
            self.user.set_password(self.password)
            self.user.save(update_fields=["password"])
        self.web = self.login(self.user.username)
        self.installation = str(uuid.uuid4())
        self.target = self.register_http(self.web, self.installation)
        self.controller = self.register_http(self.web)
        self.device_id = self.target["device_id"]
        self.revoke_url = BASE + f"devices/{self.device_id}/revoke"
        self.before = self.snapshot()

    def exchange(self, method, path, payload=None, access=None, **headers):
        address = urlsplit(self.live_server_url)
        self.assertIn(address.hostname, ("localhost", "127.0.0.1"))
        self.assertTrue(path.startswith("/api/v1/"))
        headers = {"Accept": "application/json", **headers}
        if access:
            headers["Authorization"] = "Bearer " + access
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        if body is not None:
            headers["Content-Type"] = "application/json"
        # No redirect handling, request logging or token/credential export.
        with closing(HTTPConnection(address.hostname, address.port, timeout=15)) as client:
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            content = response.read(131073)
            self.assertLessEqual(len(content), 131072)
            return response.status, json.loads(content) if content else None, dict(response.getheaders())

    def login(self, username):
        status, value, _ = self.exchange("POST", "/api/v1/auth/login", {
            "username": username, "password": self.password})
        self.assertEqual(status, 200)  # Never put a token-bearing value in failure output.
        return value["access"]

    def register_http(self, web, installation=None):
        status, value, _ = self.exchange("POST", BASE + "devices", {
            "installation_id": installation or str(uuid.uuid4()), "app_version": "phase6-disposable-http",
            "platform": "android", "protocol_version": 1,
            "device_label": "Disposable HTTP device, not an emulator"}, web)
        self.assertEqual(status, 200)
        return value

    def actor(self, role):
        with sync_boundary():
            selected, _ = Role.objects.get_or_create(slug=role, defaults={"name": role})
            actor = get_user_model().objects.create_user(username="boundary-" + uuid.uuid4().hex,
                email=uuid.uuid4().hex + "@example.invalid", password=self.password)
            actor.roles.add(selected)
        return actor

    def grant(self, registration, status=200):
        actual, body, headers = self.exchange("GET", BASE + "finance/storage/grant", access=registration["access"],
            **{"X-Mobile-Finance-Version": "1", "X-Mobile-Finance-Storage-Version": "1",
               "X-Mobile-Finance-Storage-Request": str(uuid.uuid4())})
        self.assertEqual(actual, status)
        self.assertEqual(headers["Cache-Control"], "private, no-store, max-age=0")
        if status == 200:
            self.assertEqual(body["grant"]["device_id"], registration["device_id"])
            self.assertFalse(body["grant"]["financial_uploads"])
            self.assertEqual(body["grant"]["reference_cache_seconds"], 0)
        else:
            self.assertNotIn("grant", body)

    def metadata(self):
        return {model._meta.model_name: list(model.objects.order_by("pk").values())
            for model in (MobileDevice, MobileSession, MobileDeviceAudit)}

    def assert_revoked(self, registrations, actor, reason):
        device = MobileDevice.objects.get(pk=self.device_id)
        self.assertIsNotNone(device.revoked_at)
        sessions = list(MobileSession.objects.filter(device=device))
        self.assertGreaterEqual(len(sessions), len(registrations))
        self.assertTrue(all(session.revoked_at == device.revoked_at for session in sessions))
        audit = MobileDeviceAudit.objects.get(device=device, action="revoked")
        self.assertEqual((audit.actor_id, audit.reason), (actor.pk, reason))
        self.assertEqual(self.snapshot(), self.before)

    def test_actual_revoke_twenty_replays_refuse_all_old_tokens_and_preserve_other_device(self):
        second = self.register_http(self.web, self.installation)
        self.assertEqual(second["device_id"], self.device_id)
        self.assertNotEqual(AccessToken(second["access"])["mobile_session_id"],
            AccessToken(self.target["access"])["mobile_session_id"])
        self.grant(self.target)
        self.grant(second)
        self.grant(self.controller)
        controller_before = self.metadata()
        reason = "Synthetic device lost; preserve physical evidence"
        status, result, _ = self.exchange("POST", self.revoke_url, {"reason": reason}, self.controller["access"])
        self.assertEqual(status, 200)
        self.assertEqual(set(result), {"device_id", "installation_id", "app_version", "device_label", "revoked_at"})
        self.assertEqual(result["device_id"], self.device_id)
        self.assert_revoked([self.target, second], self.user, reason)
        stable = self.metadata()
        for _ in range(20):
            status, replay, _ = self.exchange("POST", self.revoke_url, {"reason": "Do not replace original reason"},
                self.controller["access"])
            self.assertEqual(status, 200)
            self.assertEqual(replay, result)
        self.assertEqual(self.metadata(), stable)
        for registration in (self.target, second):
            self.grant(registration, 403)
            for path in ("/api/v1/auth/me", BASE + "capabilities"):
                self.assertEqual(self.exchange("GET", path, access=registration["access"])[0], 403)
            for action, payload in (("refresh", {"refresh": registration["refresh"]}),
                    ("verify", {"token": registration["access"]}), ("logout", {"refresh": registration["refresh"]})):
                self.assertEqual(self.exchange("POST", "/api/v1/auth/" + action, payload)[0], 403)
        # A legitimate new normal login still cannot re-register the old installation.
        fresh_web = self.login(self.user.username)
        self.assertEqual(self.exchange("POST", BASE + "devices", {"installation_id": self.installation,
            "app_version": "phase6-disposable-http", "platform": "android", "protocol_version": 1,
            "device_label": "Disposable HTTP device, not an emulator"}, fresh_web)[0], 403)
        self.assertEqual(self.metadata(), stable)
        self.grant(self.controller)
        for name, rows in controller_before.items():
            if name == "mobiledeviceaudit":
                continue
            for row in rows:
                belongs = str(row["id"]) != self.device_id if name == "mobiledevice" else str(row["device_id"]) != self.device_id
                if belongs:
                    self.assertIn(row, self.metadata()[name])
        self.assert_revoked([self.target, second], self.user, reason)

    def test_foreign_manager_worker_and_viewer_cannot_revoke_or_enumerate_target(self):
        for role in ("farm_manager", "general_worker", "stake_holder"):
            actor = self.actor(role)
            foreign = self.register_http(self.login(actor.username))
            before = self.metadata()
            status, body, _ = self.exchange("POST", self.revoke_url, {"reason": "Must not revoke"}, foreign["access"])
            missing, missing_body, _ = self.exchange("POST", BASE + f"devices/{uuid.uuid4()}/revoke",
                {"reason": "Must not enumerate"}, foreign["access"])
            self.assertEqual((status, missing), (404, 404))
            self.assertEqual(body, missing_body)
            self.assertEqual(self.metadata(), before)
        self.assertEqual(self.snapshot(), self.before)
        self.grant(self.target)

    def test_current_admin_can_revoke_foreign_device_with_one_original_audit(self):
        admin = self.actor("admin")
        self.assertFalse(admin.is_superuser)
        controller = self.register_http(self.login(admin.username))
        reason = "Synthetic authorized administrator revocation"
        status, _, _ = self.exchange("POST", self.revoke_url, {"reason": reason}, controller["access"])
        self.assertEqual(status, 200)
        self.assert_revoked([self.target], admin, reason)
        self.grant(self.target, 403)
        self.grant(controller)
        self.grant(self.controller)

    def test_disabled_sync_gates_refuse_mutation_without_audit_or_financial_effect(self):
        before = self.metadata()
        for flag in ("MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{flag: False}):
                self.assertEqual(self.exchange("POST", self.revoke_url, {"reason": "Disabled"}, self.controller["access"])[0], 503)
            self.assertEqual(self.metadata(), before)
        self.assertEqual(self.snapshot(), self.before)
        self.grant(self.target)

    def test_concurrent_reregistration_and_revoke_cannot_leave_live_target_session(self):
        barrier = Barrier(2, timeout=15)
        def reregister():
            barrier.wait()
            return self.exchange("POST", BASE + "devices", {"installation_id": self.installation,
                "app_version": "phase6-disposable-http", "platform": "android", "protocol_version": 1,
                "device_label": "Disposable HTTP device, not an emulator"}, self.web)
        def revoke():
            barrier.wait()
            return self.exchange("POST", self.revoke_url, {"reason": "Synthetic registration race"}, self.controller["access"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            registration_future = pool.submit(reregister)
            revoke_future = pool.submit(revoke)
            registered = registration_future.result(timeout=25)
            revoked = revoke_future.result(timeout=25)
        self.assertIn(registered[0], (200, 403))
        self.assertEqual(revoked[0], 200)
        self.assert_revoked([self.target], self.user, "Synthetic registration race")
        if registered[0] == 200:
            self.grant(registered[1], 403)
        self.grant(self.target, 403)
        self.grant(self.controller)
