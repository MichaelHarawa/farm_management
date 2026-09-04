import json

from django.core.management.base import BaseCommand

from apps.finance.models import AccountingPeriod, PeriodReportSnapshot, PeriodStatus
from apps.finance.services.reporting import create_period_report_snapshot


class Command(BaseCommand):
    help = "Create the first immutable report snapshot for legacy closed periods; dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        missing = list(
            AccountingPeriod.objects.filter(status=PeriodStatus.CLOSED)
            .exclude(report_snapshots__isnull=False)
            .order_by("period_start")
        )
        result = {
            "mode": "applied" if options["apply"] else "dry-run",
            "closed_periods_without_snapshot": [period.pk for period in missing],
            "snapshots_created": 0,
        }
        if options["apply"]:
            for period in missing:
                create_period_report_snapshot(period)
                result["snapshots_created"] += 1
        result["remaining_without_snapshot"] = AccountingPeriod.objects.filter(
            status=PeriodStatus.CLOSED, report_snapshots__isnull=True
        ).distinct().count()
        self.stdout.write(json.dumps(result, indent=2))
