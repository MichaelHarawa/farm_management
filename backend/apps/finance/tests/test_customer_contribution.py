from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (
    AccountingNature,
    AccountingPeriod,
    AllocationMethod,
    AllocationSourceType,
    CostAllocation,
    Customer,
    CustomerCostCategory,
    CustomerCostEvidenceStatus,
    CustomerCostSourceType,
    Expenditure,
    ExpenditureStatus,
    PeriodStatus,
    SalePayment,
    SalePaymentStatus,
)
from apps.finance.services.customer_contribution import (
    customer_contribution_report,
    link_sale_customer,
    record_customer_cost_attribution,
    reverse_customer_cost_attribution,
)
from apps.poultry.models import (
    Batch,
    BuyerType,
    ChicksSource,
    PaymentMethod,
    PaymentStatus,
    ProductType,
    Sales,
)


User = get_user_model()


def aware(day: date):
    return timezone.make_aware(datetime.combine(day, time(hour=12)))


class CustomerContributionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="customer-admin", email="customer-admin@example.com", password="password"
        )
        self.stakeholder = User.objects.create_user(
            username="customer-reader", email="customer-reader@example.com", password="password"
        )
        admin_role, _ = Role.objects.get_or_create(slug=RoleChoices.ADMIN, defaults={"name": "Administrator"})
        reader_role, _ = Role.objects.get_or_create(slug=RoleChoices.STAKE_HOLDER, defaults={"name": "Stakeholder"})
        self.admin.roles.add(admin_role)
        self.stakeholder.roles.add(reader_role)
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 9, 1), period_end=date(2026, 9, 30)
        )
        self.batch = Batch.objects.create(
            batch_id="CUSTOMER-001",
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(date(2026, 9, 1)),
            expected_maturity_date=aware(date(2026, 10, 13)),
            quantity=100,
            created_by=self.admin,
        )
        self.customer = Customer.objects.create(display_name="Retail Partner", created_by=self.admin)
        self.sale = Sales.objects.create(
            batch=self.batch,
            sale_date=aware(date(2026, 9, 10)),
            product_type=ProductType.LIVE_CHICKEN,
            quantity_sold=100,
            unit_price=Decimal("10000.00"),
            buyer_name="Retail Partner at sale time",
            customer=self.customer,
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.PARTIAL,
            payment_method=PaymentMethod.CASH,
            amount_paid=Decimal("400000.00"),
            balance=Decimal("600000.00"),
            receivable_follow_up_name="Collections Officer",
            sold_by_name="Seller",
            notes="",
            created_by=self.admin,
        )
        SalePayment.objects.create(
            sale=self.sale,
            amount=Decimal("400000.00"),
            payment_date=aware(date(2026, 9, 10)),
            payment_method="cash",
            received_by_name="Cashier",
            status=SalePaymentStatus.POSTED,
            created_by=self.admin,
        )
        self.production = self.expenditure("600000.00", "Batch production")
        CostAllocation.objects.create(
            accounting_period=self.period,
            batch=self.batch,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure=self.production,
            allocation_method=AllocationMethod.DIRECT,
            allocated_amount=Decimal("600000.00"),
            allocation_percentage=Decimal("100.0000"),
            generated_by=self.admin,
        )

    def expenditure(self, amount, description, nature=AccountingNature.DIRECT_COST):
        return Expenditure.objects.create(
            expenditure_date=date(2026, 9, 8),
            accounting_period=self.period,
            amount=Decimal(amount),
            accounting_nature=nature,
            description=description,
            status=ExpenditureStatus.POSTED,
            posted_by=self.admin,
            posted_at=timezone.now(),
            created_by=self.admin,
        )

    def attribute(self, amount, category, key):
        source = self.expenditure(amount, f"{category} source")
        return record_customer_cost_attribution(
            customer_id=self.customer.pk,
            sale_id=self.sale.pk,
            batch_id=self.batch.pk,
            attribution_date=date(2026, 9, 10),
            category=category,
            amount=Decimal(amount),
            source_type=CustomerCostSourceType.EXPENDITURE,
            source_id=source.pk,
            evidence_status=CustomerCostEvidenceStatus.ACTUAL,
            attribution_basis="Invoice linked to this delivery",
            reason="Directly attributable to the customer sale",
            idempotency_key=key,
            user=self.admin,
        )[0]

    def test_exact_formula_uses_revenue_not_cash_and_counts_production_once(self):
        self.attribute("50000.00", CustomerCostCategory.SUPPORT, "support")
        self.attribute("20000.00", CustomerCostCategory.REWORK, "rework")
        self.attribute("30000.00", CustomerCostCategory.ACQUISITION, "acquisition")

        report = customer_contribution_report(
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
        )
        row = report["customers"][0]
        self.assertEqual(row["revenue"], Decimal("1000000.00"))
        self.assertEqual(row["cash_collected"], Decimal("400000.00"))
        self.assertEqual(row["receivables"], Decimal("600000.00"))
        self.assertEqual(row["direct_delivery_cost"], Decimal("600000.00"))
        self.assertEqual(row["support_cost"], Decimal("50000.00"))
        self.assertEqual(row["rework_cost"], Decimal("20000.00"))
        self.assertEqual(row["acquisition_cost"], Decimal("30000.00"))
        self.assertEqual(row["contribution"], Decimal("300000.00"))
        self.assertEqual(row["margin_percent"], Decimal("30.00"))

    def test_linked_source_and_economic_source_caps_prevent_double_attribution(self):
        source = self.expenditure("100.00", "One economic cost", AccountingNature.OTHER)
        record_customer_cost_attribution(
            customer_id=self.customer.pk,
            sale_id=self.sale.pk,
            batch_id=self.batch.pk,
            attribution_date=date(2026, 9, 10),
            category=CustomerCostCategory.SUPPORT,
            amount=Decimal("60.00"),
            source_type=CustomerCostSourceType.EXPENDITURE,
            source_id=source.pk,
            evidence_status=CustomerCostEvidenceStatus.ACTUAL,
            attribution_basis="Source invoice",
            reason="Customer-specific support",
            idempotency_key="source-cap-one",
            user=self.admin,
        )
        production_allocation = CostAllocation.objects.get(expenditure=self.production)
        with self.assertRaises(ValidationError):
            record_customer_cost_attribution(
                customer_id=self.customer.pk,
                sale_id=self.sale.pk,
                batch_id=self.batch.pk,
                attribution_date=date(2026, 9, 10),
                category=CustomerCostCategory.SUPPORT,
                amount=Decimal("50.00"),
                source_type=CustomerCostSourceType.EXPENDITURE,
                source_id=source.pk,
                evidence_status=CustomerCostEvidenceStatus.ACTUAL,
                attribution_basis="Same source via batch allocation",
                reason="Must not duplicate the expense",
                idempotency_key="source-cap-two",
                user=self.admin,
            )
        allocation = CostAllocation.objects.create(
            accounting_period=self.period,
            batch=self.batch,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure=source,
            allocation_method=AllocationMethod.DIRECT,
            allocated_amount=Decimal("100.00"),
            allocation_percentage=Decimal("100.0000"),
            generated_by=self.admin,
        )
        with self.assertRaises(ValidationError):
            record_customer_cost_attribution(
                customer_id=self.customer.pk,
                sale_id=self.sale.pk,
                batch_id=self.batch.pk,
                attribution_date=date(2026, 9, 10),
                category=CustomerCostCategory.DIRECT_DELIVERY,
                amount=Decimal("10.00"),
                source_type=CustomerCostSourceType.COST_ALLOCATION,
                source_id=production_allocation.pk,
                evidence_status=CustomerCostEvidenceStatus.ACTUAL,
                attribution_basis="Batch production allocation",
                reason="Must not duplicate automatic production share",
                idempotency_key="production-double-count",
                user=self.admin,
            )

    def test_same_name_does_not_merge_or_auto_link_historical_sales(self):
        duplicate_name = Customer.objects.create(display_name=self.customer.display_name)
        unlinked = Sales.objects.create(
            batch=self.batch,
            sale_date=aware(date(2026, 9, 11)),
            product_type=ProductType.EGGS,
            quantity_sold=1,
            unit_price=Decimal("100.00"),
            buyer_name=self.customer.display_name,
            buyer_type=BuyerType.RETAIL,
            payment_status=PaymentStatus.UNPAID,
            payment_method=PaymentMethod.CREDIT,
            amount_paid=Decimal("0.00"),
            balance=Decimal("100.00"),
            receivable_follow_up_name="Collector",
            sold_by_name="Seller",
            notes="",
        )
        self.assertIsNone(unlinked.customer_id)
        self.assertNotEqual(self.customer.pk, duplicate_name.pk)
        report = customer_contribution_report(date_to=date(2026, 9, 30))
        self.assertEqual(report["summary"]["unlinked_sale_count"], 1)
        link_sale_customer(
            sale_id=unlinked.pk,
            customer_id=duplicate_name.pk,
            reason="Reviewed source document",
            user=self.admin,
        )
        unlinked.refresh_from_db()
        self.assertEqual(unlinked.customer_id, duplicate_name.pk)

    def test_report_permissions_pagination_and_full_export_totals(self):
        reader = APIClient()
        reader.force_authenticate(self.stakeholder)
        paged = reader.get(
            "/api/v1/finance/reports/customer-contributions",
            {"customer_page_size": 1},
        )
        exported = reader.get(
            "/api/v1/finance/reports/customer-contributions",
            {"export": 1},
        )
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(paged.data["summary"], exported.data["summary"])
        denied = reader.post(
            "/api/v1/finance/customers",
            {"display_name": "Cannot create"},
            format="json",
        )
        self.assertEqual(denied.status_code, 403)

    def test_missing_cost_categories_are_explicitly_incomplete(self):
        report = customer_contribution_report(date_to=date(2026, 9, 30))
        row = report["customers"][0]
        self.assertEqual(row["coverage_status"], "incomplete")
        self.assertEqual(row["category_coverage"][CustomerCostCategory.SUPPORT], "not_attributed")
        self.assertEqual(row["recommended_label"], "review")

    def test_documented_estimate_is_analytical_idempotent_and_reversible(self):
        before_expenditures = Expenditure.objects.count()
        payload = dict(
            customer_id=self.customer.pk,
            sale_id=self.sale.pk,
            batch_id=self.batch.pk,
            attribution_date=date(2026, 9, 10),
            category=CustomerCostCategory.SUPPORT,
            amount=Decimal("50.00"),
            source_type=CustomerCostSourceType.MANUAL_ESTIMATE,
            source_id=None,
            evidence_status=CustomerCostEvidenceStatus.ESTIMATED,
            attribution_basis="Two documented support hours",
            reason="Exact payroll split is unavailable",
            idempotency_key="estimate-one",
            user=self.admin,
        )
        first, created = record_customer_cost_attribution(**payload)
        second, created_again = record_customer_cost_attribution(**payload)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Expenditure.objects.count(), before_expenditures)
        reverse_customer_cost_attribution(
            attribution_id=first.pk, reason="Estimate superseded", user=self.admin
        )
        historical = customer_contribution_report(date_to=date(2026, 9, 11))
        self.assertEqual(
            historical["customers"][0]["support_cost"], Decimal("50.00")
        )
        report = customer_contribution_report(date_to=date(2026, 9, 30))
        self.assertEqual(report["customers"][0]["support_cost"], Decimal("0.00"))

    def test_closed_period_blocks_new_customer_analysis_entries(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.closed_at = timezone.now()
        self.period.closed_by = self.admin
        self.period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        with self.assertRaises(ValidationError):
            record_customer_cost_attribution(
                customer_id=self.customer.pk,
                sale_id=self.sale.pk,
                batch_id=self.batch.pk,
                attribution_date=date(2026, 9, 10),
                category=CustomerCostCategory.SUPPORT,
                amount=Decimal("10.00"),
                source_type=CustomerCostSourceType.MANUAL_ESTIMATE,
                source_id=None,
                evidence_status=CustomerCostEvidenceStatus.ESTIMATED,
                attribution_basis="Estimate",
                reason="Closed period must block",
                idempotency_key="closed-period",
                user=self.admin,
            )
