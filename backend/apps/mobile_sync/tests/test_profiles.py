"""Old operational contracts must not inherit future financial registry entries."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.mobile_sync import schema, schema_poultry
from apps.mobile_sync.commands.registry import REGISTRY
from apps.mobile_sync.commands.service import execute, normalized
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import MobileDevice, MobileSession, SyncBootstrapPage, SyncChange, SyncEntity, SyncOperationReceipt, SyncStreamState
from apps.mobile_sync.policy import scope_revision
from apps.mobile_sync.profiles import (PROFILES, V1_FIELDS, V2_FIELDS, SUMMARY_FIELDS,
    GROWTH_FIELDS, SAMPLE_FIELDS, MORTALITY_FIELDS, operational_profile, operational_result)
from apps.mobile_sync.projections import CURRENT_PACK, POULTRY_PACK, TYPES, checksum, public_payload, wire_entity
from apps.mobile_sync.serializers import PAYLOAD_SERIALIZERS, MortalityPayloadSerializer, PoultryOperationSerializer
from apps.mobile_sync.transport import included
from apps.poultry.models import Mortality
from .test_poultry import PoultryFixture, V2
from .test_sync import BASE


FUTURE_KEY = ("finance.sale", "record", 1)
FUTURE_SPEC = REGISTRY[("poultry.mortality", "record", 1)]


class FrozenProfileTests(SimpleTestCase):
    def test_frozen_positive_fields_match_existing_documented_contracts(self):
        for kind, payload in {"poultry.batch": schema.BATCH_PAYLOAD,
                "poultry.mortality": schema.MORTALITY_PAYLOAD, "poultry.feed_usage": schema.FEED_PAYLOAD}.items():
            self.assertEqual(V1_FIELDS[kind], set(payload["properties"]))
        for kind, payload in schema_poultry.PAYLOADS.items():
            self.assertEqual(V2_FIELDS[kind], set(payload["properties"]))
        for fields, payload in [(SUMMARY_FIELDS, schema_poultry.SUMMARY),
                (GROWTH_FIELDS, schema_poultry.SUMMARY["properties"]["growth"]),
                (SAMPLE_FIELDS, schema_poultry.SAMPLE),
                (MORTALITY_FIELDS, schema_poultry.SUMMARY["properties"]["mortality"])]:
            self.assertEqual(fields, set(payload["properties"]))
        with self.assertRaises(TypeError):
            PROFILES[3] = PROFILES[2]
        with self.assertRaises(TypeError):
            V2_FIELDS["finance.sale"] = frozenset({"amount"})

    def test_nested_future_financial_fields_are_removed_without_mutating_source(self):
        payload = {"batch_id": "TEST", "target_selling_price": "9000.00", "bank_balance": "500.00",
            "operational_summary": {"feed_total_kg": "2.000", "feed_cost": "100.00",
                "growth": {"state": "target_available", "margin": "9.00", "sample": {
                    "average_weight_g": 750, "sample_size": 10, "estimated_sale_value": "7500.00"}},
                "mortality": {"dead_birds": 2, "loss_value": "300.00"}}}
        original = deepcopy(payload)
        result = public_payload("poultry.batch", payload, 2)
        self.assertEqual(result, {"batch_id": "TEST", "operational_summary": {"feed_total_kg": "2.000",
            "growth": {"state": "target_available", "sample": {"average_weight_g": 750, "sample_size": 10}},
            "mortality": {"dead_birds": 2}}})
        self.assertEqual(public_payload("poultry.batch", payload, 1), {"batch_id": "TEST"})
        self.assertEqual(payload, original)
        result["operational_summary"]["growth"]["sample"]["average_weight_g"] = 1
        self.assertEqual(payload, original)

    def test_unknown_versions_and_entities_cannot_fall_back_to_operational_access(self):
        for version in [0, 3, True, "2", None]:
            with self.subTest(version=version), self.assertRaises(SyncError):
                operational_profile(version)
        for version in [1, 2]:
            with self.assertRaises(SyncError):
                public_payload("finance.sale", {"amount": "200.00"}, version)
            self.assertFalse(included(SimpleNamespace(entity_type="finance.sale", in_current_pack=True),
                [CURRENT_PACK if version == 1 else POULTRY_PACK], None))

    def test_malformed_nested_projection_is_refused_not_replaced_with_fake_values(self):
        for summary in [None, [], {"growth": []}, {"growth": {"sample": "private"}}, {"mortality": []}]:
            with self.subTest(summary=summary), self.assertRaises(SyncError) as error:
                public_payload("poultry.batch", {"operational_summary": summary}, 2)
            self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(public_payload("poultry.batch", {"operational_summary": {
            "growth": {"state": "missing_sample", "sample": None}}}, 2)["operational_summary"]["growth"]["sample"], None)

    def test_receipt_projection_filters_types_and_metadata_without_rewriting_evidence(self):
        original = {"operation_id": "original", "outcome": "accepted", "private_cash": "10.00",
            "canonical_entities": [
                {"entity_type": "finance.sale", "entity_uuid": "secret", "revision": "1", "payload": {"amount": "9.00"}},
                {"entity_type": "poultry.batch", "entity_uuid": "batch", "revision": "1", "private_cash": "1.00",
                    "payload": {"batch_id": "TEST", "target_selling_price": "5000.00"}}],
            "entity_mappings": [
                {"entity_type": "finance.sale", "server_id": "private"},
                {"entity_type": "poultry.batch", "server_id": "1", "cash": "7.00"}]}
        before = deepcopy(original)
        public = operational_result(original, 1)
        self.assertNotIn("private_cash", public)
        self.assertEqual(public["canonical_entities"], [{"entity_type": "poultry.batch", "entity_uuid": "batch", "revision": "1", "payload": {"batch_id": "TEST"}}])
        self.assertEqual(public["entity_mappings"], [{"entity_type": "poultry.batch", "server_id": "1"}])
        self.assertEqual(original, before)

    def test_future_registry_and_serializer_entries_do_not_change_openapi(self):
        before = checksum([schema_poultry.operation_schema(), schema_poultry.capabilities_schema()])
        with patch.dict(REGISTRY, {FUTURE_KEY: FUTURE_SPEC}), patch.dict(PAYLOAD_SERIALIZERS,
                {FUTURE_KEY[:2]: MortalityPayloadSerializer}):
            self.assertEqual(checksum([schema_poultry.operation_schema(), schema_poultry.capabilities_schema()]), before)
            self.assertNotIn("finance.sale", PoultryOperationSerializer().fields["entity_type"].choices)


@override_settings(**V2)
class ProfileBoundaryTests(PoultryFixture, TestCase):
    def append_change(self, entity_type, payload, kind="upsert", transaction_id=None, index=0, count=1):
        stream = SyncStreamState.objects.get(pk=1)
        stream.sequence += 1
        row = SyncChange.objects.create(stream=stream, sequence=stream.sequence,
            transaction_id=transaction_id or uuid.uuid4(), transaction_index=index, transaction_count=count,
            entity_type=entity_type, entity_uuid=uuid.uuid4(), batch_uuid=self.batch_uuid,
            revision=1, kind=kind, payload=payload, in_current_pack=True)
        stream.save(update_fields=["sequence"])
        return row

    def future_receipt(self):
        command = self.command()
        command["entity_type"] = "finance.sale"
        session = MobileSession.objects.get(pk=AccessToken(self.registration["access"])["mobile_session_id"])
        stream = SyncStreamState.objects.get(pk=1)
        immutable = normalized(command)
        request_hash = checksum({"deployment_id": str(stream.deployment_id), "actor_id": str(self.worker.pk),
            "device_id": str(session.device_id), "operation": immutable})
        receipt = SyncOperationReceipt.objects.create(stream=stream, actor=self.worker, device=session.device,
            operation_id=command["operation_id"], request_hash=request_hash, command=immutable,
            outcome="accepted", result={"operation_id": command["operation_id"], "outcome": "accepted", "amount": "SECRET"})
        return command, receipt, session

    def test_original_scope_hashes_stay_exact_when_future_registries_expand(self):
        original_entities = sorted(TYPES.values())
        original_commands = sorted(f"{kind}.{action}" for kind, action, _ in REGISTRY)
        for user in self.users.values():
            base = {"policy": 1, "projections": 1, "roles": sorted(user.roles.values_list("slug", flat=True)),
                "active": user.is_active, "superuser": user.is_superuser,
                "entities": ["poultry.batch", "poultry.mortality", "poultry.feed_usage"], "commands": ["poultry.mortality.record"]}
            expected = {1: checksum(base), 2: checksum({**base, "projections": 2,
                "entities": original_entities, "commands": original_commands})}
            with patch.dict(TYPES, {"Sales": "finance.sale"}), patch.dict(REGISTRY, {FUTURE_KEY: FUTURE_SPEC}):
                for version in [1, 2]:
                    self.assertEqual(scope_revision(user, version), expected[version])

    def test_all_role_capabilities_exclude_future_types_and_commands(self):
        with patch.dict(TYPES, {"Sales": "finance.sale"}), patch.dict(REGISTRY, {FUTURE_KEY: FUTURE_SPEC}):
            for user in self.users.values():
                client, _ = self.register(user)
                for version in [1, 2]:
                    response = client.get(BASE + "capabilities", HTTP_X_MOBILE_POULTRY_VERSION=str(version))
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["entities"], list(operational_profile(version).entities))
                    self.assertNotIn("finance.sale.record", response.data["commands"])
                    self.assertEqual(response.data["commands"]["finance"], {"available": False, "reason": "later_phase"})

    def test_all_packs_exclude_future_finance_without_requiring_a_batch_identity(self):
        stream = SyncStreamState.objects.get(pk=1)
        SyncEntity.objects.create(stream=stream, entity_type="finance.sale", source_pk="future-sale",
            batch_pk="no-operational-batch", payload={"amount": "SECRET"}, in_current_pack=True)
        for packs in [[CURRENT_PACK], [POULTRY_PACK], [f"batch:{self.batch_uuid}"], [f"batch-v2:{self.batch_uuid}"]]:
            _, rows, _ = self.snapshot(packs=packs)
            self.assertEqual({row["entity_type"] for row in rows}, {"poultry.batch", "poultry.feed_usage"})
            self.assertNotIn("SECRET", str(rows))

    def test_bootstrap_removes_new_fields_but_preserves_valid_legacy_bytes(self):
        batch = SyncEntity.objects.get(entity_uuid=self.batch_uuid)
        legacy = deepcopy(batch.payload)
        for field in ["supplier_name", "booking_reference", "operational_summary"]:
            legacy.pop(field)
        self.assertEqual(checksum(wire_entity(batch, 1)), checksum({"entity_type": batch.entity_type,
            "entity_uuid": str(batch.entity_uuid), "revision": str(batch.revision), "payload": legacy}))
        batch.payload["amount"] = "SECRET"
        batch.payload["operational_summary"]["growth"]["unit_cost"] = "SECRET"
        batch.payload["operational_summary"]["mortality"]["loss_value"] = "SECRET"
        batch.save(update_fields=["payload"])
        for packs in [[CURRENT_PACK], [POULTRY_PACK]]:
            _, rows, _ = self.snapshot(packs=packs)
            self.assertNotIn("SECRET", str(rows))
        batch.refresh_from_db()
        self.assertEqual(batch.payload["amount"], "SECRET")

    def test_hidden_future_changes_advance_both_profiles_without_serializing_payloads(self):
        for packs in [[CURRENT_PACK], [POULTRY_PACK], [f"batch:{self.batch_uuid}"], [f"batch-v2:{self.batch_uuid}"]]:
            _, _, cursor = self.snapshot(packs=packs)
            group = uuid.uuid4()
            self.append_change("finance.sale", ["SECRET"], transaction_id=group, index=0, count=2)
            last = self.append_change("finance.sale", {"amount": "SECRET"}, kind="evict_from_pack", transaction_id=group, index=1, count=2)
            with patch("apps.mobile_sync.transport.public_payload", side_effect=AssertionError("Hidden payload serialized")):
                response = self.client.get(BASE + "changes", {"cursor": cursor})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["changes"], [])
            self.assertTrue(response.data["run_complete"])
            self.assertEqual(response.data["run_watermark"], str(last.sequence))
            self.assertEqual(response.data["fragments"], [{"transaction_id": str(group), "fragment_index": 0, "fragment_final": True}])
            self.assertNotIn("SECRET", str(response.data))
            continuation = self.client.get(BASE + "changes", {"cursor": response.data["next_cursor"]})
            self.assertTrue(continuation.data["run_complete"])

    @override_settings(MOBILE_SYNC_SCAN_ROWS=1)
    def test_future_hidden_transaction_continuations_stay_bounded_and_complete(self):
        _, _, cursor = self.snapshot(packs=[POULTRY_PACK])
        group = uuid.uuid4()
        for index in range(3):
            self.append_change("finance.sale", {"private": "SECRET"}, transaction_id=group, index=index, count=3)
        previous = cursor
        for index in range(3):
            response = self.client.get(BASE + "changes", {"cursor": previous})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["changes"], [])
            self.assertEqual(response.data["run_complete"], index == 2)
            self.assertEqual(response.data["fragments"], [{"transaction_id": str(group), "fragment_index": index, "fragment_final": index == 2}])
            self.assertNotEqual(response.data["next_cursor"], previous)
            self.assertNotIn("SECRET", str(response.data))
            previous = response.data["next_cursor"]

    def test_existing_snapshot_and_cursor_remain_valid_when_future_registries_expand(self):
        manifest, rows, cursor = self.snapshot(packs=[POULTRY_PACK])
        with patch.dict(TYPES, {"Sales": "finance.sale"}), patch.dict(REGISTRY, {FUTURE_KEY: FUTURE_SPEC}):
            page = self.client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": manifest["next_page_cursor"]})
            self.assertEqual(page.status_code, 200, page.data)
            self.assertEqual(page.data["entities"], rows)
            self.assertEqual(page.data["sha256"], checksum(rows))
            changes = self.client.get(BASE + "changes", {"cursor": cursor})
            self.assertEqual(changes.status_code, 200, changes.data)
            self.assertTrue(changes.data["run_complete"])
            self.assertEqual(changes.data["changes"], [])

    def test_pull_removes_future_fields_inside_supported_operational_types(self):
        for packs in [[CURRENT_PACK], [POULTRY_PACK]]:
            _, _, cursor = self.snapshot(packs=packs)
            payload = deepcopy(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload)
            payload["price"] = "SECRET"
            payload["operational_summary"]["feed_cost"] = "SECRET"
            self.append_change("poultry.batch", payload)
            response = self.client.get(BASE + "changes", {"cursor": cursor})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(len(response.data["changes"]), 1)
            self.assertNotIn("SECRET", str(response.data))

    def test_extended_receipt_requires_original_profile_instead_of_fake_not_found(self):
        command = self.operation("poultry.weight_sample", self.fields("poultry.weight_sample"))
        self.assertEqual(self.manager_push(command)["outcome"], "accepted")
        url = BASE + f"operations/{command['operation_id']}"
        legacy = self.manager_client.get(url, HTTP_X_MOBILE_POULTRY_VERSION="1")
        self.assertEqual(legacy.status_code, 409, legacy.data)
        self.assertEqual(legacy.data["code"], "unsupported_protocol")
        self.assertEqual(self.manager_client.get(url).status_code, 200)
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)

    def test_v2_mortality_receipt_and_replay_are_projected_for_v1_without_changing_hash_or_effects(self):
        command = self.command()
        response = self.push(command)
        self.assertEqual(response.data["results"][0]["outcome"], "accepted")
        receipt = SyncOperationReceipt.objects.get(operation_id=command["operation_id"])
        original = deepcopy((receipt.command, receipt.request_hash, receipt.result))
        sequence = SyncStreamState.objects.get(pk=1).sequence
        self.client.defaults["HTTP_X_MOBILE_POULTRY_VERSION"] = "1"
        for _ in range(20):
            replay = self.push(command)
            self.assertEqual(replay.data["results"][0]["outcome"], "replayed")
            for entity in replay.data["results"][0]["canonical_entities"]:
                self.assertEqual(set(entity["payload"]), V1_FIELDS[entity["entity_type"]])
        lookup = self.client.get(BASE + f"operations/{command['operation_id']}")
        self.assertEqual(lookup.status_code, 200, lookup.data)
        self.assertNotIn("operational_summary", str(lookup.data))
        receipt.refresh_from_db()
        self.assertEqual((receipt.command, receipt.request_hash, receipt.result), original)
        self.assertEqual(Mortality.objects.count(), 1)
        self.assertEqual(SyncStreamState.objects.get(pk=1).sequence, sequence)

    def test_future_financial_receipt_cannot_be_returned_or_replayed_by_old_profiles(self):
        command, receipt, session = self.future_receipt()
        handler = Mock(side_effect=AssertionError("Future handler dispatched"))
        spec = SimpleNamespace(**{**FUTURE_SPEC.__dict__, "handler": handler})
        original = deepcopy((receipt.command, receipt.request_hash, receipt.result))
        token = AccessToken(self.registration["access"])
        with patch.dict(REGISTRY, {FUTURE_KEY: spec}):
            for version in [1, 2]:
                response = self.client.get(BASE + f"operations/{command['operation_id']}", HTTP_X_MOBILE_POULTRY_VERSION=str(version))
                self.assertEqual(response.status_code, 409, response.data)
                self.assertNotIn("SECRET", str(response.data))
                result = execute(command, self.worker, session, token, version=version)
                self.assertEqual(result["code"], "command_unavailable")
                self.assertNotIn("SECRET", str(result))
        handler.assert_not_called()
        receipt.refresh_from_db()
        self.assertEqual((receipt.command, receipt.request_hash, receipt.result), original)
        self.assertEqual(SyncOperationReceipt.objects.count(), 1)
        self.assertEqual(Mortality.objects.count(), 0)

    def test_future_combination_of_existing_kind_and_action_cannot_bypass_typed_profile(self):
        key = ("poultry.mortality", "book", 1)
        command = self.command()
        command["action"] = "book"
        with patch.dict(REGISTRY, {key: FUTURE_SPEC}), patch.dict(PAYLOAD_SERIALIZERS, {key[:2]: MortalityPayloadSerializer}):
            serializer = PoultryOperationSerializer(data=command)
            self.assertFalse(serializer.is_valid())
            self.assertIn("action", serializer.errors)
        self.assertEqual(SyncOperationReceipt.objects.count(), 0)

    def test_operation_lookup_honors_projection_flag_and_device_revocation(self):
        command = self.command()
        self.push(command)
        url = BASE + f"operations/{command['operation_id']}"
        with override_settings(MOBILE_SYNC_POULTRY_V2=False):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 409, response.data)
        revoke = self.client.post(BASE + f"devices/{self.registration['device_id']}/revoke", {"reason": "Synthetic revocation"}, format="json")
        self.assertEqual(revoke.status_code, 200, revoke.data)
        response = self.client.get(url)
        self.assertIn(response.status_code, [401, 403])
        self.assertNotIn("canonical_entities", response.data)

    def test_invalid_frozen_page_is_refused_without_rewriting_stored_checksum(self):
        response = self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": [CURRENT_PACK]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        manifest = response.data
        page = SyncBootstrapPage.objects.get(snapshot_id=manifest["snapshot_id"], number=0)
        # Use a separate newly created page to emulate a pre-existing wider
        # snapshot. Never defeat the immutable manager with an update.
        payload = deepcopy(page.payload)
        payload[0]["payload"]["price"] = "SECRET"
        new_page = SyncBootstrapPage.objects.create(snapshot=page.snapshot, number=99, payload=payload, checksum=checksum(payload))
        from apps.mobile_sync.transport import decode, encode
        device = MobileDevice.objects.get(pk=self.registration["device_id"])
        data = decode(manifest["next_page_cursor"], SyncStreamState.objects.get(pk=1), self.worker, device)
        response = self.client.get(BASE + f"bootstrap/{manifest['snapshot_id']}/pages", {"cursor": encode({**data, "page": 99})})
        self.assertEqual(response.status_code, 503, response.data)
        self.assertNotIn("SECRET", str(response.data))
        new_page.refresh_from_db()
        self.assertEqual(new_page.payload, payload)
        self.assertEqual(new_page.checksum, checksum(payload))
