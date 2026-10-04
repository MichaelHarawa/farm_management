from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Thread
import uuid

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.finance.models import AccountingPeriod, JournalEntry
from apps.mobile_sync.models import SyncChange, SyncEntity, SyncOperationReceipt
from apps.mobile_sync.projections import POULTRY_PACK, TYPES, json_value
from apps.mobile_sync.writers import UnsafeSyncWrite, sync_boundary
from apps.poultry.models import (Batch, BatchWeightSample, DrugsVaccination, FeedUsage,
                                 FlockAdjustment, FlockAdjustmentProposal, Sales)
from apps.poultry.services.feed_metrics import create_flock_adjustment, feed_summary
from apps.poultry.services.operations import record_weight
from .test_sync import BASE, TEST_SETTINGS, FixtureMixin

V2 = {**TEST_SETTINGS, "MOBILE_SYNC_POULTRY_V2": True}


class PoultryFixture(FixtureMixin):
    def setUp(self):
        self.make_fixture()
        self.supervisor = self.users["farm_supervisor"]
        self.manager_client, self.manager_registration = self.register(self.supervisor)
        self.manager_client.defaults["HTTP_X_MOBILE_POULTRY_VERSION"] = "2"
        self.client.defaults["HTTP_X_MOBILE_POULTRY_VERSION"] = "2"

    def operation(self, kind, payload, action="record", entity_uuid=None, revision=None, dependencies=None):
        return {"operation_id": str(uuid.uuid4()), "entity_uuid": entity_uuid or str(uuid.uuid4()),
                "entity_type": kind, "action": action, "payload_version": 1, "base_version": revision,
                "captured_at": json_value(timezone.now()), "depends_on": dependencies or [], "payload": payload}

    def fields(self, kind):
        at = json_value(self.arrival + timedelta(days=1))
        common = {"batch_uuid": self.batch_uuid, "reported_by_name": "Observed worker"}
        return {
            "poultry.feed_usage": {**common, "feeding_start_date": at, "feeding_end_date": at,
                "quantity_given": 1500, "unit_of_measurement": "g", "feed_type": "starter", "feed_source": "cp_feed", "notes": "Weighed"},
            "poultry.treatment": {**common, "vaccination_date": at, "drug_category": "vaccination", "drug_vaccination_type": "other",
                "other_drug_vaccination": "Test evidence only", "quantity": 1, "description": "Recorded unit: vial", "timely_status": "Recorded as observed"},
            "poultry.weight_sample": {**common, "sampled_at": at, "sample_size": 10, "average_weight_g": 75, "notes": "Sampled birds"},
            "poultry.adjustment_proposal": {"batch_uuid": self.batch_uuid, "effective_at": at, "quantity_change": -2, "reason": "Count evidence"},
        }[kind]

    def manager_push(self, operation):
        response = self.push(operation, self.manager_client, self.manager_registration)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data["results"][0]


@override_settings(**V2)
class PoultryCommandTests(PoultryFixture, TestCase):
    def test_each_new_append_replays_twenty_times_with_one_effect_and_exact_hash(self):
        for kind in ["poultry.feed_usage", "poultry.treatment", "poultry.weight_sample", "poultry.adjustment_proposal"]:
            operation = self.operation(kind, self.fields(kind), "propose" if "proposal" in kind else "record")
            accepted = self.manager_push(operation)
            self.assertEqual(accepted["outcome"], "accepted", accepted)
            receipt = SyncOperationReceipt.objects.get(operation_id=operation["operation_id"])
            for _ in range(20):
                replay = self.manager_push(operation)
                self.assertEqual(replay["outcome"], "replayed")
                self.assertEqual(replay["transaction_id"], accepted["transaction_id"])
            receipt.refresh_from_db()
            self.assertEqual(receipt.command["payload"], operation["payload"])
            changed = deepcopy(operation)
            changed["captured_at"] = json_value(timezone.now())
            self.assertEqual(self.manager_push(changed)["code"], "idempotency_mismatch")
        self.assertEqual(FeedUsage.objects.count(), 2)
        self.assertEqual(DrugsVaccination.objects.count(), 1)
        self.assertEqual(BatchWeightSample.objects.count(), 1)
        self.assertEqual(FlockAdjustmentProposal.objects.count(), 1)
        self.assertEqual(FlockAdjustment.objects.count(), 0)
        self.assertEqual(JournalEntry.objects.count(), 0)
        self.assertEqual(feed_summary(self.batch)["total_feed_kg"], Decimal("11.500"))

    def test_offline_booking_delivery_and_child_dependency_replay(self):
        arrival = self.arrival + timedelta(days=1)
        book = self.operation("poultry.batch", {"bird_type": "broilers", "broiler_strain": "ross308", "source": "central_poultry",
            "booking_date": self.arrival.date().isoformat(), "estimated_chick_arrival_date": arrival.date().isoformat(),
            "expected_quantity": 120, "entry_date": json_value(arrival), "expected_maturity_date": json_value(arrival + timedelta(days=46))}, "book")
        delivered = self.operation("poultry.batch", {"batch_uuid": book["entity_uuid"]}, "mark_delivered",
            book["entity_uuid"], dependencies=[book["operation_id"]])
        confirmed = self.operation("poultry.batch", {"batch_uuid": book["entity_uuid"], "entry_date": json_value(arrival), "quantity": 100},
            "confirm_delivery", book["entity_uuid"], dependencies=[delivered["operation_id"]])
        feed = self.operation("poultry.feed_usage", {**self.fields("poultry.feed_usage"), "batch_uuid": book["entity_uuid"]},
            dependencies=[confirmed["operation_id"]])
        blocked = self.manager_push(feed)
        self.assertEqual(blocked["outcome"], "dependency_blocked")
        response = self.manager_client.post(BASE + "push", {"protocol_version": 1, "device_id": self.manager_registration["device_id"],
            "operations": [feed, confirmed, delivered, book]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([r["outcome"] for r in response.data["results"]], ["accepted"] * 4, response.data)
        mapping = SyncEntity.objects.get(entity_uuid=book["entity_uuid"])
        self.assertEqual(mapping.payload["expected_quantity"], 120)
        self.assertEqual(mapping.payload["actual_quantity_received"], 100)
        for operation in [book, delivered, confirmed, feed]:
            self.assertEqual(self.manager_push(operation)["outcome"], "replayed")
        self.assertEqual(Batch.objects.count(), 2)
        self.assertEqual(FeedUsage.objects.count(), 2)

    def test_undelivered_event_and_revision_conflict_are_retained(self):
        with sync_boundary():
            self.batch.status = "delivered"
            self.batch.save()
        op = self.operation("poultry.weight_sample", self.fields("poultry.weight_sample"))
        rejected = self.manager_push(op)
        self.assertEqual(rejected["outcome"], "validation_failed")
        self.assertIn("delivery", str(rejected["field_errors"]).lower())
        operation = self.operation("poultry.batch", {"batch_uuid": self.batch_uuid, "entry_date": json_value(self.arrival), "quantity": 100},
            "confirm_delivery", self.batch_uuid, revision="9999")
        self.assertEqual(self.manager_push(operation)["code"], "revision_conflict")
        self.assertEqual(BatchWeightSample.objects.count(), 0)

    def test_proposal_does_not_change_balance_and_online_approval_is_once(self):
        propose = self.operation("poultry.adjustment_proposal", self.fields("poultry.adjustment_proposal"), "propose")
        self.assertEqual(self.manager_push(propose)["outcome"], "accepted")
        self.assertEqual(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload["remaining_birds"], 100)
        proposal = SyncEntity.objects.get(entity_uuid=propose["entity_uuid"])
        approve = self.operation("poultry.adjustment_proposal", {"reason": "Verified count online"}, "approve",
            propose["entity_uuid"], revision=str(proposal.revision))
        self.assertEqual(self.manager_push(approve)["code"], "online_confirmation_required")
        self.assertFalse(SyncOperationReceipt.objects.filter(operation_id=approve["operation_id"]).exists())
        for i in range(21):
            response = self.manager_client.post(BASE + "poultry-online", approve, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["outcome"], "accepted" if i == 0 else "replayed", response.data)
        self.assertEqual(FlockAdjustment.objects.count(), 1)
        self.assertEqual(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload["remaining_birds"], 98)
        self.feed.refresh_from_db()
        self.assertEqual(self.feed.current_number_of_birds, 98)

    def test_negative_backdate_checks_later_feed_and_weights(self):
        with sync_boundary():
            record_weight(batch_id=self.batch.pk, created_by=self.worker, sampled_at=self.arrival + timedelta(days=3),
                sample_size=20, average_weight_g=100, reported_by_name="Worker")
        with self.assertRaises(ValidationError), sync_boundary():
            create_flock_adjustment(batch_id=self.batch.pk, approved_by=self.supervisor, effective_at=self.arrival + timedelta(hours=1),
                quantity_change=-90, reason="Would invalidate later sample")
        self.assertEqual(FlockAdjustment.objects.count(), 0)
        self.assertEqual(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload["remaining_birds"], 100)
        self.assertEqual(self.push(self.command(90)).data["results"][0]["code"], "insufficient_birds")

    def test_legacy_pack_fields_and_types_remain_unchanged(self):
        self.assertEqual(self.manager_push(self.operation("poultry.treatment", self.fields("poultry.treatment")))["outcome"], "accepted")
        self.client.defaults.pop("HTTP_X_MOBILE_POULTRY_VERSION")
        manifest, rows, cursor = self.snapshot()
        self.assertEqual({r["entity_type"] for r in rows}, {"poultry.batch", "poultry.feed_usage"})
        self.assertNotIn("operational_summary", next(r for r in rows if r["entity_type"] == "poultry.batch")["payload"])
        self.assertEqual(self.client.get(BASE + "capabilities").data["projection_version"], 1)
        _, v2, _ = self.snapshot(self.manager_client, [POULTRY_PACK])
        self.assertIn("poultry.treatment", {r["entity_type"] for r in v2})
        data = self.client.get(BASE + "changes", {"cursor": cursor}).data
        self.assertTrue(data["run_complete"])
        self.assertFalse(data["changes"])

    def test_legacy_writer_does_not_require_new_proposal_table_before_opt_in(self):
        from unittest.mock import patch
        self.client.defaults.pop('HTTP_X_MOBILE_POULTRY_VERSION')
        with override_settings(MOBILE_SYNC_POULTRY_V2=False),patch.object(FlockAdjustmentProposal.objects,'filter',side_effect=AssertionError('Legacy writer queried Phase5 table')):
            self.assertEqual(self.push(self.command(1)).data['results'][0]['outcome'],'accepted')

    def test_strict_roles_stock_and_source_constraints(self):
        op = self.operation("poultry.feed_usage", self.fields("poultry.feed_usage"))
        for key, value in [("quantity_given", "1500"), ("unit_of_measurement", "tonnes"), ("stock_issue", {})]:
            bad = deepcopy(op)
            bad["payload"][key] = value
            self.assertEqual(self.push(bad).status_code, 400)
        self.assertEqual(self.push(op).data["results"][0]["outcome"], "accepted")
        proposal = self.operation("poultry.adjustment_proposal", self.fields("poultry.adjustment_proposal"), "propose")
        self.assertEqual(self.push(proposal).data["results"][0]["outcome"], "permission_denied")
        self.assertEqual(FlockAdjustmentProposal.objects.count(), 0)
        with override_settings(MOBILE_SYNC_POULTRY_V2=False):
            self.assertEqual(self.client.get(BASE + "capabilities").status_code, 409)

    def test_projection_missing_growth_configured_threshold_and_arrival_denominator(self):
        mapping = SyncEntity.objects.get(entity_uuid=self.batch_uuid)
        summary = mapping.payload["operational_summary"]
        self.assertEqual(summary["growth"]["state"], "missing_sample")
        self.assertIsNone(summary["fcr"])
        self.assertEqual(summary["feed_denominator_birds"], 100)
        with sync_boundary():
            self.batch.bird_type, self.batch.broiler_strain = "layers", ""
            self.batch.actual_quantity_received = 80
            self.batch.save()
        self.assertEqual(self.manager_push(self.operation("poultry.weight_sample", self.fields("poultry.weight_sample")))["outcome"], "accepted")
        self.assertEqual(self.push(self.command(8)).data["results"][0]["outcome"], "accepted")
        mapping.refresh_from_db()
        summary = mapping.payload["operational_summary"]
        self.assertEqual(summary["growth"]["state"], "target_not_applicable")
        self.assertEqual(summary["mortality"]["rate_percent"], "10.00")
        self.assertTrue(summary["mortality"]["alert"])
        self.assertEqual(summary["feed_denominator_birds"], 80)

    def test_new_writers_publish_delete_and_reject_unsafe_bulk(self):
        op = self.operation("poultry.weight_sample", self.fields("poultry.weight_sample"))
        self.assertEqual(self.manager_push(op)["outcome"], "accepted")
        with self.assertRaises(UnsafeSyncWrite):
            BatchWeightSample.objects.bulk_create([])
        with sync_boundary():
            BatchWeightSample.objects.get().delete()
        self.assertTrue(SyncEntity.objects.get(entity_uuid=op["entity_uuid"]).deleted)
        self.assertTrue(SyncChange.objects.filter(entity_uuid=op["entity_uuid"], kind="tombstone").exists())

    def test_ordinary_treatment_weight_and_feed_writers_publish_same_revisions(self):
        from rest_framework.test import APIClient
        ordinary=APIClient();ordinary.force_authenticate(self.supervisor)
        for kind, route in [('poultry.treatment','drugs_vaccine'),('poultry.weight_sample','weight_samples'),('poultry.feed_usage','feed_usage')]:
            data=self.fields(kind);data.pop('batch_uuid')
            if kind=='poultry.weight_sample':data['age_in_days']=999  # The shared service must derive, not trust it.
            if kind=='poultry.feed_usage':data['initial_age']=999
            with sync_boundary():
                response=ordinary.post(f'/api/v1/poultry-management/{self.batch.pk}/{route}',data,format='json')
            self.assertEqual(response.status_code,201,response.data)
            mapping=SyncEntity.objects.get(entity_type=kind,source_pk=str(response.data['id']))
            if kind=='poultry.weight_sample':self.assertEqual(mapping.payload['age_in_days'],1)
            if kind=='poultry.feed_usage':self.assertEqual(mapping.payload['initial_age'],1)
            self.assertTrue(SyncChange.objects.filter(entity_uuid=mapping.entity_uuid).exists())
            _,rows,_=self.snapshot(self.manager_client,[POULTRY_PACK])
            self.assertIn(str(mapping.entity_uuid),[r['entity_uuid'] for r in rows])
        self.assertEqual(JournalEntry.objects.count(),0)

    def test_cancelled_sales_eggs_manure_actual_arrivals_and_adjustments_reconcile(self):
        from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle,calculate_bird_balance
        at=self.arrival+timedelta(days=1)
        for product,status,qty in [('live_chicken','cancelled',999),('eggs','unpaid',1000),('manure','unpaid',1000),('dressed_chicken','unpaid',10)]:
            with sync_boundary():
                create_sale_with_lifecycle(batch_id=self.batch.pk,created_by=self.supervisor,sale_date=at,product_type=product,quantity_sold=qty,
                    unit_price=Decimal('0.00'),buyer_name='Synthetic buyer',buyer_type='retail',payment_status=status,payment_method='cash',
                    amount_paid=Decimal('0.00'),sold_by_name='Observed worker',notes='Synthetic evidence')
        with sync_boundary():
            create_flock_adjustment(batch_id=self.batch.pk,approved_by=self.supervisor,effective_at=at,quantity_change=5,reason='Verified arrivals')
        self.assertEqual(calculate_bird_balance(self.batch).remaining_live_birds,95)
        self.feed.refresh_from_db();self.assertEqual(self.feed.current_number_of_birds,95)
        mapping=SyncEntity.objects.get(entity_uuid=self.batch_uuid)
        self.assertEqual(mapping.payload['sold_bird_count'],10)
        self.assertEqual(mapping.payload['approved_adjustment_count'],5)
        self.assertEqual(mapping.payload['operational_summary']['feed_denominator_birds'],100)
        self.assertEqual(JournalEntry.objects.count(),0)

    def test_backdated_web_sale_cannot_invalidate_later_sample(self):
        from rest_framework.test import APIClient
        ordinary=APIClient();ordinary.force_authenticate(self.supervisor)
        with sync_boundary():
            record_weight(batch_id=self.batch.pk,created_by=self.worker,sampled_at=self.arrival+timedelta(days=3),sample_size=20,
                average_weight_g=100,reported_by_name='Worker')
        with sync_boundary():
            response=ordinary.post(f'/api/v1/poultry-management/{self.batch.pk}/sales',{
            'sale_date':json_value(self.arrival+timedelta(hours=1)),'product_type':'live_chicken','quantity_sold':90,'unit_price':'0.00',
            'buyer_name':'Synthetic buyer','buyer_type':'retail','payment_status':'unpaid','payment_method':'cash','amount_paid':'0.00',
            'sold_by_name':'Observed worker','notes':'Must not invalidate later sample'},format='json')
        self.assertEqual(response.status_code,400,response.data)
        self.assertIn('quantity_sold',response.data)
        self.assertEqual(Sales.objects.count(),0)

    def test_closed_period_retains_proposal_but_refuses_original_date_approval(self):
        from apps.finance.models import PeriodStatus
        operation=self.operation('poultry.adjustment_proposal',self.fields('poultry.adjustment_proposal'),'propose')
        self.assertEqual(self.manager_push(operation)['outcome'],'accepted')
        day=(self.arrival+timedelta(days=1)).date()
        AccountingPeriod.objects.create(period_start=day,period_end=day,status=PeriodStatus.CLOSED)
        mapping=SyncEntity.objects.get(entity_uuid=operation['entity_uuid'])
        approval=self.operation('poultry.adjustment_proposal',{'reason':'Review original date'},'approve',operation['entity_uuid'],revision=str(mapping.revision))
        response=self.manager_client.post(BASE+'poultry-online',approval,format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['outcome'],'period_locked')
        self.assertEqual(FlockAdjustment.objects.count(),0)
        self.assertEqual(FlockAdjustmentProposal.objects.get().status,'pending')
        self.assertEqual(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload['remaining_birds'],100)

    def test_poultry_positive_wire_contracts_match_actual_requests_responses_and_caps(self):
        from jsonschema import Draft7Validator,FormatChecker
        from apps.mobile_sync import schema_poultry
        def converted(value):
            if isinstance(value,list):return [converted(item) for item in value]
            if not isinstance(value,dict):return value
            result={key:converted(item) for key,item in value.items() if key!='nullable'}
            if value.get('nullable'):
                return {'anyOf':[result,{'type':'null'}]}
            return result
        def validate(shape,value):Draft7Validator(converted(shape),format_checker=FormatChecker()).validate(value)
        validate(schema_poultry.capabilities_schema(),self.manager_client.get(BASE+'capabilities').data)
        for kind in ['poultry.feed_usage','poultry.treatment','poultry.weight_sample','poultry.adjustment_proposal']:
            operation=self.operation(kind,self.fields(kind),'propose' if 'proposal' in kind else 'record')
            validate(schema_poultry.operation_schema(),operation)
            receipt=self.manager_push(operation);validate(schema_poultry.RESULT,receipt)
        _,rows,_=self.snapshot(self.manager_client,[POULTRY_PACK])
        for row in rows:validate(schema_poultry.ENTITY,row)


@override_settings(**V2)
class PoultryConcurrencyTests(PoultryFixture, TransactionTestCase):
    def test_two_devices_competing_dated_events_leave_reviewable_rejection(self):
        second, registration = self.register(self.worker)
        second.defaults["HTTP_X_MOBILE_POULTRY_VERSION"] = "2"
        barrier, results, failures = Barrier(2), [], []
        commands = [self.command(60), self.command(60)]
        def capture(client, device, command):
            try:
                barrier.wait(timeout=10)
                results.append(self.push(command, client, device).data["results"][0])
            except Exception as error:
                failures.append(type(error).__name__)
            finally:
                connections.close_all()
        threads = [Thread(target=capture, args=args) for args in [
            (self.client, self.registration, commands[0]), (second, registration, commands[1])]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertFalse(failures)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sorted(r["outcome"] for r in results), ["accepted", "conflict"])
        self.assertEqual(SyncEntity.objects.get(entity_uuid=self.batch_uuid).payload["remaining_birds"], 40)
        self.assertEqual(SyncOperationReceipt.objects.count(), 2)
