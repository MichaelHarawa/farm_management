import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.finance.models import InputCostReconciliation
from apps.finance.services.audit import finance_audit_report
from apps.finance.services.profitability import ensure_batch_funding_source
from apps.poultry.models import InputCosts, PaymentStatus, Sales


class Command(BaseCommand):
    help = (
        "Explicit, idempotent reconciliation of safe missing control records. "
        "Defaults to dry-run; pass --apply to commit."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Commit safe additions.")
        parser.add_argument("--json", action="store_true", help="Emit JSON.")

    @transaction.atomic
    def handle(self, *args, **options):
        before = finance_audit_report()
        created_sources = 0
        queued_input_costs = 0

        batches = {
            sale.batch
            for sale in Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED)
            .filter(payments__isnull=False)
            .select_related("batch")
            .distinct()
        }
        for batch in batches:
            if not batch.funding_sources.filter(source_type="batch_collection").exists():
                created_sources += 1
                if options["apply"]:
                    ensure_batch_funding_source(batch)

        for input_cost in InputCosts.objects.filter(expenditure__isnull=True):
            if not hasattr(input_cost, "financial_reconciliation"):
                queued_input_costs += 1
                if options["apply"]:
                    InputCostReconciliation.objects.create(
                        input_cost=input_cost,
                        status=InputCostReconciliation.ReconciliationStatus.UNRESOLVED,
                        match_basis="Queued by explicit finance reconciliation; accountant decision required.",
                        requires_manual_review=True,
                    )

        if not options["apply"]:
            transaction.set_rollback(True)
        after = finance_audit_report() if options["apply"] else before
        result = {
            "mode": "applied" if options["apply"] else "dry-run",
            "changes": {
                "batch_funding_sources": created_sources,
                "input_costs_queued_for_review": queued_input_costs,
            },
            "before": before["summary"],
            "after": after["summary"],
            "note": "No financial amount, posted transaction, or source document was deleted or rewritten.",
        }
        if options["json"]:
            self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
        else:
            self.stdout.write(json.dumps(result, indent=2))
