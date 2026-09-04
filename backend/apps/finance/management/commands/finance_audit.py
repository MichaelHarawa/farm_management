import json

from django.core.management.base import BaseCommand

from apps.finance.services.audit import finance_audit_report


class Command(BaseCommand):
    help = "Read-only financial integrity audit. No records are changed."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    def handle(self, *args, **options):
        report = finance_audit_report()
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return
        self.stdout.write("Finance integrity audit")
        self.stdout.write(f"Status: {'PASS' if report['ok'] else 'ACTION REQUIRED'}")
        for issue in report["issues"]:
            self.stdout.write(
                f"[{issue['severity'].upper()}] {issue['code']}: "
                f"{issue['count']} record(s), MWK {issue['amount']}"
            )
            if issue["records"]:
                self.stdout.write("  " + ", ".join(map(str, issue["records"][:20])))
        if not report["issues"]:
            self.stdout.write(self.style.SUCCESS("No reconciliation exceptions found."))

