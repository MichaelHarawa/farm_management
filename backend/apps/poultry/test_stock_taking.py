from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.finance.models import AccountingPeriod, PeriodStatus
from apps.finance.services.profitability import batch_profitability
from apps.poultry.models import Batch, BirdStockTake, FlockAdjustment, InputCosts, Mortality
from apps.poultry.services.batch_lifecycle import calculate_bird_balance, create_sale_with_lifecycle
from apps.poultry.services.feed_metrics import live_birds_at
from apps.poultry.services.stock_taking import record_stock_take


def make_batch(user):
    arrival = timezone.now() - timedelta(days=14)
    return Batch.objects.create(
        quantity=100, entry_date=arrival, expected_maturity_date=arrival + timedelta(days=42),
        created_by=user,
    )


@override_settings(MOBILE_SYNC_CAPTURE=False)
class StockTakingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="stock-manager")
        self.user.roles.add(Role.objects.get(slug="farm_manager"))
        self.batch = make_batch(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = f"/api/v1/poultry-management/{self.batch.pk}/stock-takes"

    def payload(self):
        return dict(request_id=str(uuid4()), expected_live_birds=100, physical_count=95,
                    reason="Five birds missing after counting all pens", notes="")

    def record(self, **overrides):
        payload = self.payload()
        payload.update(overrides)
        return record_stock_take(batch_id=self.batch.pk, recorded_by=self.user, **payload)

    def test_shortage_is_a_separate_adjustment_and_reduces_available_birds(self):
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["shortage"], 5)
        self.assertEqual(response.data["variance"], -5)
        adjustment = FlockAdjustment.objects.get(pk=response.data["adjustment"])
        self.assertEqual(adjustment.quantity_change, -5)
        self.assertEqual(adjustment.approved_by, self.user)
        self.assertFalse(Mortality.objects.exists())
        self.assertEqual(calculate_bird_balance(self.batch).remaining_live_birds, 95)
        self.assertEqual(live_birds_at(self.batch, timezone.now()), 95)
        summary = self.client.get(self.url).data
        self.assertEqual(summary["expected_live_birds"], 95)
        self.assertEqual(summary["records"][0]["recorded_by_name"], self.user.username)
        self.assertEqual(summary["records"][0]["expected_live_birds"], 100)

    def test_shortage_preserves_cost_and_increases_cost_per_saleable_bird(self):
        InputCosts.objects.create(
            batch=self.batch, item="Chicks", category="chicks", quantity=100,
            unit=1, unit_cost=Decimal("10"), unit_measurement="kg",
            purchase_date=self.batch.entry_date, created_by=self.user,
        )
        before = batch_profitability(self.batch)
        self.record(physical_count=80)
        after = batch_profitability(self.batch)
        self.assertEqual(after["total_attributed_cost"], before["total_attributed_cost"])
        self.assertEqual(after["management_net_position"], before["management_net_position"])
        self.assertEqual(after["provisional_cost_per_saleable_bird"], Decimal("12.50"))

    def test_matching_count_retains_evidence_without_an_adjustment(self):
        record = self.record(physical_count=100, reason="")
        self.assertEqual(record.variance, 0)
        self.assertIsNone(record.adjustment)
        self.assertFalse(FlockAdjustment.objects.exists())

    def test_surplus_requires_reason_and_increases_balance(self):
        with self.assertRaises(ValidationError):
            self.record(physical_count=103, reason=" ")
        record = self.record(physical_count=103, reason="Recount found birds in another pen")
        self.assertEqual(record.variance, 3)
        self.assertEqual(record.shortage, 0)
        self.assertEqual(calculate_bird_balance(self.batch).remaining_live_birds, 103)

    def test_repeated_request_is_one_count_and_one_adjustment(self):
        payload = self.payload()
        for _ in range(3):
            response = self.client.post(self.url, payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(BirdStockTake.objects.count(), 1)
        self.assertEqual(FlockAdjustment.objects.count(), 1)
        payload["physical_count"] = 94
        self.assertEqual(self.client.post(self.url, payload, format="json").status_code, 400)
        self.assertEqual(calculate_bird_balance(self.batch).remaining_live_birds, 95)

    def test_stale_count_cannot_apply_a_second_shortage(self):
        self.record()
        with self.assertRaisesMessage(ValidationError, "Live birds changed to 95"):
            self.record(physical_count=90)
        self.assertEqual(BirdStockTake.objects.count(), 1)
        self.assertEqual(FlockAdjustment.objects.count(), 1)

    def test_second_count_uses_adjusted_balance_and_preserves_history(self):
        first = self.record()
        second = self.record(expected_live_birds=95, physical_count=92)
        self.assertEqual(second.shortage, 3)
        first.refresh_from_db()
        self.assertEqual(first.expected_live_birds, 100)
        self.assertEqual(first.physical_count, 95)
        self.assertEqual(calculate_bird_balance(self.batch).remaining_live_birds, 92)

    def test_all_missing_closes_batch_and_retry_is_still_successful(self):
        payload = self.payload()
        payload["physical_count"] = 0
        for _ in range(2):
            response = self.client.post(self.url, payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "closed")
        self.assertEqual(BirdStockTake.objects.count(), 1)

    def test_invalid_counts_and_unexplained_shortages_leave_no_writes(self):
        for changes in ({"physical_count": -1}, {"physical_count": 2.5},
                        {"physical_count": True}, {"reason": ""}):
            payload = self.payload()
            payload.update(changes)
            response = self.client.post(self.url, payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BirdStockTake.objects.exists())
        self.assertFalse(FlockAdjustment.objects.exists())

    def test_only_supervisors_can_confirm_counts(self):
        for role in ("general_worker", "stake_holder"):
            self.user.roles.set([Role.objects.get(slug=role)])
            response = self.client.post(self.url, self.payload(), format="json")
            self.assertEqual(response.status_code, 403, response.data)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 401)
        self.assertFalse(BirdStockTake.objects.exists())

    def test_counts_rejected_for_unavailable_and_finalized_batches(self):
        for status in ("booked", "planned", "delivered", "closed"):
            Batch.objects.filter(pk=self.batch.pk).update(status=status)
            self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
        Batch.objects.filter(pk=self.batch.pk).update(status="active", profitability_finalized_at=timezone.now())
        self.assertEqual(self.client.post(self.url, self.payload(), format="json").status_code, 400)
        self.assertFalse(BirdStockTake.objects.exists())

    def test_closed_period_blocks_count(self):
        today = timezone.localdate()
        AccountingPeriod.objects.create(
            period_start=today, period_end=today, status=PeriodStatus.CLOSED,
        )
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(BirdStockTake.objects.exists())

    def test_sales_cannot_sell_birds_recorded_missing(self):
        self.record()
        with self.assertRaises(ValidationError):
            create_sale_with_lifecycle(
                batch_id=self.batch.pk, created_by=self.user, sale_date=timezone.now(),
                product_type="live_chicken", quantity_sold=96, unit_price=Decimal("10"),
                buyer_name="Buyer", buyer_type="retail", payment_status="unpaid",
                payment_method="credit", amount_paid=Decimal("0"), sold_by_name="Manager",
                receivable_follow_up_name="Manager", notes="Stock guard",
            )
        self.assertFalse(self.batch.sales_row.exists())


@override_settings(MOBILE_SYNC_CAPTURE=False)
class StockTakingConcurrencyTests(TransactionTestCase):
    def test_competing_counts_cannot_overwrite_a_new_balance(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-lock behavior requires PostgreSQL")
        user = get_user_model().objects.create_user(username="concurrent-counter")
        batch = make_batch(user)
        barrier = Barrier(2)

        def count(physical):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                record_stock_take(
                    batch_id=batch.pk, recorded_by=user, request_id=uuid4(),
                    expected_live_birds=100, physical_count=physical, reason="Pen recount",
                )
                return "saved"
            except ValidationError:
                return "stale"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(count, (95, 90)))
        self.assertCountEqual(results, ["saved", "stale"])
        self.assertEqual(BirdStockTake.objects.count(), 1)
        self.assertEqual(FlockAdjustment.objects.count(), 1)
