import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0013_expenditure_idempotency_key_expenditure_origin_and_more"),
        ("poultry", "0028_sales_due_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="inputcosts",
            name="expenditure",
            field=models.OneToOneField(blank=True, help_text="Authoritative financial transaction represented by this operational detail.", null=True, on_delete=django.db.models.deletion.PROTECT, related_name="input_cost_detail", to="finance.expenditure"),
        ),
    ]
