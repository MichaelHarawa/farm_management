import time

from django.core.management.base import BaseCommand, CommandError
from django.db import InterfaceError, OperationalError, connections


class Command(BaseCommand):
    help = "Wait for the configured database before running startup migrations."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=60)
        parser.add_argument("--interval", type=int, default=2)

    def handle(self, *args, **options):
        timeout = options["timeout"]
        interval = options["interval"]
        if timeout <= 0 or interval <= 0:
            raise CommandError("--timeout and --interval must be positive seconds.")

        connection = connections["default"]
        deadline = time.monotonic() + timeout
        while True:
            try:
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except (OperationalError, InterfaceError):
                connection.close()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CommandError(
                        f"Database unavailable after {timeout}s. Check the database "
                        "service and configured host/port. The Docker host 'db' "
                        "requires both services on the same Compose network."
                    ) from None
                self.stdout.write("Database unavailable; retrying...")
                time.sleep(min(interval, remaining))
            else:
                connection.close()
                self.stdout.write(self.style.SUCCESS("Database is ready."))
                return
