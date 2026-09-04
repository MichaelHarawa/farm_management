import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from apps.finance.models import (
    AccountingNature,
    AssetDepreciationEntry,
    Expenditure,
    ExpenditureStatus,
    FundingAllocation,
    JournalEntry,
    PayrollEntry,
    PayrollPayment,
    PayrollPaymentStatus,
    SalePayment,
    SalePaymentStatus,
)
from apps.finance.services.ledger import post_journal, trial_balance
from apps.poultry.models import PaymentStatus, Sales


ZERO = Decimal("0.00")


class Command(BaseCommand):
    help = "Idempotently backfill balanced journals from preserved source records; dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--json", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        apply = options["apply"]
        candidates = []

        for sale in Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED):
            amount = Decimal(sale.quantity_sold) * sale.unit_price
            candidates.append(
                (f"sale:{sale.pk}", sale.sale_date.date(), f"Sale {sale.sale_id}", "poultry.Sales", sale.pk, [
                    {"account": "1100", "debit": amount, "batch_id": sale.batch_id},
                    {"account": "4000", "credit": amount, "batch_id": sale.batch_id},
                ])
            )
        for payment in SalePayment.objects.filter(status=SalePaymentStatus.POSTED).select_related("sale"):
            candidates.append(
                (f"sale-payment:{payment.pk}", payment.payment_date.date(), f"Receipt {payment.payment_reference}", "finance.SalePayment", payment.pk, [
                    {"account": "1000", "debit": payment.amount},
                    {"account": "1100", "credit": payment.amount, "batch_id": payment.sale.batch_id},
                ])
            )
        debit_accounts = {
            AccountingNature.DIRECT_COST: "5000",
            AccountingNature.INDIRECT_OPERATING_EXPENSE: "6100",
            AccountingNature.CAPITAL_EXPENDITURE: "1500",
            AccountingNature.LOAN_REPAYMENT: "2200",
            AccountingNature.OWNER_WITHDRAWAL: "3100",
            AccountingNature.OTHER: "6100",
        }
        for expenditure in Expenditure.objects.filter(status=ExpenditureStatus.POSTED).exclude(payroll_entry__isnull=False):
            debit_account = debit_accounts.get(expenditure.accounting_nature)
            if not debit_account:
                continue
            batch_id = expenditure.cost_allocations.values_list("batch_id", flat=True).first()
            candidates.append(
                (f"expenditure:{expenditure.pk}", expenditure.expenditure_date, f"Expenditure {expenditure.expenditure_reference}", "finance.Expenditure", expenditure.pk, [
                    {"account": debit_account, "debit": expenditure.amount, "batch_id": batch_id},
                    {"account": "2000", "credit": expenditure.amount},
                ])
            )
        for entry in PayrollEntry.objects.select_related("accounting_period"):
            statutory = entry.deductions + entry.employer_costs
            net = entry.gross_salary - entry.deductions
            lines = []
            for account, percentage in [
                ("5100", entry.production_percentage),
                ("6100", entry.administration_percentage),
                ("6000", entry.selling_percentage),
            ]:
                amount = (entry.total_employer_cost * percentage / Decimal("100")).quantize(Decimal("0.01"))
                if amount:
                    lines.append({"account": account, "debit": amount})
            rounding = entry.total_employer_cost - sum((line["debit"] for line in lines), ZERO)
            if rounding and lines:
                lines[0]["debit"] += rounding
            lines.extend([
                {"account": "2100", "credit": net},
                {"account": "2110", "credit": statutory},
            ])
            candidates.append(
                (f"payroll:{entry.pk}", entry.accounting_period.period_end, f"Payroll entry {entry.pk}", "finance.PayrollEntry", entry.pk, lines)
            )
        for funding in FundingAllocation.objects.select_related("expenditure"):
            payable = "2100" if hasattr(funding.expenditure, "payroll_entry") else "2000"
            candidates.append(
                (f"expenditure-payment:{funding.pk}", funding.allocation_date, f"Payment of {funding.expenditure.expenditure_reference}", "finance.FundingAllocation", funding.pk, [
                    {"account": payable, "debit": funding.amount, "funding_source_id": funding.funding_source_id},
                    {"account": "1000", "credit": funding.amount, "funding_source_id": funding.funding_source_id},
                ])
            )
        for payment in PayrollPayment.objects.filter(status=PayrollPaymentStatus.POSTED):
            candidates.append(
                (f"payroll-payment:{payment.pk}", payment.payment_date, f"Payroll payment {payment.pk}", "finance.PayrollPayment", payment.pk, [
                    {"account": "2100", "debit": payment.amount},
                    {"account": "1000", "credit": payment.amount},
                ])
            )
        for depreciation in AssetDepreciationEntry.objects.select_related("accounting_period"):
            candidates.append(
                (f"depreciation:{depreciation.pk}", depreciation.accounting_period.period_end, f"Depreciation {depreciation.pk}", "finance.AssetDepreciationEntry", depreciation.pk, [
                    {"account": "6200", "debit": depreciation.period_depreciation},
                    {"account": "1590", "credit": depreciation.period_depreciation},
                ])
            )

        existing = set(JournalEntry.objects.filter(idempotency_key__in=[row[0] for row in candidates]).values_list("idempotency_key", flat=True))
        pending = [row for row in candidates if row[0] not in existing]
        before = trial_balance()
        if apply:
            for key, posting_date, description, source_model, source_id, lines in pending:
                post_journal(
                    posting_date=posting_date,
                    description=description,
                    source_model=source_model,
                    source_identifier=source_id,
                    idempotency_key=key,
                    lines=lines,
                    allow_historical=True,
                )
        else:
            transaction.set_rollback(True)
        after = trial_balance() if apply else before
        result = {
            "mode": "applied" if apply else "dry-run",
            "source_events": len(candidates),
            "already_posted": len(existing),
            "journals_to_create": len(pending),
            "before": {"debits": str(before["debits"]), "credits": str(before["credits"])},
            "after": {"debits": str(after["debits"]), "credits": str(after["credits"])},
            "balanced": after["debits"] == after["credits"],
        }
        self.stdout.write(json.dumps(result, indent=2))
