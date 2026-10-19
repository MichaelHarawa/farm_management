"""Actual signed online discovery; never a native grant or automatic upload switch."""
from unittest.mock import patch
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import RoleChoices
from apps.mobile_sync.command_views import FinancialCommandCapabilitiesView, FinancialCommandSubmitView
from apps.mobile_sync.models import MobileSession
from apps.mobile_sync.schema_command_api import CAPABILITIES
from .test_command_api import APIFixture, SETTINGS, URL, HEADERS

CAPS = URL + "/capabilities"


@override_settings(**SETTINGS)
class FinancialCommandCapabilityTests(APIFixture, TestCase):
    def read(self):
        return self.client.get(CAPS, **HEADERS)

    def validate(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        Draft7Validator(CAPABILITIES, format_checker=FormatChecker()).validate(response.data)
        self.assertEqual(response.data["actor_id"], str(self.user.pk))
        self.assertEqual(response.data["device_id"], str(self.session.device_id))
        self.assertEqual(response.data["deployment_id"], str(self.stream.deployment_id))
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertIn("Authorization", response["Vary"])
        self.assertLess(len(response.content), 8192)
        self.assertEqual(response.data["packs"], [])
        self.assertEqual(response.data["offline_cache_seconds"], 0)

    def test_enabled_writer_has_one_command_without_any_business_or_sync_effect(self):
        before = self.snapshot()
        response = self.read()
        self.validate(response)
        self.assertTrue(response.data["submission_enabled"])
        self.assertEqual(response.data["commands"], ["inventory.supplier_payment.record"])
        self.assertTrue(response.data["status_recovery_enabled"])
        self.assertTrue(response.data["requires_separate_native_storage_grant"])
        self.assertEqual(self.snapshot(), before)

    def test_each_disabled_posting_prerequisite_leaves_only_recovery_discovery(self):
        before = self.snapshot()
        for flag in (FinancialCommandSubmitView.gate, *FinancialCommandSubmitView.prerequisites):
            if flag in {"MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API", "MOBILE_SYNC_FINANCIAL_READS"}:
                continue
            with override_settings(**{flag: False}):
                response = self.read()
            self.validate(response)
            self.assertFalse(response.data["submission_enabled"], flag)
            self.assertEqual(response.data["commands"], [])
            self.assertTrue(response.data["status_recovery_enabled"])
        self.assertEqual(self.snapshot(), before)

    def test_current_read_only_role_can_discover_recovery_but_cannot_submit(self):
        self.role(RoleChoices.STAKE_HOLDER)
        before = self.snapshot()
        response = self.read()
        self.validate(response)
        self.assertFalse(response.data["submission_enabled"])
        self.assertEqual(response.data["commands"], [])
        self.assertEqual(self.snapshot(), before)
        self.role(RoleChoices.GENERAL_WORKER)
        response = self.read()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("commands", response.data)

    def test_default_off_prerequisites_refuse_all_methods_before_authentication_or_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API", "MOBILE_SYNC_FINANCIAL_READS",
                "MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{flag: False}):
                for method in ("get", "head", "options", "post", "put", "patch", "delete"):
                    with self.assertNumQueries(0):
                        response = getattr(APIClient(), method)(CAPS, HTTP_AUTHORIZATION="Bearer invalid")
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("no-store", response["Cache-Control"])

    def test_discovery_rejects_wrong_headers_query_body_and_write_methods(self):
        before = self.snapshot()
        self.assertEqual(self.client.get(CAPS).status_code, 409)
        self.assertEqual(self.client.get(CAPS + "?actor_id=override", **HEADERS).status_code, 400)
        self.assertEqual(self.client.generic("GET", CAPS, b"{}", content_type="application/json", **HEADERS).status_code, 400)
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(CAPS, {}, format="json", **HEADERS).status_code, 405)
        self.assertEqual(self.snapshot(), before)

    def test_role_change_during_discovery_cannot_release_stale_write_permission(self):
        can_submit = FinancialCommandCapabilitiesView.can_submit
        calls = 0

        def change_role(actor):
            nonlocal calls
            calls += 1
            allowed = can_submit(actor)
            if calls == 1:
                self.role(RoleChoices.STAKE_HOLDER)
            return allowed

        with patch.object(FinancialCommandCapabilitiesView, "can_submit", side_effect=change_role):
            response = self.read()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("commands", response.data)

    def test_session_revocation_during_discovery_never_releases_capability(self):
        can_submit = FinancialCommandCapabilitiesView.can_submit

        def revoke(actor):
            from django.utils import timezone
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
            return can_submit(actor)

        with patch.object(FinancialCommandCapabilitiesView, "can_submit", side_effect=revoke):
            response = self.read()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("commands", response.data)
