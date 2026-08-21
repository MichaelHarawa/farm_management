from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .models import BuyerType, PaymentStatus, Sales
from .serializers import SalesSerializer


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
