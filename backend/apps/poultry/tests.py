from decimal import Decimal

from django.core.exceptions import ValidationError
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .models import (
    Batch, BuyerType, ChicksSource, FeedSource, FeedType, FeedUsage,
    Mortality, PaymentMethod, PaymentStatus, ProductType, Sales, UnitMeasurement,
)
from .serializers import SalesSerializer
from .services.batch_lifecycle import create_sale_with_lifecycle
from .services.feed_metrics import (
    bird_days_between, feed_summary, recalculate_feed_event_populations,
    record_feed_usage,
)


def sale_payload(**overrides):
    payload = {
        "sale_date": "2026-08-21T13:50:00+02:00",
        "product_type": "live_chicken",
        "quantity_sold": 2,
        "unit_price": "7500.00",
        "buyer_name": "Banda",
        "buyer_type": BuyerType.RETAIL,
        "payment_status": PaymentStatus.PARTIAL,
        "payment_method": "cash",
        "amount_paid": "5000.00",
        "sold_by_name": "Farm Manager",
        "notes": "Recorded through Farmnotes.",
    }
    payload.update(overrides)
    return payload


class SalesSerializerTests(SimpleTestCase):
    def test_paid_sale_does_not_require_amount_and_uses_sale_total(self):
        payload = sale_payload(payment_status=PaymentStatus.PAID)
        payload.pop("amount_paid")

        serializer = SalesSerializer(data=payload)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["amount_paid"],
            Decimal("15000.00"),
        )

    def test_non_paid_sale_requires_amount_paid(self):
        payload = sale_payload(payment_status=PaymentStatus.UNPAID)
        payload.pop("amount_paid")

        serializer = SalesSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("amount_paid", serializer.errors)

    def test_other_buyer_type_requires_and_preserves_manual_value(self):
        missing_other = SalesSerializer(
            data=sale_payload(buyer_type=BuyerType.OTHER)
        )
        self.assertFalse(missing_other.is_valid())
        self.assertIn("buyer_type_other", missing_other.errors)

        serializer = SalesSerializer(
            data=sale_payload(
                buyer_type=BuyerType.OTHER,
                buyer_type_other="  Restaurant  ",
            )
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["buyer_type_other"],
            "Restaurant",
        )

    def test_predefined_buyer_type_clears_manual_value(self):
        serializer = SalesSerializer(
            data=sale_payload(buyer_type_other="Should not persist")
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["buyer_type_other"], "")


class SalesModelTests(SimpleTestCase):
    def test_paid_status_synchronizes_amount_and_balance(self):
        sale = Sales(
            quantity_sold=2,
            unit_price=Decimal("7500.00"),
            payment_status=PaymentStatus.PAID,
            amount_paid=Decimal("0.00"),
            balance=Decimal("15000.00"),
        )

        sale.sync_payment_fields()

        self.assertEqual(sale.amount_paid, Decimal("15000.00"))
        self.assertEqual(sale.balance, Decimal("0.00"))
        self.assertEqual(sale.payment_status, PaymentStatus.PAID)

    def test_zero_total_paid_sale_remains_paid(self):
        sale = Sales(
            quantity_sold=2,
            unit_price=Decimal("0.00"),
            payment_status=PaymentStatus.PAID,
            amount_paid=Decimal("0.00"),
            balance=Decimal("0.00"),
        )

        sale.sync_payment_fields()

        self.assertEqual(sale.amount_paid, Decimal("0.00"))
        self.assertEqual(sale.balance, Decimal("0.00"))
        self.assertEqual(sale.payment_status, PaymentStatus.PAID)

    def test_other_buyer_type_requires_manual_value(self):
        sale = Sales(
            buyer_type=BuyerType.OTHER,
            buyer_type_other=" ",
            quantity_sold=1,
            unit_price=Decimal("1.00"),
            amount_paid=Decimal("0.00"),
            payment_status=PaymentStatus.UNPAID,
        )

        with self.assertRaises(ValidationError) as error:
            sale.clean()

        self.assertIn("buyer_type_other", error.exception.message_dict)


class DatedFeedMetricsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="feed-auditor")
        self.arrival = timezone.make_aware(datetime.combine(date(2026, 1, 1), time(hour=8)))
        self.batch = Batch.objects.create(
            batch_id="DATED-FEED-1",
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=self.arrival,
            expected_maturity_date=self.arrival + timedelta(days=35),
            quantity=200,
            actual_quantity_received=200,
            created_by=self.user,
        )

    def feed(self, at, quantity=100, stage=FeedType.STARTER, hours=24):
        return record_feed_usage(
            batch_id=self.batch.pk,
            created_by=self.user,
            initial_age=(at.date() - self.arrival.date()).days,
            feeding_start_date=at,
            feeding_end_date=at + timedelta(hours=hours),
            feed_type=stage,
            feed_source=FeedSource.PROTO_FEED,
            quantity_given=quantity,
            unit_of_measurement=UnitMeasurement.KGS,
            notes="Dated test",
            reported_by_name="Auditor",
        )

    def test_later_sales_do_not_divide_historical_feed_by_current_birds(self):
        record = self.feed(self.arrival + timedelta(days=1), quantity=100)
        create_sale_with_lifecycle(
            batch_id=self.batch.pk, created_by=self.user,
            sale_date=self.arrival + timedelta(days=5), product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=196, unit_price=Decimal("1.00"), buyer_name="Buyer",
            buyer_type=BuyerType.RETAIL, payment_status=PaymentStatus.UNPAID,
            payment_method=PaymentMethod.CASH, amount_paid=Decimal("0.00"),
            sold_by_name="Manager", notes="Later sale",
        )
        record.refresh_from_db()
        self.assertEqual(record.current_number_of_birds, 200)
        self.assertEqual(record.feed_per_live_bird_at_event, Decimal("0.5000"))
        self.assertEqual(feed_summary(self.batch)["current_live_birds"], 4)

    def test_backdated_events_recalculate_affected_feed_and_stage_bird_days(self):
        starter = self.feed(self.arrival + timedelta(days=1), quantity=90)
        Mortality.objects.create(
            batch=self.batch, mortality_date=self.arrival + timedelta(days=2),
            quantity_dead=20, age_in_days=2, suspected_cause="Test",
            description="Dated mortality", action_taken="Reviewed",
            reported_by_name="Auditor", created_by=self.user,
        )
        grower = self.feed(self.arrival + timedelta(days=3), quantity=180, stage=FeedType.GROWER)
        self.assertEqual(starter.current_number_of_birds, 200)
        self.assertEqual(grower.current_number_of_birds, 180)
        backdated = Mortality.objects.create(
            batch=self.batch, mortality_date=self.arrival + timedelta(hours=12),
            quantity_dead=10, age_in_days=0, suspected_cause="Correction",
            description="Backdated", action_taken="Approved",
            reported_by_name="Auditor", created_by=self.user,
        )
        recalculate_feed_event_populations(self.batch)
        starter.refresh_from_db(); grower.refresh_from_db()
        self.assertEqual(starter.current_number_of_birds, 190)
        self.assertEqual(grower.current_number_of_birds, 170)
        summary = feed_summary(self.batch)
        self.assertEqual(summary["stage_feed_kg"][FeedType.STARTER], Decimal("90.000"))
        self.assertEqual(summary["stage_feed_kg"][FeedType.GROWER], Decimal("180.000"))
        self.assertGreater(summary["bird_days"], Decimal("0"))
        backdated.delete()

    def test_zero_dated_balance_rejects_feed(self):
        Mortality.objects.create(
            batch=self.batch, mortality_date=self.arrival + timedelta(hours=1),
            quantity_dead=200, age_in_days=0, suspected_cause="Test",
            description="All birds", action_taken="Reviewed", reported_by_name="Auditor",
        )
        with self.assertRaises(Exception):
            self.feed(self.arrival + timedelta(hours=2))
