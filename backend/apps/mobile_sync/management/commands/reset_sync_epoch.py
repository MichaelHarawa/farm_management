import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.mobile_sync.models import SyncStreamState


class Command(BaseCommand):
    help = "Explicit forward-only maintenance reset after a controlled import. Retains receipts/identities."

    def add_arguments(self, parser):
        parser.add_argument("--database-name", required=True)
        parser.add_argument("--rotate-deployment", action="store_true")

    def handle(self, *args, **options):
        from django.db import connection
        if connection.settings_dict["NAME"] != options["database_name"]:
            raise CommandError("Explicit database identity does not match.")
        with transaction.atomic():
            stream = SyncStreamState.objects.select_for_update().get(pk=1)
            stream.epoch = uuid.uuid4()
            stream.ready = False
            if options["rotate_deployment"]:
                stream.deployment_id = uuid.uuid4()
            stream.save()
        self.stdout.write("Epoch reset; seed_sync is required before devices can bootstrap. Previous cursors are invalid.")
