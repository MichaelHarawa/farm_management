from decimal import Decimal

from django.core.exceptions import ValidationError
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    Batch, BuyerType, ChicksSource, FeedSource, FeedType, FeedUsage, InputCosts,
    Mortality, PaymentMethod, PaymentStatus, ProductType, Sales, UnitMeasurement,
)
from .serializers import SalesSerializer
from .services.batch_lifecycle import create_sale_with_lifecycle
from .services.feed_metrics import (
    bird_days_between, feed_summary, recalculate_feed_event_populations,
    record_feed_usage, sell_by_recommendation,
)
from apps.finance.services.profitability import (
    batch_profitability,
    portfolio_expenditure_funding_mix,
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
        "receivable_follow_up_name": "Collections Officer",
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

    def test_sale_with_balance_requires_receivables_follow_up_person(self):
        payload = sale_payload(payment_status=PaymentStatus.UNPAID)
        payload["receivable_follow_up_name"] = ""

        serializer = SalesSerializer(data=payload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("receivable_follow_up_name", serializer.errors)

    def test_paid_sale_clears_receivables_follow_up_person(self):
        serializer = SalesSerializer(
            data=sale_payload(payment_status=PaymentStatus.PAID)
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["receivable_follow_up_name"],
            "",
        )

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


class SaleSellingCostTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="sales-cost-user")
        arrival = timezone.make_aware(datetime.combine(date(2026, 8, 1), time(hour=8)))
        self.batch = Batch.objects.create(
            batch_id="SELLING-COST-1",
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=arrival,
            expected_maturity_date=arrival + timedelta(days=42),
            quantity=100,
            actual_quantity_received=100,
            created_by=self.user,
        )

    def test_nested_sale_costs_are_recorded_and_reduce_profit(self):
        sale = create_sale_with_lifecycle(
            batch_id=self.batch.pk,
            created_by=self.user,
            **sale_payload(
                quantity_sold=2,
                unit_price=Decimal("7500.00"),
                amount_paid=Decimal("15000.00"),
                payment_status=PaymentStatus.PAID,
                selling_costs=[
                    {"category": "transport", "amount": "1200.00", "notes": "Delivery"},
                    {"category": "packaging", "amount": "300.00", "notes": "Crates"},
                ],
            ),
        )

        serialized = SalesSerializer(sale).data
        report = batch_profitability(self.batch)
        funding_mix = portfolio_expenditure_funding_mix(
            [self.batch], total_attributed_cost=report["total_attributed_cost"]
        )

        self.assertEqual(sale.selling_costs.count(), 2)
        self.assertEqual(Decimal(serialized["total_selling_cost"]), Decimal("1500.00"))
        self.assertEqual(report["selling_cost"], Decimal("1500.00"))
        self.assertEqual(report["management_net_position"], Decimal("13500.00"))
        unassigned = next(
            row for row in funding_mix["groups"]
            if row["key"] == "unpaid_or_unassigned"
        )
        self.assertEqual(unassigned["amount"], Decimal("1500.00"))


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

    def test_sell_by_guidance_uses_recorded_feed_cost_and_target_price_fallback(self):
        self.batch.target_selling_price = Decimal("7500.00")
        self.batch.save(update_fields=["target_selling_price", "updated_at"])
        self.feed(self.arrival + timedelta(days=1), quantity=50, hours=24)
        InputCosts.objects.create(
            batch=self.batch,
            item="Finisher feed",
            category="Feed",
            quantity=1,
            unit=50,
            unit_measurement="kg",
            unit_cost=Decimal("10.00"),
            purchase_date=self.arrival + timedelta(days=1),
            notes="Feed evidence",
            created_by=self.user,
        )

        guidance = sell_by_recommendation(self.batch)

        self.assertEqual(guidance["status"], "ready")
        self.assertEqual(guidance["average_historical_selling_price"], Decimal("7500.00"))
        self.assertEqual(guidance["feed_cost_per_kg"], Decimal("10.00"))
        self.assertEqual(guidance["typical_bag_size_kg"], Decimal("50.00"))
        self.assertGreater(guidance["bags_to_avoid"], 0)
        self.assertGreater(guidance["avoidable_feed_purchase_cost"], Decimal("0.00"))


class PoultryDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="dashboard-user")
        self.arrival = timezone.now() - timedelta(days=10)
        self.batch = Batch.objects.create(
            batch_id="DASHBOARD-1",
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=self.arrival,
            expected_maturity_date=self.arrival + timedelta(days=35),
            quantity=100,
            actual_quantity_received=100,
            created_by=self.user,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_dashboard_uses_bird_balance_and_excludes_non_bird_sales(self):
        Mortality.objects.create(
            batch=self.batch,
            mortality_date=self.arrival + timedelta(days=2),
            quantity_dead=5,
            age_in_days=2,
            suspected_cause="Stress",
            description="Test mortality",
            action_taken="Reviewed",
            reported_by_name="Manager",
            created_by=self.user,
        )
        create_sale_with_lifecycle(
            batch_id=self.batch.pk,
            created_by=self.user,
            sale_date=self.arrival + timedelta(days=8),
            product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=10,
            unit_price=Decimal("5000.00"),
            buyer_name="Buyer",
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.PARTIAL,
            payment_method=PaymentMethod.CASH,
            amount_paid=Decimal("30000.00"),
            sold_by_name="Manager",
            notes="Bird sale",
        )
        create_sale_with_lifecycle(
            batch_id=self.batch.pk,
            created_by=self.user,
            sale_date=self.arrival + timedelta(days=9),
            product_type=ProductType.MANURE,
            quantity_sold=20,
            unit_price=Decimal("100.00"),
            buyer_name="Buyer",
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CASH,
            amount_paid=Decimal("2000.00"),
            sold_by_name="Manager",
            notes="Manure sale",
        )

        response = self.client.get("/api/v1/poultry-management/dashboard")

        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["batches"][0]
        self.assertEqual(row["current_live_birds"], 85)
        self.assertEqual(row["birds_sold"], 10)
        self.assertEqual(row["mortality"], 5)
        self.assertEqual(Decimal(row["total_sales"]), Decimal("52000.00"))
        self.assertEqual(Decimal(row["amount_collected"]), Decimal("32000.00"))
        self.assertEqual(Decimal(response.data["overview"]["sales"]), Decimal("52000.00"))
        self.assertEqual(
            Decimal(response.data["overview"]["cash_collections"]),
            Decimal("32000.00"),
        )
        self.assertEqual(response.data["overview"]["deaths"], 5)
        self.assertIn("mortality", response.data["calculation_basis"].lower())
