from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from apps.mobile_sync.models import SyncStreamState
from apps.mobile_sync.writers import sync_boundary
from apps.poultry.models import Batch


class Command(BaseCommand):
    help = "Materialize operational projections without changing source records. Explicit database-name guard required."

    def add_arguments(self, parser):
        parser.add_argument("--database-name", required=True)

    def handle(self, *args, **options):
        from django.db import connection
        if options["database_name"] != connection.settings_dict["NAME"]:
            raise CommandError("Configured database does not match the explicit requested database name.")
        with override_settings(MOBILE_SYNC_CAPTURE=True):
            for batch_pk in Batch.objects.order_by("pk").values_list("pk", flat=True).iterator(chunk_size=100):
                with sync_boundary() as state:
                    state["batches"].add(str(batch_pk))
            with transaction.atomic():
                stream = SyncStreamState.objects.select_for_update().get(pk=1)
                stream.ready = True
                stream.save(update_fields=["ready"])
        self.stdout.write(self.style.SUCCESS("Operational identities/projections ready; source rows unchanged."))
