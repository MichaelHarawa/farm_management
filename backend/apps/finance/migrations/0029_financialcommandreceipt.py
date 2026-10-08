import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0028_employeesalaryadjustment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name="FinancialCommandReceipt",
        fields=[
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("submission_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("command", models.CharField(max_length=40)),
            ("request_hash", models.CharField(max_length=64)),
            ("result", models.JSONField(default=dict)),
            ("completed_at", models.DateTimeField(blank=True, null=True)),
            ("actor", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                related_name="financial_command_receipts", to=settings.AUTH_USER_MODEL)),
        ],
    )]
