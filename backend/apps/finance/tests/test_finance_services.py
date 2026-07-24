from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    Asset,
    AssetCategory,
    AssetProductionScope,
    AssetStatus,
    AssetUsageRecord,
    ConsumableUsageScope,
    CostAllocation,
    CostScope,
    EmployeeProfile,
    EmploymentType,
    PeriodStatus,
    ReplacementReserveTransaction,
    ReserveTransactionType,
    SharedConsumableLot,
    SharedExpense,
    SharedExpenseScope,
)
from apps.finance.services.allocations import (
    allocate_amount_by_driver,
    regenerate_allocations_for_period,
)
from apps.poultry.services.batch_lifecycle import (
    calculate_bird_balance,
    create_mortality_with_lifecycle,
    create_sale_with_lifecycle,
)
from apps.finance.services.bird_days import recalculate_bird_day_snapshots
from apps.finance.services.consumables import record_consumable_usage
from apps.finance.services.depreciation import generate_depreciation_for_period
from apps.finance.services.payroll import generate_payroll_for_period
from apps.finance.services.profitability import batch_profitability
from apps.finance.services.reporting import monthly_profitability_report
from apps.poultry.models import (
    Batch,
    BatchStatus,
    BuyerType,
    ChicksSource,
    InputCosts,
    PaymentMethod,
    PaymentStatus,
    ProductType,
)


User = get_user_model()


def aware(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


class FinanceServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="password",
        )

    def batch(self, quantity=100, entry=date(2026, 1, 1), maturity=date(2026, 1, 20)):
        batch = Batch.objects.create(
            bird_type="broilers",
            source=ChicksSource.PROTO,
            entry_date=aware(entry),
            expected_maturity_date=aware(maturity),
            quantity=quantity,
            created_by=self.user,
        )
        return batch

    def sale_payload(self, **overrides):
        payload = {
            "sale_date": aware(date(2026, 1, 25)),
            "product_type": ProductType.LIVE_CHICKEN,
            "quantity_sold": 1,
            "unit_price": Decimal("100.00"),
            "buyer_name": "Buyer",
            "buyer_type": BuyerType.RETAIL,
            "payment_status": PaymentStatus.PAID,
            "payment_method": PaymentMethod.CASH,
            "amount_paid": Decimal("100.00"),
            "sold_by_name": "Seller",
            "notes": "Recorded in test.",
        }
        payload.update(overrides)
        return payload

    def test_bird_day_example_and_allocation_reconciles(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 30),
        )
        batch_a = self.batch(quantity=180, entry=date(2026, 1, 1))
        batch_b = self.batch(quantity=250, entry=date(2026, 1, 11))

        snapshots = recalculate_bird_day_snapshots(period)
        by_batch = {snapshot.batch_id: snapshot for snapshot in snapshots}

        self.assertEqual(by_batch[batch_a.id].bird_days, Decimal("5400.0000"))
        self.assertEqual(by_batch[batch_b.id].bird_days, Decimal("5000.0000"))

        allocations = allocate_amount_by_driver(
            Decimal("600000.00"),
            {
                batch_a.id: by_batch[batch_a.id].bird_days,
                batch_b.id: by_batch[batch_b.id].bird_days,
            },
        )

        self.assertEqual(allocations[batch_a.id], Decimal("311538.46"))
        self.assertEqual(allocations[batch_b.id], Decimal("288461.54"))
        self.assertEqual(sum(allocations.values()), Decimal("600000.00"))

    def test_batch_closes_when_all_live_birds_are_accounted_for(self):
        batch = self.batch(quantity=200)
        create_mortality_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            mortality_date=aware(date(2026, 1, 5)),
            quantity_dead=10,
            age_in_days=5,
            suspected_cause="Heat",
            description="Observed in the pen.",
            action_taken="Separated birds and monitored flock.",
            reported_by_name="Supervisor",
        )
        create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(quantity_sold=190, amount_paid=Decimal("19000.00")),
        )

        batch.refresh_from_db()
        balance = calculate_bird_balance(batch)

        self.assertEqual(balance.remaining_live_birds, 0)
        self.assertEqual(batch.status, BatchStatus.CLOSED)
        self.assertIsNotNone(batch.closed_at)

    def test_eggs_and_manure_generate_revenue_without_reducing_birds(self):
        batch = self.batch(quantity=50)
        create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(
                product_type=ProductType.EGGS,
                quantity_sold=30,
                unit_price=Decimal("10.00"),
                amount_paid=Decimal("300.00"),
            ),
        )
        create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(
                product_type=ProductType.MANURE,
                quantity_sold=2,
                unit_price=Decimal("50.00"),
                amount_paid=Decimal("100.00"),
            ),
        )

        data = batch_profitability(batch)
        balance = calculate_bird_balance(batch)

        self.assertEqual(data["revenue"], Decimal("400.00"))
        self.assertEqual(balance.valid_bird_units_sold, 0)
        self.assertEqual(balance.remaining_live_birds, 50)

    def test_cancelled_sales_are_excluded_from_operations_and_finance(self):
        batch = self.batch(quantity=20)
        create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(
                quantity_sold=10,
                amount_paid=Decimal("0.00"),
                payment_status=PaymentStatus.CANCELLED,
            ),
        )

        data = batch_profitability(batch)
        balance = calculate_bird_balance(batch)

        self.assertEqual(data["revenue"], Decimal("0.00"))
        self.assertEqual(data["accounts_receivable"], Decimal("0.00"))
        self.assertEqual(balance.remaining_live_birds, 20)

    def test_overselling_is_rejected_transactionally(self):
        batch = self.batch(quantity=10)

        with self.assertRaises(ValueError):
            create_sale_with_lifecycle(
                batch_id=batch.id,
                created_by=self.user,
                **self.sale_payload(quantity_sold=11, amount_paid=Decimal("1100.00")),
            )

        self.assertEqual(batch.sales_row.count(), 0)

    def test_input_cost_uses_quantity_unit_and_unit_cost(self):
        batch = self.batch()
        cost = InputCosts.objects.create(
            batch=batch,
            item="Feed",
            category="Feed",
            quantity=2,
            unit=50,
            unit_measurement="kg",
            unit_cost=Decimal("250.50"),
            purchase_date=aware(date(2026, 1, 2)),
            notes="",
            created_by=self.user,
        )

        self.assertEqual(cost.direct_input_total, Decimal("25050.00"))

    def test_sales_balance_and_payment_status_are_consistent(self):
        batch = self.batch()
        sale = create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(
                quantity_sold=2,
                unit_price=Decimal("100.00"),
                amount_paid=Decimal("50.00"),
                payment_status=PaymentStatus.LOAN,
            ),
        )

        self.assertEqual(sale.balance, Decimal("150.00"))
        self.assertEqual(sale.payment_status, PaymentStatus.PARTIAL)

    def test_payroll_snapshot_does_not_change_after_salary_update(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        employee_user = User.objects.create_user(
            username="worker",
            email="worker@example.com",
            password="password",
        )
        employee = EmployeeProfile.objects.create(
            user=employee_user,
            employee_number="EMP-001",
            employment_type=EmploymentType.PERMANENT,
            job_title="Farm hand",
            employment_start_date=date(2025, 1, 1),
            base_monthly_salary=Decimal("100000.00"),
            production_percentage=Decimal("70.00"),
            administration_percentage=Decimal("20.00"),
            selling_percentage=Decimal("10.00"),
            created_by=self.user,
        )

        entry = generate_payroll_for_period(period, created_by=self.user)[0]
        employee.base_monthly_salary = Decimal("150000.00")
        employee.save()
        entry.refresh_from_db()

        self.assertEqual(entry.gross_salary, Decimal("100000.00"))

    def test_permanent_labour_allocates_by_bird_days(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 30),
        )
        batch_a = self.batch(quantity=180, entry=date(2026, 1, 1))
        batch_b = self.batch(quantity=250, entry=date(2026, 1, 11))
        employee_user = User.objects.create_user(
            username="permanent",
            email="permanent@example.com",
            password="password",
        )
        EmployeeProfile.objects.create(
            user=employee_user,
            employee_number="EMP-002",
            employment_type=EmploymentType.PERMANENT,
            job_title="Farm hand",
            employment_start_date=date(2025, 1, 1),
            base_monthly_salary=Decimal("600000.00"),
            production_percentage=Decimal("100.00"),
            administration_percentage=Decimal("0.00"),
            selling_percentage=Decimal("0.00"),
            created_by=self.user,
        )

        generate_payroll_for_period(period, created_by=self.user)
        regenerate_allocations_for_period(period, generated_by=self.user)
        allocations = {
            allocation.batch_id: allocation.allocated_amount
            for allocation in CostAllocation.objects.filter(accounting_period=period)
        }

        self.assertEqual(allocations[batch_a.id], Decimal("311538.46"))
        self.assertEqual(allocations[batch_b.id], Decimal("288461.54"))

    def test_ad_hoc_labour_scope_rules(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 30),
        )
        batch_a = self.batch(quantity=180, entry=date(2026, 1, 1))
        batch_b = self.batch(quantity=250, entry=date(2026, 1, 11))
        AdHocLabourPayment.objects.create(
            worker_name="Direct Worker",
            task_description="Catch birds",
            work_date=date(2026, 1, 20),
            payment_amount=Decimal("1000.00"),
            cost_scope=CostScope.BATCH_DIRECT,
            batch=batch_a,
            accounting_period=period,
            created_by=self.user,
        )
        AdHocLabourPayment.objects.create(
            worker_name="Shared Worker",
            task_description="Clean houses",
            work_date=date(2026, 1, 20),
            payment_amount=Decimal("600000.00"),
            cost_scope=CostScope.SHARED_PRODUCTION,
            accounting_period=period,
            created_by=self.user,
        )
        AdHocLabourPayment.objects.create(
            worker_name="Admin Worker",
            task_description="Office filing",
            work_date=date(2026, 1, 20),
            payment_amount=Decimal("5000.00"),
            cost_scope=CostScope.FARM_ADMINISTRATION,
            accounting_period=period,
            created_by=self.user,
        )

        regenerate_allocations_for_period(period, generated_by=self.user)

        direct = CostAllocation.objects.get(
            ad_hoc_labour_payment__worker_name="Direct Worker"
        )
        shared = {
            allocation.batch_id: allocation.allocated_amount
            for allocation in CostAllocation.objects.filter(
                ad_hoc_labour_payment__worker_name="Shared Worker"
            )
        }

        self.assertEqual(direct.batch_id, batch_a.id)
        self.assertEqual(direct.allocated_amount, Decimal("1000.00"))
        self.assertEqual(shared[batch_a.id], Decimal("311538.46"))
        self.assertEqual(shared[batch_b.id], Decimal("288461.54"))
        self.assertFalse(
            CostAllocation.objects.filter(
                ad_hoc_labour_payment__worker_name="Admin Worker"
            ).exists()
        )

    def test_partial_sales_report_provisional_cost_per_bird(self):
        batch = self.batch(quantity=100)
        InputCosts.objects.create(
            batch=batch,
            item="Feed",
            category="Feed",
            quantity=1,
            unit=100,
            unit_measurement="kg",
            unit_cost=Decimal("10.00"),
            purchase_date=aware(date(2026, 1, 2)),
            notes="",
            created_by=self.user,
        )
        create_sale_with_lifecycle(
            batch_id=batch.id,
            created_by=self.user,
            **self.sale_payload(quantity_sold=10, amount_paid=Decimal("1000.00")),
        )

        data = batch_profitability(batch)

        self.assertEqual(data["profitability_status"], "provisional")
        self.assertEqual(data["provisional_saleable_birds"], 100)
        self.assertEqual(data["provisional_cost_per_saleable_bird"], Decimal("10.00"))

    def test_closed_period_cannot_be_recalculated(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=PeriodStatus.CLOSED,
            closed_at=timezone.now(),
            closed_by=self.user,
        )

        with self.assertRaises(ValueError):
            regenerate_allocations_for_period(period, generated_by=self.user)

    def asset_category(self, **overrides):
        values = {
            "name": "Poultry house",
            "code": "poultry_house",
            "default_useful_life_months": 120,
            "default_production_scope": AssetProductionScope.POULTRY_PRODUCTION,
            "default_allocation_driver": "bird_days",
            "capitalization_threshold": Decimal("0.00"),
        }
        values.update(overrides)
        category, _ = AssetCategory.objects.update_or_create(
            code=values.pop("code"),
            defaults=values,
        )
        return category

    def test_consumable_lot_usage_preserves_stock_and_recognizes_cost(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        batch = self.batch()
        lot = SharedConsumableLot.objects.create(
            item="Disinfectant",
            category="Biosecurity",
            purchase_date=date(2026, 1, 1),
            quantity_purchased=Decimal("30.0000"),
            unit_of_measurement="litres",
            total_purchase_cost=Decimal("3000.00"),
            usd_exchange_rate=Decimal("2000.000000"),
            created_by=self.user,
        )

        usage = record_consumable_usage(
            recorded_by=self.user,
            consumable_lot=lot,
            usage_date=date(2026, 1, 5),
            accounting_period=period,
            quantity_used=Decimal("10.0000"),
            batch=batch,
            usage_scope=ConsumableUsageScope.BATCH_DIRECT,
            allocation_driver="direct",
            task_or_purpose="House disinfection",
        )
        lot.refresh_from_db()

        self.assertEqual(lot.unit_cost, Decimal("100.000000"))
        self.assertEqual(lot.usd_equivalent, Decimal("1.50"))
        self.assertEqual(usage.recognized_cost, Decimal("1000.00"))
        self.assertEqual(lot.quantity_available, Decimal("20.0000"))

    def test_consumable_usage_cannot_exceed_available_stock(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        lot = SharedConsumableLot.objects.create(
            item="Detergent",
            category="Cleaning",
            purchase_date=date(2026, 1, 1),
            quantity_purchased=Decimal("5.0000"),
            unit_of_measurement="litres",
            total_purchase_cost=Decimal("500.00"),
            created_by=self.user,
        )

        with self.assertRaises(ValueError):
            record_consumable_usage(
                recorded_by=self.user,
                consumable_lot=lot,
                usage_date=date(2026, 1, 5),
                accounting_period=period,
                quantity_used=Decimal("6.0000"),
                usage_scope=ConsumableUsageScope.ADMINISTRATION,
                allocation_driver="none",
                task_or_purpose="Office cleaning",
            )

    def test_shared_consumable_usage_allocates_by_bird_days(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 30),
        )
        batch_a = self.batch(quantity=180, entry=date(2026, 1, 1))
        batch_b = self.batch(quantity=250, entry=date(2026, 1, 11))
        lot = SharedConsumableLot.objects.create(
            item="Pest control",
            category="Biosecurity",
            purchase_date=date(2026, 1, 1),
            quantity_purchased=Decimal("10.0000"),
            unit_of_measurement="litres",
            total_purchase_cost=Decimal("600000.00"),
            created_by=self.user,
        )
        usage = record_consumable_usage(
            recorded_by=self.user,
            consumable_lot=lot,
            usage_date=date(2026, 1, 12),
            accounting_period=period,
            quantity_used=Decimal("10.0000"),
            usage_scope=ConsumableUsageScope.SHARED_PRODUCTION,
            allocation_driver="bird_days",
            task_or_purpose="Shared pest control",
        )

        regenerate_allocations_for_period(period, generated_by=self.user)
        allocations = {
            allocation.batch_id: allocation.allocated_amount
            for allocation in CostAllocation.objects.filter(
                accounting_period=period,
                source_type=AllocationSourceType.CONSUMABLE_USAGE,
                consumable_usage=usage,
            )
        }

        self.assertEqual(allocations[batch_a.id], Decimal("311538.46"))
        self.assertEqual(allocations[batch_b.id], Decimal("288461.54"))

    def test_straight_line_depreciation_example(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        category = self.asset_category()
        asset = Asset.objects.create(
            name="Poultry house 1",
            asset_category=category,
            purchase_date=date(2026, 1, 1),
            available_for_use_date=date(2026, 1, 1),
            purchase_price=Decimal("12000000.00"),
            residual_value=Decimal("1200000.00"),
            useful_life_months=120,
            status=AssetStatus.AVAILABLE_FOR_USE,
            created_by=self.user,
        )

        entries = generate_depreciation_for_period(period, generated_by=self.user)

        self.assertEqual(entries[0].asset, asset)
        self.assertEqual(entries[0].period_depreciation, Decimal("90000.00"))

    def test_depreciation_allocation_reconciles_by_bird_days(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 30),
        )
        batch_a = self.batch(quantity=180, entry=date(2026, 1, 1))
        batch_b = self.batch(quantity=250, entry=date(2026, 1, 11))
        category = self.asset_category(code="feeding_equipment", name="Feeding")
        Asset.objects.create(
            name="Feeder set",
            asset_category=category,
            purchase_date=date(2026, 1, 1),
            available_for_use_date=date(2026, 1, 1),
            purchase_price=Decimal("11160000.00"),
            residual_value=Decimal("0.00"),
            useful_life_months=120,
            status=AssetStatus.AVAILABLE_FOR_USE,
            created_by=self.user,
        )

        generate_depreciation_for_period(period, generated_by=self.user)
        regenerate_allocations_for_period(period, generated_by=self.user)
        allocations = {
            allocation.batch_id: allocation.allocated_amount
            for allocation in CostAllocation.objects.filter(
                accounting_period=period,
                source_type=AllocationSourceType.DEPRECIATION,
            )
        }

        self.assertEqual(allocations[batch_a.id], Decimal("46730.77"))
        self.assertEqual(allocations[batch_b.id], Decimal("43269.23"))
        self.assertEqual(sum(allocations.values()), Decimal("90000.00"))

    def test_units_of_production_depreciation_uses_actual_usage(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        category = self.asset_category(code="vehicle", name="Vehicle")
        asset = Asset.objects.create(
            name="Delivery vehicle",
            asset_category=category,
            purchase_date=date(2026, 1, 1),
            available_for_use_date=date(2026, 1, 1),
            purchase_price=Decimal("1000.00"),
            residual_value=Decimal("0.00"),
            useful_life_months=60,
            depreciation_method="units_of_production",
            depreciation_unit="km",
            estimated_total_lifetime_units=Decimal("100.0000"),
            status=AssetStatus.AVAILABLE_FOR_USE,
            created_by=self.user,
        )
        AssetUsageRecord.objects.create(
            asset=asset,
            usage_date=date(2026, 1, 5),
            accounting_period=period,
            usage_unit="km",
            quantity=Decimal("5.0000"),
            recorded_by=self.user,
        )

        entries = generate_depreciation_for_period(period, generated_by=self.user)

        self.assertEqual(entries[0].period_depreciation, Decimal("50.00"))

    def test_capital_expenditure_is_excluded_from_operating_expense(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        SharedExpense.objects.create(
            description="Feeder purchase",
            category="Equipment",
            expense_date=date(2026, 1, 10),
            accounting_period=period,
            amount=Decimal("100000.00"),
            scope=SharedExpenseScope.CAPITAL_EXPENDITURE,
            payment_status=PaymentStatus.PAID,
            created_by=self.user,
        )

        report = monthly_profitability_report(period)

        self.assertEqual(
            report["operating_costs"]["general_operating_expenses"],
            Decimal("0.00"),
        )
        self.assertEqual(
            report["cash_flow"]["capital_expenditure_paid"],
            Decimal("100000.00"),
        )

    def test_replacement_reserve_changes_cash_not_profit(self):
        period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        ReplacementReserveTransaction.objects.create(
            accounting_period=period,
            transaction_date=date(2026, 1, 20),
            transaction_type=ReserveTransactionType.CONTRIBUTION,
            amount=Decimal("50000.00"),
            authorized_by=self.user,
        )

        report = monthly_profitability_report(period)

        self.assertEqual(report["cash_flow"]["reserve_contributions"], Decimal("50000.00"))
        self.assertEqual(report["other_costs"]["net_profit_before_tax"], Decimal("0.00"))


class FinancePermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.period = AccountingPeriod.objects.create(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        for role in RoleChoices:
            Role.objects.create(slug=role, name=role.label)

    def user_with_role(self, username: str, role: RoleChoices):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="password",
        )
        user.roles.add(Role.objects.get(slug=role))
        return user

    def test_stakeholder_is_read_only(self):
        user = self.user_with_role("stakeholder", RoleChoices.STAKE_HOLDER)
        self.client.force_authenticate(user)

        read_response = self.client.get("/api/v1/finance/dashboard")
        write_response = self.client.post(
            "/api/v1/finance/expenses",
            {
                "description": "Office",
                "category": "Admin",
                "expense_date": "2026-01-10",
                "accounting_period": self.period.id,
                "amount": "100.00",
                "scope": "admin_overhead",
            },
            format="json",
        )

        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(write_response.status_code, 403)

    def test_supervisor_cannot_close_period_but_manager_can(self):
        supervisor = self.user_with_role("supervisor", RoleChoices.FARM_SUPERVISOR)
        self.client.force_authenticate(supervisor)
        denied = self.client.post(
            f"/api/v1/finance/accounting-periods/{self.period.id}/close"
        )

        manager = self.user_with_role("manager2", RoleChoices.FARM_MANAGER)
        self.client.force_authenticate(manager)
        allowed = self.client.post(
            f"/api/v1/finance/accounting-periods/{self.period.id}/close"
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
