from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.finance.models import (
    AccountingPeriod,
    AdHocLabourPayment,
    Asset,
    AssetCategory,
    AssetDepreciationEntry,
    AssetLifecycleEvent,
    CostScope,
    Expenditure,
    JournalEntry,
    StockMovement,
)
from apps.finance.serializers import AssetSerializer
from apps.finance.services.consumables import record_consumable_receipt, record_consumable_usage
from apps.finance.services.labour import approve_labour, post_labour
from apps.poultry.models import Batch, ChicksSource


def aware(day):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


class PriorityFiveToNineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="priority-manager", email="priority@example.com", password="password"
        )
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 10, 1), period_end=date(2026, 10, 31)
        )
        self.batch = Batch.objects.create(
            batch_id="PRIORITY-BATCH", bird_type="broilers", source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 10, 1)), expected_maturity_date=aware(date(2026, 11, 12)),
            quantity=100, created_by=self.user,
        )

    def test_labour_approval_and_post_create_exactly_one_payable(self):
        labour = AdHocLabourPayment.objects.create(
            worker_name="Worker", task_description="Clean poultry house", work_date=date(2026, 10, 3),
            payment_amount=Decimal("2500.00"), cost_scope=CostScope.BATCH_DIRECT,
            batch=self.batch, accounting_period=self.period, created_by=self.user,
        )
        approve_labour(labour_id=labour.pk, user=self.user)
        posted = post_labour(labour_id=labour.pk, user=self.user)
        self.assertEqual(posted.workflow_status, "posted")
        self.assertEqual(Expenditure.objects.filter(labour_source=posted).count(), 1)
        self.assertEqual(post_labour.__name__, "post_labour")

    def test_consumable_receipt_and_issue_post_stock_and_ledger_once(self):
        lot = record_consumable_receipt(
            created_by=self.user, item="Starter feed", category="Feed", purchase_date=date(2026, 10, 2),
            quantity_purchased=Decimal("10.0000"), unit_of_measurement="kg",
            total_purchase_cost=Decimal("10000.00"), storage_location="Main Store",
        )
        usage = record_consumable_usage(
            recorded_by=self.user, consumable_lot=lot, usage_date=date(2026, 10, 4),
            accounting_period=self.period, quantity_used=Decimal("2.0000"), batch=self.batch,
            usage_scope="batch_direct", allocation_driver="direct", task_or_purpose="Daily feed",
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity_available, Decimal("8.0000"))
        self.assertEqual(StockMovement.objects.filter(lot=lot).count(), 2)
        self.assertEqual(JournalEntry.objects.filter(source_identifier=str(usage.pk), source_model="finance.ConsumableUsage").count(), 1)

    def test_asset_financial_fields_lock_after_depreciation_and_events_are_immutable(self):
        category = AssetCategory.objects.create(
            name="Test equipment", code="feeding_equipment", default_useful_life_months=60
        )
        asset = Asset.objects.create(
            name="Feeder", asset_category=category, purchase_date=date(2026, 10, 1),
            available_for_use_date=date(2026, 10, 1), purchase_price=Decimal("100000.00"),
            useful_life_months=60,
        )
        AssetDepreciationEntry.objects.create(
            asset=asset, accounting_period=self.period, opening_carrying_amount=Decimal("100000.00"),
            depreciation_method_snapshot="straight_line", useful_life_snapshot=60,
            residual_value_snapshot=Decimal("0.00"), period_depreciation=Decimal("1666.67"),
            closing_carrying_amount=Decimal("98333.33"),
        )
        serializer = AssetSerializer(asset, data={"purchase_price": "90000.00"}, partial=True)
        self.assertFalse(serializer.is_valid())
        event = AssetLifecycleEvent.objects.create(
            asset=asset, event_type="maintenance", event_date=date(2026, 10, 5), details={}
        )
        with self.assertRaises(Exception):
            event.delete()

    def test_revenue_utilization_summary_is_paginated_without_n_plus_one(self):
        for number in range(25):
            Batch.objects.create(
                batch_id=f"PAGE-{number}", bird_type="broilers", source=ChicksSource.PROTO,
                entry_date=aware(date(2026, 10, 1)), expected_maturity_date=aware(date(2026, 11, 12)), quantity=10,
            )
        client = APIClient()
        client.force_authenticate(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = client.get("/api/v1/finance/reports/revenue-utilization?page=1&page_size=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 10)
        self.assertLessEqual(len(queries), 8)
