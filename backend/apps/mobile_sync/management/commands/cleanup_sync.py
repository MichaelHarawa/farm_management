from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.mobile_sync.models import SyncBootstrap, SyncChange
from apps.mobile_sync.writers import sync_boundary
from apps.mobile_sync.immutability import change_pruning
from django.test.utils import override_settings


class Command(BaseCommand):
    help = "Preview/bounded cleanup of expired snapshots and whole old stream groups. Never deletes identities or receipts."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--database-name", required=True)
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        from django.db import connection
        if options["database_name"] != connection.settings_dict["NAME"] or not 1 <= options["limit"] <= 10000:
            raise CommandError("Database identity or bounded cleanup limit is invalid.")
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary() as state:
            snapshots = SyncBootstrap.objects.filter(expires_at__lt=timezone.now()).order_by("expires_at")
            cutoff = timezone.now() - timedelta(days=90)
            # Contiguous oldest whole groups only; a cursor at/above the new
            # minimum still has every subsequent change, including fragments.
            old = list(SyncChange.objects.filter(stream=state["stream"]).order_by("sequence")[:options["limit"]])
            through = state["stream"].minimum_sequence
            for change in old:
                if change.created_at >= cutoff:
                    break
                if change.transaction_index == change.transaction_count - 1:
                    through = change.sequence
            snapshot_ids = list(snapshots.values_list("pk", flat=True)[:options["limit"]])
            self.stdout.write(f"{'APPLY' if options['apply'] else 'DRY RUN'}: {len(snapshot_ids)} snapshots; change prefix through {through}; receipts untouched.")
            if options["apply"]:
                SyncBootstrap.objects.filter(pk__in=snapshot_ids).delete()
                with change_pruning():
                    SyncChange.objects.filter(stream=state["stream"], sequence__lte=through).delete()
                state["stream"].minimum_sequence = through
                state["stream"].save(update_fields=["minimum_sequence"])
