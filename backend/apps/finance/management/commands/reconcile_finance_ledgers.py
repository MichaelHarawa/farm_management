from django.core.management.base import BaseCommand
from apps.finance.services.audit import finance_audit_report


class Command(BaseCommand):
    help = "Deprecated read-only compatibility wrapper for the comprehensive finance audit."

    def add_arguments(self, parser):
        parser.add_argument("--create-batch-sources", action="store_true", help="Deprecated; ignored for safety.")

    def handle(self, *args, **options):
        if options["create_batch_sources"]:
            self.stdout.write(self.style.WARNING(
                "--create-batch-sources is no longer executed here. Use apply_finance_reconciliation "
                "for an explicit dry-run, then opt in with --apply."
            ))
        report = finance_audit_report()
        for issue in report["issues"]:
            self.stdout.write(
                f"{issue['severity'].upper()} {issue['code']}: "
                f"count={issue['count']} amount={issue['amount']}"
            )
        style = self.style.SUCCESS if report["ok"] else self.style.WARNING
        self.stdout.write(style(f"Finance audit complete: {report['summary']['issues']} issue class(es)."))
