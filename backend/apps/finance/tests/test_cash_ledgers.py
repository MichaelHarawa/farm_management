from datetime import date, datetime, time
from decimal import Decimal
from threading import Barrier, Thread

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.finance.models import (
    AccountingNature,
    Expenditure,
    ExpenditureCategory,
    FundingReceipt,
    FundingSource,
    FundingSourceType,
    SalePayment,
)
from apps.finance.services.collections import record_sale_payment, reverse_sale_payment
from apps.finance.services.profitability import (
    available_batch_cash,
    available_funding_source_cash,
    batch_cash_collected,
    cash_used_from_batch,
)
from apps.poultry.models import (
    Batch,
    BuyerType,
    ChicksSource,
    PaymentMethod,
    PaymentStatus,
    ProductType,
)
from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle


User = get_user_model()


def aware(day: date):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


class CashLedgerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="ledger-manager",
            email="ledger@example.com",
            password="password",
        )
        self.batch = Batch.objects.create(
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 1, 1)),
            expected_maturity_date=aware(date(2026, 1, 21)),
            quantity=20,
            created_by=self.user,
        )

    def make_sale(self, *, total=Decimal("200.00"), paid=Decimal("50.00")):
        return create_sale_with_lifecycle(
            batch_id=self.batch.pk,
            created_by=self.user,
            sale_date=aware(date(2026, 1, 25)),
            product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=2,
            unit_price=total / 2,
            buyer_name="Ledger Buyer",
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.PARTIAL,
            payment_method=PaymentMethod.CASH,
            amount_paid=paid,
            sold_by_name="Manager",
            notes="Ledger test.",
        )

    def test_initial_and_later_payments_are_append_only_and_idempotent(self):
        sale = self.make_sale()
        self.assertEqual(SalePayment.objects.filter(sale=sale).count(), 1)
        self.assertEqual(batch_cash_collected(self.batch), Decimal("50.00"))

        first, created = record_sale_payment(
            sale_id=sale.pk,
            amount=Decimal("50.00"),
            payment_date=aware(date(2026, 1, 26)),
            payment_method=PaymentMethod.CASH,
            created_by=self.user,
            idempotency_key="receipt-001",
        )
        duplicate, duplicate_created = record_sale_payment(
            sale_id=sale.pk,
            amount=Decimal("50.00"),
            payment_date=aware(date(2026, 1, 26)),
            payment_method=PaymentMethod.CASH,
            created_by=self.user,
            idempotency_key="receipt-001",
        )
        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(first.pk, duplicate.pk)
        sale.refresh_from_db()
        self.assertEqual(sale.amount_paid, Decimal("100.00"))
        self.assertEqual(sale.payment_status, PaymentStatus.PARTIAL)

        record_sale_payment(
            sale_id=sale.pk,
            amount=Decimal("100.00"),
            payment_date=aware(date(2026, 1, 27)),
            payment_method=PaymentMethod.BANK_TRANSFER,
            created_by=self.user,
            idempotency_key="receipt-002",
        )
        sale.refresh_from_db()
        self.assertEqual(sale.amount_paid, sale.sale_total)
        self.assertEqual(sale.balance, Decimal("0.00"))
        self.assertEqual(sale.payment_status, PaymentStatus.PAID)

    def test_posting_requires_full_funding_and_updates_revenue_usage(self):
        self.make_sale(total=Decimal("200.00"), paid=Decimal("100.00"))
        source = FundingSource.objects.get(
            source_type=FundingSourceType.BATCH_COLLECTION,
            batch=self.batch,
        )
        category = ExpenditureCategory.objects.create(
            name="Ledger feed",
            code="ledger_feed",
            default_accounting_nature=AccountingNature.DIRECT_COST,
        )
        expenditure = Expenditure.objects.create(
            expenditure_date=date(2026, 1, 26),
            amount=Decimal("100.00"),
            category=category,
            accounting_nature=AccountingNature.DIRECT_COST,
            description="Feed paid from collections",
            beneficiary_type="one_poultry_batch",
            beneficiary_detail=self.batch.batch_id,
            created_by=self.user,
        )
        client = APIClient()
        client.force_authenticate(self.user)
        no_funding = client.post(
            f"/api/v1/finance/expenditures/{expenditure.pk}/post",
            {},
            format="json",
        )
        self.assertEqual(no_funding.status_code, 400)
        expenditure.refresh_from_db()
        self.assertEqual(expenditure.status, "draft")

        posted = client.post(
            f"/api/v1/finance/expenditures/{expenditure.pk}/post",
            {"funding_allocations": [{"funding_source": source.pk, "amount": "100.00"}]},
            format="json",
        )
        self.assertEqual(posted.status_code, 200, posted.data)
        self.assertEqual(cash_used_from_batch(self.batch), Decimal("100.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))

        payment = SalePayment.objects.get(sale__batch=self.batch)
        with self.assertRaisesMessage(ValidationError, "cannot be reversed"):
            reverse_sale_payment(
                payment_id=payment.pk,
                reason="Bad receipt",
                reversed_by=self.user,
            )

        reversed_response = client.post(
            f"/api/v1/finance/expenditures/{expenditure.pk}/void",
            {"reason": "Supplier invoice corrected"},
            format="json",
        )
        self.assertEqual(reversed_response.status_code, 200)
        expenditure.refresh_from_db()
        self.assertEqual(expenditure.status, "void")
        self.assertEqual(expenditure.reversal_reason, "Supplier invoice corrected")
        self.assertEqual(expenditure.reversed_by, self.user)
        self.assertIsNotNone(expenditure.reversed_at)
        self.assertEqual(expenditure.funding_allocations.count(), 1)
        self.assertEqual(cash_used_from_batch(self.batch), Decimal("0.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("100.00"))
        reversed_payment = reverse_sale_payment(
            payment_id=payment.pk,
            reason="Duplicate receipt",
            reversed_by=self.user,
        )
        self.assertEqual(reversed_payment.status, "reversed")
        reversed_payment.sale.refresh_from_db()
        self.assertEqual(reversed_payment.sale.amount_paid, Decimal("0.00"))
        self.assertEqual(reversed_payment.sale.balance, Decimal("200.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))

    def test_owner_cash_does_not_increase_batch_cash(self):
        source = FundingSource.objects.create(
            source_type=FundingSourceType.OWNER_CAPITAL,
            description="Owner working capital",
        )
        FundingReceipt.objects.create(
            funding_source=source,
            amount=Decimal("300.00"),
            receipt_date=aware(date(2026, 1, 20)),
            created_by=self.user,
        )
        self.assertEqual(available_funding_source_cash(source), Decimal("300.00"))
        self.assertEqual(batch_cash_collected(self.batch), Decimal("0.00"))
        category = ExpenditureCategory.objects.create(
            name="Owner-funded admin",
            code="owner_admin",
            default_accounting_nature=AccountingNature.INDIRECT_OPERATING_EXPENSE,
        )
        expenditure = Expenditure.objects.create(
            expenditure_date=date(2026, 1, 20),
            amount=Decimal("100.00"),
            category=category,
            accounting_nature=AccountingNature.INDIRECT_OPERATING_EXPENSE,
            description="Owner-funded farm administration",
            beneficiary_type="general_admin",
            created_by=self.user,
        )
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post(
            f"/api/v1/finance/expenditures/{expenditure.pk}/post",
            {"funding_allocations": [{"funding_source": source.pk, "amount": "100.00"}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(available_funding_source_cash(source), Decimal("200.00"))
        self.assertEqual(cash_used_from_batch(self.batch), Decimal("0.00"))


class ConcurrentPaymentTests(TransactionTestCase):
    reset_sequences = True

    def test_row_lock_prevents_concurrent_over_settlement(self):
        user = User.objects.create_superuser(
            username="concurrent-manager",
            email="concurrent@example.com",
            password="password",
        )
        batch = Batch.objects.create(
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 2, 1)),
            expected_maturity_date=aware(date(2026, 2, 21)),
            quantity=10,
            created_by=user,
        )
        sale = create_sale_with_lifecycle(
            batch_id=batch.pk,
            created_by=user,
            sale_date=aware(date(2026, 2, 25)),
            product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=1,
            unit_price=Decimal("100.00"),
            buyer_name="Concurrent Buyer",
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.UNPAID,
            payment_method=PaymentMethod.CASH,
            amount_paid=Decimal("0.00"),
            sold_by_name="Manager",
            notes="Concurrency test.",
        )
        barrier = Barrier(2)
        outcomes: list[str] = []

        def submit(key: str):
            close_old_connections()
            barrier.wait()
            try:
                record_sale_payment(
                    sale_id=sale.pk,
                    amount=Decimal("75.00"),
                    payment_date=aware(date(2026, 2, 26)),
                    payment_method=PaymentMethod.CASH,
                    created_by=User.objects.get(pk=user.pk),
                    idempotency_key=key,
                )
                outcomes.append("posted")
            except ValidationError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [Thread(target=submit, args=(f"concurrent-{index}",)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertCountEqual(outcomes, ["posted", "rejected"])
        sale.refresh_from_db()
        self.assertEqual(sale.amount_paid, Decimal("75.00"))
        self.assertEqual(sale.balance, Decimal("25.00"))
