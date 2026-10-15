"""Private global-reference publication on NEW owned PostgreSQL databases only."""
from copy import deepcopy
from threading import Event, Thread
import time
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleChoices
from apps.finance.models import FinancialCommandReceipt, FundingSource, FundingSourceType, JournalEntry
from apps.finance.services.inventory_invoices import record_inventory_invoice
from apps.finance.tests import test_inventory_invoices as invoices, test_inventory_purchase_proof as proof
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import financial_references as funding, reference_publication as publication
from apps.mobile_sync import schema_reference_publication as wire, transport
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import FinancialPublicationBinding, MobileSession, SyncChange, SyncEntity, SyncStreamState
from apps.mobile_sync.projections import canonical
from apps.mobile_sync.writers import sync_boundary, UnsafeSyncWrite
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_sync import BASE

SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCES": True,
    "MOBILE_SYNC_FINANCIAL_PUBLICATION": True}


class PublicationFixture(BridgeFixture):
    def setUp(self):
        # Original synthetic business fixtures predate this explicit metadata baseline.
        with override_settings(MOBILE_SYNC_FINANCIAL_PUBLICATION=False):
            super().setUp()

    def seed(self, sources=None, receipts=None):
        return publication.initialize_reference_publication(
            [str(source.pk) for source in sources or []], receipts or [], self.user, self.session, self.token)

    def entity(self, source=None, kind=wire.FUNDING_TYPE):
        return SyncEntity.objects.get(entity_type=kind, source_pk=str((source or self.source).pk))

    def read(self, entity=None):
        return publication.read_reference_projection(str((entity or self.entity()).entity_uuid), self.user, self.session, self.token)

    def snapshot(self):
        return {**super().snapshot(), "bindings": list(FinancialPublicationBinding.objects.order_by("pk").values())}

    def refused(self, action, code=None):
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            action()
        if code:
            self.assertEqual(error.exception.detail["code"], code)
        self.assertEqual(self.snapshot(), before)
        return error.exception

    def extra(self, **values):
        with sync_boundary():
            return FundingSource.objects.create(source_type=FundingSourceType.LOAN,
                description="Synthetic publishable selection", notes="PRIVATE-NOTES", **values)


@override_settings(**SETTINGS)
class ReferencePublicationTests(PublicationFixture, TestCase):
    def test_explicit_baseline_is_metadata_only_one_group_and_positive_private_fields(self):
        original = proof.snapshot()
        result = self.seed([self.source], [self.invoice["invoice_group_id"], self.second["invoice_group_id"]])
        self.assertEqual(result, {"prepared": 3, "created": 3, "financial_uploads": False})
        self.assertEqual(proof.snapshot(), original)
        changes = list(SyncChange.objects.order_by("sequence"))
        self.assertEqual(len(changes), 3)
        self.assertEqual(len({row.transaction_id for row in changes}), 1)
        self.assertEqual([row.transaction_index for row in changes], [0, 1, 2])
        self.assertTrue(all(row.transaction_count == 3 and row.batch_uuid is None and not row.in_current_pack for row in changes))
        self.assertEqual(FinancialPublicationBinding.objects.count(), 3)
        self.assertEqual(SyncEntity.objects.count(), 4)  # Separate original funding resolver identity.
        for entity in SyncEntity.objects.filter(entity_type__in=publication.TYPES):
            value = self.read(entity)
            Draft7Validator(wire.ENTITY, format_checker=FormatChecker()).validate(value)
            self.assertNotIn('"source_pk"', canonical(value))
            self.assertNotIn('"actor_id"', canonical(value))
            self.assertNotIn('"notes"', canonical(value))
            self.assertEqual(value["revision"], "1")
        source = self.entity()
        self.assertNotEqual(str(source.entity_uuid), source.payload["reference"]["reference_id"])
        invoice = self.entity(FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"]), wire.INVOICE_TYPE)
        self.assertNotEqual(str(invoice.entity_uuid), self.invoice["invoice_group_id"])
        self.assertEqual(invoice.financial_binding.audience_actor_id, self.user.pk)
        self.assertTrue(source.financial_binding.requires_owner_access)

    def test_twenty_baseline_retries_and_reads_never_change_original_state(self):
        self.seed([self.source], [self.invoice["invoice_group_id"]])
        original, value = self.snapshot(), self.read()
        for _ in range(20):
            self.assertEqual(self.seed([self.source], [self.invoice["invoice_group_id"]])["created"], 0)
            self.assertEqual(self.read(), value)
        self.assertEqual(self.snapshot(), original)

    def test_new_source_is_published_and_private_resolver_mapping_stays_revision_one(self):
        source = self.extra()
        entity = self.entity(source)
        self.assertEqual(entity.revision, 1)
        self.assertEqual(entity.payload["reference"]["source_type"], "loan")
        self.assertTrue(entity.payload["available"])
        self.assertNotIn("PRIVATE-NOTES", canonical(entity.payload))
        mapping = SyncEntity.objects.get(entity_type=funding.ENTITY_TYPE, source_pk=str(source.pk))
        before = deepcopy(mapping.payload)
        with sync_boundary():
            source.description = "New label"
            source.is_active = False
            source.save(update_fields=["description", "is_active", "updated_at"])
        entity.refresh_from_db()
        mapping.refresh_from_db()
        self.assertEqual(entity.revision, 2)
        self.assertFalse(entity.payload["available"])
        self.assertEqual(entity.payload["reference"]["label"], "New label")
        self.assertEqual((mapping.revision, mapping.payload), (1, before))
        self.assertEqual(SyncChange.objects.count(), 2)

    def test_notes_and_same_value_or_rolled_back_updates_do_not_publish(self):
        source = self.extra()
        before = self.snapshot()["sync"]
        with sync_boundary():
            source.notes = "Still private"
            source.save(update_fields=["notes", "updated_at"])
            FundingSource.objects.filter(pk=source.pk).update(description=source.description)
            try:
                with transaction.atomic():
                    FundingSource.objects.filter(pk=source.pk).update(description="Rolled back")
                    raise RuntimeError("Synthetic savepoint loss")
            except RuntimeError:
                pass
        self.assertEqual(self.snapshot()["sync"], before)

    def test_predicate_changing_queryset_update_and_bulk_update_publish_final_values_once(self):
        first, second = self.extra(), self.extra()
        with sync_boundary():
            self.assertEqual(FundingSource.objects.filter(pk=first.pk, is_active=True).update(is_active=False), 1)
            first.refresh_from_db()
            for row in (first, second):
                row.description = "Final bounded bulk label"
            FundingSource.objects.bulk_update([first, second], ["description"])
        self.assertEqual((self.entity(first).revision, self.entity(second).revision), (2, 2))
        self.assertFalse(self.entity(first).payload["available"])
        self.assertEqual(SyncChange.objects.count(), 4)
        self.assertEqual(len(set(SyncChange.objects.order_by("-sequence").values_list("transaction_id", flat=True)[:2])), 1)

    def test_source_deletion_paths_tombstone_once_and_do_not_rebind_reused_pk(self):
        for method in ("instance", "queryset", "raw"):
            with self.subTest(method=method):
                source = self.extra()
                pk, entity = source.pk, self.entity(source)
                with sync_boundary():
                    if method == "instance":
                        source.delete()
                    elif method == "queryset":
                        FundingSource.objects.filter(pk=pk).delete()
                    else:
                        FundingSource.objects.filter(pk=pk)._raw_delete("default")
                entity.refresh_from_db()
                self.assertEqual((entity.deleted, entity.revision, entity.payload), (True, 2, {}))
                self.assertEqual(self.read(entity)["deleted"], True)
                last = SyncChange.objects.order_by("-sequence").first()
                self.assertEqual((last.kind, last.batch_uuid, last.payload), ("tombstone", None, {}))
                self.refused(lambda: self.extra(pk=pk), "funding_reference_review_required")
                self.assertFalse(FundingSource.objects.filter(pk=pk).exists())

    def test_caught_savepoint_seed_and_create_delete_do_not_create_phantom_changes(self):
        before = self.snapshot()
        with sync_boundary():
            try:
                with transaction.atomic():
                    self.seed([self.source])
                    raise RuntimeError("Synthetic baseline savepoint rollback")
            except RuntimeError:
                pass
            transient = self.extra()
            transient.delete()
        self.assertEqual(self.snapshot(), before)

    def test_existing_source_needs_explicit_baseline_never_silent_adoption(self):
        def change():
            with sync_boundary():
                FundingSource.objects.filter(pk=self.source.pk).update(description="Changed historical label")
        self.refused(change, "financial_publication_review_required")
        self.seed([self.source])
        original = proof.snapshot()
        change()
        self.assertEqual(self.entity().revision, 2)
        self.assertEqual(JournalEntry.objects.count(), len(original["journalentry"]))

    def test_bulk_create_raw_import_and_unscoped_atomic_writers_fail_before_effect(self):
        def bulk():
            with sync_boundary():
                FundingSource.objects.bulk_create([FundingSource(source_type=FundingSourceType.LOAN)])
        self.refused(bulk, "financial_publication_bulk_unavailable")
        self.seed([self.source])
        before = self.snapshot()
        with self.assertRaises(UnsafeSyncWrite):
            self.source.save_base(update_fields=["description"])
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(SyncError), sync_boundary():
            self.source.save_base(raw=True, update_fields=["description"])
        self.assertEqual(self.snapshot(), before)
        with sync_boundary():
            self.source.description = "Explicit low-level original writer"
            self.source.save_base(update_fields=["description"])
        self.assertEqual(self.entity().revision, 2)

    def test_source_identity_rebind_is_refused_and_rolled_back(self):
        source = self.extra()
        def change():
            with sync_boundary():
                FundingSource.objects.filter(pk=source.pk).update(source_type=FundingSourceType.GENERAL_FARM_CASH)
        self.refused(change)

    def test_flag_off_gap_is_not_served_reseeded_or_bridged_by_next_write(self):
        source = self.extra()
        entity = self.entity(source)
        with override_settings(MOBILE_SYNC_FINANCIAL_PUBLICATION=False), sync_boundary():
            FundingSource.objects.filter(pk=source.pk).update(description="Missed while publication disabled")
        self.refused(lambda: self.read(entity), "financial_publication_review_required")
        self.refused(lambda: self.seed([source]), "financial_publication_review_required")
        def change():
            with sync_boundary():
                FundingSource.objects.filter(pk=source.pk).update(description="Must not repair gap")
        self.refused(change, "financial_publication_review_required")

    def test_publisher_failure_and_combined_group_budget_roll_back_every_effect(self):
        before = self.snapshot()
        with patch.object(SyncChange.objects, "bulk_create", side_effect=RuntimeError("Synthetic publication crash")):
            with self.assertRaises(RuntimeError):
                self.extra()
        self.assertEqual(self.snapshot(), before)
        with override_settings(MOBILE_SYNC_GROUP_ROWS=1):
            self.refused(lambda: self.seed([self.source], [self.invoice["invoice_group_id"]]), "transaction_too_large")

    def test_dirty_limits_and_positive_schema_fail_without_partial_source_or_metadata(self):
        with patch.object(publication, "MAX_DIRTY", 1):
            def create():
                with sync_boundary():
                    self.extra()
                    self.extra()
            self.refused(create, "financial_publication_limit")
        with patch.object(publication, "MAX_ENTITY_BYTES", 1):
            self.refused(self.extra, "financial_publication_limit")
        source = self.extra()
        with sync_boundary():
            FundingSource.objects.filter(pk=source.pk).update(is_active=False)
        self.assertFalse(self.read(self.entity(source))["payload"]["available"])

    def test_new_original_invoice_publishes_header_once_and_twenty_retries_do_not_repeat(self):
        request = invoices.invoice_request(self, invoice_reference="SYNTHETIC-PUBLISHED-NEW")
        with sync_boundary():
            result, created = record_inventory_invoice(**request)
        self.assertTrue(created)
        entity = self.entity(FinancialCommandReceipt.objects.get(pk=result["invoice_group_id"]), wire.INVOICE_TYPE)
        self.assertEqual(entity.payload["invoice"]["original_total_purchase_cost"], "150.00")
        self.assertEqual(SyncChange.objects.count(), 1)
        original = self.snapshot()
        for _ in range(20):
            with sync_boundary():
                self.assertEqual(record_inventory_invoice(**request), (result, False))
        self.assertEqual(self.snapshot(), original)

    def test_actual_invoice_service_rolls_back_domain_on_publication_failure(self):
        before = self.snapshot()
        with patch.object(SyncChange.objects, "bulk_create", side_effect=RuntimeError("Synthetic invoice publisher crash")):
            with self.assertRaises(RuntimeError), sync_boundary():
                record_inventory_invoice(**invoices.invoice_request(self, invoice_reference="SYNTHETIC-ROLLBACK"))
        self.assertEqual(self.snapshot(), before)

    def test_late_access_loss_rolls_back_entire_baseline(self):
        with patch.object(funding, "_unchanged_access", side_effect=SyncError("permission_denied", "Synthetic late access loss", 403)):
            self.refused(lambda: self.seed([self.source], [self.invoice["invoice_group_id"]]), "permission_denied")

    def test_owner_actor_and_current_session_gates_never_disclose_global_payload(self):
        self.seed([self.source], [self.invoice["invoice_group_id"]])
        source = self.entity()
        parent = self.entity(FinancialCommandReceipt.objects.get(pk=self.invoice["invoice_group_id"]), wire.INVOICE_TYPE)
        self.role(RoleChoices.FARM_MANAGER)
        self.refused(lambda: self.read(source), "funding_reference_unavailable")
        self.assertIn("invoice", self.read(parent)["payload"])
        with sync_boundary():
            other = get_user_model().objects.create_user(username="publication-other-admin",
                email="publication-other@example.invalid", is_superuser=True)
        _, _, session, token = self.register(other)
        self.refused(lambda: publication.read_reference_projection(str(parent.entity_uuid), other, session, token), "funding_reference_unavailable")
        with sync_boundary():
            MobileSession.objects.filter(pk=self.session.pk).update(revoked_at=timezone.now())
        self.refused(lambda: self.read(parent))

    def test_missing_binding_and_changed_projection_are_never_repaired(self):
        source = self.extra()
        entity = self.entity(source)
        # Owned disposable DB corruption probe: immutable binding cannot be changed by ORM.
        with self.assertRaises(ValueError):
            entity.financial_binding.delete()
        changed = deepcopy(entity.payload)
        changed["reference"]["label"] = "Unproved projection tampering"
        corrupt_inventory(SyncEntity, entity.pk, payload=__import__("json").dumps(changed))
        self.refused(lambda: self.read(entity), "financial_publication_review_required")
        self.refused(lambda: self.seed([source]), "financial_publication_review_required")

    def test_damaged_permanent_binding_is_refused_without_automatic_repair(self):
        source = self.extra()
        entity = self.entity(source)
        corrupt_inventory(FinancialPublicationBinding, entity.financial_binding.pk, source_identity="0" * 64)
        self.refused(lambda: self.read(entity), "financial_publication_review_required")
        self.refused(lambda: self.seed([source]), "financial_publication_review_required")

    def test_ordinary_finance_api_writer_joins_the_same_publication_boundary(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        response = client.post("/api/v1/finance/funding-sources", {"source_type": "loan",
            "description": "Ordinary synthetic finance API", "notes": "Not published"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        source = FundingSource.objects.get(pk=response.data["id"])
        self.assertEqual(self.entity(source).payload["reference"]["label"], "Ordinary synthetic finance API")
        self.assertEqual(SyncChange.objects.count(), 1)

    def test_default_off_and_capture_disabled_refuse_private_reads_before_sql(self):
        for flags in ({"MOBILE_SYNC_FINANCIAL_PUBLICATION": False}, {"MOBILE_SYNC_CAPTURE": False}, {"MOBILE_SYNC_ENABLED": False}):
            with override_settings(**flags), self.assertNumQueries(0), self.assertRaises(SyncError):
                self.seed([self.source])
            with override_settings(**flags), self.assertNumQueries(0), self.assertRaises(SyncError):
                self.read(SyncEntity(entity_uuid=uuid.uuid4()))

    def test_global_rows_constrained_to_no_batch_not_operational_and_valid_original_rows(self):
        values = dict(stream=self.stream, sequence=1, transaction_id=uuid.uuid4(), transaction_index=0,
            transaction_count=1, entity_type=wire.FUNDING_TYPE, entity_uuid=uuid.uuid4(), revision=1, kind="upsert")
        for changes in ({"batch_uuid": uuid.uuid4()}, {"batch_uuid": None, "in_current_pack": True},
                {"batch_uuid": None, "kind": "evict_from_pack"},
                {"entity_type": "poultry.batch", "batch_uuid": None}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                SyncChange.objects.create(**{**values, **changes})

    def test_hidden_global_changes_do_not_enter_either_operational_profile(self):
        for pack in ("operational-current-v1", "operational-current-v2"):
            with override_settings(MOBILE_SYNC_POULTRY_V2=True):
                before = SyncChange.objects.count()
                # Use a current-bound pre-publication cursor, not a fabricated grant.
                stream = SyncStreamState.objects.get(pk=1)
                cursor = transport.encode({**transport.cursor_base(stream, self.user, self.session.device, [pack]),
                    "kind": "changes", "position": stream.sequence, "upper": None, "group": None, "fragment": 0})
                self.extra()
                with override_settings(MOBILE_SYNC_SNAPSHOT_ROWS=1):
                    snapshot = transport.create_bootstrap(self.user, self.session.device, [pack])
                self.assertEqual(snapshot.row_count, 0)  # All global and resolver rows excluded in SQL.
                page = transport.pull_changes(self.user, self.session.device, cursor, 50)
                self.assertEqual(page["changes"], [])
                self.assertTrue(page["run_complete"])
                self.assertTrue(page["fragments"][-1]["fragment_final"])
                self.assertEqual(SyncChange.objects.count(), before + 1)
                self.assertNotIn("finance.", canonical(page))

    def test_mixed_operational_and_global_changes_share_one_complete_group(self):
        stream = SyncStreamState.objects.get(pk=1)
        cursor = transport.encode({**transport.cursor_base(stream, self.user, self.session.device, ["operational-current-v1"]),
            "kind": "changes", "position": stream.sequence, "upper": None, "group": None, "fragment": 0})
        with sync_boundary() as state:
            self.batch.save()
            self.extra()
        changes = state["changes"]
        self.assertTrue(any(row.entity_type.startswith("poultry.") for row in changes))
        self.assertEqual(changes[-1].entity_type, wire.FUNDING_TYPE)
        self.assertEqual(len({row.transaction_id for row in changes}), 1)
        self.assertEqual([row.transaction_index for row in changes], list(range(len(changes))))
        self.assertTrue(all(row.transaction_count == len(changes) for row in changes))
        self.assertIsNone(changes[-1].batch_uuid)
        self.assertTrue(all(row.batch_uuid is not None for row in changes[:-1]))
        fragments, exposed, runs = [], [], 0
        # A hidden global tail must finish the SAME mixed group even when scanned separately.
        with override_settings(MOBILE_SYNC_SCAN_ROWS=1):
            while True:
                page = transport.pull_changes(self.user, self.session.device, cursor, 50)
                fragments.extend(page["fragments"])
                exposed.extend(page["changes"])
                runs += 1
                self.assertLess(runs, 10)
                if page["run_complete"]:
                    break
                cursor = page["next_cursor"]
        self.assertEqual(len(exposed), len(changes) - 1)
        self.assertTrue(all(row["entity_type"].startswith("poultry.") for row in exposed))
        self.assertFalse(any(row["fragment_final"] for row in fragments[:-1]))
        self.assertTrue(fragments[-1]["fragment_final"])
        self.assertEqual([row["fragment_index"] for row in fragments], list(range(len(changes))))


@override_settings(**SETTINGS)
class ReferencePublicationConcurrencyTests(PublicationFixture, TransactionTestCase):
    def test_concurrent_baseline_has_one_original_publication_group(self):
        original = proof.snapshot()
        def prepare():
            result = self.seed([self.source], [self.invoice["invoice_group_id"]])
            return None, result["created"]
        self.assertCountEqual(proof.race(self, [prepare, prepare]), [2, 0])
        self.assertEqual(SyncChange.objects.count(), 2)
        self.assertEqual(FinancialPublicationBinding.objects.count(), 2)
        self.assertEqual(proof.snapshot(), original)

    def test_next_source_writer_really_waits_for_stream_and_cannot_publish_behind_cursor(self):
        started, pids, results = Event(), [], []
        def second():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.append(cursor.fetchone()[0])
                started.set()
                results.append(self.extra().pk)
            except Exception as error:
                results.append(type(error).__name__)
            finally:
                close_old_connections()
        with sync_boundary():
            first = self.extra()
            worker = Thread(target=second)
            worker.start()
            self.assertTrue(started.wait(10))
            waiting, deadline = False, time.monotonic() + 3
            while time.monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [pids[0]])
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                time.sleep(0.01)
            self.assertTrue(waiting, "Second PostgreSQL writer must actually wait on original stream")
        worker.join(25)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], int)
        changes = list(SyncChange.objects.order_by("sequence"))
        self.assertEqual([row.sequence for row in changes], [1, 2])
        self.assertEqual([row.entity_uuid for row in changes], [self.entity(first).entity_uuid,
            self.entity(FundingSource.objects.get(pk=results[0])).entity_uuid])
        self.assertNotEqual(changes[0].transaction_id, changes[1].transaction_id)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_FINANCIAL_PUBLICATION=False)
class ReferencePublicationMigrationTests(TransactionTestCase):
    def test_0002_to_0003_preserves_original_rows_without_binding_or_source_backfill(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_mobile_phase02_"))
        executor = MigrationExecutor(connection)
        old, latest = [("mobile_sync", "0002_seed_identity")], [("mobile_sync", "0003_financial_reference_publication")]
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            Stream, Change = apps.get_model("mobile_sync", "SyncStreamState"), apps.get_model("mobile_sync", "SyncChange")
            stream, _ = Stream.objects.get_or_create(pk=1)
            Change.objects.create(stream=stream, sequence=77, transaction_id=uuid.uuid4(), transaction_index=0,
                transaction_count=1, entity_type="poultry.batch", entity_uuid=uuid.uuid4(), batch_uuid=uuid.uuid4(),
                revision=9, kind="upsert", payload={"original": "unchanged"})
            original = list(Change.objects.order_by("pk").values())
            # Current default-off source writer must also work against retained0002,
            # without querying the absent binding table or inserting global changes.
            with override_settings(MOBILE_SYNC_CAPTURE=True):
                FundingSource.objects.create(source_type=FundingSourceType.LOAN, description="Unmigrated default-off compatibility")
            self.assertEqual(list(Change.objects.order_by("pk").values()), original)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            self.assertEqual(list(SyncChange.objects.order_by("pk").values()), original)
            self.assertEqual(FinancialPublicationBinding.objects.count(), 0)
            self.assertEqual(SyncEntity.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
