"""Private authorized UUID references on owned PostgreSQL, not native upload."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import uuid
from threading import Event, Thread
import time

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import FundingSource, FundingSourceType, FundingAllocation, JournalEntry
from apps.finance.services.cash_funding import dated_source_cash
from apps.finance.tests import test_expenditure_drafts as drafts
from apps.finance.tests.inventory_corruption import corrupt_inventory
from apps.mobile_sync import financial_references as references
from apps.mobile_sync import schema_financial_references as wire
from apps.mobile_sync.commands import financial as bridge
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import SyncEntity, SyncOperationReceipt, SyncStreamState
from apps.mobile_sync.projections import canonical
from apps.mobile_sync.writers import sync_boundary
from .test_financial_commands import BridgeFixture, SETTINGS as BRIDGE_SETTINGS
from .test_sync import BASE
from apps.finance.tests import test_inventory_purchase_proof as proof


SETTINGS = {**BRIDGE_SETTINGS, "MOBILE_SYNC_FINANCIAL_REFERENCES": True}


@override_settings(**SETTINGS)
class FinancialFundingReferenceTests(BridgeFixture, TestCase):
    def prepare(self, sources=None):
        return references.prepare_funding_references([str(source.pk) for source in sources or [self.source]],
            self.user, self.session, self.token)

    def catalog(self, **kwargs):
        result = references.funding_reference_catalog(self.user, self.session, self.token, **kwargs)
        Draft7Validator.check_schema(wire.CATALOG)
        Draft7Validator(wire.CATALOG, format_checker=FormatChecker()).validate(result)
        return result

    def rows(self, source=None, **changes):
        source = source or self.source
        row = next(row for row in self.catalog()["rows"] if row["reference_id"] == str(references._id(self.stream, source.pk)))
        return [{"funding_source": row["reference_id"], "funding_version": row["reference_version"],
            "amount": "50.00", **changes}]

    def resolve(self, rows):
        return references.resolve_funding_references(rows, self.user, self.session, self.token)

    def refused(self, function, code):
        before = self.snapshot()
        with self.assertRaises(SyncError) as error:
            function()
        self.assertEqual(error.exception.detail["code"], code)
        self.assertEqual(self.snapshot(), before)
        return error.exception

    def extra(self, **changes):
        with sync_boundary():
            return FundingSource.objects.create(source_type=FundingSourceType.LOAN,
                description="Synthetic loan selection", notes="PRIVATE-FUNDING-NOTES-NOT-PROJECTED", **changes)

    def test_preparation_is_metadata_only_idempotent_and_never_operational_publication(self):
        before = self.snapshot()
        self.assertEqual(self.prepare(), {"prepared": 1, "created": 1, "financial_uploads": False})
        after = self.snapshot()
        self.assertEqual(before["finance"], after["finance"])
        for key in ("syncstreamstate", "syncchange", "syncoperationreceipt"):
            self.assertEqual(before["sync"][key], after["sync"][key])
        self.assertEqual(self.prepare()["created"], 0)
        self.assertEqual(self.snapshot(), after)
        mapping = SyncEntity.objects.get(entity_type=references.ENTITY_TYPE)
        self.assertEqual(mapping.batch_pk, "")
        self.assertFalse(mapping.in_current_pack)
        self.assertNotIn("server_id", mapping.payload)

    def test_twenty_reads_resolutions_are_exact_nonmutating_and_no_money_claim(self):
        self.prepare()
        rows = self.rows(classification="working_capital")
        original = deepcopy(rows)
        before = self.snapshot()
        for _ in range(20):
            page = self.catalog()
            self.assertEqual(page["offline_cache_seconds"], 0)
            self.assertFalse(page["financial_uploads"])
            self.assertEqual(self.resolve(rows), [{"funding_source": str(self.source.pk), "amount": "50.00", "classification": "working_capital"}])
        self.assertEqual(rows, original)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(page["rows"][0]), {"reference_id", "reference_version", "source_type", "label",
            "currency", "cash_pool_id", "cash_pool_semantics", "balance_semantics"})
        self.assertNotIn("PRIVATE", canonical(page))
        self.assertEqual(page["rows"][0]["cash_pool_semantics"], "source_specific")

    def test_unprepared_catalog_refuses_instead_of_seeding_on_read(self):
        self.refused(self.catalog, "funding_catalog_not_prepared")
        self.prepare()
        self.extra()
        self.refused(self.catalog, "funding_catalog_not_prepared")

    def test_catalog_pages_all_rows_once_and_cursor_contains_no_private_source_pks(self):
        sources = [self.source] + [self.extra() for _ in range(54)]
        self.prepare(sources)
        before = self.snapshot()
        first = self.catalog()
        second = self.catalog(cursor=first["next_cursor"])
        self.assertEqual((len(first["rows"]), len(second["rows"])), (50, 5))
        self.assertEqual((first["total_authorized_rows"], second["total_authorized_rows"]), (55, 55))
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(len({row["reference_id"] for row in first["rows"] + second["rows"]}), 55)
        point = signing.loads(first["next_cursor"], salt=references.BASIS + "-cursor")
        self.assertEqual(set(point), {"version", "scope", "catalog", "last"})
        self.assertEqual(self.snapshot(), before)

    def test_tampered_expired_foreign_or_wrong_catalog_cursors_refuse(self):
        self.prepare([self.source, self.extra()])
        with patch.object(references, "PAGE_ROWS", 1):
            first = self.catalog()
            self.refused(lambda: self.catalog(cursor=first["next_cursor"] + "bad"), "funding_catalog_changed")
            self.refused(lambda: self.catalog(cursor=7), "funding_catalog_changed")
            with patch.object(signing, "loads", side_effect=signing.SignatureExpired):
                self.refused(lambda: self.catalog(cursor=first["next_cursor"]), "funding_catalog_changed")
            other_client, registration, other_session, other_token = self.register(self.user)
            self.refused(lambda: references.funding_reference_catalog(self.user, other_session, other_token,
                cursor=first["next_cursor"]), "funding_catalog_changed")
            self.extra()
            # Incomplete new membership refuses before attempting cursor reuse.
            self.refused(lambda: self.catalog(cursor=first["next_cursor"]), "funding_catalog_not_prepared")

    def test_changed_label_or_membership_invalidates_page_not_original_reference(self):
        extra = self.extra()
        self.prepare([self.source, extra])
        selected = self.rows()
        with patch.object(references, "PAGE_ROWS", 1):
            first = self.catalog()
            with sync_boundary():
                extra.description = "Corrected visible source label"
                extra.save(update_fields=["description", "updated_at"])
            self.refused(lambda: self.catalog(cursor=first["next_cursor"]), "funding_catalog_changed")
        self.assertEqual(self.resolve(selected)[0]["funding_source"], str(self.source.pk))

    def test_catalog_limits_fail_explicitly_without_truncation(self):
        self.prepare([self.source, self.extra()])
        with patch.object(references, "MAX_CATALOG_ROWS", 1):
            self.refused(self.catalog, "funding_catalog_limit")
        with patch.object(references, "MAX_CATALOG_BYTES", 1):
            self.refused(self.catalog, "funding_catalog_limit")

    def test_current_write_roles_only_and_no_owner_catalog_for_manager_supervisor(self):
        extra = self.extra()
        self.prepare([self.source, extra])
        owner_rows = self.rows()
        for role in (RoleChoices.FARM_MANAGER, RoleChoices.FARM_SUPERVISOR):
            with self.subTest(role=role):
                self.role(role)
                page = self.catalog()
                self.assertEqual([row["source_type"] for row in page["rows"]], [FundingSourceType.LOAN])
                self.refused(lambda: self.resolve(owner_rows), "funding_reference_unavailable")
                self.refused(self.prepare, "funding_reference_unavailable")
        for role in (RoleChoices.GENERAL_WORKER, RoleChoices.STAKE_HOLDER, None):
            with self.subTest(role=role):
                self.role(role)
                self.refused(self.catalog, "permission_denied")
                self.refused(lambda: self.resolve(owner_rows), "permission_denied")

    def test_director_can_select_owner_source_without_exposing_owner_identity(self):
        self.prepare()
        self.role(RoleChoices.DIRECTOR)
        page = self.catalog()
        self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(page["rows"][0]["source_type"], FundingSourceType.OWNER_CAPITAL)
        if self.source.description:
            self.assertNotIn(self.source.description, page["rows"][0]["label"])
        self.assertNotIn("owner_id", canonical(page))
        self.assertNotIn("notes", canonical(page))

    def test_shared_batch_aliases_share_one_pool_not_two_cash_balances(self):
        with override_settings(MOBILE_SYNC_CAPTURE=False):
            original = drafts.funded_source(self)
            alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION, batch=original.batch,
                description="Synthetic same-pool alias")
        self.prepare([self.source, original, alias])
        page = self.catalog()
        batches = [row for row in page["rows"] if row["source_type"] == FundingSourceType.BATCH_COLLECTION]
        self.assertEqual(len(batches), 2)
        self.assertNotEqual(batches[0]["reference_id"], batches[1]["reference_id"])
        self.assertEqual(batches[0]["cash_pool_id"], batches[1]["cash_pool_id"])
        self.assertTrue(all(row["cash_pool_semantics"] == "shared_batch_collection" for row in batches))

    def test_source_disabling_and_deleted_mapping_have_no_substitute_identity(self):
        self.prepare()
        rows = self.rows()
        with sync_boundary():
            self.source.is_active = False
            self.source.save(update_fields=["is_active", "updated_at"])
        self.refused(lambda: self.resolve(rows), "funding_reference_unavailable")
        self.assertEqual(self.catalog()["rows"], [])
        with sync_boundary():
            self.source.is_active = True
            self.source.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.rows(), rows)
        SyncEntity.objects.filter(entity_type=references.ENTITY_TYPE).update(deleted=True)
        self.refused(self.catalog, "funding_reference_review_required")
        self.refused(self.prepare, "funding_reference_review_required")
        self.refused(lambda: self.resolve(rows), "funding_reference_review_required")

    def test_wrong_version_or_unknown_uuid_retains_original_selection(self):
        self.prepare()
        rows = self.rows()
        wrong = deepcopy(rows)
        wrong[0]["funding_version"] = "0" * 64
        self.refused(lambda: self.resolve(wrong), "funding_reference_changed")
        wrong = deepcopy(rows)
        wrong[0]["funding_source"] = str(uuid.uuid4())
        self.refused(lambda: self.resolve(wrong), "funding_reference_unavailable")

    def test_private_pk_number_float_extra_fields_and_bad_money_are_not_wire_references(self):
        self.prepare()
        original = self.rows()
        for key, value in (("funding_source", str(self.source.pk)), ("funding_source", self.source.pk),
                ("amount", 50), ("amount", 50.0), ("amount", "1e2"), ("amount", "50.001"),
                ("amount", "050.00"), ("amount", "0.00"), ("classification", "loan"),
                ("owner_id", "PRIVATE"), ("funding_version", "0"), ("amount", "50.00\n"),
                ("amount", "50.00\r\n"), ("funding_version", "a" * 64 + "\n")):
            with self.subTest(key=key, value=value):
                changed = deepcopy(original)
                changed[0][key] = value
                self.refused(lambda: self.resolve(changed), "malformed_request")
        self.refused(lambda: self.resolve(original * 2), "malformed_request")
        self.refused(lambda: self.resolve([]), "malformed_request")
        self.refused(lambda: self.resolve(original * 101), "malformed_request")

    def test_bounded_exact_money_is_preserved_without_using_numeric_pks_on_wire(self):
        self.prepare()
        rows = self.rows(amount="999999999999.99", classification="cost_recovery")
        self.assertEqual(self.resolve(rows)[0]["amount"], "999999999999.99")
        self.assertEqual(self.resolve(rows)[0]["classification"], "cost_recovery")
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("200.00"))

    def test_preparation_strict_private_ids_and_partial_setup_roll_back(self):
        for ids in ([], [self.source.pk], [str(self.source.pk)] * 2, ["0"], ["9223372036854775808"], ["1"] * 101):
            self.refused(lambda: references.prepare_funding_references(ids, self.user, self.session, self.token), "malformed_request")
        self.refused(lambda: references.prepare_funding_references([str(self.source.pk), "9223372036854775807"],
            self.user, self.session, self.token), "funding_reference_unavailable")

    def test_corrupt_binding_mapping_rebinding_or_private_pk_is_never_repaired(self):
        self.prepare()
        rows = self.rows()
        mapping = SyncEntity.objects.get(entity_type=references.ENTITY_TYPE)
        for change in ({"payload": {}}, {"entity_uuid": uuid.uuid4()}, {"source_pk": "not-a-pk"},
                {"batch_pk": str(self.batch.pk)}, {"in_current_pack": True}, {"revision": 2}):
            with self.subTest(change=change):
                original = {key: getattr(mapping, key) for key in change}
                SyncEntity.objects.filter(pk=mapping.pk).update(**change)
                self.refused(self.catalog, "funding_catalog_not_prepared" if "source_pk" in change else "funding_reference_review_required")
                self.refused(lambda: self.resolve(rows), "funding_reference_unavailable" if "entity_uuid" in change else "funding_reference_review_required")
                SyncEntity.objects.filter(pk=mapping.pk).update(**original)
        # Privileged corruption is confined to this owned scratch DB.
        corrupt_inventory(FundingSource, self.source.pk, source_type=FundingSourceType.LOAN, owner_id=None)
        self.refused(self.catalog, "funding_reference_review_required")
        self.refused(self.prepare, "funding_reference_review_required")
        self.refused(lambda: self.resolve(rows), "funding_reference_review_required")

    def test_wrong_kind_or_deployment_uuid_has_same_missing_response(self):
        self.prepare()
        rows = self.rows()
        mapping = SyncEntity.objects.get(entity_type=references.ENTITY_TYPE)
        SyncEntity.objects.filter(pk=mapping.pk).update(entity_type="poultry.batch")
        missing = self.refused(lambda: self.resolve(rows), "funding_reference_unavailable")
        other_stream = SyncStreamState(pk=1, deployment_id=uuid.uuid4())
        foreign = deepcopy(rows)
        foreign[0]["funding_source"] = str(references._id(other_stream, self.source.pk))
        error = self.refused(lambda: self.resolve(foreign), "funding_reference_unavailable")
        self.assertEqual(str(error), str(missing))

    def test_gate_off_before_queries_for_all_three_functions(self):
        for setting in ("MOBILE_SYNC_FINANCIAL_REFERENCES", "MOBILE_SYNC_ENABLED", "MOBILE_SYNC_CAPTURE"):
            with override_settings(**{setting: False}), self.assertNumQueries(0):
                for action in (self.prepare, self.catalog, lambda: self.resolve([])):
                    with self.assertRaises(SyncError) as error:
                        action()
                    self.assertEqual(error.exception.status_code, 503)

    def test_revoked_session_actor_or_deployment_refuses_before_funding_lookup(self):
        self.prepare()
        rows = self.rows()
        token = deepcopy(self.token)
        token["deployment_id"] = str(uuid.uuid4())
        self.refused(lambda: references.resolve_funding_references(rows, self.user, self.session, token), "device_revoked")
        token = deepcopy(self.token)
        token["user_id"] = str(uuid.uuid4())
        self.refused(lambda: references.resolve_funding_references(rows, self.user, self.session, token), "foreign_actor")
        self.session.revoked_at = timezone.now()
        self.session.save(update_fields=["revoked_at"])
        with patch.object(references, "_sources", side_effect=AssertionError("Must not query funds")):
            self.refused(self.catalog, "device_revoked")
            self.refused(lambda: self.resolve(rows), "device_revoked")

    def test_late_owner_permission_loss_cannot_release_catalog_or_private_resolution(self):
        self.prepare()
        rows = self.rows()
        original = references._access
        for action in (self.catalog, lambda: self.resolve(rows), self.prepare):
            self.role(RoleChoices.DIRECTOR)
            before = self.snapshot()
            count = 0
            def downgrade(*args):
                nonlocal count
                count += 1
                if count == 3:
                    self.role(RoleChoices.FARM_MANAGER)
                return original(*args)
            with patch.object(references, "_access", side_effect=downgrade):
                self.refused(action, "financial_reference_scope_changed")
            self.assertEqual(self.snapshot(), before)

    def test_preparation_failure_on_second_identity_leaves_no_partial_mapping(self):
        extra = self.extra()
        original = references._check_mapping
        count = 0
        def fail(*args):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("Synthetic preparation crash")
            return original(*args)
        before = self.snapshot()
        with patch.object(references, "_check_mapping", side_effect=fail), self.assertRaises(RuntimeError):
            self.prepare([self.source, extra])
        self.assertEqual(self.snapshot(), before)

    def test_private_resolution_does_not_bypass_original_dated_payment_service(self):
        self.prepare()
        command = self.command()
        for invoice in command["payload"]["invoices"]:
            for line in invoice["lines"]:
                line["funding_allocations"] = self.resolve(self.rows(amount=line["amount"]))
        accepted = self.execute(command)
        self.assertEqual(accepted["outcome"], "accepted")
        self.assertEqual(sum(FundingAllocation.objects.values_list("amount", flat=True)), Decimal("150.00"))
        before = self.snapshot()
        # The resolver still grants no spendable cash; the posting boundary
        # rejects another 150.00 against the remaining confirmed 50.00.
        fresh = deepcopy(command)
        fresh["operation_id"] = str(uuid.uuid4())
        fresh["payload"]["external_reference"] = "SYNTHETIC-SECOND-TRANSFER"
        result = self.execute(fresh)
        self.assertEqual(result["outcome"], "validation_failed")
        self.assertEqual(self.snapshot()["finance"], before["finance"])
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 12)), Decimal("50.00"))

    def test_private_gate_advertises_no_http_route_upload_or_operational_finance(self):
        self.prepare()
        response = self.client.get(BASE + "finance/funding-sources")
        self.assertEqual(response.status_code, 404)
        response = self.client.get(BASE + "capabilities")
        self.assertFalse(response.data["commands"]["finance"]["available"])
        self.assertEqual(SyncOperationReceipt.objects.count(), 0)

    def test_unsupported_future_types_do_not_expand_catalog_or_schema(self):
        future = self.extra()
        corrupt_inventory(FundingSource, future.pk, source_type="future-financial-source")
        self.prepare()
        self.assertEqual(len(self.catalog()["rows"]), 1)
        self.refused(lambda: self.prepare([future]), "funding_reference_unavailable")
        self.assertEqual(set(wire.SOURCE_TYPES), set(FundingSourceType.values))

    def test_large_integer_source_id_remains_private_exact_text_not_javascript_number(self):
        with sync_boundary():
            large = FundingSource.objects.create(pk=9007199254740993, source_type=FundingSourceType.LOAN,
                description="Synthetic large private identity")
        self.prepare([self.source, large])
        selected = self.rows(large)
        self.assertEqual(self.resolve(selected)[0]["funding_source"], "9007199254740993")
        self.assertNotIn("9007199254740993", canonical(self.catalog()))

    def test_deleted_source_pk_reuse_cannot_adopt_original_mapping(self):
        extra = self.extra()
        self.prepare([self.source, extra])
        selected = self.rows(extra)
        original_pk, original_created = extra.pk, extra.created_at
        with sync_boundary():
            extra.delete()
        self.refused(lambda: self.resolve(selected), "funding_reference_unavailable")
        with sync_boundary():
            recreated = FundingSource.objects.create(pk=original_pk, source_type=FundingSourceType.LOAN,
                description="Synthetic loan selection")
        self.assertNotEqual(recreated.created_at, original_created)
        self.refused(self.catalog, "funding_reference_review_required")
        self.refused(lambda: self.prepare([recreated]), "funding_reference_review_required")
        self.refused(lambda: self.resolve(selected), "funding_reference_review_required")

    def test_resolution_does_not_take_cash_locks_ahead_of_period_and_payable_locks(self):
        self.prepare()
        selected = self.rows()
        with CaptureQueriesContext(connection) as queries:
            self.resolve(selected)
        funding_queries = [row["sql"] for row in queries if '"finance_fundingsource"' in row["sql"]]
        self.assertTrue(funding_queries)
        self.assertTrue(all("FOR UPDATE" not in sql for sql in funding_queries))
        self.assertTrue(any("FOR UPDATE" in row["sql"] and '"mobile_sync_syncstreamstate"' in row["sql"] for row in queries))

    def test_operational_capability_and_frozen_bootstrap_do_not_expand_with_financial_mapping(self):
        before = self.client.get(BASE + "capabilities").data
        first = self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": ["operational-current-v1"]}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        self.prepare()
        after = self.client.get(BASE + "capabilities").data
        for response in (before, after):
            response.pop("server_time")
        self.assertEqual(before, after)
        second = self.client.post(BASE + "bootstrap", {"protocol_version": 1, "packs": ["operational-current-v1"]}, format="json")
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["snapshot_id"], second.data["snapshot_id"])
        self.assertEqual(first.data["manifest"], second.data["manifest"])
        self.assertNotIn(references.ENTITY_TYPE, canonical(second.data))

    def test_reference_catalog_does_not_depend_on_or_enable_new_payment_posting(self):
        self.prepare()
        with override_settings(MOBILE_SYNC_FINANCIAL_COMMANDS=False, FINANCE_INVENTORY_INVOICES=False):
            page = self.catalog()
            self.assertFalse(page["financial_uploads"])
            self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(SyncOperationReceipt.objects.count(), 0)


@override_settings(**SETTINGS)
class FinancialFundingReferenceConcurrencyTests(BridgeFixture, TransactionTestCase):
    def prepare(self):
        return references.prepare_funding_references([str(self.source.pk)], self.user, self.session, self.token)

    def test_concurrent_preparation_creates_one_stable_metadata_identity_no_money(self):
        before = proof.snapshot()
        def prepare():
            result = self.prepare()
            return None, "created" if result["created"] else "existing"
        self.assertCountEqual(proof.race(self, [prepare, prepare]), ["created", "existing"])
        self.assertEqual(SyncEntity.objects.filter(entity_type=references.ENTITY_TYPE).count(), 1)
        self.assertEqual(proof.snapshot(), before)

    def test_owner_access_removed_during_real_stream_wait_is_rechecked_before_lookup(self):
        self.prepare()
        started, results, pids = Event(), [], []
        original = references._access
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
                results.append(references.funding_reference_catalog(self.user, self.session, self.token))
            except SyncError as error:
                results.append(error.status_code)
            finally:
                close_old_connections()
        with patch.object(references, "_access", side_effect=authorized), sync_boundary():
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
            self.assertTrue(waiting, "Second PostgreSQL connection must really wait for stream")
            get_user_model().objects.filter(pk=self.user.pk).update(is_superuser=False)
            role, _ = Role.objects.get_or_create(slug=RoleChoices.GENERAL_WORKER, defaults={"name": "Synthetic worker"})
            self.user.roles.add(role)
        worker.join(25)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [403])
        self.assertFalse(FundingAllocation.objects.exists())
        self.assertFalse(SyncOperationReceipt.objects.exists())
