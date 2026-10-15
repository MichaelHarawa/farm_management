"""External UUID capture/linkage candidate, newly owned PostgreSQL only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from threading import Event, Thread
import time
import json
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import FinancialCommandReceipt, FundingAllocation, PeriodStatus
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.tests import test_inventory_purchase_proof as proof
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import financial_references as references
from apps.mobile_sync.commands import financial as bridge, financial_uuid as adapter, financial_uuid_schema as wire
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import SyncEntity, SyncOperationReceipt
from apps.mobile_sync.projections import json_value, canonical
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_sync import BASE

SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCES": True, "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS": True}


class UUIDFixture(BridgeFixture):
    def setUp(self):
        super().setUp()
        references.prepare_funding_references([str(self.source.pk)], self.user, self.session, self.token)
        self.selection = references.funding_reference_catalog(self.user, self.session, self.token)["rows"][0]

    def command(self, **changes):
        command = super().command(**{"financial_command_version": 2, **changes})
        for invoice in command["payload"]["invoices"]:
            for line in invoice["lines"]:
                for row in line["funding_allocations"]:
                    row.update(funding_source=self.selection["reference_id"], funding_version=self.selection["reference_version"])
        return command

    def execute(self, command):
        return adapter.execute_uuid_command(command, self.user, self.session, self.token)

    def recover(self, command):
        return adapter.recover_uuid_command(command["operation_id"], self.user, self.session, self.token)

    def envelope(self, operations):
        return {"financial_protocol_version": 1, "deployment_id": str(self.stream.deployment_id),
            "device_id": str(self.session.device_id), "operations": operations}

    def push(self, operations):
        return adapter.execute_uuid_envelope(self.envelope(operations), self.user, self.session, self.token)

    def inner_receipt(self, command):
        return SyncOperationReceipt.objects.get(stream=self.stream, actor=self.user,
            operation_id=adapter.inner_id(self.stream, self.user, self.session.device, command["operation_id"]))

    def root_id(self, command):
        return bridge.submission_id(self.stream, self.user, self.session.device,
            adapter.inner_id(self.stream, self.user, self.session.device, command["operation_id"]))

    def validate(self, result):
        Draft7Validator(wire.RESULT, format_checker=FormatChecker()).validate(result)
        self.assertEqual(result["financial_command_version"], 2)

    def refused(self, action, code, *, unchanged=True):
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            action()
        self.assertEqual(error.exception.detail["code"], code)
        if unchanged:
            self.assertEqual(self.snapshot(), before)
        return error.exception

    def partial(self, command, amount="25.00"):
        command = deepcopy(command)
        command["payload"]["invoices"] = command["payload"]["invoices"][:1]
        invoice = command["payload"]["invoices"][0]
        invoice["lines"] = invoice["lines"][:1]
        invoice["total_payment_amount"] = command["payload"]["total_payment_amount"] = amount
        invoice["lines"][0]["amount"] = invoice["lines"][0]["funding_allocations"][0]["amount"] = amount
        return command


@override_settings(**SETTINGS)
class FinancialUUIDCommandTests(UUIDFixture, TestCase):
    def test_atomic_external_uuid_capture_resolution_inner_root_and_twenty_replays(self):
        command, before = self.command(), self.snapshot()
        accepted = self.execute(command)
        self.validate(accepted)
        self.assertEqual(accepted["outcome"], "accepted")
        receipt, inner = self.receipt(command), self.inner_receipt(command)
        self.assertEqual(receipt.command, command)
        self.assertEqual(receipt.request_hash, adapter.command_hash(self.stream, self.user, self.session.device, command))
        self.assertNotEqual(receipt.request_hash, inner.request_hash)
        self.assertNotEqual(receipt.operation_id, inner.operation_id)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)
        self.assertEqual(receipt.result["resolution"]["funding"][0]["source_pk"], str(self.source.pk))
        self.assertEqual(accepted["financial_evidence"]["submission_id"], str(self.root_id(command)))
        after = self.snapshot()
        for _ in range(20):
            self.assertEqual(self.execute(command), {**accepted, "outcome": "replayed"})
        self.assertEqual(self.recover(command), accepted)
        self.assertEqual(self.snapshot(), after)
        self.assertEqual(len(after["finance"]["financialcommandreceipt"]) - len(before["finance"]["financialcommandreceipt"]), 7)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))

    def test_recovery_never_resolves_current_source_after_disable_or_identity_change(self):
        command = self.command()
        accepted = self.execute(command)
        with sync_boundary():
            self.source.is_active = False
            self.source.save(update_fields=["is_active", "updated_at"])
        corrupt_inventory(SyncEntity, SyncEntity.objects.get(entity_type=references.ENTITY_TYPE).pk, deleted=True)
        before = self.snapshot()
        with patch.object(adapter, "_resolve", side_effect=AssertionError("Never resolve an accepted UUID again")), \
                patch.object(bridge, "execute_financial", side_effect=AssertionError("Never post again")):
            self.assertEqual(self.recover(command), accepted)
            self.assertEqual(self.execute(command), {**accepted, "outcome": "replayed"})
        self.assertEqual(self.snapshot(), before)

    def test_read_role_downgrade_and_capture_flags_off_can_recover_original_acceptance(self):
        command = self.command()
        accepted = self.execute(command)
        self.role(RoleChoices.STAKE_HOLDER)
        with override_settings(MOBILE_SYNC_FINANCIAL_UUID_COMMANDS=False, MOBILE_SYNC_FINANCIAL_COMMANDS=False,
                MOBILE_SYNC_FINANCIAL_REFERENCES=False, FINANCE_INVENTORY_INVOICES=False):
            self.assertEqual(self.recover(command), accepted)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)

    def test_changed_uuid_version_amount_date_capture_notes_dependencies_is_not_replay(self):
        command = self.command()
        self.execute(command)
        before = self.snapshot()
        changes = []
        for key, value in (("funding_source", str(uuid.uuid4())), ("funding_version", "0" * 64), ("amount", "51.00")):
            changed = deepcopy(command)
            changed["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0][key] = value
            changes.append(changed)
        for field, value in (("payment_date", "2026-01-13"), ("notes", "Changed private note")):
            changed = deepcopy(command)
            changed["payload"][field] = value
            changes.append(changed)
        changes += [{**command, "captured_at": json_value(timezone.now() - timedelta(seconds=1))},
            {**command, "depends_on": [str(uuid.uuid4())]}]
        for changed in changes:
            result = self.execute(changed)
            self.assertEqual((result["outcome"], result["code"]), ("conflict", "idempotency_mismatch"))
        self.assertEqual(self.snapshot(), before)

    def test_crash_on_external_receipt_rolls_back_inner_payment_and_all_receipts(self):
        command, before = self.command(), self.snapshot()
        original = SyncOperationReceipt.objects.create
        def crash(**kwargs):
            if kwargs["command"].get("financial_command_version") == 2:
                raise RuntimeError("Synthetic outer receipt loss")
            return original(**kwargs)
        with patch.object(SyncOperationReceipt.objects, "create", side_effect=crash), self.assertRaises(RuntimeError):
            self.execute(command)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.execute(command)["outcome"], "accepted")

    def test_corrupt_frozen_binding_or_inner_command_is_review_not_repost(self):
        command = self.command()
        self.execute(command)
        receipt = self.receipt(command)
        for field, value in (("source_pk", "9223372036854775807"), ("reference_version", "0" * 64), ("identity", "0" * 64)):
            changed = deepcopy(receipt.result)
            changed["resolution"]["funding"][0][field] = value
            corrupt_inventory(SyncOperationReceipt, receipt.pk, result=json.dumps(changed))
            self.refused(lambda: self.recover(command), "financial_receipt_review_required")
            corrupt_inventory(SyncOperationReceipt, receipt.pk, result=json.dumps(receipt.result))
        inner = self.inner_receipt(command)
        changed = deepcopy(inner.command)
        changed["payload"]["external_reference"] = "CHANGED-INNER-REFERENCE"
        corrupt_inventory(SyncOperationReceipt, inner.pk, command=json.dumps(changed))
        self.refused(lambda: self.recover(command), "financial_receipt_review_required")

    def test_lost_inner_receipt_or_root_never_recreates_accepted_money(self):
        command = self.command()
        self.execute(command)
        root = FinancialCommandReceipt.objects.get(pk=self.root_id(command))
        proof.erase_receipt(root)
        self.refused(lambda: self.recover(command), "financial_receipt_review_required")
        self.refused(lambda: self.execute(command), "financial_receipt_review_required")

    def test_sealed_invalid_binding_is_independently_detected(self):
        command = self.command()
        self.execute(command)
        receipt = self.receipt(command)
        changed = deepcopy(receipt.result)
        changed["resolution"]["funding"][0]["source_pk"] = "9223372036854775807"
        changed["anchor"] = adapter._seal(self.stream, self.user, self.session.device, command,
            receipt.request_hash, receipt.outcome, changed["public"], changed["resolution"])
        corrupt_inventory(SyncOperationReceipt, receipt.pk, result=json.dumps(changed))
        self.refused(lambda: self.recover(command), "financial_receipt_review_required")

    def test_independent_inner_receipt_or_domain_root_cannot_be_adopted(self):
        command = self.command()
        with sync_boundary():
            resolution = adapter._resolve(command, self.stream, self.user, self.session, self.token)
            private = adapter._translate(command, resolution, self.stream, self.user, self.session)
            bridge.execute_financial(private, self.user, self.session, self.token)
        self.refused(lambda: self.execute(command), "financial_receipt_review_required")
        self.assertFalse(SyncOperationReceipt.objects.filter(operation_id=command["operation_id"]).exists())

    def test_terminal_period_failure_retains_external_uuid_and_reopen_does_not_retry(self):
        command = self.command()
        with sync_boundary():
            self.period.status = PeriodStatus.CLOSED
            self.period.save(update_fields=["status"])
        before = proof.snapshot()
        result = self.execute(command)
        self.assertEqual(result["outcome"], "period_locked")
        self.assertEqual(self.receipt(command).command, command)
        self.assertEqual(proof.snapshot(), before)
        with sync_boundary():
            self.period.status = PeriodStatus.OPEN
            self.period.save(update_fields=["status"])
        self.assertEqual(self.execute(command), result)
        self.assertEqual(self.recover(command), result)
        self.assertFalse(FundingAllocation.objects.exists())

    def test_new_uuid_supersedes_terminal_capture_only_one_correction_accepts(self):
        original = self.command()
        original["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0]["funding_version"] = "0" * 64
        self.assertEqual(self.execute(original)["code"], "funding_reference_changed")
        corrected = self.command(supersedes_operation_id=original["operation_id"])
        self.assertEqual(self.execute(corrected)["outcome"], "accepted")
        self.assertEqual(self.execute(self.command(supersedes_operation_id=original["operation_id"]))["code"], "supersession_already_accepted")
        self.assertEqual(self.receipt(original).command, original)

    def test_unauthorized_or_missing_original_invoice_has_identical_protected_rejection(self):
        first = self.command()
        with sync_boundary():
            outsider = get_user_model().objects.create_user(username="synthetic-other-invoice-owner",
                email="synthetic-other-invoice-owner@example.invalid", is_superuser=True)
        corrupt_inventory(FinancialCommandReceipt, first["payload"]["invoices"][0]["invoice_group_id"], actor_id=outsider.pk)
        result = self.execute(first)
        self.assertEqual(result["code"], "invoice_reference_unavailable")
        second = self.command()
        second["payload"]["invoices"][0]["invoice_group_id"] = str(uuid.uuid4())
        missing = self.execute(second)
        self.assertEqual((result["message"], result["code"], result["field_errors"]),
            (missing["message"], missing["code"], missing["field_errors"]))
        self.assertFalse(FundingAllocation.objects.exists())

    def test_current_owner_source_denial_or_stale_source_preserves_external_capture(self):
        for mode in ("role", "inactive", "version"):
            command = self.command()
            with self.subTest(mode=mode):
                if mode == "role":
                    self.role(RoleChoices.FARM_MANAGER)
                elif mode == "inactive":
                    self.role(RoleChoices.DIRECTOR)
                    with sync_boundary():
                        self.source.is_active = False
                        self.source.save(update_fields=["is_active", "updated_at"])
                else:
                    with sync_boundary():
                        self.source.is_active = True
                        self.source.save(update_fields=["is_active", "updated_at"])
                    command["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0]["funding_version"] = "0" * 64
                result = self.execute(command)
                self.assertEqual(result["code"], "funding_reference_changed" if mode == "version" else "funding_reference_unavailable")
                self.assertEqual(self.receipt(command).command, command)
        self.assertFalse(FundingAllocation.objects.exists())

    def test_read_only_action_denial_is_terminal_without_funding_lookup(self):
        command = self.command()
        self.role(RoleChoices.STAKE_HOLDER)
        with patch.object(adapter, "_resolve", side_effect=AssertionError("No restricted lookup")):
            result = self.execute(command)
            self.assertEqual(result["outcome"], "permission_denied")
            self.assertEqual(self.recover(command), result)
        self.assertIsNone(self.receipt(command).result["resolution"])

    def test_late_owner_role_loss_rolls_back_money_and_both_command_receipts(self):
        command, before = self.command(), self.snapshot()
        original = bridge.execute_financial
        def downgrade(*args):
            result = original(*args)
            self.role(RoleChoices.FARM_MANAGER)
            return result
        with patch.object(bridge, "execute_financial", side_effect=downgrade):
            self.refused(lambda: self.execute(command), "financial_reference_scope_changed")
        self.assertEqual(self.snapshot(), before)

    def test_late_revocation_after_inner_post_rolls_back_every_effect(self):
        command = self.command()
        original = bridge.execute_financial
        def revoke(*args):
            result = original(*args)
            self.session.revoked_at = timezone.now()
            self.session.save(update_fields=["revoked_at"])
            return result
        with patch.object(bridge, "execute_financial", side_effect=revoke):
            self.refused(lambda: self.execute(command), "device_revoked")

    def test_recovery_is_original_device_only_and_worker_cannot_see_result(self):
        command = self.command()
        self.execute(command)
        _, _, other_session, other_token = self.register(self.user)
        self.refused(lambda: adapter.recover_uuid_command(command["operation_id"], self.user, other_session, other_token), "foreign_device")
        self.role(RoleChoices.GENERAL_WORKER)
        self.refused(lambda: self.recover(command), "permission_denied")

    def test_gates_off_refuse_before_queries_and_disabled_prerequisites_do_not_consume_ids(self):
        with override_settings(MOBILE_SYNC_FINANCIAL_UUID_COMMANDS=False), self.assertNumQueries(0):
            with self.assertRaises(SyncError):
                self.execute(self.command())
        for flag in ("MOBILE_SYNC_FINANCIAL_COMMANDS", "MOBILE_SYNC_FINANCIAL_REFERENCES", "FINANCE_INVENTORY_INVOICES"):
            command = self.command()
            before = self.snapshot()
            with override_settings(**{flag: False}):
                self.assertEqual(self.execute(command)["outcome"], "retry_later")
            self.assertEqual(self.snapshot(), before)

    def test_only_strict_uuid_wire_no_raw_pk_numeric_whitespace_or_extra_fields(self):
        for field, value in (("funding_source", str(self.source.pk)), ("funding_source", self.source.pk),
                ("amount", 50.0), ("amount", "50.00\n"), ("funding_version", "a" * 64 + "\n"), ("owner_id", "PRIVATE")):
            command = self.command()
            command["payload"]["invoices"][0]["lines"][0]["funding_allocations"][0][field] = value
            self.refused(lambda: self.execute(command), "malformed_request")
        self.refused(lambda: self.execute(self.command(financial_command_version=1)), "malformed_request")
        for suffix in ("\n", "\r\n", " "):
            self.refused(lambda: self.execute(self.command(captured_at="2026-10-14T12:00:00Z" + suffix)), "malformed_request")

    def test_legacy_private_receipt_or_derived_id_cannot_become_external_operation(self):
        old = BridgeFixture.command(self)
        bridge.execute_financial(old, self.user, self.session, self.token)
        new = self.command(operation_id=old["operation_id"])
        self.refused(lambda: self.execute(new), "unsupported_protocol")

    def test_future_capture_preserves_terminal_evidence_without_resolving_money(self):
        command = self.command(captured_at=json_value(timezone.now() + timedelta(days=1)))
        with patch.object(adapter, "_resolve", side_effect=AssertionError("No funding lookup")):
            result = self.execute(command)
            self.assertEqual(result["code"], "future_capture")
            self.assertEqual(self.recover(command), result)

    def test_positive_result_has_no_capture_bindings_money_source_or_owner_data(self):
        command = self.command()
        result = self.execute(command)
        self.validate(result)
        self.assertNotIn("resolution", result)
        self.assertNotIn("source_pk", canonical(result))
        self.assertNotIn("funding_", canonical(result))
        self.assertNotIn("150.00", canonical(result))
        self.assertEqual(self.client.post(BASE + "finance/push", self.envelope([command]), format="json").status_code, 404)
        self.assertFalse(self.client.get(BASE + "capabilities").data["commands"]["finance"]["available"])

    def test_batch_duplicate_ids_cycles_and_bad_later_shape_prevent_any_effect(self):
        first = self.command()
        second = self.command(depends_on=[first["operation_id"]])
        self.refused(lambda: self.push([first, first]), "duplicate_operation")
        self.refused(lambda: self.push([{**first, "depends_on": [second["operation_id"]]}, second]), "dependency_cycle")
        self.refused(lambda: self.push([{**first, "depends_on": [first["operation_id"]]}]), "dependency_cycle")
        self.refused(lambda: self.push([first, {**second, "unexpected": "field"}]), "malformed_request")

    def test_envelope_foreign_device_deployment_or_actor_override_has_no_effect(self):
        envelope = self.envelope([self.command()])
        for field in ("deployment_id", "device_id"):
            changed = {**envelope, field: str(uuid.uuid4())}
            self.refused(lambda: adapter.execute_uuid_envelope(changed, self.user, self.session, self.token), "foreign_environment")
        self.refused(lambda: adapter.execute_uuid_envelope({**envelope, "actor_id": str(self.user.pk)}, self.user, self.session, self.token), "malformed_request")

    def test_forward_dependency_is_ordered_and_individual_commands_commit_atomically(self):
        parent = self.partial(self.command())
        child = self.partial(self.command(depends_on=[parent["operation_id"]]))
        child["payload"]["external_reference"] = "SYNTHETIC-SECOND-OBSERVED-PAYMENT"
        response = self.push([child, parent])
        Draft7Validator(wire.RESPONSE, format_checker=FormatChecker()).validate(response)
        self.assertEqual([row["operation_id"] for row in response["results"]], [parent["operation_id"], child["operation_id"]])
        self.assertEqual([row["outcome"] for row in response["results"]], ["accepted", "accepted"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("50.00"))
        self.assertEqual(SyncOperationReceipt.objects.count(), 4)

    def test_missing_or_rejected_parent_does_not_consume_child_operation(self):
        child = self.command(depends_on=[str(uuid.uuid4())])
        before = self.snapshot()
        self.assertEqual(self.execute(child)["outcome"], "dependency_blocked")
        self.assertEqual(self.snapshot(), before)
        rejected = self.command()
        rejected["payload"]["total_payment_amount"] = "149.00"
        self.assertEqual(self.execute(rejected)["outcome"], "validation_failed")
        child["depends_on"] = [rejected["operation_id"]]
        before = self.snapshot()
        self.assertEqual(self.execute(child)["outcome"], "dependency_blocked")
        self.assertEqual(self.snapshot(), before)

    def test_budget_defers_unstarted_work_without_creating_receipts(self):
        command = self.command()
        before = self.snapshot()
        with patch.object(adapter, "REQUEST_SECONDS", -1):
            response = self.push([command])
        self.assertEqual(response["results"][0]["code"], "request_budget_exceeded")
        self.assertEqual(response["results"][0]["outcome"], "retry_later")
        self.assertEqual(self.snapshot(), before)

    def test_envelope_max_operations_and_byte_budget_are_prevalidated(self):
        self.refused(lambda: self.push([self.command() for _ in range(21)]), "malformed_request")
        with patch.object(adapter, "MAX_BYTES", 1):
            self.refused(lambda: self.push([self.command()]), "request_too_large")

    def test_resolution_requires_own_outer_stream_boundary(self):
        self.refused(lambda: adapter._resolve(self.command(), self.stream, self.user, self.session, self.token), "financial_boundary_required")

    def test_later_business_rejection_does_not_undo_earlier_envelope_acceptance(self):
        first, second = self.partial(self.command()), self.partial(self.command())
        second["payload"]["external_reference"] = "SYNTHETIC-SECOND-INVALID-INVOICE"
        second["payload"]["invoices"][0]["invoice_version"] = "0" * 64
        response = self.push([first, second])
        self.assertEqual([row["outcome"] for row in response["results"]], ["accepted", "validation_failed"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("25.00"))
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("175.00"))
        self.assertEqual(self.recover(first), response["results"][0])

    def test_missing_inner_receipt_is_review_even_when_original_financial_root_survives(self):
        command = self.command()
        self.execute(command)
        inner = self.inner_receipt(command)
        if not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_"):
            raise AssertionError("Deletion only on newly owned scratch database")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM mobile_sync_syncoperationreceipt WHERE id=%s", [inner.pk])
        self.assertTrue(FinancialCommandReceipt.objects.filter(pk=self.root_id(command)).exists())
        self.refused(lambda: self.recover(command), "financial_receipt_review_required")
        self.refused(lambda: self.execute(command), "financial_receipt_review_required")

    def test_foreign_actor_cannot_recover_owned_operation_and_late_recovery_revocation_refuses(self):
        command = self.command()
        self.execute(command)
        with sync_boundary():
            other = get_user_model().objects.create_user(username="synthetic-uuid-reader",
                email="synthetic-uuid-reader@example.invalid", is_superuser=True)
        _, _, session, token = self.register(other)
        self.refused(lambda: adapter.recover_uuid_command(command["operation_id"], other, session, token), "operation_not_found")
        original = adapter._retained
        def revoke(*args):
            result = original(*args)
            self.session.revoked_at = timezone.now()
            self.session.save(update_fields=["revoked_at"])
            return result
        with patch.object(adapter, "_retained", side_effect=revoke):
            self.refused(lambda: self.recover(command), "device_revoked")

    def test_private_v1_parent_is_not_adopted_as_uuid_dependency(self):
        old = BridgeFixture.command(self)
        # Smaller accepted private payment leaves enough cash for the child.
        old = self.partial(old)
        bridge.execute_financial(old, self.user, self.session, self.token)
        child = self.partial(self.command(depends_on=[old["operation_id"]]))
        child["payload"]["external_reference"] = "SYNTHETIC-UNSUPPORTED-PARENT-PROFILE"
        result = self.execute(child)
        self.assertEqual(result["code"], "dependency_profile_mismatch")
        self.assertEqual(self.recover(child), result)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("25.00"))

    def test_archived_accepted_command_does_not_reapply_new_capture_date_rules(self):
        command = self.command()
        accepted = self.execute(command)
        with patch("apps.finance.services.inventory_invoice_payments.timezone.localdate", return_value=date(2025, 1, 1)):
            self.assertEqual(self.recover(command), accepted)
            self.assertEqual(self.execute(command), {**accepted, "outcome": "replayed"})


@override_settings(**SETTINGS)
class FinancialUUIDConcurrencyTests(UUIDFixture, TransactionTestCase):
    def test_same_external_id_race_commits_one_payment_and_one_pair_of_receipts(self):
        command = self.command()
        self.assertCountEqual(proof.race(self, [lambda: (None, self.execute(command)["outcome"])] * 2), ["accepted", "replayed"])
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))

    def test_two_external_ids_compete_for_cash_without_overdraw(self):
        first, second = self.command(), self.command()
        second["payload"]["external_reference"] = "SYNTHETIC-OTHER-COMPETING-TRANSFER"
        self.assertCountEqual(proof.race(self, [lambda: (None, self.execute(first)["outcome"]),
            lambda: (None, self.execute(second)["outcome"])]), ["accepted", "validation_failed"])
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        self.assertEqual(SyncOperationReceipt.objects.count(), 4)

    def test_read_authority_removed_while_waiting_for_stream_prevents_uuid_resolution(self):
        command, started, pids, results = self.command(), Event(), [], []
        original = bridge._bound
        def authorized(*args):
            result = original(*args)
            if not started.is_set():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                started.set()
            return result
        def run():
            close_old_connections()
            try:
                self.execute(command)
            except SyncError as error:
                results.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(bridge, "_bound", side_effect=authorized), sync_boundary():
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
            self.assertTrue(waiting)
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            role, _ = Role.objects.get_or_create(slug=RoleChoices.GENERAL_WORKER, defaults={"name": "Synthetic worker"})
            self.user.roles.add(role)
        worker.join(25)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [403])
        self.assertFalse(FundingAllocation.objects.exists())
        self.assertFalse(SyncOperationReceipt.objects.exists())
