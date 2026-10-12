"""Accounting-calendar boundaries in new owned PostgreSQL databases only."""
from copy import deepcopy
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.db import connection
from django.db.models import Sum
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.finance.models import (AccountingPeriod, FinanceActionEvent, FinancialCommandReceipt,
    FundingSource, FundingSourceType, JournalEntry, JournalLine, OwnerContributor,
    PeriodReportSnapshot, PeriodStatus)
from apps.finance.services.bird_days import calculate_batch_bird_days, recalculate_bird_day_snapshots
from apps.finance.services.financial_values import accounting_calendar, business_date
from apps.finance.services.financial_capture import (record_financial_owner_contribution,
    record_financial_receipt, record_financial_sale, record_financial_supplier_payment)
from apps.finance.services.funding_capture import funding_source_version, record_financial_funding_receipt
from apps.finance.services.profitability import batch_portfolio_report, batch_profitability, batch_survivor_cost_basis
from apps.finance.services.reporting import (create_period_report_snapshot, dashboard_indicators,
    dashboard_warnings, monthly_profitability_report, receivables_report)
from apps.finance.services.selling_cost_settlement import record_sale_cost_payment
from apps.poultry.models import Batch
from . import test_expenditure_drafts as drafts
from . import test_financial_capture as fixtures


LATE_JANUARY = datetime(2026, 1, 31, 23, 30, tzinfo=datetime_timezone.utc)
EARLY_FEBRUARY = datetime(2026, 2, 1, 0, 30, tzinfo=datetime_timezone.utc)
DISPLAY_ZONES = ("Africa/Blantyre", "America/Los_Angeles")


@override_settings(TIME_ZONE="UTC", MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False,
    MOBILE_SYNC_POULTRY_V2=False, FINANCE_FUNDING_RECEIPTS=True, FINANCE_FUNDING_REVERSALS=False,
    FINANCE_SALE_COST_SETTLEMENT=True, FINANCE_SALE_COST_REVERSALS=False)
class ReportingCalendarTests(TestCase):
    def setUp(self):
        fixtures.fixture(self)
        self.february = AccountingPeriod.objects.create(
            period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        self.sales = []
        for instant in (LATE_JANUARY, EARLY_FEBRUARY):
            sale = record_financial_sale(**{**fixtures.sale_payload(self), "sale_date": instant,
                "due_date": date(2026, 1, 31),
                "selling_costs": [{"category": "transport", "amount": "40.00"}],
                "initial_receipt": {"amount": "100.00", "payment_date": instant,
                    "payment_method": "cash"}})[0]
            self.sales.append(sale)
        record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=self.sales[0].pk, amount="50.00", payment_date=EARLY_FEBRUARY,
            payment_method="cash", external_reference="SYNTHETIC-MONTH-BOUNDARY")
        loan = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
        for amount, instant, reference in (("500.00", LATE_JANUARY, "SYNTHETIC-JAN-LOAN"),
                                          ("200.00", EARLY_FEBRUARY, "SYNTHETIC-FEB-LOAN")):
            record_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
                funding_source_id=loan.pk, source_version=funding_source_version(loan), amount=amount,
                receipt_date=instant, counterparty="Synthetic lender", payment_method="bank_transfer",
                reference=reference)
        owner = OwnerContributor.objects.create(display_name="Synthetic calendar owner", created_by=self.user)
        record_financial_owner_contribution(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            owner_id=owner.pk, amount="300.00", receipt_date=LATE_JANUARY, reference="SYNTHETIC-JAN-OWNER")
        expense = drafts.draft(self, expenditure_date=date(2026, 1, 30), post=True)
        source = FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=self.batch)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            expenditure_id=expense.pk, payment_date=date(2026, 2, 1),
            funding_allocations=[{"funding_source": source.pk, "amount": "25.00"}])
        record_sale_cost_payment(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            selling_cost_id=self.sales[0].selling_costs.get().pk, payment_date=date(2026, 2, 1),
            funding_allocations=[{"funding_source": source.pk, "amount": "20.00"}],
            payee="Synthetic transporter", payment_method="cash")

    def journal_balance(self, code, cutoff, *, credit=False):
        totals = JournalLine.objects.filter(account__code=code, journal_entry__posting_date__lte=cutoff,
            journal_entry__status="posted").aggregate(debits=Sum("debit"), credits=Sum("credit"))
        net = (totals["debits"] or Decimal("0")) - (totals["credits"] or Decimal("0"))
        return -net if credit else net

    def reports(self):
        return [monthly_profitability_report(period) for period in (self.period, self.february)]

    def test_cash_receivables_capital_and_payables_match_posted_calendar_cutoffs(self):
        # These are entirely managed new transactions, not a claim that the
        # legacy/mixed-source farm or all management WIP is ledger-certified.
        with timezone.override("UTC"):
            reports = self.reports()
        for report, period, cash, receivable, payable, loan in (
                (reports[0], self.period, "900.00", "100.00", "140.00", "500.00"),
                (reports[1], self.february, "1205.00", "150.00", "135.00", "700.00")):
            statement = report["statement_of_financial_position"]
            for field, code, expected, credit in (("cash", "1000", cash, False),
                    ("receivables", "1100", receivable, False), ("supplier_payables", "2000", payable, True),
                    ("loans", "2200", loan, True), ("owner_contributed_equity", "3000", "300.00", True)):
                with self.subTest(period=period.pk, field=field):
                    self.assertEqual(statement[field], Decimal(expected))
                    self.assertEqual(statement[field], self.journal_balance(code, period.period_end, credit=credit))
        self.assertEqual([r["revenue"]["total_revenue"] for r in reports], [Decimal("200.00")] * 2)
        self.assertEqual(reports[1]["cash_flow"]["opening_cash"], Decimal("900.00"))
        self.assertEqual(reports[1]["comparatives"]["previous_period_revenue"], Decimal("200.00"))
        self.assertEqual(reports[1]["comparatives"]["ytd_revenue"], Decimal("400.00"))
        roll = reports[1]["collections"]["roll_forward"]
        self.assertEqual((roll["opening_receivables"], roll["collections_against_opening"],
            roll["collections_against_current_sales"], roll["closing_receivables"]),
            (Decimal("100.00"), Decimal("50.00"), Decimal("100.00"), Decimal("150.00")))

    def test_eager_monthly_reports_ignore_display_timezone_and_do_not_write(self):
        with timezone.override("UTC"):
            expected = self.reports()
        before = [list(model.objects.order_by("pk").values()) for model in (
            JournalEntry, JournalLine, FinancialCommandReceipt, FinanceActionEvent, PeriodReportSnapshot)]
        with CaptureQueriesContext(connection) as queries:
            for zone in DISPLAY_ZONES:
                with self.subTest(zone=zone), timezone.override(zone):
                    self.assertEqual(self.reports(), expected)
                    self.assertEqual(timezone.get_current_timezone_name(), zone)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries))
        self.assertEqual(before, [list(model.objects.order_by("pk").values()) for model in (
            JournalEntry, JournalLine, FinancialCommandReceipt, FinanceActionEvent, PeriodReportSnapshot)])

    def test_dashboard_dates_warnings_and_money_ignore_display_timezone(self):
        with patch("django.utils.timezone.now", return_value=LATE_JANUARY):
            with timezone.override("UTC"):
                expected = dashboard_indicators({"period": str(self.period.pk)})
                warnings = dashboard_warnings(self.period)
                batch = batch_profitability(self.batch)
                portfolio = batch_portfolio_report([self.batch, self.other_batch])
            for zone in DISPLAY_ZONES:
                with self.subTest(zone=zone), timezone.override(zone):
                    self.assertEqual(dashboard_indicators({"period": str(self.period.pk)}), expected)
                    self.assertEqual(dashboard_warnings(self.period), warnings)
                    self.assertEqual(batch_profitability(self.batch), batch)
                    self.assertEqual(batch_portfolio_report([self.batch, self.other_batch]), portfolio)
                    self.assertEqual(timezone.get_current_timezone_name(), zone)

    def test_original_offset_instant_is_preserved_but_not_grouped_by_display_day(self):
        offset_instant = LATE_JANUARY.astimezone(timezone.get_fixed_timezone(120))
        self.assertEqual(offset_instant.date(), date(2026, 2, 1))
        sale = record_financial_sale(**{**fixtures.sale_payload(self), "sale_date": offset_instant,
            "quantity_sold": 1, "unit_price": "10.00", "initial_receipt": {
                "amount": "5.00", "payment_date": offset_instant, "payment_method": "cash"}})[0]
        sale.refresh_from_db()
        self.assertEqual(sale.sale_date, LATE_JANUARY)
        self.assertEqual(JournalEntry.objects.get(idempotency_key=f"financial-sale:{sale.pk}").posting_date,
            date(2026, 1, 31))
        for zone in DISPLAY_ZONES:
            with self.subTest(zone=zone), timezone.override(zone):
                report = monthly_profitability_report(self.period)
                self.assertEqual(report["revenue"]["total_revenue"], Decimal("210.00"))
                self.assertEqual(report["cash_flow"]["closing_cash"], Decimal("905.00"))
                self.assertEqual(report["statement_of_financial_position"]["receivables"], Decimal("105.00"))

    def test_year_boundary_comparatives_and_opening_cash_follow_posting_calendar(self):
        december = AccountingPeriod.objects.create(period_start=date(2025, 12, 1), period_end=date(2025, 12, 31))
        batch = Batch.objects.create(bird_type="broilers", source="proto", quantity=10, created_by=self.user,
            entry_date=datetime(2025, 12, 1, 12, tzinfo=datetime_timezone.utc),
            expected_maturity_date=datetime(2025, 12, 15, 12, tzinfo=datetime_timezone.utc))
        instant = datetime(2025, 12, 31, 23, 30, tzinfo=datetime_timezone.utc)
        sale = record_financial_sale(**{**fixtures.sale_payload(self), "batch_id": batch.pk,
            "sale_date": instant, "quantity_sold": 1, "unit_price": "50.00",
            "initial_receipt": {"amount": "20.00", "payment_date": instant, "payment_method": "cash"}})[0]
        self.assertEqual(JournalEntry.objects.get(idempotency_key=f"financial-sale:{sale.pk}").accounting_period_id,
            december.pk)
        for zone in DISPLAY_ZONES:
            with self.subTest(zone=zone), timezone.override(zone):
                report = monthly_profitability_report(self.period)
                self.assertEqual(report["comparatives"]["previous_period_revenue"], Decimal("50.00"))
                self.assertEqual(report["comparatives"]["ytd_revenue"], Decimal("200.00"))
                self.assertEqual(report["cash_flow"]["opening_cash"], Decimal("20.00"))
                self.assertEqual(report["cash_flow"]["closing_cash"], Decimal("920.00"))
                self.assertEqual(report["statement_of_financial_position"]["receivables"], Decimal("130.00"))

    def test_receivable_due_today_is_not_overdue_in_display_tomorrow(self):
        with patch("django.utils.timezone.now", return_value=LATE_JANUARY):
            with timezone.override("UTC"):
                expected = receivables_report()
                overdue = receivables_report({"status": "overdue"})
            self.assertEqual(overdue["count"], 0)
            for zone in DISPLAY_ZONES:
                with self.subTest(zone=zone), timezone.override(zone):
                    self.assertEqual(receivables_report(), expected)
                    self.assertEqual(receivables_report({"status": "overdue"}), overdue)
                    self.assertEqual(timezone.get_current_timezone_name(), zone)

    def test_new_close_snapshot_uses_accounting_calendar_existing_snapshot_is_not_rewritten(self):
        with timezone.override("UTC"):
            expected = monthly_profitability_report(self.period)
        with timezone.override("Africa/Blantyre"):
            snapshot = create_period_report_snapshot(self.period, generated_by=self.user)
            self.assertEqual(snapshot.report_data["revenue"]["total_revenue"], str(expected["revenue"]["total_revenue"]))
            self.assertEqual(snapshot.report_data["cash_flow"]["closing_cash"], str(expected["cash_flow"]["closing_cash"]))
            self.assertEqual(timezone.get_current_timezone_name(), "Africa/Blantyre")
        original = deepcopy(snapshot.report_data)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with patch("apps.finance.services.reporting._calculate_monthly_profitability_report",
                side_effect=AssertionError("Never recompute a saved closed report")):
            for zone in DISPLAY_ZONES:
                with self.subTest(zone=zone), timezone.override(zone):
                    self.assertEqual(monthly_profitability_report(self.period), original)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.report_data, original)
        self.assertEqual(PeriodReportSnapshot.objects.count(), 1)

    def test_standalone_financial_bird_day_driver_ignores_display_timezone(self):
        with timezone.override("UTC"):
            expected = calculate_batch_bird_days(self.batch, self.period)
        self.assertEqual(expected["valid_bird_units_sold"], 2)
        for zone in DISPLAY_ZONES:
            with self.subTest(zone=zone), timezone.override(zone):
                self.assertEqual(calculate_batch_bird_days(self.batch, self.period), expected)
                self.assertEqual(timezone.get_current_timezone_name(), zone)

    def test_financial_driver_snapshot_and_customer_cost_bridge_use_same_calendar(self):
        with timezone.override("UTC"):
            expected = calculate_batch_bird_days(self.batch, self.period)
            costs = batch_survivor_cost_basis([self.batch, self.other_batch])
        with timezone.override("Africa/Blantyre"):
            snapshots = recalculate_bird_day_snapshots(self.period)
            snapshot = next(item for item in snapshots if item.batch_id == self.batch.pk)
            for field, value in expected.items():
                self.assertEqual(getattr(snapshot, field), value)
            self.assertEqual(batch_survivor_cost_basis([self.batch, self.other_batch]), costs)
            self.assertEqual(timezone.get_current_timezone_name(), "Africa/Blantyre")
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with timezone.override("America/Los_Angeles"):
            with self.assertRaises(ValueError):
                recalculate_bird_day_snapshots(self.period)
            self.assertEqual(timezone.get_current_timezone_name(), "America/Los_Angeles")


class AccountingCalendarContextTests(SimpleTestCase):
    def test_default_is_resolved_at_call_time_and_explicit_date_is_not_converted(self):
        @accounting_calendar
        def read():
            return timezone.get_current_timezone_name(), business_date(LATE_JANUARY), business_date(date(2026, 1, 31))
        for configured, expected_day in (("UTC", date(2026, 1, 31)), ("Africa/Blantyre", date(2026, 2, 1))):
            with self.subTest(configured=configured), override_settings(TIME_ZONE=configured), timezone.override("America/Los_Angeles"):
                self.assertEqual(read(), (configured, expected_day, date(2026, 1, 31)))
                self.assertEqual(timezone.get_current_timezone_name(), "America/Los_Angeles")

    @override_settings(TIME_ZONE="UTC")
    def test_context_restores_display_timezone_on_exception_and_preserves_signature_metadata(self):
        @accounting_calendar
        def read(value):
            """Synthetic eager read."""
            self.assertEqual(timezone.get_current_timezone_name(), "UTC")
            raise ValueError(value)
        with timezone.override("Africa/Blantyre"):
            with self.assertRaisesRegex(ValueError, "synthetic failure"):
                read("synthetic failure")
            self.assertEqual(timezone.get_current_timezone_name(), "Africa/Blantyre")
        self.assertEqual(read.__name__, "read")
        self.assertEqual(read.__doc__, "Synthetic eager read.")

    @override_settings(TIME_ZONE="UTC")
    def test_nested_eager_reads_restore_outer_calendar_then_caller(self):
        @accounting_calendar
        def inner():
            return timezone.get_current_timezone_name()
        @accounting_calendar
        def outer():
            self.assertEqual(inner(), "UTC")
            self.assertEqual(timezone.get_current_timezone_name(), "UTC")
            return "complete"
        with timezone.override("Africa/Blantyre"):
            self.assertEqual(outer(), "complete")
            self.assertEqual(timezone.get_current_timezone_name(), "Africa/Blantyre")
