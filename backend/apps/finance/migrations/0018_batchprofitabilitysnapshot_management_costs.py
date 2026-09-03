from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0017_payroll_payment_ledger_and_legacy_expenses"),
    ]

    operations = [
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="central_selling_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="total_selling_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="allocated_administration_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="allocated_finance_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="allocated_tax", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="total_attributed_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="management_net_position", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="batchprofitabilitysnapshot", name="management_cost_breakdown", field=models.JSONField(blank=True, default=list)),
    ]
