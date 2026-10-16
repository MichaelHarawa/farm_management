"""Actual JWT/HTTP evidence-grant boundary on freshly owned PostgreSQL only."""
from contextlib import closing
from datetime import timedelta
from http.client import HTTPConnection
import json
import os
from pathlib import Path
from unittest.mock import patch
import uuid

from django.db import connection, DatabaseError
from django.test import TestCase, LiveServerTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import RoleChoices
from apps.mobile_sync import financial_storage as storage, schema_storage_api as wire
from apps.mobile_sync.models import MobileSession, MobileDevice
from .test_financial_commands import BridgeFixture
from .test_financial_storage import SETTINGS
from .test_sync import BASE

URL = BASE + "finance/storage/grant"
REQUEST = "a1f8534b-7a5a-4b45-bae1-46e179a819cf"
HEADERS = {"HTTP_X_MOBILE_FINANCE_VERSION": "1", "HTTP_X_MOBILE_FINANCE_STORAGE_VERSION": "1",
    "HTTP_X_MOBILE_FINANCE_STORAGE_REQUEST": REQUEST}
VARY = ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-Storage-Version", "X-Mobile-Finance-Storage-Request")


@override_settings(**SETTINGS)
class StorageGrantAPITests(BridgeFixture, TestCase):
    def read(self, **headers):
        # APIClient.credentials takes precedence over per-request Authorization.
        # A separate client is essential to test the supplied token, not the
        # fixture's valid default credential.
        client = APIClient() if "HTTP_AUTHORIZATION" in headers else self.client
        return client.get(URL, **{**HEADERS, **headers})

    def no_store(self, response):
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        for name in VARY:
            self.assertIn(name, response["Vary"])

    def validate(self, response, request_id=REQUEST):
        self.assertEqual(response.status_code, 200, response.data)
        Draft7Validator(wire.RESPONSE, format_checker=FormatChecker()).validate(response.data)
        self.assertEqual(response.data["request_id"], request_id)
        self.no_store(response)

    def test_actual_signed_bound_access_get_returns_exact_scoped_grant_no_financial_queries(self):
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            response = self.read()
        self.validate(response)
        self.assertFalse(any('"finance_' in entry["sql"] for entry in queries))
        grant = response.data["grant"]
        for key, value in (("actor_id", self.user.pk), ("device_id", self.session.device_id),
                ("session_id", self.session.pk), ("stream_epoch", self.stream.epoch), ("deployment_id", self.stream.deployment_id)):
            self.assertEqual(grant[key], str(value))
        self.assertFalse(grant["financial_uploads"])
        self.assertEqual(grant["reference_cache_seconds"], 0)
        self.assertEqual(self.snapshot(), before)

    def test_every_flag_disabled_refuses_all_methods_before_authentication_or_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_STORAGE", "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS", "MOBILE_SYNC_CAPTURE", "MOBILE_SYNC_ENABLED"):
            with override_settings(**{flag: False}):
                for method in ("get", "head", "post", "put", "patch", "delete", "options"):
                    with self.assertNumQueries(0):
                        response = getattr(self.client, method)(URL, **{**HEADERS, "HTTP_AUTHORIZATION": "Bearer invalid-not-to-be-parsed"})
                    self.assertEqual(response.status_code, 503)
                    self.no_store(response)

    def test_explicit_versions_and_canonical_fresh_request_id_are_required(self):
        for headers in ({}, {"HTTP_X_MOBILE_POULTRY_VERSION": "2"}, {**HEADERS, "HTTP_X_MOBILE_FINANCE_VERSION": "01"},
                {**HEADERS, "HTTP_X_MOBILE_FINANCE_STORAGE_VERSION": "2"}):
            response = self.client.get(URL, **headers)
            self.assertEqual(response.status_code, 409, response.data)
            self.no_store(response)
        for value in ("", "invalid", REQUEST.upper(), REQUEST + "\n", REQUEST + "," + REQUEST, "0" * 36):
            response = self.read(HTTP_X_MOBILE_FINANCE_STORAGE_REQUEST=value)
            self.assertEqual(response.status_code, 400, response.data)
            self.no_store(response)

    def test_anonymous_unbound_expired_tampered_and_refresh_tokens_cannot_get_grants(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(URL, **HEADERS).status_code, 401)
        expired = AccessToken(self.registration["access"])
        expired.set_exp(lifetime=-timedelta(seconds=1))
        for token, status in ((str(expired), 401), (self.registration["refresh"], 401),
                (str(self.token)[:-8] + "tampered", 401), (str(RefreshToken.for_user(self.user).access_token), 403)):
            response = self.read(HTTP_AUTHORIZATION="Bearer " + token)
            self.assertEqual(response.status_code, status, response.data)
            self.no_store(response)

    def test_foreign_actor_deployment_device_session_and_partial_binding_cannot_get_grants(self):
        for key in ("user_id", "deployment_id", "mobile_device_id", "mobile_session_id"):
            token = AccessToken(self.registration["access"])
            token[key] = str(uuid.uuid4())
            response = self.read(HTTP_AUTHORIZATION="Bearer " + str(token))
            self.assertIn(response.status_code, (401, 403))
            self.no_store(response)
        token = AccessToken(self.registration["access"])
        del token["mobile_session_id"]
        self.assertEqual(self.read(HTTP_AUTHORIZATION="Bearer " + str(token)).status_code, 403)

    def test_current_roles_not_cached_roles_control_grant_and_no_operational_capability_expansion(self):
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER, None):
            self.role(role)
            response = self.read()
            self.assertEqual(response.status_code, 403)
            self.no_store(response)
        for role in (RoleChoices.FARM_SUPERVISOR, RoleChoices.FARM_MANAGER, RoleChoices.DIRECTOR, RoleChoices.ADMIN):
            self.role(role)
            self.validate(self.read())
            self.assertFalse(self.client.get(BASE + "capabilities").data["commands"]["finance"]["available"])

    def test_revoke_session_device_or_expire_session_denies_current_access(self):
        for changes in ({"revoked_at": timezone.now()}, {"expires_at": timezone.now() - timedelta(seconds=1)}):
            MobileSession.objects.filter(pk=self.session.pk).update(**changes)
            self.assertEqual(self.read().status_code, 403)
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=None, expires_at=timezone.now() + timedelta(days=3))
        MobileDevice.objects.filter(pk=self.session.device_id).update(revoked_at=timezone.now())
        self.assertEqual(self.read().status_code, 403)

    def test_no_query_body_or_financial_command_override_is_allowed(self):
        before = self.snapshot()
        with patch.object(storage, "financial_storage_grant", side_effect=AssertionError("Malformed request must not issue grant")):
            for query in ("actor_id=x", "offline_hours=168", "request_id=" + REQUEST, "fields=balance", "command=finance.post", "a=1&a=2", "empty="):
                response = self.client.get(URL + "?" + query, **HEADERS)
                self.assertEqual(response.status_code, 400, response.data)
                self.no_store(response)
            response = self.client.generic("GET", URL, data=b'{"offline_hours":168}', content_type="application/json", **HEADERS)
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_unsupported_writes_and_options_do_not_issue_grants_or_change_records(self):
        before = self.snapshot()
        with patch.object(storage, "financial_storage_grant", side_effect=AssertionError("No issuance outside GET/HEAD")):
            for method in ("post", "put", "patch", "delete"):
                response = getattr(self.client, method)(URL, **HEADERS)
                self.assertEqual(response.status_code, 405, response.data)
                self.no_store(response)
            response = self.client.options(URL, **HEADERS)
            self.assertEqual(response.status_code, 200)
            self.no_store(response)
        self.assertEqual(self.snapshot(), before)

    def test_twenty_repeated_requests_echo_their_own_challenge_and_have_no_business_effect(self):
        before = self.snapshot()
        for _ in range(20):
            request_id = str(uuid.uuid4())
            response = self.read(HTTP_X_MOBILE_FINANCE_STORAGE_REQUEST=request_id)
            self.validate(response, request_id)
            self.assertEqual(response.data["grant"]["scope_revision"], storage._scope(self.stream, self.user, self.session))
        self.assertEqual(self.snapshot(), before)

    def test_late_revocation_or_scope_change_cannot_release_a_grant(self):
        original = storage._scope
        calls = []
        def revoked(*args):
            scope = original(*args)
            calls.append(1)
            if len(calls) == 1:
                MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
            return scope
        with patch.object(storage, "_scope", side_effect=revoked):
            response = self.read()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("grant", response.data)
        self.no_store(response)

    def test_database_failure_is_safe_retry_error_with_no_grant(self):
        with patch.object(storage, "financial_storage_grant", side_effect=DatabaseError("PRIVATE-NOT-TO-BE-ECHOED")):
            response = self.read()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "retry_later")
        self.assertNotIn("PRIVATE", json.dumps(response.data))
        self.no_store(response)


@override_settings(**SETTINGS)
class StorageGrantHTTPTests(BridgeFixture, LiveServerTestCase):
    def test_real_tcp_grants_head_rejected_post_and_revocation_do_not_change_business_state(self):
        before = self.snapshot()
        headers = {"Authorization": "Bearer " + str(self.token), "X-Mobile-Finance-Version": "1",
            "X-Mobile-Finance-Storage-Version": "1", "X-Mobile-Finance-Storage-Request": REQUEST}
        address = self.live_server_url.removeprefix("http://")
        first_observed = None
        for _ in range(20):
            request_id = str(uuid.uuid4())
            with closing(HTTPConnection(address, timeout=10)) as client:
                client.request("GET", URL, headers={**headers, "X-Mobile-Finance-Storage-Request": request_id})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "private, no-store, max-age=0")
                result = json.loads(response.read())
                Draft7Validator(wire.RESPONSE, format_checker=FormatChecker()).validate(result)
                self.assertEqual(result["request_id"], request_id)
                if first_observed is None:
                    first_observed = {"response": result, "cache_control": response.getheader("Cache-Control"), "vary": response.getheader("Vary")}
        for method, status in (("HEAD", 200), ("POST", 405)):
            with closing(HTTPConnection(address, timeout=10)) as client:
                client.request(method, URL, headers=headers)
                response = client.getresponse()
                self.assertEqual(response.status, status)
                body = response.read()
                if method == "HEAD":
                    self.assertEqual(body, b"")
        MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        with closing(HTTPConnection(address, timeout=10)) as client:
            client.request("GET", URL, headers=headers)
            response = client.getresponse()
            self.assertEqual(response.status, 403)
            self.assertNotIn("grant", json.loads(response.read()))
        self.assertEqual(self.snapshot(), before)
        output = os.environ.get("MOBILE_STORAGE_API_FIXTURE_OUTPUT")
        if output:
            root = Path(__file__).resolve().parents[4]
            target = (root / output).resolve()
            if not connection.settings_dict["NAME"].startswith("test_mobile_phase02_") or not target.is_relative_to(root / "docs/mobile/evidence"):
                raise AssertionError("Refuse non-owned HTTP fixture export")
            fixture = {**first_observed, "owned_database": connection.settings_dict["NAME"],
                "actual_http": True, "financial_effects_unchanged": True, "native": False,
                "binding": {"actorId": str(self.user.pk), "deviceId": str(self.session.device_id),
                    "deploymentId": str(self.stream.deployment_id), "sessionId": str(self.session.pk)}}
            with target.open("x", encoding="utf-8") as destination:
                json.dump(fixture, destination, ensure_ascii=False, indent=2)
                destination.write("\n")
