# Generated migration for adding expenditure link to CostAllocation and EXPENDITURE source type

from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0004_add_expenditure_funding_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="costallocation",
            name="expenditure",
            field=models.ForeignKey(
                blank=True,
                help_text="Link when this cost allocation comes from a general Expenditure.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cost_allocations",
                to="finance.expenditure",
            ),
        ),
        migrations.AlterField(
            model_name="costallocation",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("payroll", "Payroll"),
                    ("ad_hoc_labour", "Ad-hoc labour"),
                    ("shared_expense", "Shared expense"),
                    ("consumable_usage", "Consumable usage"),
                    ("depreciation", "Depreciation"),
                    ("expenditure", "Expenditure"),
                ],
                max_length=30,
            ),
        ),
    ]
