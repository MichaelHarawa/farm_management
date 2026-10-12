"""Dated cash and shared-source races in owned, disposable PostgreSQL only."""
from copy import deepcopy
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.finance.models import (AccountingPeriod, CostAllocation, EmployeeProfile,
    EmploymentType, Expenditure, FinanceActionEvent, FinancialCommandReceipt,
    FundingAllocation, FundingReceipt, FundingSource, FundingSourceType,
    InventoryLocationStock, InventoryLotBinding, InventoryValuePool, JournalEntry,
    JournalLine, OwnerContributor, PayrollPayment, PayrollPaymentFunding, PeriodStatus,
    SaleCostPayment, SharedConsumableLot, StockMovement)
from apps.finance.services.cash_funding import dated_source_cash, lock_cash_sources
from apps.finance.services.expenditure_drafts import post_financial_expenditure_draft
from apps.finance.services.expenditures import post_expenditure, record_expenditure_payment
from apps.finance.services.financial_capture import (record_financial_owner_contribution, record_financial_receipt,
    record_financial_sale, record_financial_supplier_payment)
from apps.finance.services.funding_capture import funding_source_version, record_financial_funding_receipt
from apps.finance.services.funding_reversals import funding_receipt_version, reverse_financial_funding_receipt
from apps.finance.services.inventory_capture import record_inventory_purchase
from apps.finance.services.ledger import trial_balance
from apps.finance.services.payable_evidence import verified_payable
from apps.finance.services.payroll import generate_payroll_for_period
from apps.finance.services.profitability import (available_batch_cash, available_funding_source_cash,
    ensure_batch_funding_source)
from apps.finance.services.sale_cost_reversals import refund_sale_cost_payment, sale_cost_payment_group_version
from apps.finance.services.salary_payments import record_salary_payment
from apps.finance.services.selling_cost_settlement import record_sale_cost_payment
from . import test_expenditure_drafts as drafts
from . import test_financial_capture as fixtures
from . import test_inventory_capture as inventory
from .inventory_corruption import corrupt_inventory

SETTINGS = dict(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False,
    FINANCE_FUNDING_RECEIPTS=False, FINANCE_FUNDING_REVERSALS=False,
    FINANCE_SALE_COST_SETTLEMENT=False, FINANCE_SALE_COST_REVERSALS=False)
MODELS = [Expenditure, CostAllocation, FundingAllocation, JournalEntry, JournalLine,
    FinancialCommandReceipt, FinanceActionEvent, SharedConsumableLot, StockMovement,
    InventoryLotBinding, InventoryLocationStock, InventoryValuePool, PayrollPayment,
    PayrollPaymentFunding, SaleCostPayment]


def snapshot():
    return {model._meta.model_name: list(model.objects.order_by("pk").values()) for model in MODELS}


def setup(test):
    fixtures.fixture(test)
    test.source = drafts.funded_source(test, "100.00")
    test.alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION,
        batch=test.batch, description="Second label for the SAME synthetic batch cash")
    test.expense = drafts.draft(test, expenditure_date=date(2026, 1, 10), post=True)


def payment(test, amount="100.00", **extra):
    return dict(dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", expenditure_id=test.expense.pk,
        payment_date=date(2026, 1, 20), funding_allocations=[{"funding_source": test.source.pk, "amount": amount}]), **extra)


def salary_entry(test):
    EmployeeProfile.objects.create(employee_number="SYNTHETIC-CASH-RACE", employment_type=EmploymentType.PERMANENT,
        first_name="Synthetic", last_name="Cash test", job_title="Synthetic only",
        employment_start_date=date(2025, 1, 1), base_monthly_salary=Decimal("100.00"),
        production_percentage=Decimal("0"), administration_percentage=Decimal("100"),
        selling_percentage=Decimal("0"), created_by=test.user)
    return generate_payroll_for_period(test.period, created_by=test.user)[0]


def salary(test, entry, amount="100.00", rows=None):
    return record_salary_payment(payroll_entry_id=entry.pk, amount=amount,
        payment_date="2026-01-25", payment_method="Cash", user=test.user,
        funding_rows=rows or [{"funding_source": test.alias.pk, "amount": amount}],
        idempotency_key=str(uuid.uuid4()), external_reference="SYNTHETIC-SALARY")


def selling_cost(test):
    sale = record_financial_sale(**{**fixtures.sale_payload(test), "batch_id": test.other_batch.pk,
        "selling_costs": [{"category": "transport", "amount": "100.00"}]})[0]
    return dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", selling_cost_id=sale.selling_costs.get().pk,
        payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": test.alias.pk, "amount": "100.00"}],
        payee="Synthetic transporter", payment_method="cash")


@override_settings(**SETTINGS)
class DatedSupplierCashTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, **changes):
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            record_financial_supplier_payment(**payment(self, **changes))
        self.assertIn("funding_allocations", error.exception.detail)
        self.assertEqual(snapshot(), before)

    def test_later_batch_receipt_cannot_fund_older_supplier_payment(self):
        self.assertEqual(available_batch_cash(self.batch), Decimal("100"))
        self.refused(payment_date=date(2026, 1, 19))
        self.assertTrue(verified_payable(self.expense))
        record_financial_supplier_payment(**payment(self))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))
        self.assertEqual(FundingAllocation.objects.get().allocation_date, date(2026, 1, 20))

    @override_settings(FINANCE_FUNDING_RECEIPTS=True)
    def test_later_loan_receipt_cannot_fund_older_supplier_payment(self):
        self.source = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        record_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            funding_source_id=self.source.pk, source_version=funding_source_version(self.source), amount="100.00",
            receipt_date=fixtures.instant(), counterparty="Synthetic lender", payment_method="bank_transfer",
            reference="SYNTHETIC-LOAN-CASH")
        self.refused(payment_date=date(2026, 1, 19))
        record_financial_supplier_payment(**payment(self))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0"))

    def test_later_owner_contribution_cannot_fund_older_supplier_payment(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic owner")
        receipt = record_financial_owner_contribution(submission_id=uuid.uuid4(), user=self.user,
            currency="MWK", owner_id=owner.pk, amount="100.00", receipt_date=fixtures.instant(),
            reference="SYNTHETIC-OWNER-CASH", designations=[])[0]
        self.source = receipt.funding_source
        self.refused(payment_date=date(2026, 1, 19))
        record_financial_supplier_payment(**payment(self))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("0"))

    def test_future_confirmed_supplier_use_is_reserved_against_earlier_new_payment(self):
        record_financial_supplier_payment(**payment(self, "80", payment_date=date(2026, 1, 25)))
        self.expense = drafts.draft(self, expenditure_date=date(2026, 1, 10), post=True)
        self.refused(amount="30", payment_date=date(2026, 1, 21))
        record_financial_supplier_payment(**payment(self, "20", payment_date=date(2026, 1, 21)))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))
        self.assertEqual(sorted(FundingAllocation.objects.values_list("allocation_date", flat=True)),
            [date(2026, 1, 21), date(2026, 1, 25)])

    def test_partial_early_receipts_are_not_topped_up_by_later_receipts(self):
        sale = self.batch.sales_row.get()
        record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK", sale_id=sale.pk,
            amount="100.00", payment_date=fixtures.instant(day=25), payment_method="cash")
        self.assertEqual(ensure_batch_funding_source(self.batch).pk, self.source.pk)
        self.assertEqual(self.batch.funding_sources.count(), 2)
        self.expense = drafts.draft(self, expenditure_date=date(2026, 1, 10), amount="150.00",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "150.00"}], post=True)
        self.refused(amount="150", payment_date=date(2026, 1, 21))
        record_financial_supplier_payment(**payment(self, "150", payment_date=date(2026, 1, 25)))
        self.assertEqual(available_batch_cash(self.batch), Decimal("50"))

    def test_accounting_day_uses_default_calendar_not_active_display_timezone(self):
        for receipt_day, allowed in [(20, True), (21, False)]:
            with self.subTest(receipt_day=receipt_day), transaction.atomic():
                instant = datetime(2026, 1, receipt_day, 23 if receipt_day == 20 else 0, 30,
                    tzinfo=datetime_timezone.utc)
                record_financial_sale(**{**fixtures.sale_payload(self), "batch_id": self.other_batch.pk,
                    "sale_date": fixtures.instant(day=19),
                    "initial_receipt": {"amount": "100", "payment_date": instant, "payment_method": "cash"}})
                source = FundingSource.objects.get(source_type="batch_collection", batch=self.other_batch)
                rows = [{"funding_source": source.pk, "amount": "100"}]
                with timezone.override("Pacific/Auckland" if allowed else "America/Los_Angeles"):
                    if allowed:
                        record_financial_supplier_payment(**payment(self, funding_allocations=rows))
                    else:
                        self.refused(funding_allocations=rows)
                transaction.set_rollback(True)

    def test_current_payment_works_after_original_expense_period_closes_without_redating(self):
        original = Expenditure.objects.filter(pk=self.expense.pk).values().get()
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        record_financial_supplier_payment(**payment(self, payment_date=date(2026, 2, 2)))
        self.expense.refresh_from_db()
        self.assertEqual((self.expense.expenditure_date, self.expense.amount, self.expense.cost_allocation_plan),
            (original["expenditure_date"], original["amount"], original["cost_allocation_plan"]))
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual(FundingAllocation.objects.get().allocation_date, date(2026, 2, 2))

    def test_closed_actual_payment_date_refuses_without_changing_work(self):
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            record_financial_supplier_payment(**payment(self))
        self.assertIn("period_locked", error.exception.detail)
        self.assertEqual(snapshot(), before)

    def test_two_source_aliases_cannot_each_spend_the_same_cash(self):
        rows = [{"funding_source": self.source.pk, "amount": "60"},
                {"funding_source": self.alias.pk, "amount": "60"}]
        self.expense = drafts.draft(self, amount="120", post=True,
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "120"}])
        self.refused(funding_allocations=rows, payment_date=date(2026, 1, 22))

    def test_valid_alias_splits_and_twenty_retries_keep_one_payment_group_and_original_receipt(self):
        rows = [{"funding_source": self.source.pk, "amount": "60"},
                {"funding_source": self.alias.pk, "amount": "40"}]
        command = payment(self, funding_allocations=rows)
        record_financial_supplier_payment(**command)
        receipt = FinancialCommandReceipt.objects.get(pk=command["submission_id"])
        original = deepcopy((receipt.request_hash, receipt.result, receipt.completed_at))
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**command)[1])
        receipt.refresh_from_db()
        self.assertEqual((receipt.request_hash, receipt.result, receipt.completed_at), original)
        self.assertEqual((FundingAllocation.objects.count(), available_batch_cash(self.batch)), (2, Decimal("0")))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0"))
        self.assertTrue(verified_payable(self.expense))
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("500"), Decimal("500")))
        for change in [{"payment_date": date(2026, 1, 21)}, {"funding_allocations": list(reversed(rows)) + rows}]:
            before = snapshot()
            with self.assertRaises(ValidationError):
                record_financial_supplier_payment(**{**command, **change})
            self.assertEqual(snapshot(), before)

    def test_repeated_rows_for_one_source_are_combined(self):
        rows = [{"funding_source": self.source.pk, "amount": "60"},
                {"funding_source": self.source.pk, "amount": "60"}]
        self.expense = drafts.draft(self, amount="120", post=True,
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "120"}])
        self.refused(funding_allocations=rows, payment_date=date(2026, 1, 22))

    def test_independent_batch_sources_have_independent_cash(self):
        record_financial_sale(**{**fixtures.sale_payload(self), "batch_id": self.other_batch.pk,
            "initial_receipt": {"amount": "100", "payment_date": fixtures.instant(), "payment_method": "cash"}})
        source = FundingSource.objects.get(source_type="batch_collection", batch=self.other_batch)
        record_financial_supplier_payment(**payment(self, funding_allocations=[
            {"funding_source": self.source.pk, "amount": "50"}, {"funding_source": source.pk, "amount": "50"}]))
        self.assertEqual((available_batch_cash(self.batch), available_batch_cash(self.other_batch)),
            (Decimal("50"), Decimal("50")))

    def test_inactive_or_missing_source_does_not_pay(self):
        self.source.is_active = False
        self.source.save(update_fields=["is_active"])
        self.refused()
        self.refused(funding_allocations=[{"funding_source": self.source.pk + 1000000, "amount": "100"}])

    def test_binding_change_while_waiting_for_cash_lock_refuses_and_rolls_back(self):
        original = FundingSource.objects.select_for_update
        def rebound(*args, **kwargs):
            corrupt_inventory(FundingSource, self.source.pk, batch=self.other_batch.pk)
            return original(*args, **kwargs)
        with patch.object(FundingSource.objects, "select_for_update", side_effect=rebound):
            self.refused()
        self.source.refresh_from_db()
        self.assertEqual(self.source.batch_id, self.batch.pk)

    def test_lock_family_includes_every_alias_in_pk_order_and_is_bounded(self):
        extra = FundingSource.objects.create(source_type="batch_collection", batch=self.batch)
        with CaptureQueriesContext(connection) as captured:
            sources = lock_cash_sources([extra.pk, self.alias.pk])
        self.assertEqual(set(sources), {extra.pk, self.alias.pk})
        locks = [q["sql"] for q in captured if "FOR UPDATE" in q["sql"]]
        self.assertEqual(len(locks), 1)
        self.assertIn('ORDER BY "finance_fundingsource"."id" ASC', locks[0])
        self.assertIn(str(self.source.pk), locks[0])
        with patch("apps.finance.services.cash_funding.MAX_CASH_SOURCES", 2), self.assertRaises(ValidationError):
            lock_cash_sources([self.alias.pk])

    def test_owner_permission_and_classification_checks_are_preserved(self):
        source = FundingSource.objects.create(source_type="owner_capital")
        FundingReceipt.objects.create(funding_source=source, amount="100", receipt_date=fixtures.instant(), created_by=self.user)
        worker = get_user_model().objects.create_user(username="synthetic-no-owner-access", email="no-owner@synthetic.test")
        from apps.finance.services.expenditures import _validate_payment_rows
        with self.assertRaises(PermissionDenied):
            _validate_payment_rows([{"funding_source": source.pk, "amount": "10"}], Decimal("100"),
                allow_less=True, user=worker, payment_date=date(2026, 1, 20))
        self.refused(funding_allocations=[{"funding_source": self.source.pk, "amount": "100", "classification": "owner_drawing"}])
        self.refused(funding_allocations=[{"funding_source": self.source.pk, "amount": "100", "classification": "not-a-class"}])

    def test_flags_off_reads_never_query_new_sale_cost_or_reversal_tables(self):
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(dated_source_cash(self.source, date(2026, 1, 20)), Decimal("100"))
            record_financial_supplier_payment(**payment(self))
        self.assertFalse(any(any(name in q["sql"] for name in ["finance_salecostpayment", "finance_fundingreceiptreversal"])
            for q in captured))

    def test_legacy_supplier_payment_keeps_existing_date_policy_but_groups_alias_splits(self):
        expense = Expenditure.objects.create(expenditure_date=date(2026, 1, 10), amount="120", category=self.category,
            accounting_nature="direct_cost", description="Synthetic legacy service", payee="Synthetic supplier",
            cost_allocation_plan=[{"batch": self.other_batch.pk, "amount": "120"}], created_by=self.user)
        post_expenditure(expenditure_id=expense.pk, user=self.user, funding_rows=[], allow_unpaid=True)
        before = snapshot()
        with self.assertRaises(ValidationError):
            record_expenditure_payment(expenditure_id=expense.pk, user=self.user, payment_group_key="legacy-aliased",
                payment_date=date(2026, 1, 19), funding_rows=[{"funding_source": self.source.pk, "amount": "60"},
                    {"funding_source": self.alias.pk, "amount": "60"}])
        self.assertEqual(snapshot(), before)
        record_expenditure_payment(expenditure_id=expense.pk, user=self.user, payment_group_key="legacy-earlier-date",
            payment_date=date(2026, 1, 19), funding_rows=[{"funding_source": self.alias.pk, "amount": "100"}])
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))
        self.assertEqual(FundingAllocation.objects.get().allocation_date, date(2026, 1, 19))

    def test_salary_splits_share_batch_cash_and_future_salary_use_is_reserved(self):
        entry = salary_entry(self)
        entry.gross_salary = Decimal("120")
        entry.save()
        before = snapshot()
        with self.assertRaises(ValidationError):
            salary(self, entry, "120", [{"funding_source": self.source.pk, "amount": "60"},
                {"funding_source": self.alias.pk, "amount": "60"}])
        self.assertEqual(snapshot(), before)
        salary(self, entry, "80")
        self.refused(amount="30")
        record_financial_supplier_payment(**payment(self, "20"))
        self.assertEqual((available_batch_cash(self.batch), PayrollPaymentFunding.objects.count(), FundingAllocation.objects.count()),
            (Decimal("0"), 1, 1))

    @override_settings(FINANCE_SALE_COST_SETTLEMENT=True)
    def test_future_selling_cost_use_through_an_alias_is_reserved(self):
        command = selling_cost(self)
        command["funding_allocations"][0]["amount"] = "80"
        record_sale_cost_payment(**command)
        self.refused(amount="30")
        record_financial_supplier_payment(**payment(self, "20"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))

    @override_settings(FINANCE_SALE_COST_SETTLEMENT=True, FINANCE_SALE_COST_REVERSALS=True)
    def test_actual_refund_reopens_cash_only_on_its_actual_date(self):
        command = selling_cost(self)
        payments = record_sale_cost_payment(**command)[0]
        anchor = FinancialCommandReceipt.objects.get(pk=command["submission_id"])
        refund_sale_cost_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            original_submission_id=command["submission_id"], source_version=sale_cost_payment_group_version(anchor, payments),
            refund_date=date(2026, 1, 25), refund_method="cash", external_reference="SYNTHETIC-REFUND", reason="Actual refund")
        self.refused(payment_date=date(2026, 1, 24))
        record_financial_supplier_payment(**payment(self, payment_date=date(2026, 1, 25)))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))

    @override_settings(FINANCE_FUNDING_RECEIPTS=True, FINANCE_FUNDING_REVERSALS=True)
    def test_committed_loan_correction_is_reserved_even_for_earlier_payment(self):
        self.source = FundingSource.objects.create(source_type="loan")
        receipt = record_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            funding_source_id=self.source.pk, source_version=funding_source_version(self.source), amount="100",
            receipt_date=fixtures.instant(), counterparty="Synthetic lender", payment_method="cash", reference="LOAN")[0]
        reverse_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK", receipt_id=receipt.pk,
            source_version=funding_receipt_version(receipt), reversal_date=date(2026, 1, 25), reason="Actual cash returned")
        self.refused()
        self.assertEqual(dated_source_cash(self.source, date(2026, 1, 20)), Decimal("0"))


@override_settings(**SETTINGS)
class InitialDatedCashRollbackTests(TestCase):
    def setUp(self):
        inventory.inventory_fixture(self)
        self.source = drafts.funded_source(self, "100.00")

    def test_initial_expense_rolls_back_posting_cost_cash_audit_and_receipt(self):
        before = snapshot()
        with self.assertRaises(ValidationError):
            drafts.draft(self, expenditure_date=date(2026, 1, 10), post=True,
                funding_allocations=[{"funding_source": self.source.pk, "amount": "100"}], payment_date=date(2026, 1, 19))
        self.assertEqual(snapshot(), before)

    def test_versioned_draft_post_failure_preserves_exact_original_draft(self):
        expense = drafts.draft(self, expenditure_date=date(2026, 1, 10))
        command = drafts.posting(self, expense, funding_allocations=[{"funding_source": self.source.pk, "amount": "100"}],
            payment_date=date(2026, 1, 19))
        before = snapshot()
        with self.assertRaises(ValidationError):
            post_financial_expenditure_draft(**command)
        self.assertEqual(snapshot(), before)

    def test_paid_stock_receipt_failure_leaves_no_lot_movement_pool_or_payable(self):
        before = snapshot()
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**inventory.purchase(self,
                funding_allocations=[{"funding_source": self.source.pk, "amount": "100"}], payment_date=date(2026, 1, 19)))
        self.assertEqual(snapshot(), before)
        self.assertEqual(available_batch_cash(self.batch), Decimal("100"))


def race(test, calls):
    barrier, results = Barrier(len(calls)), []
    def run(call):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            call()
            results.append("accepted")
        except ValidationError:
            results.append("rejected")
        except Exception as error:
            results.append(type(error).__name__)
        finally:
            close_old_connections()
    threads = [Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=25)
        test.assertFalse(thread.is_alive())
    return results


@override_settings(**SETTINGS)
class SharedCashConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_different_payables_with_different_aliases_cannot_double_spend(self):
        other = drafts.draft(self, expenditure_date=date(2026, 1, 10), post=True)
        first = payment(self)
        second = payment(self, expenditure_id=other.pk, funding_allocations=[{"funding_source": self.alias.pk, "amount": "100"}])
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**first),
            lambda: record_financial_supplier_payment(**second)]), ["accepted", "rejected"])
        self.assertEqual((FundingAllocation.objects.count(), available_batch_cash(self.batch)), (1, Decimal("0")))

    def test_supplier_and_salary_using_different_aliases_compete_for_one_pool(self):
        entry = salary_entry(self)
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**payment(self)),
            lambda: salary(self, entry)]), ["accepted", "rejected"])
        self.assertEqual(FundingAllocation.objects.count() + PayrollPaymentFunding.objects.count(), 1)
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))

    @override_settings(FINANCE_SALE_COST_SETTLEMENT=True)
    def test_supplier_and_selling_cost_using_different_aliases_compete_for_one_pool(self):
        command = selling_cost(self)
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**payment(self)),
            lambda: record_sale_cost_payment(**command)]), ["accepted", "rejected"])
        self.assertEqual(FundingAllocation.objects.count() + SaleCostPayment.objects.count(), 1)
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))

    def test_same_intent_replays_once_even_with_alias_splits(self):
        command = payment(self, funding_allocations=[{"funding_source": self.source.pk, "amount": "50"},
            {"funding_source": self.alias.pk, "amount": "50"}])
        self.assertCountEqual(race(self, [lambda: record_financial_supplier_payment(**command)] * 2), ["accepted", "accepted"])
        self.assertEqual(FundingAllocation.objects.count(), 2)
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=command["submission_id"]).count(), 1)
        self.assertEqual(available_batch_cash(self.batch), Decimal("0"))

    def test_source_lock_requires_atomic_payment_transaction(self):
        with self.assertRaises(ValidationError):
            lock_cash_sources([self.source.pk])

    def test_dated_supplier_payment_does_not_publish_to_operational_sync(self):
        from apps.mobile_sync.models import SyncChange, SyncStreamState
        from apps.mobile_sync.writers import sync_boundary
        SyncStreamState.objects.get_or_create(pk=1)
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary():
            record_financial_supplier_payment(**payment(self))
        self.assertEqual(SyncChange.objects.count(), 0)

    def test_first_batch_source_creation_is_serialized_without_duplicate_aliases(self):
        ids = []
        self.assertCountEqual(race(self, [lambda: ids.append(ensure_batch_funding_source(self.other_batch).pk)] * 2),
            ["accepted", "accepted"])
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.other_batch.funding_sources.count(), 1)
