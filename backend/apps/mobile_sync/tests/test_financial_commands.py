"""Private device-bound payment bridge on newly owned PostgreSQL only."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
import json
from threading import Event, Thread
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (AccountingPeriod, FinancialCommandReceipt, FundingAllocation,
    FundingClassification, JournalEntry, JournalLine, PeriodStatus)
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.services.inventory_referenced_payments import record_referenced_inventory_payment
from apps.finance.tests import test_inventory_referenced_payments as references
from apps.finance.tests import test_inventory_purchase_proof as proof
from apps.finance.tests import test_expenditure_drafts as drafts
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync.commands import financial as bridge, financial_schema as wire
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import MobileSession, MobileDevice, SyncChange, SyncEntity, SyncOperationReceipt, SyncStreamState
from apps.mobile_sync.projections import json_value, canonical, checksum
from apps.mobile_sync.writers import sync_boundary
from .test_sync import TEST_SETTINGS, BASE


SETTINGS = {**TEST_SETTINGS, "MOBILE_SYNC_FINANCIAL_COMMANDS": True,
    "MOBILE_SYNC_FINANCIAL_READS": True, "FINANCE_INVENTORY_INVOICES": True}


class BridgeFixture:
    def setUp(self):
        with override_settings(MOBILE_SYNC_CAPTURE=False):
            references.setup(self)
        self.stream, _ = SyncStreamState.objects.get_or_create(pk=1)
        self.stream.ready = True
        self.stream.save(update_fields=["ready"])
        self.client, self.registration, self.session, self.token = self.register(self.user)

    def register(self, actor):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(actor).access_token}")
        response = client.post(BASE + "devices", {"installation_id": str(uuid.uuid4()), "app_version": "private-finance-bridge-test",
            "platform": "android", "protocol_version": 1, "device_label": "Synthetic bridge device"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        token = AccessToken(response.data["access"])
        session = MobileSession.objects.get(pk=token["mobile_session_id"])
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client, response.data, session, token

    def command(self, **changes):
        capture = references.request(self)
        capture.pop("submission_id")
        capture.pop("user")
        capture["payment_date"] = capture["payment_date"].isoformat()
        capture["total_payment_amount"] = format(Decimal(capture["total_payment_amount"]), ".2f")
        for invoice in capture["invoices"]:
            invoice["total_payment_amount"] = format(Decimal(invoice["total_payment_amount"]), ".2f")
            for line in invoice["lines"]:
                line["amount"] = format(Decimal(line["amount"]), ".2f")
                for row in line["funding_allocations"]:
                    row["funding_source"] = str(row["funding_source"])
                    row["amount"] = format(Decimal(row["amount"]), ".2f")
        return {"financial_command_version": 1, "command": wire.COMMAND, "operation_id": str(uuid.uuid4()),
            "captured_at": json_value(timezone.now()), "depends_on": [], "payload": capture, **changes}

    def execute(self, command):
        return bridge.execute_financial(command, self.user, self.session, self.token)

    def recover(self, command):
        return bridge.recover_financial(command["operation_id"], self.user, self.session, self.token)

    def snapshot(self):
        return {"finance": proof.snapshot(), "sync": {model._meta.model_name: list(model.objects.order_by("pk").values())
            for model in (SyncStreamState, SyncEntity, SyncChange, SyncOperationReceipt)}}

    def receipt(self, command):
        return SyncOperationReceipt.objects.get(stream=self.stream, actor=self.user, operation_id=command["operation_id"])

    def root_id(self, command):
        return bridge.submission_id(self.stream, self.user, self.session.device, command["operation_id"])

    def validate(self, result):
        Draft7Validator(wire.RESULT, format_checker=FormatChecker()).validate(result)
        self.assertLess(len(canonical(result).encode("utf-8")), 4096)

    def role(self, role):
        with sync_boundary():
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            self.user.roles.clear()
            if role:
                selected, _ = Role.objects.get_or_create(slug=role, defaults={"name": role})
                self.user.roles.add(selected)


@override_settings(**SETTINGS)
class FinancialCommandBridgeTests(BridgeFixture, TestCase):
    def test_post_and_twenty_unknown_response_replays_have_one_exact_effect(self):
        command = self.command()
        before = self.snapshot()
        accepted = self.execute(command)
        self.validate(accepted)
        self.assertEqual(accepted["outcome"], "accepted")
        original = self.snapshot()
        for _ in range(20):
            replay = self.execute(command)
            self.assertEqual(replay, {**accepted, "outcome": "replayed"})
        self.assertEqual(self.recover(command), accepted)
        self.assertEqual(self.snapshot(), original)
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)
        self.assertEqual(len(original["finance"]["financialcommandreceipt"]) - len(before["finance"]["financialcommandreceipt"]), 7)
        self.assertEqual(JournalEntry.objects.count() - len(before["finance"]["journalentry"]), 4)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))

    def test_distinct_command_and_financial_hashes_ids_preserve_original_capture(self):
        command = self.command()
        original = deepcopy(command)
        result = self.execute(command)
        receipt = self.receipt(command)
        self.assertEqual(receipt.command, original)
        self.assertEqual(command, original)
        self.assertEqual(receipt.request_hash, bridge.command_hash(self.stream, self.user, self.session.device, original))
        self.assertEqual(result["financial_evidence"]["submission_id"], str(self.root_id(command)))
        self.assertNotEqual(result["financial_evidence"]["submission_id"], command["operation_id"])
        self.assertNotEqual(result["financial_evidence"]["receipt_hash"], result["command_hash"])
        self.assertFalse(SyncEntity.objects.filter(entity_uuid=self.root_id(command)).exists())

    def test_changed_amount_date_reference_source_notes_or_capture_is_not_replay(self):
        command = self.command()
        self.execute(command)
        before = self.snapshot()
        variants = []
        for key, value in (("total_payment_amount", "151.00"), ("payment_date", "2026-01-13"),
                           ("external_reference", "OTHER-SYNTHETIC-TRANSFER"), ("notes", "Original changed notes")):
            changed = deepcopy(command)
            changed["payload"][key] = value
            variants.append(changed)
        changed = deepcopy(command)
        changed["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0]["funding_source"] = "9223372036854775807"
        variants.append(changed)
        variants.append({**command, "captured_at": json_value(timezone.now() - timedelta(seconds=1))})
        for variant in variants:
            result = self.execute(variant)
            self.assertEqual((result["outcome"], result["code"]), ("conflict", "idempotency_mismatch"))
            self.assertEqual(result["recovery_action"], "recover_original_operation")
        self.assertEqual(self.snapshot(), before)

    def test_crash_before_command_receipt_rolls_back_every_payment_and_retries_original(self):
        command, before = self.command(), self.snapshot()
        with patch.object(SyncOperationReceipt.objects, "create", side_effect=RuntimeError("Synthetic before-bound-receipt crash")):
            with self.assertRaises(RuntimeError):
                self.execute(command)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.execute(command)["outcome"], "accepted")

    def test_postcommit_response_loss_recovers_without_running_handler_again(self):
        command = self.command()
        accepted = self.execute(command)  # Discard transport delivery; do not undo commit.
        before = self.snapshot()
        with patch.object(bridge, "REGISTRY", {wire.COMMAND: lambda **kwargs: self.fail("No second financial effect")}):
            self.assertEqual(self.recover(command), accepted)
            self.assertEqual(self.execute(command), {**accepted, "outcome": "replayed"})
        self.assertEqual(self.snapshot(), before)

    def test_period_rejection_retains_exact_wire_evidence_and_no_payment(self):
        command = self.command()
        with sync_boundary():
            self.period.status = PeriodStatus.CLOSED
            self.period.save(update_fields=["status"])
        before = proof.snapshot()
        result = self.execute(command)
        self.assertEqual((result["outcome"], result["code"]), ("period_locked", "period_locked"))
        self.assertEqual(self.receipt(command).command, command)
        self.assertEqual(self.receipt(command).request_hash, result["command_hash"])
        self.assertEqual(proof.snapshot(), before)
        self.assertNotIn("financial_evidence", result)
        self.assertIsNone(self.receipt(command).committed_at)
        with sync_boundary():
            self.period.status = PeriodStatus.OPEN
            self.period.save(update_fields=["status"])
        self.assertEqual(self.execute(command), result)  # No silent retry on reopened period.
        self.assertFalse(FundingAllocation.objects.exists())

    def test_corrected_rejection_uses_new_id_and_only_one_accepted_supersession(self):
        original = self.command()
        original["payload"]["total_payment_amount"] = "149.00"
        self.assertEqual(self.execute(original)["outcome"], "validation_failed")
        corrected = self.command(supersedes_operation_id=original["operation_id"])
        self.assertEqual(self.execute(corrected)["outcome"], "accepted")
        another = self.command(supersedes_operation_id=original["operation_id"])
        another["payload"]["external_reference"] = "OTHER-ACTUAL-TRANSFER"
        self.assertEqual(self.execute(another)["code"], "supersession_already_accepted")
        self.assertEqual(self.receipt(original).command, original)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))

    def test_accepted_or_missing_operation_cannot_be_superseded(self):
        accepted = self.command()
        self.execute(accepted)
        for parent in (accepted["operation_id"], str(uuid.uuid4())):
            changed = self.command(supersedes_operation_id=parent)
            self.assertEqual(self.execute(changed)["code"], "invalid_supersession")
        self.assertEqual(SyncOperationReceipt.objects.filter(outcome="accepted").count(), 1)

    def test_missing_or_rejected_dependency_retains_child_without_terminal_receipt(self):
        parent = self.command()
        parent["payload"]["total_payment_amount"] = "1.00"
        child = self.command(depends_on=[parent["operation_id"]])
        for _ in range(2):
            result = self.execute(child)
            self.assertEqual(result["outcome"], "dependency_blocked")
            self.assertFalse(SyncOperationReceipt.objects.filter(operation_id=child["operation_id"]).exists())
            if not SyncOperationReceipt.objects.filter(operation_id=parent["operation_id"]).exists():
                self.execute(parent)
        self.assertFalse(FundingAllocation.objects.exists())

    def test_known_accepted_dependency_is_verified_without_extra_parent_payment(self):
        parent = self.command()
        self.execute(parent)
        child = self.command(depends_on=[parent["operation_id"]])
        child["payload"]["external_reference"] = "SYNTHETIC-CHILD-TRANSFER"
        for invoice in child["payload"]["invoices"]:
            invoice["total_payment_amount"] = "15.00"
            for line, amount in zip(invoice["lines"], ("10.00", "5.00")):
                line["amount"] = line["funding_allocations"][0]["amount"] = amount
        child["payload"]["total_payment_amount"] = "30.00"
        self.assertEqual(self.execute(child)["outcome"], "accepted")

    def test_stakeholder_denial_is_durable_but_worker_and_roleless_never_store_commands(self):
        self.role(RoleChoices.STAKE_HOLDER)
        command, before = self.command(), proof.snapshot()
        result = self.execute(command)
        self.assertEqual(result["outcome"], "permission_denied")
        self.assertEqual(self.receipt(command).command, command)
        self.assertEqual(proof.snapshot(), before)
        for role in (RoleChoices.GENERAL_WORKER, None):
            self.role(role)
            command, before = self.command(), self.snapshot()
            with self.assertRaises(SyncError) as error:
                self.execute(command)
            self.assertEqual(error.exception.status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_read_role_can_recover_original_acceptance_after_write_permission_removed(self):
        command = self.command()
        accepted = self.execute(command)
        self.role(RoleChoices.STAKE_HOLDER)
        before = self.snapshot()
        self.assertEqual(self.recover(command), accepted)
        self.assertEqual(self.execute(command)["outcome"], "replayed")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.execute(self.command())["outcome"], "permission_denied")

    def test_all_finance_write_roles_use_non_owner_sources_and_owner_gate_still_applies(self):
        with override_settings(MOBILE_SYNC_CAPTURE=False):
            non_owner = drafts.funded_source(self)
        for role in (RoleChoices.ADMIN, RoleChoices.DIRECTOR, RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR):
            with self.subTest(role=role), transaction.atomic():
                self.role(role)
                command = self.command()
                command["payload"]["payment_date"] = "2026-01-20"
                for invoice in command["payload"]["invoices"]:
                    for line in invoice["lines"]:
                        line["funding_allocations"][0]["funding_source"] = str(non_owner.pk)
                self.assertEqual(self.execute(command)["outcome"], "accepted")
                transaction.set_rollback(True)
        self.role(RoleChoices.FARM_MANAGER)
        command = self.command()
        result = self.execute(command)
        self.assertEqual(result["outcome"], "permission_denied")
        self.assertNotIn("funding_source", canonical(result))
        self.assertNotIn("financial_evidence", result)

    def test_default_off_and_capture_off_refuse_before_database_queries(self):
        command = self.command()
        for values in ({"MOBILE_SYNC_FINANCIAL_COMMANDS": False}, {"MOBILE_SYNC_CAPTURE": False}, {"MOBILE_SYNC_ENABLED": False}):
            with override_settings(**values), self.assertNumQueries(0), self.assertRaises(SyncError):
                self.execute(command)

    def test_disabled_posting_is_nonterminal_and_original_recovery_survives_flags_off(self):
        command = self.command()
        with override_settings(FINANCE_INVENTORY_INVOICES=False):
            self.assertEqual(self.execute(command)["outcome"], "retry_later")
            self.assertFalse(SyncOperationReceipt.objects.exists())
        accepted = self.execute(command)
        with override_settings(MOBILE_SYNC_FINANCIAL_COMMANDS=False, FINANCE_INVENTORY_INVOICES=False):
            self.assertEqual(self.recover(command), accepted)

    def test_foreign_device_actor_deployment_session_and_revocation_cannot_replay(self):
        command = self.command()
        self.execute(command)
        _, _, second, second_token = self.register(self.user)
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            bridge.execute_financial(command, self.user, second, second_token)
        self.assertEqual(error.exception.detail["code"], "foreign_device")
        with self.assertRaises(SyncError):
            bridge.recover_financial(command["operation_id"], self.user, second, second_token)
        for field in ("deployment_id", "mobile_device_id", "mobile_session_id", "user_id"):
            token = AccessToken(self.registration["access"])
            token[field] = str(uuid.uuid4())
            with self.assertRaises((SyncError, PermissionDenied)):
                bridge.execute_financial(command, self.user, self.session, token)
        with sync_boundary():
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        with self.assertRaises(SyncError):
            self.execute(command)
        self.assertEqual(self.snapshot(), before)

    def test_same_client_id_from_another_actor_is_not_adopted_or_replayed(self):
        command = self.command()
        self.execute(command)
        with sync_boundary():
            other = get_user_model().objects.create_superuser(username="bridge-other", email="bridge-other@synthetic.invalid", password="Synthetic-only")
        _, _, session, token = self.register(other)
        result = bridge.execute_financial(command, other, session, token)
        self.assertEqual(result["code"], "possible_duplicate")
        self.assertNotEqual(self.root_id(command), bridge.submission_id(self.stream, other, session.device, command["operation_id"]))
        self.assertEqual(SyncOperationReceipt.objects.filter(operation_id=command["operation_id"]).count(), 2)
        self.assertEqual(SyncOperationReceipt.objects.filter(outcome="accepted").count(), 1)

    def test_private_root_without_bound_command_is_never_adopted(self):
        command = self.command()
        with sync_boundary():
            record_referenced_inventory_payment(submission_id=self.root_id(command), user=self.user, **command["payload"])
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            self.execute(command)
        self.assertEqual(error.exception.detail["code"], "financial_receipt_review_required")
        self.assertEqual(self.snapshot(), before)

    def test_missing_root_or_corrupt_bound_receipt_never_reexecutes_or_repairs_payment(self):
        command = self.command()
        self.execute(command)
        root = FinancialCommandReceipt.objects.get(pk=self.root_id(command))
        proof.erase_receipt(root)
        before = self.snapshot()
        with self.assertRaises(SyncError):
            self.execute(command)
        self.assertEqual(self.snapshot(), before)
        receipt = self.receipt(command)
        corrupt_inventory(SyncOperationReceipt, receipt.pk, request_hash="0" * 64)
        before = self.snapshot()
        with self.assertRaises(SyncError):
            self.recover(command)
        self.assertEqual(self.snapshot(), before)

    def test_root_or_result_insert_failure_does_not_leave_accepted_or_terminal_placeholders(self):
        command, before = self.command(), self.snapshot()
        manager = FinancialCommandReceipt.objects
        original = manager.create
        def fail_root(**kwargs):
            if kwargs["command"] == wire.COMMAND:
                raise RuntimeError("Synthetic root write failure")
            return original(**kwargs)
        with patch.object(manager, "create", side_effect=fail_root):
            with self.assertRaises(RuntimeError):
                self.execute(command)
        self.assertEqual(self.snapshot(), before)

    def test_receipt_status_proof_failure_rolls_back_new_effects_not_false_rejection(self):
        command, before = self.command(), self.snapshot()
        with patch.object(bridge, "retained_payment_status", side_effect=SyncError("payment_receipt_review_required", "Synthetic proof failure", 503)):
            with self.assertRaises(SyncError):
                self.execute(command)
        self.assertEqual(self.snapshot(), before)

    def test_schema_rejects_float_bool_unknown_fields_wrong_classes_and_injections_before_queries(self):
        command = self.command()
        variants = [{**command, "financial_command_version": True}, {**command, "command": "finance.anything"},
                    {**command, "actor_id": str(self.user.pk)}, {**command, "depends_on": [command["operation_id"]] * 2}]
        for key, value in (("total_payment_amount", 150.0), ("paid", True), ("payment_date", "2026-02-30")):
            changed = deepcopy(command)
            changed["payload"][key] = value
            variants.append(changed)
        changed = deepcopy(command)
        changed["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0]["classification"] = "loan"
        variants.append(changed)
        for value in variants:
            with self.assertNumQueries(0), self.assertRaises(SyncError) as error:
                self.execute(value)
            self.assertEqual(error.exception.status_code, 400)
        self.assertFalse(SyncOperationReceipt.objects.exists())
        self.assertEqual(wire.FUNDING["properties"]["classification"]["enum"], list(FundingClassification.values))

    def test_future_capture_is_terminal_without_changing_original_instant(self):
        command = self.command(captured_at=json_value(timezone.now() + timedelta(hours=1)))
        result = self.execute(command)
        self.assertEqual(result["code"], "future_capture")
        self.assertEqual(self.receipt(command).command, command)
        self.assertFalse(FundingAllocation.objects.exists())

    def test_accepted_response_never_exposes_source_ids_money_owner_notes_or_raw_receipts(self):
        command = self.command()
        command["payload"]["notes"] = "PRIVATE-PHYSICAL-CASH-EVIDENCE"
        result = self.execute(command)
        self.validate(result)
        encoded = canonical(result)
        for forbidden in ("PRIVATE-PHYSICAL", "funding_source", "invoices", "capture", '"amount"', "owner", "journal", "source_pk"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(self.receipt(command).command, command)

    def test_existing_read_api_recovers_root_but_operational_receipt_profile_refuses_command(self):
        command = self.command()
        result = self.execute(command)
        response = self.client.get(BASE + f"finance/supplier-payments/{self.root_id(command)}/status", HTTP_X_MOBILE_FINANCE_VERSION="1")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["receipt_hash"], result["financial_evidence"]["receipt_hash"])
        response = self.client.get(BASE + f"operations/{command['operation_id']}")
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "unsupported_protocol")
        self.assertNotIn("financial_evidence", response.data)
        self.assertEqual(SyncChange.objects.count(), 0)

    def test_capture_flag_does_not_enable_public_upload_route_or_operational_capability(self):
        command = self.command()
        response = self.client.post(BASE + "finance/push", command, format="json")
        self.assertEqual(response.status_code, 404)
        response = self.client.get(BASE + "capabilities")
        self.assertFalse(response.data["commands"]["finance"]["available"])
        self.assertFalse(SyncOperationReceipt.objects.exists())

    def test_root_namespace_and_fingerprint_bind_deployment_actor_device_and_full_capture(self):
        command = self.command()
        other = type("Other", (), {"pk": uuid.uuid4(), "deployment_id": uuid.uuid4()})()
        root = self.root_id(command)
        baseline = bridge.command_hash(self.stream, self.user, self.session.device, command)
        for stream, actor, device in ((other, self.user, self.session.device), (self.stream, other, self.session.device),
                                     (self.stream, self.user, other)):
            self.assertNotEqual(root, bridge.submission_id(stream, actor, device, command["operation_id"]))
            self.assertNotEqual(baseline, bridge.command_hash(stream, actor, device, command))

    def test_summary_display_limit_never_prevents_acceptance_or_status_replay(self):
        command = self.command()
        with patch("apps.finance.services.inventory_payment_summary.MAX_VERIFIED_FUNDING_ROWS", 1):
            accepted = self.execute(command)
            self.assertEqual(accepted["outcome"], "accepted")
            self.assertEqual(self.recover(command), accepted)
            self.assertEqual(self.execute(command)["outcome"], "replayed")

    def test_parent_from_operational_profile_cannot_be_used_as_financial_dependency(self):
        # Explicit metadata-only unsupported-profile fixture, not proof that an
        # operational domain action actually posted. No financial effect may follow.
        parent = str(uuid.uuid4())
        with sync_boundary():
            SyncOperationReceipt.objects.create(stream=self.stream, actor=self.user, device=self.session.device,
                operation_id=parent, request_hash="0" * 64, command={"entity_type": "poultry.mortality"},
                outcome="accepted", result={})
        command = self.command(depends_on=[parent])
        self.assertEqual(self.execute(command)["code"], "dependency_profile_mismatch")
        self.assertFalse(FundingAllocation.objects.exists())

    def test_budget_failure_has_no_receipt_or_effect_and_does_not_truncate_input(self):
        command, before = self.command(), self.snapshot()
        for setting in ("MAX_COMMAND_BYTES", "MAX_FUNDING_ROWS"):
            with patch.object(bridge, setting, 1), self.assertRaises(SyncError) as error:
                self.execute(command)
            self.assertEqual(error.exception.status_code, 413)
        self.assertEqual(self.snapshot(), before)

    def test_after_effect_write_role_removal_rolls_back_before_durable_denial(self):
        command, before = self.command(), proof.snapshot()
        self.role(RoleChoices.ADMIN)
        original = bridge.REGISTRY[wire.COMMAND]
        def remove_write(**kwargs):
            result = original(**kwargs)
            self.user.roles.clear()
            self.user.roles.add(Role.objects.get_or_create(slug=RoleChoices.STAKE_HOLDER, defaults={"name": "Synthetic read-only"})[0])
            return result
        with patch.object(bridge, "REGISTRY", {wire.COMMAND: remove_write}):
            result = self.execute(command)
        self.assertEqual(result["outcome"], "permission_denied")
        self.assertEqual(proof.snapshot(), before)
        self.assertEqual(self.receipt(command).command, command)

    def test_after_effect_session_revocation_rolls_back_without_saving_restricted_command(self):
        command, before = self.command(), self.snapshot()
        original = bridge.REGISTRY[wire.COMMAND]
        def revoke(**kwargs):
            result = original(**kwargs)
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
            return result
        with patch.object(bridge, "REGISTRY", {wire.COMMAND: revoke}), self.assertRaises(SyncError):
            self.execute(command)
        self.assertEqual(self.snapshot(), before)

    def test_recovery_rechecks_session_after_proof_before_releasing_financial_result(self):
        command = self.command()
        self.execute(command)
        original = bridge._retained
        def revoke(*args):
            result = original(*args)
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
            return result
        with patch.object(bridge, "_retained", side_effect=revoke), self.assertRaises(SyncError):
            self.recover(command)

    def test_changed_domain_reference_cannot_silently_post_under_original_command_hash(self):
        command, before = self.command(), self.snapshot()
        original = bridge.REGISTRY[wire.COMMAND]
        def changed_reference(**kwargs):
            kwargs["external_reference"] = "SYNTHETIC-WRONG-DOMAIN-REFERENCE"
            return original(**kwargs)
        with patch.object(bridge, "REGISTRY", {wire.COMMAND: changed_reference}), self.assertRaises(SyncError):
            self.execute(command)
        self.assertEqual(self.snapshot(), before)

    def test_replay_after_server_clock_change_does_not_reapply_new_payment_date_policy(self):
        command = self.command()
        accepted = self.execute(command)
        with patch("apps.finance.services.inventory_invoice_payments.timezone.localdate", return_value=date(2025, 1, 1)):
            self.assertEqual(self.execute(command)["outcome"], "replayed")
            self.assertEqual(self.recover(command), accepted)

    def test_new_payment_policy_uses_existing_accounting_calendar_not_display_timezone(self):
        moment = datetime(2026, 1, 11, 22, 30, tzinfo=datetime_timezone.utc)
        command = self.command(captured_at=json_value(moment))
        with timezone.override("Africa/Blantyre"), patch("django.utils.timezone.now", return_value=moment):
            result = self.execute(command)
            self.assertEqual(timezone.get_current_timezone_name(), "Africa/Blantyre")
        self.assertEqual(result["outcome"], "validation_failed")
        self.assertEqual(self.receipt(command).command["payload"]["payment_date"], "2026-01-12")
        self.assertFalse(FundingAllocation.objects.exists())


@override_settings(**SETTINGS)
class FinancialCommandBridgeConcurrencyTests(BridgeFixture, TransactionTestCase):
    def race(self, calls):
        return proof.race(self, [lambda call=call: (None, call()["outcome"]) for call in calls])

    def test_identical_bound_commands_commit_one_payment_and_one_receipt(self):
        command = self.command()
        self.assertCountEqual(self.race([lambda: self.execute(command)] * 2), ["accepted", "replayed"])
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)
        self.assertEqual(FundingAllocation.objects.count(), 4)

    def test_distinct_references_compete_for_last_confirmed_cash_without_overdraw(self):
        first, second = self.command(), self.command()
        second["payload"]["external_reference"] = "SYNTHETIC-COMPETING-TRANSFER"
        self.assertCountEqual(self.race([lambda: self.execute(first), lambda: self.execute(second)]), ["accepted", "validation_failed"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)

    def test_duplicate_reference_competition_retains_losing_physical_evidence(self):
        first, second = self.command(), self.command()
        self.assertCountEqual(self.race([lambda: self.execute(first), lambda: self.execute(second)]), ["accepted", "conflict"])
        self.assertEqual(FundingAllocation.objects.count(), 4)
        self.assertEqual(SyncOperationReceipt.objects.filter(outcome="conflict").count(), 1)

    def test_same_id_changed_content_cannot_race_into_two_financial_effects(self):
        first = self.command()
        second = deepcopy(first)
        second["payload"]["external_reference"] = "SYNTHETIC-CHANGED-INTENT"
        self.assertCountEqual(self.race([lambda: self.execute(first), lambda: self.execute(second)]), ["accepted", "conflict"])
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)
        self.assertEqual(FundingAllocation.objects.count(), 4)

    def test_role_removed_while_waiting_for_stream_is_rechecked_before_posting(self):
        command, started, result, worker_pid = self.command(), Event(), [], []
        original = bridge._bound
        def authorized(*args):
            value = original(*args)
            if not started.is_set():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    worker_pid.append(cursor.fetchone()[0])
                started.set()  # First access check really passed before the wait.
            return value
        def run():
            close_old_connections()
            try:
                self.execute(command)
            except SyncError as error:
                result.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(bridge, "_bound", side_effect=authorized), sync_boundary():
            thread = Thread(target=run)
            thread.start()
            self.assertTrue(started.wait(10))
            # Hold stream until PostgreSQL confirms the other connection is
            # actually waiting for a lock, not merely scheduled to make a call.
            deadline, waiting = time.monotonic() + 3, False
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [worker_pid[0]])
                    row = cursor.fetchone()
                if row and row[0]:
                    waiting = True
                    break
                time.sleep(0.01)
            self.assertTrue(waiting, "The real second PostgreSQL connection must wait on stream")
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            selected, _ = Role.objects.get_or_create(slug=RoleChoices.GENERAL_WORKER, defaults={"name": "Synthetic worker"})
            self.user.roles.add(selected)
        thread.join(25)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [403])
        self.assertFalse(SyncOperationReceipt.objects.exists())
        self.assertFalse(FundingAllocation.objects.exists())
