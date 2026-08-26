from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finance.models import (
    AccountingNature,
    AccountingPeriod,
    Expenditure,
    ExpenditureCategory,
    ExpenditureOrigin,
    ExpenditurePaymentStatus,
    FundingReceipt,
    FundingSource,
    FundingSourceType,
    InputCostReconciliation,
)
from apps.finance.services.expenditures import (
    batch_cost_records,
    create_batch_cost_transaction,
    post_expenditure,
    reconciliation_summary,
    record_expenditure_payment,
    reverse_expenditure,
)
from apps.finance.services.profitability import (
    available_batch_cash,
    available_funding_source_cash,
    batch_profitability,
    cash_used_from_batch,
)
from apps.poultry.models import (
    Batch,
    BuyerType,
    ChicksSource,
    InputCosts,
    PaymentMethod,
    PaymentStatus,
    ProductType,
)
from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle


User = get_user_model()


def aware(day: date):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


class UnifiedExpenditureWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="unified-finance-manager",
            email="unified@example.com",
            password="password",
        )
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        self.batch_a = self.make_batch("BATCH-A")
        self.batch_b = self.make_batch("BATCH-B")
        self.feed = ExpenditureCategory.objects.create(
            name="Unified Feed",
            code="unified_feed",
            default_accounting_nature=AccountingNature.DIRECT_COST,
            requires_item_details=True,
            requires_batch_beneficiary=True,
        )
        self.medication = ExpenditureCategory.objects.create(
            name="Unified Medication",
            code="unified_medication",
            default_accounting_nature=AccountingNature.DIRECT_COST,
            requires_item_details=True,
            requires_batch_beneficiary=True,
        )
        self.batch_a_source = self.make_batch_revenue(self.batch_a, Decimal("1000.00"))
        self.batch_b_source = self.make_batch_revenue(self.batch_b, Decimal("1000.00"))
        self.equity = FundingSource.objects.create(
            source_type=FundingSourceType.OWNER_CAPITAL,
            description="Owner equity",
        )
        FundingReceipt.objects.create(
            funding_source=self.equity,
            amount=Decimal("1000.00"),
            receipt_date=aware(date(2026, 1, 10)),
            created_by=self.user,
        )

    def make_batch(self, batch_id):
        return Batch.objects.create(
            batch_id=batch_id,
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 1, 1)),
            expected_maturity_date=aware(date(2026, 1, 21)),
            quantity=100,
            created_by=self.user,
        )

    def make_batch_revenue(self, batch, amount):
        create_sale_with_lifecycle(
            batch_id=batch.pk,
            created_by=self.user,
            sale_date=aware(date(2026, 1, 15)),
            product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=1,
            unit_price=amount,
            buyer_name="Cash buyer",
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CASH,
            amount_paid=amount,
            sold_by_name="Manager",
            notes="Funding source fixture.",
        )
        return FundingSource.objects.get(
            source_type=FundingSourceType.BATCH_COLLECTION,
            batch=batch,
        )

    def cost_data(self, *, amount, key, category=None, payment="paid", rows=None):
        return {
            "item": "Starter feed",
            "category_id": (category or self.feed).pk,
            "quantity": 1,
            "unit_measurement": "bag",
            "unit": 1,
            "unit_cost": Decimal(amount),
            "purchase_date": aware(date(2026, 1, 20)),
            "notes": "Unified workflow test.",
            "payment_status": payment,
            "funding_allocations": rows or [],
            "idempotency_key": key,
        }

    def test_same_batch_funding_creates_one_transaction_and_is_idempotent(self):
        data = self.cost_data(
            amount="200.00",
            key="same-batch-cost",
            rows=[{"funding_source": self.batch_a_source.pk, "amount": "200.00"}],
        )
        detail = create_batch_cost_transaction(
            batch=self.batch_a, data=dict(data), user=self.user
        )
        retry = create_batch_cost_transaction(
            batch=self.batch_a, data=dict(data), user=self.user
        )

        self.assertEqual(retry.pk, detail.pk)
        self.assertEqual(Expenditure.objects.filter(idempotency_key="same-batch-cost").count(), 1)
        self.assertEqual(InputCosts.objects.filter(expenditure=detail.expenditure).count(), 1)
        self.assertEqual(detail.expenditure.cost_allocations.get().batch, self.batch_a)
        self.assertEqual(cash_used_from_batch(self.batch_a), Decimal("200.00"))
        self.assertEqual(available_batch_cash(self.batch_a), Decimal("800.00"))
        self.assertEqual(batch_profitability(self.batch_a)["direct_batch_cost"], Decimal("200.00"))
        self.assertEqual(len(batch_cost_records(self.batch_a)), 1)

    def test_cross_batch_equity_and_split_funding_keep_dimensions_separate(self):
        cross = create_batch_cost_transaction(
            batch=self.batch_b,
            data=self.cost_data(
                amount="150.00",
                key="cross-batch-cost",
                category=self.medication,
                rows=[{"funding_source": self.batch_a_source.pk, "amount": "150.00"}],
            ),
            user=self.user,
        )
        create_batch_cost_transaction(
            batch=self.batch_b,
            data=self.cost_data(
                amount="300.00",
                key="equity-cost",
                rows=[{"funding_source": self.equity.pk, "amount": "300.00"}],
            ),
            user=self.user,
        )
        split = create_batch_cost_transaction(
            batch=self.batch_b,
            data=self.cost_data(
                amount="400.00",
                key="split-cost",
                rows=[
                    {"funding_source": self.batch_a_source.pk, "amount": "250.00"},
                    {"funding_source": self.equity.pk, "amount": "150.00"},
                ],
            ),
            user=self.user,
        )

        self.assertEqual(cross.expenditure.cost_allocations.get().batch, self.batch_b)
        self.assertEqual(split.expenditure.funding_allocations.count(), 2)
        self.assertEqual(batch_profitability(self.batch_b)["direct_batch_cost"], Decimal("850.00"))
        self.assertEqual(batch_profitability(self.batch_a)["direct_batch_cost"], Decimal("0.00"))
        self.assertEqual(cash_used_from_batch(self.batch_a), Decimal("400.00"))
        self.assertEqual(available_funding_source_cash(self.equity), Decimal("550.00"))
        self.assertEqual(cash_used_from_batch(self.batch_b), Decimal("0.00"))

    def test_credit_cost_is_incurred_then_paid_without_duplicate(self):
        detail = create_batch_cost_transaction(
            batch=self.batch_b,
            data=self.cost_data(amount="100.00", key="credit-cost", payment="credit"),
            user=self.user,
        )
        expenditure = detail.expenditure

        self.assertEqual(expenditure.payment_status, ExpenditurePaymentStatus.UNPAID)
        self.assertEqual(batch_profitability(self.batch_b)["direct_batch_cost"], Decimal("100.00"))
        self.assertEqual(cash_used_from_batch(self.batch_a), Decimal("0.00"))

        record_expenditure_payment(
            expenditure_id=expenditure.pk,
            funding_rows=[{"funding_source": self.batch_a_source.pk, "amount": "40.00"}],
            payment_group_key="credit-payment-one",
            payment_date=date(2026, 1, 22),
            user=self.user,
        )
        expenditure.refresh_from_db()
        self.assertEqual(expenditure.payment_status, ExpenditurePaymentStatus.PARTIAL)

        record_expenditure_payment(
            expenditure_id=expenditure.pk,
            funding_rows=[{"funding_source": self.batch_a_source.pk, "amount": "60.00"}],
            payment_group_key="credit-payment-two",
            payment_date=date(2026, 1, 23),
            user=self.user,
        )
        expenditure.refresh_from_db()
        self.assertEqual(expenditure.payment_status, ExpenditurePaymentStatus.PAID)
        self.assertEqual(cash_used_from_batch(self.batch_a), Decimal("100.00"))
        self.assertEqual(Expenditure.objects.filter(pk=expenditure.pk).count(), 1)
        self.assertEqual(InputCosts.objects.filter(pk=detail.pk).count(), 1)

    def test_insufficient_funds_roll_back_and_reversal_restores_cash_and_cost(self):
        with self.assertRaises(ValidationError):
            create_batch_cost_transaction(
                batch=self.batch_b,
                data=self.cost_data(
                    amount="1200.00",
                    key="insufficient-cost",
                    rows=[{"funding_source": self.batch_a_source.pk, "amount": "1200.00"}],
                ),
                user=self.user,
            )
        self.assertFalse(Expenditure.objects.filter(idempotency_key="insufficient-cost").exists())

        detail = create_batch_cost_transaction(
            batch=self.batch_b,
            data=self.cost_data(
                amount="200.00",
                key="reversible-cost",
                rows=[{"funding_source": self.batch_a_source.pk, "amount": "200.00"}],
            ),
            user=self.user,
        )
        reverse_expenditure(
            expenditure_id=detail.expenditure_id,
            reason="Supplier invoice cancelled.",
            user=self.user,
        )
        self.assertEqual(cash_used_from_batch(self.batch_a), Decimal("0.00"))
        self.assertEqual(available_batch_cash(self.batch_a), Decimal("1000.00"))
        self.assertEqual(batch_profitability(self.batch_b)["direct_batch_cost"], Decimal("0.00"))

    def test_finance_entry_projects_into_batch_costs_and_reconciliation_is_reported(self):
        expenditure = Expenditure.objects.create(
            expenditure_date=date(2026, 1, 20),
            accounting_period=self.period,
            amount=Decimal("75.00"),
            category=self.medication,
            accounting_nature=AccountingNature.DIRECT_COST,
            description="Medication entered centrally",
            origin=ExpenditureOrigin.FINANCE,
            beneficiary_type="one_poultry_batch",
            beneficiary_detail=self.batch_b.batch_id,
            cost_allocation_plan=[{"batch": self.batch_b.pk, "amount": "75.00"}],
            created_by=self.user,
        )
        post_expenditure(
            expenditure_id=expenditure.pk,
            user=self.user,
            funding_rows=[{"funding_source": self.equity.pk, "amount": "75.00"}],
        )

        rows = batch_cost_records(self.batch_b)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["expenditure"], expenditure.pk)
        self.assertEqual(rows[0]["item"], "Medication entered centrally")
        self.assertEqual(batch_profitability(self.batch_b)["direct_batch_cost"], Decimal("75.00"))
        self.assertFalse(InputCosts.objects.filter(expenditure=expenditure).exists())

        historical_detail = InputCosts.objects.create(
            batch=self.batch_a,
            item="Legacy uncertain item",
            category="Other",
            quantity=1,
            unit_measurement="item",
            unit=1,
            unit_cost=Decimal("10.00"),
            purchase_date=aware(date(2026, 1, 5)),
            notes="Review manually.",
            created_by=self.user,
        )
        InputCostReconciliation.objects.create(
            input_cost=historical_detail,
            status="uncertain",
            match_basis="Candidate was not conclusive.",
            requires_manual_review=True,
        )
        self.assertEqual(reconciliation_summary()["uncertain"], 1)
        self.assertEqual(reconciliation_summary()["manual_review_required"], 1)

    def test_batch_cost_api_requires_authentication(self):
        response = APIClient().post(
            f"/api/v1/poultry-management/{self.batch_b.pk}/input_costs",
            self.cost_data(amount="10.00", key="anonymous-cost", payment="credit"),
            format="json",
        )
        self.assertIn(response.status_code, {401, 403})
