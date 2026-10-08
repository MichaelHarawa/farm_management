from datetime import date, datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier, Thread
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.finance.models import (AccountingNature, AccountingPeriod, ChartOfAccount, CostAllocation,
    Expenditure, ExpenditureCategory, FinancialCommandReceipt, FundingAllocation, FundingReceipt,
    FundingSource, FundingSourceType, JournalEntry, JournalLine, OwnerContributor, PeriodStatus, SalePayment)
from apps.finance.services.collections import record_sale_payment
from apps.finance.services.financial_capture import (record_financial_sale, record_financial_receipt,
    record_financial_expenditure, record_financial_supplier_payment, record_financial_owner_contribution)
from apps.finance.services.financial_values import exact_decimal
from apps.finance.services.ledger import post_journal, reverse_journal, trial_balance
from apps.finance.services.profitability import available_batch_cash, available_funding_source_cash
from apps.poultry.models import Batch, Sales, SaleSellingCost


def instant(month=1, day=20):
    return datetime(2026, month, day, 12, tzinfo=datetime_timezone.utc)


def fixture(test):
    # TransactionTestCase flush removes seed data between cases. Restore only
    # the existing chart definitions inside the owned test DB, never production.
    from importlib import import_module
    for code, name, account_type, normal_balance, control_type in import_module(
            "apps.finance.migrations.0021_seed_chart_and_reporting_policy").ACCOUNTS:
        ChartOfAccount.objects.get_or_create(code=code, defaults=dict(name=name, account_type=account_type,
            normal_balance=normal_balance, control_type=control_type))
    test.user = get_user_model().objects.create_superuser(username="phase6-synthetic-admin", password="synthetic-only")
    test.period = AccountingPeriod.objects.create(period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    test.batch = Batch.objects.create(bird_type="broilers", source="proto", entry_date=instant(day=1),
        expected_maturity_date=instant(day=15), quantity=10, created_by=test.user)
    test.other_batch = Batch.objects.create(bird_type="broilers", source="proto", entry_date=instant(day=1),
        expected_maturity_date=instant(day=15), quantity=10, created_by=test.user)
    test.category = ExpenditureCategory.objects.create(name="Phase6 non-stock direct service", code="phase6_service",
        default_accounting_nature=AccountingNature.DIRECT_COST)


def sale_payload(test):
    return dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", batch_id=test.batch.pk,
        sale_date=instant(), product_type="live_chicken", quantity_sold=2, unit_price="100.00",
        buyer_name="Synthetic buyer", buyer_type="retail", sold_by_name="Synthetic supervisor",
        receivable_follow_up_name="Synthetic collector", notes="Not farm records")


class ExactFinancialValueTests(SimpleTestCase):
    def test_captured_money_never_rounds_or_uses_floating_point(self):
        self.assertEqual(exact_decimal("1.10"), Decimal("1.10"))
        for value in ["NaN", "Infinity", "-Infinity", "-0.01", "1.001", True, 1.1, None, "1000000000000.00"]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                exact_decimal(value)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class FinancialCaptureTests(TestCase):
    def setUp(self):
        fixture(self)

    def test_twenty_sale_retries_create_one_sale_cost_set_receipt_and_journal_set(self):
        payload = sale_payload(self)
        payload.update(selling_costs=[{"category": "transport", "amount": "15.00"},
                                     {"category": "packaging", "amount": "5.00"}],
            initial_receipt={"amount": "80.00", "payment_date": instant(), "payment_method": "cash"})
        original, created = record_financial_sale(**payload)
        self.assertTrue(created)
        for _ in range(20):
            replay, created = record_financial_sale(**payload)
            self.assertFalse(created)
            self.assertEqual(replay.pk, original.pk)
        self.assertEqual((Sales.objects.count(), SaleSellingCost.objects.count(), SalePayment.objects.count()), (1, 2, 1))
        self.assertEqual((JournalEntry.objects.count(), JournalLine.objects.count(), FinancialCommandReceipt.objects.count()), (4, 8, 1))
        original.refresh_from_db()
        self.assertEqual((original.sale_total, original.amount_paid, original.balance),
                         (Decimal("200.00"), Decimal("80.00"), Decimal("120.00")))
        self.assertEqual(available_batch_cash(self.batch), Decimal("80.00"))
        # Selling costs are the existing source, not duplicate input expenditures.
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count()), (0, 0))
        balance = trial_balance()
        self.assertEqual(balance["debits"], Decimal("300.00"))
        self.assertEqual(balance["credits"], balance["debits"])
        for change in [{"unit_price": "101.00"}, {"batch_id": self.other_batch.pk},
                       {"sale_date": instant(day=21)}, {"buyer_name": "Changed"},
                       {"selling_costs": [{"category": "transport", "amount": "19.00"}]}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_sale(**{**payload, **change})
        self.assertEqual(JournalEntry.objects.count(), 4)

    def test_sale_atomic_rollback_includes_receipt_costs_flock_and_claim(self):
        payload = sale_payload(self)
        payload.update(selling_costs=[{"category": "transport", "amount": "10.00"}],
            initial_receipt={"amount": "201.00", "payment_date": instant(), "payment_method": "cash"})
        with self.assertRaises(ValidationError):
            record_financial_sale(**payload)
        self.assertEqual((Sales.objects.count(), SalePayment.objects.count(), SaleSellingCost.objects.count(),
                          JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (0, 0, 0, 0, 0))
        # A missing journal account also rolls back the earlier source records.
        ChartOfAccount.objects.filter(code="4000").update(is_active=False)
        payload["initial_receipt"]["amount"] = "50.00"
        with self.assertRaises(ValidationError):
            record_financial_sale(**payload)
        self.assertEqual((Sales.objects.count(), JournalEntry.objects.count()), (0, 0))

    def test_optional_sale_note_is_empty_evidence_not_fabricated_text(self):
        payload = sale_payload(self)
        payload.pop("notes")
        sale, _ = record_financial_sale(**payload)
        self.assertEqual(sale.notes, "")

    def test_current_receipt_for_closed_older_sale_uses_actual_receipt_date(self):
        sale, _ = record_financial_sale(**sale_payload(self))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", sale_id=sale.pk,
            amount="50.00", payment_date=instant(month=2, day=2), payment_method="cash", external_reference="TEST-RECEIPT")
        payment, _ = record_financial_receipt(**payload)
        for _ in range(20):
            replay, created = record_financial_receipt(**payload)
            self.assertEqual(replay.pk, payment.pk)
            self.assertFalse(created)
        journal = JournalEntry.objects.get(source_model="finance.SalePayment", source_identifier=str(payment.pk))
        self.assertEqual(journal.posting_date, date(2026, 2, 2))
        self.assertEqual(SalePayment.objects.count(), 1)
        for change in [{"amount": "51.00"}, {"payment_date": instant(month=2, day=3)},
                       {"external_reference": "Changed"}, {"payment_method": "bank_transfer"}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_receipt(**{**payload, **change})
        with self.assertRaises(ValidationError):
            record_financial_receipt(**{**payload, "submission_id": uuid.uuid4(), "payment_date": instant()})
        self.assertEqual(SalePayment.objects.count(), 1)

    def test_shared_receipt_replay_detects_amount_date_and_evidence_changes(self):
        sale, _ = record_financial_sale(**sale_payload(self))
        payload = dict(sale_id=sale.pk, amount=Decimal("50.00"), payment_date=instant(),
            payment_method="cash", created_by=self.user, idempotency_key="shared-receipt-proof")
        original, _ = record_sale_payment(**payload)
        self.assertEqual(record_sale_payment(**payload)[0].pk, original.pk)
        for change in [{"amount": Decimal("49.00")}, {"payment_date": instant(day=21)},
                       {"notes": "Changed"}, {"external_reference": "Changed"}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_sale_payment(**{**payload, **change})
        self.assertEqual(SalePayment.objects.count(), 1)

    def make_spending(self, **extra):
        return record_financial_expenditure(**dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic cleaning service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "100.00"}], post=True, **extra))[0]

    def test_funding_origin_does_not_become_cost_bearer_or_second_expense(self):
        sale_data = sale_payload(self)
        sale_data["initial_receipt"] = {"amount": "200.00", "payment_date": instant(), "payment_method": "cash"}
        record_financial_sale(**sale_data)
        source = FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch)
        expense = self.make_spending()
        self.assertEqual(expense.payment_status, "unpaid")
        self.assertEqual(available_batch_cash(self.batch), Decimal("200.00"))
        pay = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", expenditure_id=expense.pk,
            payment_date=date(2026, 1, 22), funding_allocations=[{"funding_source": source.pk, "amount": "60.00"}])
        record_financial_supplier_payment(**pay)
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**pay)[1])
        for change in [{"payment_date": date(2026, 1, 23)},
                       {"funding_allocations": [{"funding_source": source.pk, "amount": "59.00"}]}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_financial_supplier_payment(**{**pay, **change})
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), FundingAllocation.objects.count()), (1, 1, 1))
        cost = CostAllocation.objects.get(expenditure=expense)
        self.assertEqual((cost.batch_id, cost.allocated_amount), (self.other_batch.pk, Decimal("100.00")))
        self.assertEqual(available_batch_cash(self.batch), Decimal("140.00"))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0.00"))
        expense.refresh_from_db()
        self.assertEqual(expense.payment_status, "partial")
        expense_journal = JournalEntry.objects.get(source_model="finance.Expenditure", source_identifier=str(expense.pk))
        self.assertEqual(expense_journal.lines.get(debit__gt=0).debit, Decimal("100.00"))
        self.assertEqual(JournalEntry.objects.filter(source_model="finance.FundingAllocation").count(), 1)

    def test_initial_payment_rollback_keeps_cash_and_payable_unchanged(self):
        source = FundingSource.objects.create(source_type=FundingSourceType.GENERAL_FARM_CASH)
        with self.assertRaises(ValidationError):
            self.make_spending(funding_allocations=[{"funding_source": source.pk, "amount": "1.00"}],
                               payment_date=date(2026, 1, 21))
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), FundingAllocation.objects.count(),
                          JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (0, 0, 0, 0, 0))

    def test_owner_equity_and_designation_do_not_create_revenue_or_cost(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic owner")
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", owner_id=owner.pk,
            amount="500.00", receipt_date=instant(), reference="SYNTHETIC-CAPITAL",
            designations=[{"batch": self.batch.pk, "amount": "300.00"}])
        receipt, _ = record_financial_owner_contribution(**payload)
        for _ in range(20):
            self.assertFalse(record_financial_owner_contribution(**payload)[1])
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(), CostAllocation.objects.count()), (1, 1, 0))
        self.assertEqual(available_funding_source_cash(receipt.funding_source), Decimal("500.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
        self.assertEqual(receipt.owner_designations.count(), 1)
        self.assertFalse(JournalLine.objects.filter(account__code="4000").exists())

    def test_owner_designation_rejects_rounding_before_legacy_helper(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic exact designation owner")
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", owner_id=owner.pk,
            amount="500.00", receipt_date=instant())
        for value in ["300.001", 300.1, True, "NaN", None]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                record_financial_owner_contribution(**payload,
                    designations=[{"batch": self.batch.pk, "amount": value}])
        for value in [False, "x" * 256]:
            with self.subTest(source_description=value), self.assertRaises(ValidationError):
                record_financial_owner_contribution(**payload, source_description=value)
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(),
                          FinancialCommandReceipt.objects.count()), (0, 0, 0))

    def test_nested_capture_is_bounded_and_ids_are_not_truncated(self):
        payload = sale_payload(self)
        for invalid in [True, 1.9, "-1", "1.0", None, "9223372036854775808"]:
            with self.subTest(identifier=invalid), self.assertRaises(ValidationError):
                record_financial_sale(**{**payload, "batch_id": invalid})
        for rows in [{}, "not rows", [None], [{"category": "transport", "amount": "1.00"}] * 51,
                     [{"category": "transport", "amount": "1.00", "notes": {"untrusted": "text"}}]]:
            with self.subTest(rows=rows), self.assertRaises(ValidationError):
                record_financial_sale(**{**payload, "selling_costs": rows})
        for rows in [[{"amount": "100.00"}], [{"batch": 1.9, "amount": "100.00"}], "not rows"]:
            with self.subTest(costs=rows), self.assertRaises(ValidationError):
                record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                    expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
                    accounting_nature="direct_cost", description="Invalid nested synthetic evidence", payee="Synthetic",
                    cost_allocations=rows)
        self.assertEqual((Sales.objects.count(), Expenditure.objects.count(),
                          FinancialCommandReceipt.objects.count()), (0, 0, 0))

    def test_owner_offset_instant_uses_same_utc_calendar_for_locks_and_journal(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic timezone owner")
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        at = datetime(2026, 2, 1, 0, 30, tzinfo=datetime_timezone(timedelta(hours=2)))
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency="MWK", owner_id=owner.pk,
            amount="100.00", receipt_date=at)
        with self.assertRaises(ValidationError) as caught:
            record_financial_owner_contribution(**payload)
        self.assertIn("period_locked", caught.exception.detail)
        self.assertEqual(FundingReceipt.objects.count(), 0)
        self.period.status = PeriodStatus.OPEN
        self.period.save()
        receipt, _ = record_financial_owner_contribution(**payload)
        self.assertEqual(receipt.receipt_date, at.astimezone(datetime_timezone.utc))
        self.assertEqual(JournalEntry.objects.get(source_identifier=str(receipt.pk)).posting_date, date(2026, 1, 31))

    def test_current_role_and_currency_are_checked_even_on_replay(self):
        payload = sale_payload(self)
        record_financial_sale(**payload)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            record_financial_sale(**payload)
        with self.assertRaises(ValidationError):
            record_financial_sale(**{**payload, "currency": "USD"})
        self.assertEqual(Sales.objects.count(), 1)

    def test_receipt_model_is_immutable_and_failed_capture_leaves_no_claim(self):
        record_financial_sale(**sale_payload(self))
        receipt = FinancialCommandReceipt.objects.get()
        with self.assertRaises(DjangoValidationError):
            receipt.save()
        with self.assertRaises(DjangoValidationError):
            receipt.delete()
        replacement = FinancialCommandReceipt(submission_id=receipt.pk, actor=self.user,
            command=receipt.command, request_hash="0" * 64, result={"sale_id": "999"}, completed_at=receipt.completed_at)
        with self.assertRaises(DjangoValidationError):
            replacement.save(force_update=True)
        receipt.refresh_from_db()
        self.assertNotEqual(receipt.request_hash, replacement.request_hash)
        with self.assertRaises(DjangoValidationError):
            FinancialCommandReceipt.objects.filter(pk=receipt.pk).update(result={"sale_id": "999"})
        with self.assertRaises(DjangoValidationError):
            FinancialCommandReceipt.objects.all().delete()

    def test_journal_replay_matches_all_posting_content_and_reversal_nets_zero(self):
        payload = dict(posting_date=date(2026, 1, 20), description="Synthetic balance", source_model="test.Source",
            source_identifier="1", idempotency_key="phase6-journal-proof", user=self.user,
            lines=[{"account": "1000", "debit": "75.00"}, {"account": "3000", "credit": "75.00"}])
        entry = post_journal(**payload)
        for _ in range(20):
            self.assertEqual(post_journal(**payload).pk, entry.pk)
        for change in [{"posting_date": date(2026, 1, 21)}, {"source_identifier": "2"},
                       {"lines": [{"account": "1000", "debit": "76.00"}, {"account": "3000", "credit": "76.00"}]}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                post_journal(**{**payload, **change})
        reverse_journal(entry, posting_date=date(2026, 1, 22), reason="Synthetic correction", user=self.user)
        self.assertTrue(all(row["balance"] == Decimal("0.00") for row in trial_balance()["accounts"]))
        historical = {row["code"]: row["balance"] for row in trial_balance(cutoff=date(2026, 1, 21))["accounts"]}
        self.assertEqual(historical["1000"], Decimal("75.00"))

    def test_unposted_draft_has_no_payable_cash_cost_or_journal_effect(self):
        expense, created = record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic draft", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "100.00"}])
        self.assertTrue(created)
        self.assertEqual(expense.status, "draft")
        self.assertEqual((CostAllocation.objects.count(), FundingAllocation.objects.count(), JournalEntry.objects.count()), (0, 0, 0))

    def test_source_cost_shares_must_sum_exactly_and_period_dates_are_not_shifted(self):
        with self.assertRaises(ValidationError):
            record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
                accounting_nature="direct_cost", description="Bad synthetic shares", payee="Synthetic supplier",
                cost_allocations=[{"batch": self.batch.pk, "amount": "99.99"}], post=True)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError) as caught:
            self.make_spending()
        self.assertIn("period_locked", caught.exception.detail)
        self.assertEqual((Expenditure.objects.count(), FinancialCommandReceipt.objects.count()), (0, 0))

    def test_receipt_midnight_matches_existing_utc_finance_calendar_not_phone_display(self):
        sale, _ = record_financial_sale(**sale_payload(self))
        at = datetime(2026, 1, 31, 22, 30, tzinfo=datetime_timezone.utc)  # Feb1 on the farm display.
        payment, _ = record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=sale.pk, amount="10.00", payment_date=at, payment_method="cash")
        journal = JournalEntry.objects.get(source_model="finance.SalePayment", source_identifier=str(payment.pk))
        self.assertEqual(payment.payment_date, at)
        self.assertEqual(journal.posting_date, date(2026, 1, 31))


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class FinancialCaptureConcurrencyTests(TransactionTestCase):
    def setUp(self):
        fixture(self)
        self.assertEqual(connection.vendor, "postgresql", "Only PostgreSQL can establish these lock guarantees.")

    def race(self, functions):
        barrier = Barrier(len(functions))
        results = []
        def work(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(("accepted", function()))
            except (ValidationError, PermissionDenied, DjangoValidationError, ValueError) as error:
                results.append(("rejected", getattr(error, "detail", type(error).__name__)))
            except Exception as error:
                results.append(("unexpected", type(error).__name__))
            finally:
                close_old_connections()
        threads = [Thread(target=work, args=(function,)) for function in functions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive(), "Financial lock did not finish within the test bound.")
        self.assertFalse(any(result[0] == "unexpected" for result in results), results)
        return results

    def test_same_financial_submission_races_commit_one_effect(self):
        payload = sale_payload(self)
        outcomes = self.race([lambda: record_financial_sale(**payload)] * 2)
        self.assertEqual([row[0] for row in outcomes], ["accepted", "accepted"])
        self.assertEqual(sum(row[1][1] for row in outcomes), 1)
        self.assertEqual((Sales.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (1, 1, 1))

    def test_last_birds_cannot_be_sold_twice(self):
        first = {**sale_payload(self), "quantity_sold": 10}
        second = {**first, "submission_id": uuid.uuid4()}
        outcomes = self.race([lambda: record_financial_sale(**first), lambda: record_financial_sale(**second)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(list(Sales.objects.values_list("quantity_sold", flat=True)), [10])

    def test_last_receivable_balance_cannot_be_collected_twice(self):
        sale, _ = record_financial_sale(**sale_payload(self))
        pay = dict(user=self.user, currency="MWK", sale_id=sale.pk, amount="200.00", payment_date=instant(), payment_method="cash")
        outcomes = self.race([lambda: record_financial_receipt(submission_id=uuid.uuid4(), **pay)] * 2)
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(list(SalePayment.objects.values_list("amount", flat=True)), [Decimal("200.00")])

    def test_last_confirmed_source_cash_cannot_fund_two_payables(self):
        payload = sale_payload(self)
        payload["initial_receipt"] = {"amount": "100.00", "payment_date": instant(), "payment_method": "cash"}
        record_financial_sale(**payload)
        source = FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch)
        expenses = [record_financial_expenditure(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_date=date(2026, 1, 21), amount="100.00", category_id=self.category.pk,
            accounting_nature="direct_cost", description="Synthetic service", payee="Synthetic supplier",
            cost_allocations=[{"batch": self.other_batch.pk, "amount": "100.00"}], post=True)[0] for _ in range(2)]
        pay = dict(user=self.user, currency="MWK", payment_date=date(2026, 1, 22),
            funding_allocations=[{"funding_source": source.pk, "amount": "100.00"}])
        outcomes = self.race([lambda: record_financial_supplier_payment(submission_id=uuid.uuid4(), expenditure_id=expenses[0].pk, **pay),
                             lambda: record_financial_supplier_payment(submission_id=uuid.uuid4(), expenditure_id=expenses[1].pk, **pay)])
        self.assertEqual(sorted(row[0] for row in outcomes), ["accepted", "rejected"])
        self.assertEqual(list(FundingAllocation.objects.values_list("amount", flat=True)), [Decimal("100.00")])
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
