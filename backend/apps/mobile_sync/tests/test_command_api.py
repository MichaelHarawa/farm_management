"""Actual gated financial HTTP boundary on new disposable PostgreSQL only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from http.client import HTTPConnection
import json
import re
from threading import Event
from unittest.mock import patch
import uuid

from django.db import connection
from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, LiveServerTestCase, override_settings
from django.utils import timezone
from django.urls import resolve
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import FundingAllocation, JournalEntry
from apps.finance.services.cash_funding import dated_source_cash
from apps.mobile_sync.commands import financial_uuid as commands, financial_uuid_schema as wire
from apps.mobile_sync.models import MobileSession, SyncOperationReceipt
from apps.mobile_sync.errors import SyncError
from .test_financial_uuid import UUIDFixture, SETTINGS as UUID_SETTINGS
from .test_sync import BASE

SETTINGS = {**UUID_SETTINGS, "MOBILE_SYNC_FINANCIAL_COMMAND_API": True,
    "MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API": True}
URL = BASE + "finance/commands"
HEADERS = {"HTTP_X_MOBILE_FINANCE_VERSION": "1", "HTTP_X_MOBILE_FINANCE_COMMAND_VERSION": "2"}


class FinancialCommandSchemaTests(SimpleTestCase):
    def test_openapi_validates_and_new_paths_preserve_existing_financial_contract(self):
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        from django.urls import include, path
        from apps.mobile_sync.urls import urlpatterns
        from apps.mobile_sync.schema_command_api import openapi_schema

        financial = [p for p in urlpatterns if str(p.pattern).startswith("finance/")]
        original = [p for p in financial if not str(p.pattern).startswith("finance/commands")]

        def generate(patterns):
            return SchemaGenerator(patterns=[path("api/v1/mobile-sync/", include(patterns))]).get_schema(request=None, public=True)

        baseline, specification = generate(original), generate(financial)
        validate_schema(specification)
        for old_path, operations in baseline["paths"].items():
            self.assertEqual(specification["paths"][old_path], operations)
        self.assertEqual(specification["components"], baseline["components"])
        post = specification["paths"][URL]["post"]
        self.assertEqual(set(specification["paths"][URL]), {"post"})
        self.assertTrue(post["requestBody"]["required"])
        self.assertEqual(set(post["requestBody"]["content"]), {"application/json"})
        self.assertEqual(post["requestBody"]["content"]["application/json"]["schema"], openapi_schema(wire.ENVELOPE))
        self.assertEqual(set(specification["paths"][URL + "/{operation_id}"]), {"get"})
        for operation in (post, specification["paths"][URL + "/{operation_id}"]["get"]):
            headers = {item["name"]: item for item in operation["parameters"] if item["in"] == "header"}
            for name, version in (("X-Mobile-Finance-Version", 1), ("X-Mobile-Finance-Command-Version", 2)):
                self.assertTrue(headers[name]["required"])
                self.assertEqual(headers[name]["schema"]["enum"], [version])
            self.assertFalse(operation["responses"]["200"]["content"]["application/json"]["schema"]["additionalProperties"])

    def test_openapi_conversion_does_not_mutate_runtime_validation_or_relax_money(self):
        from apps.mobile_sync.schema_command_api import openapi_schema

        original = deepcopy(wire.ENVELOPE)
        converted = openapi_schema(wire.ENVELOPE)
        self.assertEqual(wire.ENVELOPE, original)
        self.assertNotIn('"const"', json.dumps(converted))
        payload = converted["properties"]["operations"]["items"]["properties"]["payload"]
        self.assertEqual(payload["properties"]["total_payment_amount"]["not"], {"enum": ["0.00"]})
        self.assertEqual(converted["properties"]["financial_protocol_version"]["enum"], [1])
        self.assertNotIn("required", openapi_schema(wire.RESULT)["properties"]["field_errors"])
        converted["properties"]["financial_protocol_version"]["enum"].append(999)
        self.assertEqual(wire.ENVELOPE, original)


class APIFixture(UUIDFixture):
    def setUp(self):
        if connection.vendor != "postgresql" or not re.fullmatch(r"test_mobile_phase02_[0-9a-f]{12}", connection.settings_dict["NAME"]):
            raise RuntimeError("Requires a NEW owned PostgreSQL test DB before business fixtures")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            if cursor.fetchone()[0] != connection.settings_dict["NAME"]:
                raise RuntimeError("Actual owned test DB mismatch")
        super().setUp()

    def submit(self, operations):
        return self.client.post(URL, self.envelope(operations), format="json", **HEADERS)

    def status(self, operation_id, client=None):
        return (client or self.client).get(URL + "/" + operation_id, **HEADERS)

    def validate_response(self, response):
        self.assertEqual(response.status_code, 200, response.data)
        Draft7Validator(wire.RESPONSE, format_checker=FormatChecker()).validate(response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        for value in ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-Command-Version"):
            self.assertIn(value, response["Vary"])
        self.assertLess(len(response.content), 128 * 1024)


@override_settings(**SETTINGS)
class FinancialCommandAPITests(APIFixture, TestCase):
    def test_default_off_and_all_submission_prerequisites_refuse_before_auth_or_sql(self):
        for flag in ("MOBILE_SYNC_FINANCIAL_COMMAND_API", "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS",
                "MOBILE_SYNC_FINANCIAL_COMMANDS", "MOBILE_SYNC_FINANCIAL_REFERENCES", "FINANCE_INVENTORY_INVOICES",
                "MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API", "MOBILE_SYNC_FINANCIAL_READS",
                "MOBILE_SYNC_CAPTURE", "MOBILE_SYNC_ENABLED"):
            with override_settings(**{flag: False}):
                for method in ("post", "get", "head", "options", "put", "delete"):
                    with self.assertNumQueries(0):
                        response = getattr(APIClient(), method)(URL, HTTP_AUTHORIZATION="Bearer invalid")
                    self.assertEqual(response.status_code, 503)
                    self.assertIn("no-store", response["Cache-Control"])
        for flag in ("MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API", "MOBILE_SYNC_FINANCIAL_READS"):
            with override_settings(**{flag: False}), self.assertNumQueries(0):
                response = APIClient().get(URL + "/" + str(uuid.uuid4()), HTTP_AUTHORIZATION="Bearer invalid")
            self.assertEqual(response.status_code, 503)

    def test_signed_bound_request_posts_once_and_twenty_replays_keep_exact_effect(self):
        command, before = self.command(), self.snapshot()
        response = self.submit([command])
        self.validate_response(response)
        accepted = response.data["results"][0]
        self.assertEqual(accepted["outcome"], "accepted")
        original = self.snapshot()
        for _ in range(20):
            replay = self.submit([command])
            self.validate_response(replay)
            self.assertEqual(replay.data["results"], [{**accepted, "outcome": "replayed"}])
        recovered = self.status(command["operation_id"])
        self.validate_response(recovered)
        self.assertEqual(recovered.data["results"], [accepted])
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)
        self.assertEqual(JournalEntry.objects.count() - len(before["finance"]["journalentry"]), 4)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))

    def test_status_survives_submission_flags_off_and_write_downgrade(self):
        command = self.command()
        accepted = self.submit([command]).data["results"][0]
        self.role(RoleChoices.STAKE_HOLDER)
        before = self.snapshot()
        with override_settings(MOBILE_SYNC_FINANCIAL_COMMAND_API=False, MOBILE_SYNC_FINANCIAL_COMMANDS=False,
                MOBILE_SYNC_FINANCIAL_UUID_COMMANDS=False, MOBILE_SYNC_FINANCIAL_REFERENCES=False,
                FINANCE_INVENTORY_INVOICES=False):
            response = self.status(command["operation_id"])
        self.validate_response(response)
        self.assertEqual(response.data["results"], [accepted])
        self.assertEqual(self.snapshot(), before)
        for private in ("payee", "amount", "funding_source", "notes", "source_pk", "resolution"):
            self.assertNotIn('"' + private + '"', response.content.decode())

    def test_anonymous_tampered_unbound_refresh_and_expired_jwt_refused(self):
        body, before = self.envelope([self.command()]), self.snapshot()
        expired = AccessToken(self.registration["access"])
        expired.set_exp(lifetime=-timedelta(seconds=1))
        for token in (None, str(self.token)[:-8] + "tampered", self.registration["refresh"], str(expired),
                str(RefreshToken.for_user(self.user).access_token)):
            client = APIClient()
            if token:
                client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
            response = client.post(URL, body, format="json", **HEADERS)
            self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.snapshot(), before)

    def test_wrong_headers_query_body_and_methods_cannot_dispatch(self):
        body, before = self.envelope([self.command()]), self.snapshot()
        for headers in ({}, {**HEADERS, "HTTP_X_MOBILE_FINANCE_VERSION": "2"},
                {**HEADERS, "HTTP_X_MOBILE_FINANCE_COMMAND_VERSION": "1"}):
            self.assertEqual(self.client.post(URL, body, format="json", **headers).status_code, 409)
        self.assertEqual(self.client.post(URL + "?actor=other", body, format="json", **HEADERS).status_code, 400)
        for method in ("get", "put", "patch", "delete"):
            self.assertEqual(getattr(self.client, method)(URL, **HEADERS).status_code, 405)
        self.assertEqual(self.client.post(URL, "text", content_type="text/plain", **HEADERS).status_code, 415)
        self.assertEqual(self.client.generic("GET", URL + "/" + str(uuid.uuid4()), data="{}",
            content_type="application/json", **HEADERS).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_duplicate_fields_floating_json_and_non_utf8_refused_before_dispatch(self):
        body, before = self.envelope([self.command()]), self.snapshot()
        original = json.dumps(body)
        malformed = [original.replace('"financial_protocol_version": 1', '"financial_protocol_version": 1, "financial_protocol_version": 1'),
            original.replace('"invoice_line_index": 0', '"invoice_line_index": 0.0'),
            original.replace('"invoice_line_index": 0', '"invoice_line_index": NaN'), b'\xff']
        with patch.object(commands, "execute_uuid_envelope", side_effect=AssertionError("Malformed JSON cannot dispatch")):
            for raw in malformed:
                self.assertEqual(self.client.post(URL, raw, content_type="application/json", **HEADERS).status_code, 400)
        self.assertEqual(self.snapshot(), before)

    def test_complete_envelope_validation_precedes_effects_and_environment_binding(self):
        command, before = self.command(), self.snapshot()
        invalid = deepcopy(command)
        invalid["payload"]["total_payment_amount"] = 150.00
        for body in (self.envelope([command, invalid]), self.envelope([command, command]),
                {**self.envelope([command]), "device_id": str(uuid.uuid4())},
                {**self.envelope([command]), "deployment_id": str(uuid.uuid4())}):
            response = self.client.post(URL, body, format="json", **HEADERS)
            self.assertIn(response.status_code, (400, 403))
            self.assertEqual(self.snapshot(), before)

    def test_missing_dependency_does_not_consume_id_but_terminal_rejection_does(self):
        command = self.command(depends_on=[str(uuid.uuid4())])
        blocked = self.submit([command])
        self.validate_response(blocked)
        self.assertEqual(blocked.data["results"][0]["outcome"], "dependency_blocked")
        self.assertEqual(SyncOperationReceipt.objects.count(), 0)
        rejected = self.command()
        rejected["payload"]["invoices"][0]["invoice_group_id"] = str(uuid.uuid4())
        result = self.submit([rejected]).data["results"][0]
        self.assertEqual(result["outcome"], "conflict")
        before = self.snapshot()
        self.assertEqual(self.status(rejected["operation_id"]).data["results"], [result])
        self.assertEqual(self.snapshot(), before)

    def test_current_role_and_session_revocation_refuse_no_foreign_recovery(self):
        command = self.command()
        accepted = self.submit([command])
        self.validate_response(accepted)
        foreign, _, _, _ = self.register(self.user)
        self.assertEqual(self.status(command["operation_id"], foreign).status_code, 403)
        for role in (RoleChoices.GENERAL_WORKER, None):
            self.role(role)
            self.assertEqual(self.status(command["operation_id"]).status_code, 403)
        self.role(RoleChoices.FARM_MANAGER)
        MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        before = self.snapshot()
        self.assertEqual(self.status(command["operation_id"]).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_changed_content_never_reposts_and_unknown_status_is_not_rejection(self):
        command = self.command()
        self.submit([command])
        before = self.snapshot()
        changed = deepcopy(command)
        changed["payload"]["notes"] += " changed"
        result = self.submit([changed]).data["results"][0]
        self.assertEqual(result["code"], "idempotency_mismatch")
        self.assertEqual(self.status(str(uuid.uuid4())).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_actor_recovery_is_identical_to_missing_operation(self):
        command = self.command()
        self.submit([command])
        actor = get_user_model().objects.create_user(username="other-command-manager", email="other@example.invalid", password="synthetic-only")
        role, _ = Role.objects.get_or_create(slug=RoleChoices.FARM_MANAGER, defaults={"name": "Farm manager"})
        actor.roles.add(role)
        client, _, _, _ = self.register(actor)
        before = self.snapshot()
        foreign = self.status(command["operation_id"], client)
        missing = self.status(str(uuid.uuid4()), client)
        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.data, missing.data)
        self.assertEqual(self.snapshot(), before)

    def test_forward_dependencies_are_ordered_and_later_http_failure_keeps_first_receipt(self):
        first = self.partial(self.command(), "25.00")
        second = self.partial(self.command(depends_on=[first["operation_id"]]), "25.00")
        second["payload"]["external_reference"] += "-SECOND"
        original = commands.execute_uuid_command

        def fail_later(command, *args):
            if command["operation_id"] == second["operation_id"]:
                raise SyncError("retry_later", "Synthetic transport failure after the earlier operation committed.", 503)
            return original(command, *args)

        with patch.object(commands, "execute_uuid_command", side_effect=fail_later):
            # Reverse input: the dependency graph, not UI order, dispatches first.
            response = self.submit([second, first])
        self.assertEqual(response.status_code, 503)
        accepted = self.status(first["operation_id"])
        self.validate_response(accepted)
        self.assertEqual(accepted.data["results"][0]["outcome"], "accepted")
        self.assertEqual(self.status(second["operation_id"]).status_code, 404)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)
        response = self.submit([second, first])
        self.validate_response(response)
        self.assertEqual([row["operation_id"] for row in response.data["results"]], [first["operation_id"], second["operation_id"]])
        self.assertEqual([row["outcome"] for row in response.data["results"]], ["replayed", "accepted"])
        self.assertEqual(SyncOperationReceipt.objects.count(), 4)

    def test_oversized_request_refuses_before_auth_or_sql_and_post_is_non_atomic_at_request_level(self):
        with self.assertNumQueries(0):
            response = APIClient().post(URL, b'x' * (commands.MAX_BYTES + 1), content_type="application/json",
                HTTP_AUTHORIZATION="Bearer invalid", **HEADERS)
        self.assertEqual(response.status_code, 413)
        # Domain/service transactions remain atomic per operation even if the
        # deployment later opts into Django's ATOMIC_REQUESTS wrapper.
        self.assertIn("default", resolve(URL).func._non_atomic_requests)

    def test_response_budget_failure_after_commit_recovers_original_without_second_effect(self):
        command = self.command()
        with patch("apps.mobile_sync.command_views.MAX_RESPONSE_BYTES", 1):
            response = self.submit([command])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "financial_response_unavailable")
        original = self.snapshot()
        result = self.status(command["operation_id"])
        self.validate_response(result)
        self.assertEqual(result.data["results"][0]["outcome"], "accepted")
        self.assertEqual(self.submit([command]).data["results"][0]["outcome"], "replayed")
        self.assertEqual(self.snapshot(), original)


@override_settings(**SETTINGS)
class FinancialCommandHTTPTests(APIFixture, LiveServerTestCase):
    def request(self, method, path, body=None):
        client = HTTPConnection(self.server_thread.host, self.server_thread.port, timeout=15)
        client.request(method, path, body=None if body is None else json.dumps(body), headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + self.registration["access"],
            "X-Mobile-Finance-Version": "1", "X-Mobile-Finance-Command-Version": "2"})
        response = client.getresponse()
        raw = response.read(128 * 1024 + 1)
        status = response.status
        client.close()
        self.assertLessEqual(len(raw), 128 * 1024)
        return status, json.loads(raw)

    def test_real_tcp_response_lost_after_commit_recovery_and_twenty_replays(self):
        command, before = self.command(), self.snapshot()
        committed, release = Event(), Event()
        execute = commands.execute_uuid_envelope

        def delayed(*args, **kwargs):
            result = execute(*args, **kwargs)
            committed.set()
            if not release.wait(10):
                raise RuntimeError("Synthetic response-loss coordination timeout")
            return result

        client = HTTPConnection(self.server_thread.host, self.server_thread.port, timeout=15)
        with patch.object(commands, "execute_uuid_envelope", side_effect=delayed):
            try:
                client.request("POST", URL, json.dumps(self.envelope([command])), headers={
                    "Content-Type": "application/json", "Authorization": "Bearer " + self.registration["access"],
                    "X-Mobile-Finance-Version": "1", "X-Mobile-Finance-Command-Version": "2"})
                self.assertTrue(committed.wait(10), "Actual commit must precede deliberate response loss")
                client.close()  # No status/body consumed; original IDs are the recovery keys.
            finally:
                release.set()
                client.close()
        status, response = self.request("GET", URL + "/" + command["operation_id"])
        self.assertEqual(status, 200)
        accepted = response["results"][0]
        self.assertEqual(accepted["outcome"], "accepted")
        after = self.snapshot()
        for _ in range(20):
            status, replay = self.request("POST", URL, self.envelope([command]))
            self.assertEqual(status, 200)
            self.assertEqual(replay["results"], [{**accepted, "outcome": "replayed"}])
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(JournalEntry.objects.count() - len(before["finance"]["journalentry"]), 4)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
