"""Add global financial-reference metadata only; no source/backfill writes."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("mobile_sync", "0002_seed_identity"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(model_name="syncchange", name="batch_uuid", field=models.UUIDField(blank=True, null=True)),
        migrations.AddConstraint(model_name="syncchange", constraint=models.CheckConstraint(condition=(
            models.Q(entity_type__in=["finance.funding_selection", "finance.invoice_reference"], batch_uuid__isnull=True,
                in_current_pack=False, kind__in=["upsert", "tombstone"])
            | (~models.Q(entity_type__in=["finance.funding_selection", "finance.invoice_reference"]) & models.Q(batch_uuid__isnull=False))),
            name="sync_change_global_reference")),
        migrations.CreateModel(name="FinancialPublicationBinding", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("source_identity", models.CharField(max_length=64)),
            ("requires_owner_access", models.BooleanField(default=False)),
            ("profile_version", models.PositiveSmallIntegerField(default=1)),
            ("anchor", models.CharField(max_length=64)),
            ("audience_actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ("entity", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="financial_binding", to="mobile_sync.syncentity")),
        ], options={"abstract": False}),
    ]
