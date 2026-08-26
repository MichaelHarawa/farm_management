import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0012_fix_expenditure_cost_allocation_source"),
        ("poultry", "0028_sales_due_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="expenditure",
            name="idempotency_key",
            field=models.CharField(blank=True, help_text="Client-generated key that prevents duplicate expenditure submissions.", max_length=120, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="expenditure",
            name="origin",
            field=models.CharField(choices=[("batch_cost", "Batch cost form"), ("finance", "Finance expenditure form"), ("historical_input_cost", "Historical input cost migration")], db_index=True, default="finance", max_length=30),
        ),
        migrations.AddField(
            model_name="expenditure",
            name="payment_status",
            field=models.CharField(choices=[("unpaid", "Unpaid / payable"), ("partial", "Partially paid"), ("paid", "Paid"), ("historical_unassigned", "Historical funding unassigned")], db_index=True, default="unpaid", max_length=30),
        ),
        migrations.AddField(
            model_name="expenditurecategory",
            name="requires_batch_beneficiary",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="expenditurecategory",
            name="requires_item_details",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="fundingallocation",
            name="payment_group_key",
            field=models.CharField(blank=True, db_index=True, default="", help_text="Groups split funding rows belonging to one idempotent payment.", max_length=120),
        ),
        migrations.CreateModel(
            name="InputCostReconciliation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("status", models.CharField(choices=[("matched", "Matched existing expenditure"), ("migrated", "Migrated to new expenditure"), ("uncertain", "Possible match requires review"), ("unresolved", "Unresolved")], db_index=True, max_length=20)),
                ("match_basis", models.TextField(blank=True, default="")),
                ("requires_manual_review", models.BooleanField(db_index=True, default=False)),
                ("expenditure", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="input_cost_reconciliations", to="finance.expenditure")),
                ("input_cost", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="financial_reconciliation", to="poultry.inputcosts")),
            ],
            options={"ordering": ["status", "input_cost_id"]},
        ),
    ]
