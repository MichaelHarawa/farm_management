"""Real PostgreSQL/DRF financial recovery, only on the guarded owned test DB."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import FinancialCommandReceipt, FundingAllocation, JournalLine
from apps.finance.services import inventory_payment_summary as summaries
from apps.finance.services.inventory_referenced_payments import record_referenced_inventory_payment
from apps.finance.tests import test_inventory_referenced_payments as references
from apps.finance.tests import test_inventory_purchase_proof as proof
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import schema_financial_reads as wire
from apps.mobile_sync import financial_reads
from apps.mobile_sync.models import (MobileDevice, MobileSession, SyncBootstrap, SyncChange,
    SyncEntity, SyncOperationReceipt, SyncStreamState)
from apps.mobile_sync.projections import canonical
from apps.mobile_sync.writers import sync_boundary
from .test_sync import BASE, TEST_SETTINGS


FINANCE = BASE + "finance/"
HEADER = {"HTTP_X_MOBILE_FINANCE_VERSION": "1"}
SETTINGS = {**TEST_SETTINGS, "MOBILE_SYNC_FINANCIAL_READS": True, "FINANCE_INVENTORY_INVOICES": True}


@override_settings(**SETTINGS)
class FinancialReceiptReadTests(TestCase):
    def setUp(self):
        # Existing private posting fixtures run with operational capture off.
        # Enabling only online reads afterwards does NOT seed financial packs.
        with override_settings(MOBILE_SYNC_CAPTURE=False):
            references.setup(self)
            capture = references.request(self, notes="PRIVATE-FUNDING-OWNER-NOTE-DO-NOT-PUBLISH")
            self.original, _ = record_referenced_inventory_payment(**capture)
            self.receipt = FinancialCommandReceipt.objects.get(pk=capture["submission_id"])
        self.stream, _ = SyncStreamState.objects.get_or_create(pk=1)
        self.stream.ready = True
        self.stream.save(update_fields=["ready"])
        self.client, self.registration = self.register(self.user)

    def register(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        response = client.post(BASE + "devices", {"installation_id": str(uuid.uuid4()),
            "app_version": "financial-read-test", "platform": "android", "protocol_version": 1,
            "device_label": "Owned synthetic financial read test"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client, response.data

    def url(self, part="status", operation_id=None):
        return FINANCE + f"supplier-payments/{operation_id or self.receipt.pk}/{part}"

    def read(self, part="status", client=None, operation_id=None):
        return (client or self.client).get(self.url(part, operation_id), **HEADER)

    def validate(self, response, schema):
        self.assertEqual(response.status_code, 200, response.data)
        Draft7Validator.check_schema(schema)
        Draft7Validator(schema, format_checker=FormatChecker()).validate(response.data)
        self.assertEqual(response["Cache-Control"], "private, no-store, max-age=0")
        self.assertIn("Authorization", response["Vary"])
        self.assertIn("X-Mobile-Finance-Version", response["Vary"])

    def snapshot(self):
        return {"finance": proof.snapshot(), "sync": {
            model._meta.model_name: list(model.objects.order_by("pk").values())
            for model in (SyncStreamState, SyncEntity, SyncChange, SyncOperationReceipt, SyncBootstrap)}}

    def actor_role(self, role):
        with sync_boundary():
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            self.user.roles.clear()
            if role:
                selected, _ = Role.objects.get_or_create(slug=role, defaults={"name": role})
                self.user.roles.add(selected)

    def test_twenty_status_recoveries_return_exact_original_acceptance_without_effects(self):
        before = self.snapshot()
        for _ in range(20):
            response = self.read()
            self.validate(response, wire.STATUS)
            self.assertEqual(response.data["operation_id"], str(self.receipt.pk))
            self.assertEqual(response.data["receipt_hash"], self.receipt.request_hash)
            self.assertEqual(response.data["payment_version"], self.original["payment_version"])
            self.assertEqual(response.data["identity_kind"], "financial_command_receipt")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150"))
        self.assertNotIn("amount", response.data)
        self.assertNotIn("canonical_entities", response.data)

    def test_summary_is_positive_exact_and_excludes_protected_fields_and_private_notes(self):
        before = self.snapshot()
        response = self.read("summary")
        self.validate(response, wire.SUMMARY)
        summary = response.data["summary"]
        self.assertEqual(summary["amount"], "150.00")
        self.assertEqual(summary["payment_date"], "2026-01-12")
        self.assertEqual(summary["operation_id"], str(self.receipt.pk))
        self.assertTrue(summary["note_available"])
        self.assertTrue(summary["recorded_at"].endswith("Z"))
        self.assertEqual(summary["recorded_at"], self.read().data["recorded_at"])
        for forbidden in ("PRIVATE-FUNDING", "funding_source", "classification", "actor_id", "journal", "expenditure_id", '"notes"'):
            self.assertNotIn(forbidden, canonical(response.data))
        self.assertEqual(self.snapshot(), before)

    def test_separate_capabilities_grant_no_upload_pack_or_offline_access(self):
        response = self.client.get(FINANCE + "capabilities", **HEADER)
        self.validate(response, wire.CAPABILITIES)
        self.assertFalse(response.data["financial_uploads"])
        self.assertEqual(response.data["packs"], [])
        self.assertEqual(response.data["offline_cache_seconds"], 0)
        operational = self.client.get(BASE + "capabilities")
        self.assertEqual(operational.status_code, 200, operational.data)
        self.assertFalse(operational.data["commands"]["finance"]["available"])
        self.assertNotIn("financial_read_version", operational.data)

    def test_default_off_rejects_all_reads_before_any_database_query(self):
        with override_settings(MOBILE_SYNC_FINANCIAL_READS=False):
            for url in (FINANCE + "capabilities", self.url(), self.url("summary")):
                with self.subTest(url=url), self.assertNumQueries(0):
                    response = self.client.get(url, **HEADER)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.data["code"], "financial_reads_disabled")
                self.assertIn("no-store", response["Cache-Control"])

    def test_explicit_finance_version_is_required_and_cannot_fall_back_to_poultry(self):
        with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
            for header in ({}, {"HTTP_X_MOBILE_POULTRY_VERSION": "2"},
                    {"HTTP_X_MOBILE_FINANCE_VERSION": "2"}, {"HTTP_X_MOBILE_FINANCE_VERSION": "01"}):
                response = self.client.get(self.url(), **header)
                self.assertEqual(response.status_code, 409, response.data)
            lookup.assert_not_called()

    def test_unbound_ordinary_jwt_cannot_read_financial_receipts(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
            response = self.read(client=client)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data["code"], "device_required")
            lookup.assert_not_called()

    def test_foreign_deployment_or_partial_session_binding_cannot_read_receipts(self):
        for field, value in (("deployment_id", str(uuid.uuid4())), ("mobile_device_id", str(uuid.uuid4())),
                             ("mobile_session_id", str(uuid.uuid4())), ("mobile_session_id", None)):
            token = AccessToken(self.registration["access"])
            if value is None:
                del token[field]
            else:
                token[field] = value
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
            with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
                response = self.read(client=client)
                self.assertEqual(response.status_code, 403, response.data)
                lookup.assert_not_called()

    def test_other_actor_including_admin_cannot_read_original_receipt(self):
        with sync_boundary():
            other = get_user_model().objects.create_superuser(username="other-financial-reader",
                email="other-reader@synthetic.invalid", password="Synthetic-only")
        client, _ = self.register(other)
        for part in ("status", "summary"):
            foreign = self.read(part, client)
            missing = self.read(part, client, uuid.uuid4())
            self.assertEqual(foreign.status_code, 404)
            self.assertEqual(foreign.data, missing.data)

    def test_same_original_actor_can_recover_from_another_current_bound_device(self):
        client, registration = self.register(self.user)
        response = self.read(client=client)
        self.validate(response, wire.STATUS)
        self.assertNotEqual(registration["device_id"], self.registration["device_id"])
        self.assertEqual(response.data["device_id"], registration["device_id"])
        self.assertEqual(response.data["receipt_hash"], self.receipt.request_hash)

    def test_worker_and_roleless_are_denied_before_financial_lookup(self):
        for role in (RoleChoices.GENERAL_WORKER, None):
            self.actor_role(role)
            with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
                for part in ("status", "summary"):
                    response = self.read(part)
                    self.assertEqual(response.status_code, 403, response.data)
                lookup.assert_not_called()

    def test_all_five_finance_read_roles_have_only_the_same_original_actor_fields(self):
        baseline = None
        for role in (RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER,
                     RoleChoices.FARM_SUPERVISOR, RoleChoices.STAKE_HOLDER):
            self.actor_role(role)
            response = self.read("summary")
            self.validate(response, wire.SUMMARY)
            if baseline is None:
                baseline = response.data["summary"]
            self.assertEqual(response.data["summary"], baseline)

    def test_inactive_actor_is_denied_before_financial_lookup(self):
        with sync_boundary():
            get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
            response = self.read()
            self.assertIn(response.status_code, (401, 403))
            lookup.assert_not_called()

    def test_revoked_device_revoked_session_and_expired_session_are_denied(self):
        session_id = AccessToken(self.registration["access"])["mobile_session_id"]
        for model, key, values, restore in (
            (MobileDevice, self.registration["device_id"], {"revoked_at": timezone.now()}, {"revoked_at": None}),
            (MobileSession, session_id, {"revoked_at": timezone.now()}, {"revoked_at": None}),
            (MobileSession, session_id, {"expires_at": timezone.now() - timedelta(seconds=1)},
                {"expires_at": timezone.now() + timedelta(days=1)})):
            with sync_boundary():
                model.objects.filter(pk=key).update(**values)
            with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
                response = self.read()
                self.assertEqual(response.status_code, 403, response.data)
                lookup.assert_not_called()
            with sync_boundary():
                model.objects.filter(pk=key).update(**restore)

    def test_current_role_is_rechecked_after_expensive_summary_proof(self):
        self.actor_role(RoleChoices.FARM_MANAGER)
        original = summaries._summary

        def remove_role(receipt):
            result = original(receipt)
            self.user.roles.clear()
            return result

        with patch.object(summaries, "_summary", side_effect=remove_role):
            response = self.read("summary")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertNotIn("summary", response.data)

    def test_current_session_is_rechecked_after_summary_proof(self):
        original = summaries._summary
        session_id = AccessToken(self.registration["access"])["mobile_session_id"]

        def revoke(receipt):
            result = original(receipt)
            MobileSession.objects.filter(pk=session_id).update(revoked_at=timezone.now())
            return result

        with patch.object(summaries, "_summary", side_effect=revoke):
            response = self.read("summary")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertNotIn("summary", response.data)

    def test_no_query_override_can_expand_actor_deployment_fields_or_pagination(self):
        with patch("apps.mobile_sync.financial_views.own_payment_receipt") as lookup:
            for data in ({"actor_id": str(uuid.uuid4())}, {"deployment_id": str(uuid.uuid4())},
                         {"fields": "funding_source"}, {"limit": "999999"}):
                response = self.client.get(self.url(), data, **HEADER)
                self.assertEqual(response.status_code, 400)
            lookup.assert_not_called()

    def test_status_stays_accepted_when_summary_funding_proof_exceeds_budget(self):
        before = self.snapshot()
        with patch.object(summaries, "MAX_VERIFIED_FUNDING_ROWS", 3):
            summary = self.read("summary")
            self.assertEqual(summary.status_code, 409, summary.data)
            self.assertEqual(summary.data["code"], "payment_summary_limit")
            status = self.read()
            self.validate(status, wire.STATUS)
        self.assertEqual(self.snapshot(), before)

    def test_status_stays_accepted_when_summary_output_exceeds_budget(self):
        with patch.object(summaries, "MAX_SUMMARY_BYTES", 1):
            response = self.read("summary")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.data["code"], "payment_summary_limit")
            self.validate(self.read(), wire.STATUS)

    def test_damaged_source_graph_requires_review_without_rejecting_intact_acceptance(self):
        # Explicit privileged corruption ONLY in the owned scratch database.
        line = JournalLine.objects.filter(account__code="2000", debit__gt=0).first()
        corrupt_inventory(JournalLine, line.pk, debit=Decimal("1.00"))
        before = self.snapshot()
        summary = self.read("summary")
        self.assertEqual(summary.status_code, 503, summary.data)
        self.assertEqual(summary.data["code"], "payment_summary_review_required")
        self.validate(self.read(), wire.STATUS)
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_root_receipt_never_returns_acceptance_or_sensitive_error_details(self):
        result = deepcopy(self.receipt.result)
        result["capture"]["notes"] = "CORRUPT-PRIVATE-CONTENT"
        corrupt_inventory(FinancialCommandReceipt, self.receipt.pk, result=json.dumps(result))
        before = self.snapshot()
        for part in ("status", "summary"):
            response = self.read(part)
            self.assertEqual(response.status_code, 503, response.data)
            self.assertEqual(response.data["code"], "payment_receipt_review_required")
            self.assertNotIn("CORRUPT-PRIVATE", canonical(response.data))
            self.assertNotIn("outcome", response.data)
        self.assertEqual(self.snapshot(), before)

    def test_retained_reads_work_when_new_invoice_capture_is_disabled(self):
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            self.validate(self.read(), wire.STATUS)
            self.validate(self.read("summary"), wire.SUMMARY)

    def test_private_legacy_and_other_command_ids_are_not_adopted_as_supplier_payments(self):
        other = FinancialCommandReceipt.objects.exclude(command=self.receipt.command).first()
        for operation_id in (uuid.uuid4(), other.pk):
            response = self.read(operation_id=operation_id)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data["code"], "payment_receipt_not_found")

    def test_mutating_methods_cannot_create_payments_or_sync_records(self):
        before = self.snapshot()
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)(self.url(), {"amount": "999"}, format="json", **HEADER)
            self.assertEqual(response.status_code, 405, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_status_proof_has_an_independent_bounded_budget_and_never_truncates(self):
        with patch.object(financial_reads, "MAX_RECEIPT_PROOF_BYTES", 1):
            response = self.read()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.data["code"], "payment_receipt_review_required")
            self.assertNotIn("outcome", response.data)

    def test_poultry_operation_recovery_cannot_resolve_financial_receipt_ids(self):
        response = self.client.get(BASE + f"operations/{self.receipt.pk}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "operation_not_found")
        self.assertFalse(SyncOperationReceipt.objects.filter(operation_id=self.receipt.pk).exists())

    def test_read_flag_does_not_grant_generic_finance_rest_or_command_mutations(self):
        before = self.snapshot()
        response = self.client.get("/api/v1/finance/dashboard")
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(response.data["code"], "command_unavailable")
        response = self.client.post(BASE + "push", {"protocol_version": 1,
            "device_id": self.registration["device_id"], "operations": [{
                "operation_id": str(uuid.uuid4()), "entity_uuid": str(uuid.uuid4()),
                "entity_type": "inventory.supplier_payment", "action": "record",
                "payload_version": 1, "base_version": None, "captured_at": "2026-10-14T07:00:00Z",
                "depends_on": [], "payload": {"amount": "999.00"}}]}, format="json", **HEADER)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_openapi_has_explicit_separate_read_header_and_positive_response_fields(self):
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        from django.urls import include, path
        from apps.mobile_sync.urls import urlpatterns
        # Scope this contract check to the new routes. Whole-project generation
        # currently crashes in the inherited OperationalBatchSerializer facade
        # (no .fields); do not silently patch unrelated public poultry behavior.
        financial_patterns = [pattern for pattern in urlpatterns if str(pattern.pattern).startswith("finance/")]
        specification = SchemaGenerator(patterns=[path("api/v1/mobile-sync/", include(financial_patterns))]).get_schema(request=None, public=True)
        validate_schema(specification)
        for path in (FINANCE + "capabilities", FINANCE + "supplier-payments/{operation_id}/status",
                     FINANCE + "supplier-payments/{operation_id}/summary"):
            operations = specification["paths"][path]
            self.assertEqual(set(operations), {"get"})
            header = next(item for item in operations["get"]["parameters"] if item["name"] == "X-Mobile-Finance-Version")
            self.assertTrue(header["required"])
            self.assertEqual(header["schema"]["enum"], [1])
            response = operations["get"]["responses"]["200"]["content"]["application/json"]["schema"]
            self.assertFalse(response["additionalProperties"])
            self.assertEqual(response["properties"]["offline_cache_seconds"], {"enum": [0]})
