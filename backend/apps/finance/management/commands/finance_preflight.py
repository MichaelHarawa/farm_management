from django.core.management.base import BaseCommand, CommandError

from apps.finance.services.audit import migration_state


class Command(BaseCommand):
    help = "Fail deployment preflight when database migrations are unapplied."

    def handle(self, *args, **options):
        state = migration_state()
        if not state["ok"]:
            raise CommandError("Unapplied migrations: " + ", ".join(state["unapplied"]))
        self.stdout.write(self.style.SUCCESS("Finance preflight passed: all migrations are applied."))

