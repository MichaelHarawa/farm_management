"""Metadata-only identity backfill; do not call current business model saves."""
import uuid
from django.db import migrations


def seed_identity(apps, schema_editor):
    alias = schema_editor.connection.alias
    State = apps.get_model("mobile_sync", "SyncStreamState")
    Entity = apps.get_model("mobile_sync", "SyncEntity")
    state, _ = State.objects.using(alias).get_or_create(pk=1)
    for model_name, entity_type in (("Batch", "poultry.batch"), ("Mortality", "poultry.mortality"), ("FeedUsage", "poultry.feed_usage")):
        Model = apps.get_model("poultry", model_name)
        fields = ["pk"] if model_name == "Batch" else ["pk", "batch_id"]
        pending = []
        for row in Model.objects.using(alias).order_by("pk").values(*fields).iterator(chunk_size=500):
            pending.append(Entity(stream_id=state.pk, entity_type=entity_type, source_pk=str(row["pk"]),
                                  entity_uuid=uuid.uuid4(), batch_pk=str(row["pk"] if model_name == "Batch" else row["batch_id"])))
            if len(pending) == 500:
                Entity.objects.using(alias).bulk_create(pending)
                pending = []
        Entity.objects.using(alias).bulk_create(pending)


class Migration(migrations.Migration):
    dependencies = [("mobile_sync", "0001_initial"), ("poultry", "0034_salesellingcost")]
    operations = [migrations.RunPython(seed_identity, reverse_code=migrations.RunPython.noop)]
