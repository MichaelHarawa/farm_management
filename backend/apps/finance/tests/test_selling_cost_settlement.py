from datetime import date
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.finance.models import (AccountingPeriod, ChartOfAccount, CostAllocation, Expenditure,
    FinanceActionEvent, FinancialCommandReceipt, FundingAllocation, FundingReceipt, FundingSource,
    FundingSourceType, JournalEntry, PeriodStatus, SaleCostPayment, SalePayment)
from apps.finance.services.financial_capture import (record_financial_sale, record_financial_receipt,
    record_financial_expenditure, record_financial_supplier_payment)
from apps.finance.services.ledger import trial_balance, reverse_journal
from apps.finance.services.profitability import (available_batch_cash, available_funding_source_cash,
    batch_revenue_utilization, funding_source_available_balances, selling_cost_total,
    portfolio_expenditure_funding_mix)
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.services.selling_cost_settlement import (record_sale_cost_payment,
    sale_cost_payment_total, sale_cost_payable_summary)
from apps.finance.tests.test_financial_capture import fixture, instant, sale_payload
from apps.finance.tests import test_financial_capture as financial_fixtures
from apps.poultry.models import Sales, SaleSellingCost


def settlement_fixture(test, cash="200.00"):
    fixture(test)
    data = sale_payload(test)
    data["initial_receipt"] = {"amount": cash, "payment_date": instant(), "payment_method": "cash"}
    record_financial_sale(**data)
    test.source = FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=test.batch)
    data = {**sale_payload(test), "batch_id": test.other_batch.pk,
            "selling_costs": [{"category": "transport", "amount": "100.00", "notes": "Original cost evidence"}]}
    test.sale, _ = record_financial_sale(**data)
    test.cost = test.sale.selling_costs.get()


def payment_payload(test, amount="60.00"):
    return dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", selling_cost_id=test.cost.pk,
        payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": test.source.pk, "amount": amount}],
        payee="Synthetic transporter", payment_method="cash", external_reference="SYNTHETIC-PAYMENT", notes="Not farm records")


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_SALE_COST_SETTLEMENT=True)
class SellingCostSettlementTests(TestCase):
    def setUp(self):
        settlement_fixture(self)

    def test_twenty_partial_and_final_retries_preserve_cost_identity_and_balances(self):
        original = dict(SaleSellingCost.objects.filter(pk=self.cost.pk).values().get())
        request = payment_payload(self)
        rows, created = record_sale_cost_payment(**request)
        self.assertTrue(created)
        receipt = FinancialCommandReceipt.objects.get(pk=request["submission_id"])
        fingerprint, result = receipt.request_hash, receipt.result
        for _ in range(20):
            replay, created = record_sale_cost_payment(**request)
            self.assertFalse(created)
            self.assertEqual([row.pk for row in replay], [row.pk for row in rows])
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("60.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0.00"))
        self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("140.00")})
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        final = {**payment_payload(self, "40.00"), "payment_date": date(2026, 2, 2)}
        record_sale_cost_payment(**final)
        for _ in range(20):
            self.assertFalse(record_sale_cost_payment(**final)[1])
        self.assertEqual(available_batch_cash(self.batch), Decimal("100.00"))
        self.assertEqual(sale_cost_payment_total(self.cost, cutoff=date(2026, 1, 31)), Decimal("60.00"))
        self.assertEqual(sale_cost_payment_total(self.cost), Decimal("100.00"))
        self.assertEqual(SaleCostPayment.objects.count(), 2)
        self.assertEqual(Expenditure.objects.count(), 0)
        self.assertEqual(CostAllocation.objects.count(), 0)
        self.assertEqual(FundingAllocation.objects.count(), 0)
        self.assertEqual(selling_cost_total(self.other_batch), Decimal("100.00"))
        self.assertEqual(dict(SaleSellingCost.objects.filter(pk=self.cost.pk).values().get()), original)
        receipt.refresh_from_db()
        self.assertEqual((receipt.request_hash, receipt.result), (fingerprint, result))
        for row in SaleCostPayment.objects.all():
            journal = JournalEntry.objects.get(source_model="finance.SaleCostPayment", source_identifier=str(row.pk))
            self.assertEqual(journal.posting_date, row.payment_date)
            self.assertEqual(journal.lines.get(account__code="2000").debit, row.amount)
            self.assertEqual(journal.lines.get(account__code="1000").credit, row.amount)
        balance = trial_balance()
        self.assertEqual(balance["debits"], balance["credits"])
        # Replaying the January operation still works after its period closed.
        self.assertFalse(record_sale_cost_payment(**request)[1])
        self.assertEqual(sale_cost_payable_summary(feb.period_end)["total"], Decimal("0.00"))

    def test_changed_amount_date_cost_source_or_evidence_cannot_reuse_operation(self):
        request = payment_payload(self)
        record_sale_cost_payment(**request)
        other = FundingSource.objects.create(source_type="general_farm_cash")
        for change in [{"payment_date": date(2026, 1, 23)}, {"payee": "Different payee"},
                {"payment_method": "bank_transfer"}, {"external_reference": "Changed"}, {"notes": "Changed"},
                {"selling_cost_id": self.cost.pk + 1},
                {"funding_allocations": [{"funding_source": self.source.pk, "amount": "59.00"}]},
                {"funding_allocations": [{"funding_source": other.pk, "amount": "60.00"}]}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_sale_cost_payment(**{**request, **change})
        self.assertEqual(SaleCostPayment.objects.count(), 1)

    def test_split_payment_is_atomic_and_each_source_only_consumes_its_split(self):
        other = FundingSource.objects.create(source_type="general_farm_cash")
        FundingReceipt.objects.create(funding_source=other, amount="30.00", receipt_date=instant(), created_by=self.user)
        request = payment_payload(self)
        request["funding_allocations"] = [{"funding_source": self.source.pk, "amount": "60.00"},
                                         {"funding_source": other.pk, "amount": "20.00"}]
        rows, _ = record_sale_cost_payment(**request)
        self.assertEqual(len(rows), 2)
        self.assertEqual(available_funding_source_cash(other), Decimal("10.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
        self.assertEqual(funding_source_available_balances([self.source, other]),
                         {self.source.pk: Decimal("140.00"), other.pk: Decimal("10.00")})
        self.assertEqual(sale_cost_payable_summary(date(2026, 1, 31))["total"], Decimal("20.00"))

    def test_overpayment_empty_unknown_inactive_and_insufficient_funding_have_zero_effect(self):
        empty = FundingSource.objects.create(source_type="general_farm_cash")
        for funding in [[], [{"funding_source": self.source.pk, "amount": "100.01"}],
                [{"funding_source": empty.pk, "amount": "1.00"}], [{"funding_source": 999999, "amount": "1.00"}]]:
            with self.subTest(funding=funding), self.assertRaises(ValidationError):
                record_sale_cost_payment(**{**payment_payload(self), "funding_allocations": funding})
        self.source.is_active = False
        self.source.save()
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 0)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)

    def test_alias_batch_sources_cannot_double_the_available_cash(self):
        alias = FundingSource.objects.create(source_type="batch_collection", batch=self.batch)
        # Reduce original collections to 50 only inside this owned fixture.
        from .inventory_corruption import corrupt_inventory
        corrupt_inventory(SalePayment, self.batch.sales_row.get().payments.get().pk, amount="50.00")
        request = payment_payload(self)
        request["funding_allocations"] = [{"funding_source": self.source.pk, "amount": "40.00"},
                                         {"funding_source": alias.pk, "amount": "40.00"}]
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**request)
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_batch_source_alias_balances_include_unselected_alias_payments(self):
        alias = FundingSource.objects.create(source_type="batch_collection", batch=self.batch)
        record_sale_cost_payment(**{**payment_payload(self),
            "funding_allocations": [{"funding_source": alias.pk, "amount": "60.00"}]})
        self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("140.00")})
        self.assertEqual(funding_source_available_balances([alias]), {alias.pk: Decimal("140.00")})

    def test_batch_source_alias_balances_include_unselected_expenditure_funding(self):
        alias = FundingSource.objects.create(source_type="batch_collection", batch=self.batch)
        expense, _ = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="60.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "60.00"}], post=True)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=expense.pk, payment_date=date(2026, 1, 22),
            funding_allocations=[{"funding_source": alias.pk, "amount": "60.00"}])
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False):
            self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("140.00")})

    def test_future_or_pre_sale_or_closed_payment_dates_do_not_change_evidence(self):
        for day in [date(2026, 1, 19), date(2099, 1, 1)]:
            with self.subTest(day=day), self.assertRaises(ValidationError):
                record_sale_cost_payment(**{**payment_payload(self), "payment_date": day})
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_later_collection_cannot_fund_backdated_payment(self):
        from .inventory_corruption import corrupt_inventory
        corrupt_inventory(SalePayment, self.batch.sales_row.get().payments.get().pk, payment_date=instant(day=25))
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_later_nonsale_receipt_cannot_fund_backdated_payment(self):
        source = FundingSource.objects.create(source_type="general_farm_cash")
        FundingReceipt.objects.create(funding_source=source, amount="100.00", receipt_date=instant(day=25), created_by=self.user)
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**{**payment_payload(self),
                "funding_allocations": [{"funding_source": source.pk, "amount": "60.00"}]})

    def test_settlement_cash_is_not_available_for_another_expenditure(self):
        record_sale_cost_payment(**payment_payload(self, "100.00"))
        expense, _ = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="101.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "101.00"}], post=True)
        with self.assertRaises(ValidationError):
            record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                expenditure_id=expense.pk, payment_date=date(2026, 1, 23),
                funding_allocations=[{"funding_source": self.source.pk, "amount": "101.00"}])
        self.assertEqual(FundingAllocation.objects.count(), 0)

    def test_missing_chart_or_failure_after_journal_rolls_back_payment_audit_and_receipt(self):
        count = JournalEntry.objects.count()
        for fail in ["account", "audit"]:
            with self.subTest(fail=fail):
                if fail == "account":
                    ChartOfAccount.objects.filter(code="1000").update(is_active=False)
                    with self.assertRaises(ValidationError):
                        record_sale_cost_payment(**payment_payload(self))
                    ChartOfAccount.objects.filter(code="1000").update(is_active=True)
                else:
                    with patch("apps.finance.services.selling_cost_settlement.record_finance_action", side_effect=RuntimeError("synthetic crash")), self.assertRaises(RuntimeError):
                        record_sale_cost_payment(**payment_payload(self))
                self.assertEqual(SaleCostPayment.objects.count(), 0)
                self.assertEqual(JournalEntry.objects.count(), count)
                self.assertEqual(FinancialCommandReceipt.objects.count(), 2)
                self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))

    def test_original_cost_and_sale_economics_mutation_require_review_without_adoption(self):
        from .inventory_corruption import corrupt_inventory
        for model, pk, field, original, changed in [
            (SaleSellingCost, self.cost.pk, "amount", self.cost.amount, Decimal("101.00")),
            (SaleSellingCost, self.cost.pk, "category", self.cost.category, "packaging"),
            (SaleSellingCost, self.cost.pk, "notes", self.cost.notes, "Changed"),
            (Sales, self.sale.pk, "sale_date", self.sale.sale_date, instant(day=21)),
            (Sales, self.sale.pk, "unit_price", self.sale.unit_price, Decimal("101.00"))]:
            with self.assertRaises(DjangoValidationError):
                model.objects.filter(pk=pk).update(**{field: changed})
            corrupt_inventory(model, pk, **{field: changed})
            with self.subTest(field=field), self.assertRaises(ValidationError):
                record_sale_cost_payment(**payment_payload(self))
            corrupt_inventory(model, pk, **{field: original})
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_derived_collection_updates_do_not_change_cost_authorization(self):
        record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=self.sale.pk, amount="50.00", payment_date=instant(day=21), payment_method="cash")
        record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 1)

    def test_cost_parent_rebinding_between_discovery_and_lock_is_refused(self):
        original_lock = Sales.objects.select_for_update
        def rebound(*args, **kwargs):
            from .inventory_corruption import corrupt_inventory
            corrupt_inventory(SaleSellingCost, self.cost.pk, sale=self.batch.sales_row.get().pk)
            return original_lock(*args, **kwargs)
        with patch.object(Sales.objects, "select_for_update", side_effect=rebound), self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.cost.refresh_from_db()
        self.assertEqual(self.cost.sale_id, self.sale.pk)
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_cash_source_rebinding_between_discovery_and_lock_is_refused(self):
        original_lock = FundingSource.objects.select_for_update
        def rebound(*args, **kwargs):
            from .inventory_corruption import corrupt_inventory
            corrupt_inventory(FundingSource, self.source.pk, source_type="owner_capital", batch=None)
            return original_lock(*args, **kwargs)
        with patch.object(FundingSource.objects, "select_for_update", side_effect=rebound), self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.source.refresh_from_db()
        self.assertEqual((self.source.source_type, self.source.batch_id), ("batch_collection", self.batch.pk))
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_disabled_gate_keeps_legacy_reads_away_from_unmigrated_payment_table(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False), CaptureQueriesContext(connection) as captured:
            self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
            self.assertEqual(funding_source_available_balances([self.source]), {self.source.pk: Decimal("200.00")})
            report = monthly_profitability_report(self.period)
            self.assertNotIn("sale_cost_settlement", report)
        self.assertFalse(any("finance_salecostpayment" in query["sql"] for query in captured))

    def test_missing_or_reversed_liability_or_cancelled_sale_cannot_be_paid(self):
        journal = JournalEntry.objects.get(source_model="poultry.SaleSellingCost", source_identifier=str(self.cost.pk))
        # Pre-existing reversed liability fixture ONLY in the owned test DB.
        from .inventory_corruption import corrupt_inventory
        corrupt_inventory(JournalEntry, journal.pk, status="reversed")
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_journal_only_reversal_cannot_bypass_cost_or_cash_source_evidence(self):
        rows, _ = record_sale_cost_payment(**payment_payload(self))
        original = JournalEntry.objects.get(source_model="poultry.SaleSellingCost", source_identifier=str(self.cost.pk))
        payment = JournalEntry.objects.get(source_model="finance.SaleCostPayment", source_identifier=str(rows[0].pk))
        count = JournalEntry.objects.count()
        for journal in [original, payment]:
            with self.subTest(source=journal.source_model), self.assertRaises(ValidationError):
                reverse_journal(journal, posting_date=date(2026, 1, 23), reason="Synthetic rejected reversal", user=self.user)
        self.assertEqual((SaleCostPayment.objects.count(), JournalEntry.objects.count()), (1, count))
        self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
        self.assertEqual(sale_cost_payable_summary(date(2026, 1, 31))["total"], Decimal("40.00"))

    def test_multiple_original_selling_costs_keep_separate_payable_balances(self):
        data = {**sale_payload(self), "batch_id": self.other_batch.pk,
            "selling_costs": [{"category": "packaging", "amount": "5.00"},
                              {"category": "commission", "amount": "15.00"}]}
        sale, _ = record_financial_sale(**data)
        packaging, commission = list(sale.selling_costs.order_by("pk"))
        record_sale_cost_payment(**{**payment_payload(self, "5.00"), "selling_cost_id": packaging.pk})
        self.assertEqual(sale_cost_payment_total(packaging), Decimal("5.00"))
        self.assertEqual(sale_cost_payment_total(commission), Decimal("0.00"))
        self.assertEqual(sale_cost_payable_summary(date(2026, 1, 31))["total"], Decimal("115.00"))
        self.assertEqual(Expenditure.objects.count(), 0)

    def test_cancelled_sale_is_refused_but_original_payable_remains_for_review(self):
        from .inventory_corruption import corrupt_inventory
        corrupt_inventory(Sales, self.sale.pk, payment_status="cancelled")
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        report = sale_cost_payable_summary(date(2026, 1, 31))
        self.assertEqual((report["total"], report["review_required"]), (Decimal("100.00"), 1))

    def test_versionless_earlier_receipt_is_not_rewritten_to_authorize_settlement(self):
        receipt = FinancialCommandReceipt.objects.get(result__sale_id=str(self.sale.pk))
        # Exact earlier schema fixture; privileged SQL ONLY in this owned DB.
        with connection.cursor() as cursor:
            cursor.execute("UPDATE finance_financialcommandreceipt SET result = result - 'selling_cost_versions' WHERE submission_id = %s", [receipt.pk])
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        receipt.refresh_from_db()
        self.assertNotIn("selling_cost_versions", receipt.result)

    def test_exact_money_identifiers_method_classification_and_evidence_are_positive_fields(self):
        for change in [{"currency": "USD"}, {"payment_method": "credit"}, {"payment_method": {}},
                {"payee": " "}, {"payee": None}, {"selling_cost_id": True}, {"selling_cost_id": "1.5"},
                {"external_reference": "x" * 121}, {"notes": "x" * 4001},
                *[{"funding_allocations": [{"funding_source": self.source.pk, "amount": value}]}
                  for value in [1.1, "NaN", "1.001", "-1.00", True]],
                *[{"funding_allocations": [{"funding_source": self.source.pk, "amount": "1.00", "classification": value}]}
                  for value in [{}, [], "owner_drawing", "debt_service"]],
                {"funding_allocations": [{"funding_source": self.source.pk, "amount": "1.00", "journal": []}]}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_sale_cost_payment(**{**payment_payload(self), **change})
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_owner_cash_is_explicitly_unavailable_not_inferred_from_admin_role(self):
        owner = FundingSource.objects.create(source_type="owner_capital")
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**{**payment_payload(self),
                "funding_allocations": [{"funding_source": owner.pk, "amount": "1.00"}]})

    def test_current_roles_rechecked_for_new_payment_and_replay(self):
        request = payment_payload(self)
        record_sale_cost_payment(**request)
        worker = get_user_model().objects.create_user(username="synthetic-cost-worker", email="synthetic-cost-worker@example.invalid")
        with self.assertRaises(PermissionDenied):
            record_sale_cost_payment(**{**payment_payload(self), "user": worker})
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            record_sale_cost_payment(**request)
        self.assertEqual(SaleCostPayment.objects.count(), 1)

    def test_immutable_rows_and_protected_original_source(self):
        rows, _ = record_sale_cost_payment(**payment_payload(self))
        row = rows[0]
        for mutation in [lambda: row.save(), lambda: row.save_base(raw=True), lambda: row.delete(),
                lambda: SaleCostPayment.objects.filter(pk=row.pk).update(amount="1.00"),
                lambda: SaleCostPayment.objects.bulk_update([row], ["amount"]),
                lambda: SaleCostPayment.objects.bulk_create([row]), lambda: SaleCostPayment.objects.all().delete()]:
            with self.assertRaises(DjangoValidationError):
                mutation()
        with self.assertRaises((ProtectedError, DjangoValidationError)):
            self.cost.delete()

    def test_monthly_payable_cash_and_cost_cutoffs_and_utilization_reconcile(self):
        record_sale_cost_payment(**payment_payload(self))
        jan = monthly_profitability_report(self.period)
        feb_period = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        record_sale_cost_payment(**{**payment_payload(self, "40.00"), "payment_date": date(2026, 2, 2)})
        feb = monthly_profitability_report(feb_period)
        self.assertEqual(jan["sale_cost_settlement"]["verified_payables"], Decimal("40.00"))
        self.assertEqual(jan["sale_cost_settlement"]["cash_paid_in_period"], Decimal("60.00"))
        self.assertEqual(jan["operating_costs"]["selling_distribution_costs"], Decimal("100.00"))
        self.assertEqual(feb["sale_cost_settlement"]["verified_payables"], Decimal("0.00"))
        self.assertEqual(feb["sale_cost_settlement"]["cash_paid_in_period"], Decimal("40.00"))
        self.assertEqual(feb["operating_costs"]["selling_distribution_costs"], Decimal("0.00"))
        self.assertEqual(jan["cash_flow"]["operating"]["outflows"], Decimal("60.00"))
        self.assertEqual(feb["cash_flow"]["operating"]["outflows"], Decimal("40.00"))
        self.assertEqual(jan["cash_flow"]["closing_cash"], Decimal("140.00"))
        self.assertEqual((feb["cash_flow"]["opening_cash"], feb["cash_flow"]["closing_cash"]),
                         (Decimal("140.00"), Decimal("100.00")))
        utilization = batch_revenue_utilization(self.batch)
        self.assertEqual((utilization["cash_used"], utilization["available_cash"]), (Decimal("100.00"), Decimal("100.00")))
        self.assertEqual(sum((row["amount"] for row in utilization["transactions"]), Decimal("0.00")), Decimal("100.00"))
        self.assertEqual(utilization["transactions"][-1]["remaining_cash_after"], Decimal("100.00"))

    def test_funding_mix_attributes_payment_to_sale_batch_not_source_batch(self):
        record_sale_cost_payment(**payment_payload(self))
        mix = portfolio_expenditure_funding_mix([self.other_batch], total_attributed_cost=Decimal("100.00"))
        self.assertEqual(mix["total_batch_expenditure"], Decimal("100.00"))
        self.assertEqual(mix["total_paid_for_batches"], Decimal("60.00"))
        groups = {row["key"]: row["amount"] for row in mix["groups"]}
        self.assertEqual((groups["other_batch_sales"], groups["own_batch_sales"], groups["unpaid_or_unassigned"]),
                         (Decimal("60.00"), Decimal("0.00"), Decimal("40.00")))
        source_mix = portfolio_expenditure_funding_mix([self.batch])
        self.assertEqual(source_mix["total_paid_for_batches"], Decimal("0.00"))

    def test_mutated_cost_does_not_remove_original_journal_based_liability(self):
        record_sale_cost_payment(**payment_payload(self))
        from .inventory_corruption import corrupt_inventory
        corrupt_inventory(SaleSellingCost, self.cost.pk, amount="1.00")
        summary = sale_cost_payable_summary(date(2026, 1, 31))
        self.assertEqual((summary["total"], summary["review_required"]), (Decimal("40.00"), 1))

    def test_corrupt_payable_lines_are_not_authority_for_payment(self):
        journal = JournalEntry.objects.get(source_model="poultry.SaleSellingCost", source_identifier=str(self.cost.pk))
        from .inventory_corruption import corrupt_inventory
        line = journal.lines.get(account__code="2000")
        corrupt_inventory(type(line), line.pk, batch=self.batch.pk)
        with self.assertRaises(ValidationError):
            record_sale_cost_payment(**payment_payload(self))
        self.assertEqual(SaleCostPayment.objects.count(), 0)

    def test_false_gate_does_not_touch_new_schema_or_dispatch(self):
        with override_settings(FINANCE_SALE_COST_SETTLEMENT=False):
            with self.assertNumQueries(0), self.assertRaises(ValidationError):
                record_sale_cost_payment(**payment_payload(self))


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False,
                   FINANCE_SALE_COST_SETTLEMENT=True)
class SellingCostSettlementConcurrencyTests(TransactionTestCase):
    race = financial_fixtures.FinancialCaptureConcurrencyTests.race

    def setUp(self):
        settlement_fixture(self, cash="100.00")
        self.assertEqual(connection.vendor, "postgresql")

    def test_same_operation_concurrently_accepts_and_replays_one_original(self):
        request = payment_payload(self, "100.00")
        results = self.race([lambda: record_sale_cost_payment(**request)] * 2)
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "accepted"])
        self.assertEqual(sum(row[1][1] for row in results), 1)
        self.assertEqual(SaleCostPayment.objects.count(), 1)

    def test_different_operations_cannot_pay_last_payable_balance_twice(self):
        request = payment_payload(self, "100.00")
        results = self.race([lambda: record_sale_cost_payment(**{**request, "submission_id": uuid.uuid4()})] * 2)
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual((SaleCostPayment.objects.count(), available_batch_cash(self.batch)), (1, Decimal("0.00")))

    def test_two_costs_compete_for_last_confirmed_cash(self):
        data = {**sale_payload(self), "batch_id": self.other_batch.pk,
                "selling_costs": [{"category": "packaging", "amount": "100.00"}]}
        other, _ = record_financial_sale(**data)
        request = payment_payload(self, "100.00")
        results = self.race([lambda: record_sale_cost_payment(**request), lambda: record_sale_cost_payment(
            **{**request, "submission_id": uuid.uuid4(), "selling_cost_id": other.selling_costs.get().pk})])
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual((SaleCostPayment.objects.count(), available_batch_cash(self.batch)), (1, Decimal("0.00")))

    def test_sale_cost_and_expenditure_compete_for_the_same_cash(self):
        expense, _ = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "100.00"}], post=True)
        request = payment_payload(self, "100.00")
        results = self.race([lambda: record_sale_cost_payment(**request), lambda: record_financial_supplier_payment(
            submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
            payment_date=request["payment_date"], funding_allocations=request["funding_allocations"])])
        self.assertEqual(sorted(row[0] for row in results), ["accepted", "rejected"])
        self.assertEqual(SaleCostPayment.objects.count() + FundingAllocation.objects.count(), 1)
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
