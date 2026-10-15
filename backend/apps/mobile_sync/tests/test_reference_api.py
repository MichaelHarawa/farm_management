"""Real JWT/DRF online reference API on newly owned PostgreSQL only."""
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
from http.client import HTTPConnection
import json
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase, TestCase, override_settings
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import RoleChoices
from apps.finance.models import FinancialCommandReceipt, FundingSource, FundingSourceType
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import financial_references as funding, invoice_references as invoices, reference_views as views
from apps.mobile_sync import schema_reference_api as wire, schema_financial_references as funding_wire, schema_invoice_references as invoice_wire
from apps.mobile_sync.models import SyncBootstrap, SyncBootstrapPage, SyncOperationReceipt
from apps.mobile_sync.projections import canonical
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_sync import BASE

ROOT = BASE + "finance/references/"
HEADER = {"HTTP_X_MOBILE_FINANCE_VERSION": "1", "HTTP_X_MOBILE_FINANCE_REFERENCES_VERSION": "1"}
SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCES": True}


@override_settings(**SETTINGS)
class FinancialReferenceAPITests(BridgeFixture, TestCase):
    def setUp(self):
        super().setUp()
        funding.prepare_funding_references([str(self.source.pk)], self.user, self.session, self.token)

    def urls(self):
        return [ROOT + "capabilities", ROOT + "funding", ROOT + "invoices", self.detail_url()]

    def detail_url(self, original=None):
        original = original or self.invoice
        return ROOT + "invoices/" + original["invoice_group_id"] + "?invoice_version=" + original["invoice_version"]

    def read(self, path, **headers):
        return self.client.get(path, **{**HEADER, **headers})

    def validate(self, response, schema):
        self.assertEqual(response.status_code, 200, response.data)
        Draft7Validator(schema, format_checker=FormatChecker()).validate(response.data)
        self.no_store(response)

    def no_store(self, response):
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        for header in ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-References-Version"):
            self.assertIn(header, response["Vary"])

    def test_four_reads_use_current_bound_identity_without_financial_effects(self):
        before = self.snapshot()
        for path, schema in zip(self.urls(), (wire.CAPABILITIES, funding_wire.CATALOG, invoice_wire.CATALOG, invoice_wire.DETAIL), strict=True):
            response = self.read(path)
            self.validate(response, schema)
            self.assertEqual(response.data["deployment_id"], str(self.stream.deployment_id))
            self.assertEqual(response.data["device_id"], str(self.session.device_id))
            self.assertFalse(response.data["financial_uploads"])
            self.assertEqual(response.data["offline_cache_seconds"], 0)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(SyncBootstrap.objects.exists())
        self.assertFalse(SyncBootstrapPage.objects.exists())
        self.assertFalse(SyncOperationReceipt.objects.exists())

    def test_capabilities_bind_actor_and_both_separate_selection_scopes_not_uploads(self):
        response = self.read(ROOT + "capabilities")
        self.validate(response, wire.CAPABILITIES)
        self.assertEqual(response.data["actor_id"], str(self.user.pk))
        self.assertEqual(response.data["scopes"]["funding"], self.read(ROOT + "funding").data["scope_revision"])
        self.assertEqual(response.data["scopes"]["original_invoices"], self.read(ROOT + "invoices").data["scope_revision"])
        self.assertNotEqual(response.data["scopes"]["funding"], response.data["scopes"]["original_invoices"])
        self.assertEqual(response.data["packs"], [])
        self.assertEqual(self.client.get(BASE + "capabilities").data["commands"]["finance"]["available"], False)

    def test_default_off_either_read_gate_or_operational_gate_refuses_before_auth_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_READS", "MOBILE_SYNC_FINANCIAL_REFERENCES", "MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{flag: False}):
                for path in self.urls():
                    with self.assertNumQueries(0):
                        response = self.read(path, HTTP_AUTHORIZATION="Bearer invalid-do-not-authenticate")
                    self.assertEqual(response.status_code, 503, response.data)
                    self.no_store(response)

    def test_both_explicit_headers_required_no_poultry_or_receipt_fallback(self):
        for headers in ({}, {"HTTP_X_MOBILE_FINANCE_VERSION": "1"}, {"HTTP_X_MOBILE_FINANCE_REFERENCES_VERSION": "1"},
                {**HEADER, "HTTP_X_MOBILE_FINANCE_VERSION": "2"}, {**HEADER, "HTTP_X_MOBILE_FINANCE_REFERENCES_VERSION": "01"},
                {"HTTP_X_MOBILE_POULTRY_VERSION": "2"}):
            response = self.client.get(ROOT + "funding", **headers)
            self.assertEqual(response.status_code, 409, response.data)
            self.assertEqual(response.data["code"], "unsupported_protocol")
            self.no_store(response)

    def test_anonymous_and_ordinary_unbound_jwt_cannot_read(self):
        client = APIClient()
        for path in self.urls():
            response = client.get(path, **HEADER)
            self.assertEqual(response.status_code, 401, response.data)
            self.no_store(response)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        for path in self.urls():
            response = client.get(path, **HEADER)
            self.assertEqual(response.status_code, 403, response.data)
            self.assertEqual(response.data["code"], "device_required")

    def test_expired_tampered_and_refresh_token_are_not_authenticated_access(self):
        expired = AccessToken(self.registration["access"])
        expired.set_exp(lifetime=-timedelta(seconds=1))
        tokens = [str(expired), str(self.token)[:-8] + "tampered", self.registration["refresh"]]
        for token in tokens:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            response = self.read(ROOT + "capabilities")
            self.assertEqual(response.status_code, 401, response.data)
            self.no_store(response)

    def test_wrong_deployment_device_session_or_partial_binding_is_refused(self):
        for key, value in (("deployment_id", str(uuid.uuid4())), ("mobile_device_id", str(uuid.uuid4())),
                ("mobile_session_id", str(uuid.uuid4())), ("mobile_session_id", None)):
            token = AccessToken(self.registration["access"])
            if value is None:
                del token[key]
            else:
                token[key] = value
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            response = self.read(ROOT + "invoices")
            self.assertEqual(response.status_code, 403, response.data)
            self.no_store(response)

    def test_revoked_or_expired_session_cannot_read(self):
        self.session.expires_at = timezone.now() - timedelta(seconds=1)
        self.session.save(update_fields=["expires_at"])
        for path in self.urls():
            response = self.read(path)
            self.assertEqual(response.status_code, 403, response.data)
            self.no_store(response)

    def test_worker_and_stakeholder_are_denied_before_any_financial_lookup(self):
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER):
            self.role(role)
            with patch.object(funding, "_sources", side_effect=AssertionError("Must not lookup money")), patch.object(invoices, "_owned", side_effect=AssertionError("Must not lookup invoices")):
                for path in self.urls():
                    response = self.read(path)
                    self.assertEqual(response.status_code, 403, response.data)
                    self.no_store(response)

    def test_other_actor_even_admin_has_no_invoice_and_same_missing_error(self):
        foreign = get_user_model().objects.create_superuser(username="api-reference-foreign", email="api-reference-foreign@example.invalid", password="Synthetic-only-password")
        self.client, _, _, _ = self.register(foreign)
        response = self.read(ROOT + "invoices")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["total_authorized_rows"], 0)
        foreign_detail = self.read(self.detail_url())
        missing = self.read(self.detail_url({"invoice_group_id": str(uuid.uuid4()), "invoice_version": self.invoice["invoice_version"]}))
        self.assertEqual(foreign_detail.status_code, 404)
        self.assertEqual(foreign_detail.data, missing.data)
        self.no_store(foreign_detail)

    def test_owner_references_hidden_from_manager_and_worker_never_learns_owner(self):
        self.role(RoleChoices.FARM_MANAGER)
        response = self.read(ROOT + "funding")
        self.validate(response, funding_wire.CATALOG)
        self.assertEqual(response.data["total_authorized_rows"], 0)
        self.assertNotIn("owner_capital", canonical(response.data))

    def test_identity_field_limit_and_duplicate_query_overrides_are_refused(self):
        suffixes = ["actor_id=" + str(self.user.pk), "device_id=" + str(self.session.device_id),
            "deployment_id=" + str(self.stream.deployment_id), "fields=notes", "limit=99999", "cursor=a&cursor=b", "cursor="]
        with patch.object(funding, "funding_reference_catalog", side_effect=AssertionError("Malformed input must not select sources")):
            for suffix in suffixes:
                response = self.read(ROOT + "funding?" + suffix)
                self.assertEqual(response.status_code, 400, response.data)
                self.no_store(response)
        for suffix in ("", "?invoice_version=", "?invoice_version=a&invoice_version=b", "?cursor=a"):
            response = self.read(ROOT + "invoices/" + self.invoice["invoice_group_id"] + suffix)
            self.assertEqual(response.status_code, 400, response.data)

    def test_get_body_and_unsupported_writes_have_no_business_effect(self):
        before = self.snapshot()
        for path in self.urls():
            response = self.client.generic("GET", path, data=json.dumps({"actor_id": str(self.user.pk)}), content_type="application/json", **HEADER)
            self.assertEqual(response.status_code, 400, response.data)
            self.no_store(response)
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                response = self.client.generic(method, path, **HEADER)
                self.assertEqual(response.status_code, 405, response.data)
                self.no_store(response)
        self.assertEqual(self.snapshot(), before)

    def test_unprepared_funding_returns_explicit_failure_without_get_seeding(self):
        with sync_boundary():
            FundingSource.objects.create(source_type=FundingSourceType.LOAN, description="Synthetic unprepared reference")
        before = self.snapshot()
        response = self.read(ROOT + "funding")
        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data["code"], "funding_catalog_not_prepared")
        self.no_store(response)
        self.assertEqual(self.snapshot(), before)

    def test_http_invoice_paging_is_scope_bound_and_returns_each_original_once(self):
        with patch.object(invoices, "PAGE_ROWS", 1):
            first = self.read(ROOT + "invoices")
            self.validate(first, invoice_wire.CATALOG)
            last = self.client.get(ROOT + "invoices", {"cursor": first.data["next_cursor"]}, **HEADER)
            self.validate(last, invoice_wire.CATALOG)
            self.assertEqual(len({row["invoice_group_id"] for row in first.data["rows"] + last.data["rows"]}), 2)
            self.assertIsNone(last.data["next_cursor"])
            self.role(RoleChoices.FARM_MANAGER)
            response = self.client.get(ROOT + "invoices", {"cursor": first.data["next_cursor"]}, **HEADER)
            self.assertEqual(response.status_code, 409, response.data)
            self.no_store(response)

    def test_wrong_version_and_damaged_evidence_are_protected_review_not_fake_empty(self):
        response = self.read(self.detail_url().replace(self.invoice["invoice_version"], "0" * 64))
        self.assertEqual(response.status_code, 409, response.data)
        damaged = deepcopy(self.invoice)
        damaged["capture"]["notes"] = "Changed private evidence"
        corrupt_inventory(FinancialCommandReceipt, self.invoice["invoice_group_id"], result=json.dumps(damaged))
        response = self.read(ROOT + "invoices")
        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data["code"], "invoice_reference_review_required")
        self.assertNotIn("Changed private evidence", canonical(response.data))
        self.no_store(response)

    def test_late_scope_loss_never_releases_catalog(self):
        self.role(RoleChoices.DIRECTOR)
        original = funding._row
        def downgrade(*args):
            row = original(*args)
            self.role(RoleChoices.FARM_MANAGER)
            return row
        with patch.object(funding, "_row", side_effect=downgrade):
            response = self.read(ROOT + "funding")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "financial_reference_scope_changed")
        self.assertNotIn("rows", response.data)
        self.no_store(response)

    def test_late_capability_revocation_is_refused_before_release(self):
        original = funding._scope
        count = 0
        def revoke(*args):
            nonlocal count
            scope = original(*args)
            count += 1
            if count == 1:
                self.session.revoked_at = timezone.now()
                self.session.save(update_fields=["revoked_at"])
            return scope
        with patch.object(funding, "_scope", side_effect=revoke):
            response = self.read(ROOT + "capabilities")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertNotIn("scopes", response.data)

    def test_current_finance_writers_can_read_their_own_invoices(self):
        for role in (RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR, RoleChoices.DIRECTOR, RoleChoices.ADMIN):
            self.role(role)
            self.validate(self.read(ROOT + "invoices"), invoice_wire.CATALOG)
            self.validate(self.read(self.detail_url()), invoice_wire.DETAIL)

    def test_new_capture_flags_not_required_and_do_not_enable_financial_post(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False, MOBILE_SYNC_FINANCIAL_COMMANDS=False,
                MOBILE_SYNC_FINANCIAL_UUID_COMMANDS=False):
            self.validate(self.read(self.detail_url()), invoice_wire.DETAIL)
            self.assertEqual(self.client.post(BASE + "finance/push", {}, format="json", **HEADER).status_code, 404)
            self.assertEqual(self.client.post(ROOT + "funding", {}, format="json", **HEADER).status_code, 400)

    def test_catalog_limits_have_finite_http_error_no_partial_success(self):
        with patch.object(invoices, "MAX_CATALOG_ROWS", 1):
            response = self.read(ROOT + "invoices")
        self.assertEqual(response.status_code, 413, response.data)
        self.assertEqual(response.data["code"], "invoice_reference_limit")
        self.assertNotIn("rows", response.data)
        self.no_store(response)


@override_settings(**SETTINGS)
class FinancialReferenceHTTPTests(BridgeFixture, LiveServerTestCase):
    def test_actual_tcp_reads_repeat_exact_parent_and_refuse_writes_without_effects(self):
        funding.prepare_funding_references([str(self.source.pk)], self.user, self.session, self.token)
        before = self.snapshot()
        # This server binds an ephemeral loopback port INSIDE the isolated test
        # container, never 7070/7074 or a farm business database. No token logged.
        address = self.live_server_url.removeprefix("http://")
        headers = {"Authorization": "Bearer " + str(self.token), "X-Mobile-Finance-Version": "1",
            "X-Mobile-Finance-References-Version": "1"}
        schemas = [wire.CAPABILITIES, funding_wire.CATALOG, invoice_wire.CATALOG, invoice_wire.DETAIL]
        urls = [ROOT + "capabilities", ROOT + "funding", ROOT + "invoices",
            ROOT + "invoices/" + self.invoice["invoice_group_id"] + "?invoice_version=" + self.invoice["invoice_version"]]
        original_detail = None
        for index, path in enumerate(urls + [urls[-1]] * 20):
            with closing(HTTPConnection(address, timeout=10)) as client:
                client.request("GET", path, headers=headers)
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Cache-Control"), "private, no-store, max-age=0")
                body = json.loads(response.read())
            Draft7Validator(schemas[min(index, 3)], format_checker=FormatChecker()).validate(body)
            if index >= 3:
                immutable = {key: value for key, value in body.items() if key != "server_time"}
                if original_detail is None:
                    original_detail = immutable
                self.assertEqual(immutable, original_detail)
        with closing(HTTPConnection(address, timeout=10)) as client:
            client.request("POST", ROOT + "funding", headers=headers)
            response = client.getresponse()
            self.assertEqual(response.status, 405)
            response.read()
        with closing(HTTPConnection(address, timeout=10)) as client:
            client.request("HEAD", ROOT + "invoices", headers=headers)
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")
        self.assertEqual(self.snapshot(), before)
