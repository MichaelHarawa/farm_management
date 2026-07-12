from django.db import migrations, models


def normalize_batch_sources(apps, schema_editor):
    batch_model = apps.get_model("poultry", "Batch")
    known_sources = {
        "central poultry": "central_poultry",
        "central_poultry": "central_poultry",
        "cp_feed": "central_poultry",
        "proto": "proto",
        "proto feed": "proto",
        "proto_feed": "proto",
        "other": "other",
        "others": "other",
    }

    for batch in batch_model.objects.all():
        raw_source = (batch.source or "").strip()

        if not raw_source:
            batch.source = "proto"
            batch.source_other = ""
            batch.save(update_fields=["source", "source_other"])
            continue

        normalized_source = known_sources.get(raw_source.lower())

        if normalized_source:
            batch.source = normalized_source
            if normalized_source != "other":
                batch.source_other = ""
        else:
            batch.source = "other"
            batch.source_other = raw_source

        batch.save(update_fields=["source", "source_other"])


class Migration(migrations.Migration):

    dependencies = [
        ("poultry", "0015_alter_batch_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="source_other",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.RunPython(normalize_batch_sources, migrations.RunPython.noop),
    ]
