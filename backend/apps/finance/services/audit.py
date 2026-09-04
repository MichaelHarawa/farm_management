from __future__ import annotations

from collections import Counter
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Count, F, Sum

from apps.poultry.models import InputCosts, PaymentStatus, Sales

from ..models import (
    AccountingPeriod,
    AssetDepreciationEntry,
    BatchProfitabilitySnapshot,
    ConsumableUsage,
    CostAllocation,
    Expenditure,
    ExpenditureStatus,
    FinancePaymentStatus,
    FundingSource,
    FundingSourceType,
    InputCostReconciliation,
    JournalEntry,
    JournalStatus,
    PayrollEntry,
    PayrollPaymentStatus,
    PeriodStatus,
    SalePayment,
    SalePaymentStatus,
)

ZERO = Decimal("0.00")


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def migration_state() -> dict:
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)
    return {
        "ok": not plan,
        "unapplied": [f"{migration.app_label}.{migration.name}" for migration, _ in plan],
    }


def finance_audit_report() -> dict:
    """Return a read-only, machine-serializable financial integrity report."""

    issues: list[dict] = []

    def add(code: str, severity: str, count: int, amount=Decimal("0.00"), records=None):
        if count:
            issues.append(
                {
                    "code": code,
                    "severity": severity,
                    "count": count,
                    "amount": str(_money(amount)),
                    "records": list(records or []),
                }
            )

    migrations = migration_state()
    add("unapplied_migrations", "critical", len(migrations["unapplied"]), records=migrations["unapplied"])

    unlinked = InputCosts.objects.filter(expenditure__isnull=True)
    add(
        "unlinked_operational_costs",
        "warning",
        unlinked.count(),
        sum((row.quantity * row.unit * row.unit_cost for row in unlinked), Decimal("0.00")),
        unlinked.values_list("pk", flat=True),
    )
    void_linked = InputCosts.objects.filter(expenditure__status=ExpenditureStatus.VOID)
    add(
        "void_linked_operational_costs",
        "critical",
        void_linked.count(),
        sum((row.quantity * row.unit * row.unit_cost for row in void_linked), Decimal("0.00")),
        void_linked.values_list("pk", flat=True),
    )

    allocation_problems = []
    for expenditure in Expenditure.objects.filter(status=ExpenditureStatus.POSTED).prefetch_related("cost_allocations"):
        allocated = _money(sum((row.allocated_amount for row in expenditure.cost_allocations.all()), Decimal("0.00")))
        if expenditure.cost_allocations.exists() and allocated != _money(expenditure.amount):
            allocation_problems.append(expenditure.expenditure_reference or str(expenditure.pk))
    add("allocation_discrepancies", "critical", len(allocation_problems), records=allocation_problems)

    funding_rows = []
    funding_gap = Decimal("0.00")
    for expenditure in Expenditure.objects.filter(status=ExpenditureStatus.POSTED).prefetch_related("funding_allocations"):
        funded = _money(sum((row.amount for row in expenditure.funding_allocations.all()), Decimal("0.00")))
        gap = max(_money(expenditure.amount) - funded, Decimal("0.00"))
        if gap:
            funding_rows.append(expenditure.expenditure_reference or str(expenditure.pk))
            funding_gap += gap
    add("unfunded_or_partly_funded_expenditures", "warning", len(funding_rows), funding_gap, funding_rows)

    sale_rows = []
    for sale in Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED).prefetch_related("payments"):
        posted = _money(sum((p.amount for p in sale.payments.all() if p.status == SalePaymentStatus.POSTED), Decimal("0.00")))
        if posted != _money(sale.amount_paid):
            sale_rows.append(sale.sale_id)
    add("unreconciled_sale_payments", "critical", len(sale_rows), records=sale_rows)

    payroll_rows = []
    payroll_gap = Decimal("0.00")
    closed_liabilities = []
    for entry in PayrollEntry.objects.select_related("accounting_period", "employee", "expenditure").prefetch_related("payments", "expenditure__funding_allocations"):
        payroll_paid = _money(sum((p.amount for p in entry.payments.all() if p.status == PayrollPaymentStatus.POSTED), Decimal("0.00")))
        expenditure_paid = _money(
            sum((row.amount for row in entry.expenditure.funding_allocations.all()), Decimal("0.00"))
            if entry.expenditure_id
            else ZERO
        )
        paid = max(payroll_paid, expenditure_paid)
        outstanding = max(_money(entry.net_salary_payable) - paid, Decimal("0.00"))
        expected_status = FinancePaymentStatus.PAID if outstanding == 0 else (FinancePaymentStatus.PARTIAL if paid else FinancePaymentStatus.UNPAID)
        if entry.payment_status != expected_status:
            payroll_rows.append(entry.pk)
        if entry.accounting_period.status == PeriodStatus.CLOSED and outstanding:
            closed_liabilities.append(entry.pk)
            payroll_gap += outstanding
    add("unreconciled_payroll_payments", "critical", len(payroll_rows), records=payroll_rows)
    add("open_liabilities_in_closed_periods", "warning", len(closed_liabilities), payroll_gap, closed_liabilities)

    duplicate_rows = []
    fingerprints = Counter(
        Expenditure.objects.filter(status=ExpenditureStatus.POSTED).values_list(
            "expenditure_date", "amount", "description", "payee"
        )
    )
    duplicate_rows.extend(str(key) for key, count in fingerprints.items() if count > 1)
    add("possible_duplicate_economic_events", "warning", len(duplicate_rows), records=duplicate_rows)

    lock_count = (
        CostAllocation.objects.filter(accounting_period__status=PeriodStatus.CLOSED, locked=False).count()
        + ConsumableUsage.objects.filter(accounting_period__status=PeriodStatus.CLOSED, locked=False).count()
        + AssetDepreciationEntry.objects.filter(accounting_period__status=PeriodStatus.CLOSED, locked=False).count()
    )
    add("period_lock_violations", "critical", lock_count)

    unbalanced_journals = []
    for journal in JournalEntry.objects.filter(status=JournalStatus.POSTED).annotate(
        debit_total=Sum("lines__debit"), credit_total=Sum("lines__credit")
    ):
        if _money(journal.debit_total) != _money(journal.credit_total):
            unbalanced_journals.append(journal.reference)
    add(
        "unbalanced_posted_journals",
        "critical",
        len(unbalanced_journals),
        records=unbalanced_journals,
    )

    expected_journal_keys = set()
    expected_journal_keys.update(
        f"sale:{pk}"
        for pk in Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED).values_list("pk", flat=True)
    )
    expected_journal_keys.update(
        f"sale-payment:{pk}"
        for pk in SalePayment.objects.filter(status=SalePaymentStatus.POSTED).values_list("pk", flat=True)
    )
    expected_journal_keys.update(
        f"expenditure:{pk}"
        for pk in Expenditure.objects.filter(status=ExpenditureStatus.POSTED)
        .exclude(payroll_entry__isnull=False)
        .values_list("pk", flat=True)
    )
    expected_journal_keys.update(f"payroll:{pk}" for pk in PayrollEntry.objects.values_list("pk", flat=True))
    actual_journal_keys = set(
        JournalEntry.objects.filter(idempotency_key__in=expected_journal_keys).values_list(
            "idempotency_key", flat=True
        )
    )
    missing_journal_keys = sorted(expected_journal_keys - actual_journal_keys)
    add(
        "source_events_pending_general_ledger_backfill",
        "warning",
        len(missing_journal_keys),
        records=missing_journal_keys,
    )

    return {
        "ok": not any(issue["severity"] == "critical" for issue in issues),
        "migration_state": migrations,
        "summary": {
            "issues": len(issues),
            "critical": sum(issue["severity"] == "critical" for issue in issues),
            "warnings": sum(issue["severity"] == "warning" for issue in issues),
            "posted_expenditures": Expenditure.objects.filter(status=ExpenditureStatus.POSTED).count(),
            "sale_payments": Sales.objects.aggregate(count=Count("payments"))["count"] or 0,
            "final_batch_snapshots": BatchProfitabilitySnapshot.objects.filter(final=True).count(),
        },
        "issues": issues,
    }
