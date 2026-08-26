from django.core.management.base import BaseCommand

from apps.finance.models import InputCostReconciliation
from apps.finance.services.expenditures import reconciliation_summary


class Command(BaseCommand):
    help = "Report historical poultry input-cost to expenditure reconciliation results."

    def add_arguments(self, parser):
        parser.add_argument(
            "--details",
            action="store_true",
            help="List records requiring manual review.",
        )

    def handle(self, *args, **options):
        summary = reconciliation_summary()
        self.stdout.write("Input cost reconciliation")
        for status in ("matched", "migrated", "uncertain", "unresolved"):
            self.stdout.write(f"{status}: {summary[status]}")
        self.stdout.write(
            f"manual_review_required: {summary['manual_review_required']}"
        )

        if options["details"]:
            rows = InputCostReconciliation.objects.filter(
                requires_manual_review=True
            ).select_related("input_cost", "input_cost__batch", "expenditure")
            for row in rows:
                self.stdout.write(
                    f"InputCost #{row.input_cost_id} | {row.input_cost.batch.batch_id} | "
                    f"{row.input_cost.item} | {row.status} | {row.match_basis}"
                )
