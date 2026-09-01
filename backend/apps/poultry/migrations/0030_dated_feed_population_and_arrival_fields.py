from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_arrival_and_feed_population(apps, schema_editor):
    Batch = apps.get_model("poultry", "Batch")
    FeedUsage = apps.get_model("poultry", "FeedUsage")
    FlockAdjustment = apps.get_model("poultry", "FlockAdjustment")
    Mortality = apps.get_model("poultry", "Mortality")
    Sales = apps.get_model("poultry", "Sales")

    for batch in Batch.objects.all().iterator():
        status = "active" if batch.status == "planned" and not batch.booking_date else batch.status
        expected = batch.quantity
        actual = None if status in {"booked", "planned", "delivered"} else batch.quantity
        Batch.objects.filter(pk=batch.pk).update(
            status=status,
            expected_quantity=expected,
            actual_quantity_received=actual,
        )
        if actual is None:
            continue
        for feed in FeedUsage.objects.filter(batch_id=batch.pk).iterator():
            mortality = sum(
                Mortality.objects.filter(
                    batch_id=batch.pk,
                    mortality_date__lte=feed.feeding_start_date,
                ).values_list("quantity_dead", flat=True)
            )
            sold = sum(
                Sales.objects.filter(
                    batch_id=batch.pk,
                    sale_date__lte=feed.feeding_start_date,
                    product_type__in=["live_chicken", "dressed_chicken"],
                ).exclude(payment_status="cancelled").values_list("quantity_sold", flat=True)
            )
            adjustments = sum(
                FlockAdjustment.objects.filter(
                    batch_id=batch.pk,
                    effective_at__lte=feed.feeding_start_date,
                    status="approved",
                ).values_list("quantity_change", flat=True)
            )
            FeedUsage.objects.filter(pk=feed.pk).update(
                current_number_of_birds=max(actual + adjustments - mortality - sold, 0),
                population_calculation_version="dated-flock-events-v1",
            )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("poultry", "0029_inputcosts_expenditure"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="actual_quantity_received",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="batch",
            name="booking_reference",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="batch",
            name="expected_quantity",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="batch",
            name="supplier_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="feedusage",
            name="population_calculated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="feedusage",
            name="population_calculation_version",
            field=models.CharField(default="dated-flock-events-v1", max_length=40),
        ),
        migrations.CreateModel(
            name="FlockAdjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("effective_at", models.DateTimeField(db_index=True)),
                ("quantity_change", models.IntegerField(help_text="Signed correction to the live-bird cohort.")),
                ("reason", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("approved", "Approved"), ("reversed", "Reversed")], db_index=True, default="approved", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("approved_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="approved_flock_adjustments", to=settings.AUTH_USER_MODEL)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="flock_adjustments", to="poultry.batch")),
            ],
            options={"ordering": ["effective_at", "pk"]},
        ),
        migrations.RunPython(backfill_arrival_and_feed_population, migrations.RunPython.noop),
    ]
