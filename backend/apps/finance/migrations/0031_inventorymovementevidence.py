import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('finance', '0030_inventory_purchase_foundations')]

    operations = [
        migrations.CreateModel(name='InventoryMovementEvidence', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('expected_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
            ('counted_quantity', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
            ('movement', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name='inventory_evidence', to='finance.stockmovement')),
            ('original_issue', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='stock_returns', to='finance.stockmovement')),
        ], options={'constraints': [
            models.CheckConstraint(condition=models.Q(('expected_quantity__isnull', True),
                ('expected_quantity__gte', 0), _connector='OR'), name='inventory_evidence_expected_nonnegative'),
            models.CheckConstraint(condition=models.Q(('counted_quantity__isnull', True),
                ('counted_quantity__gte', 0), _connector='OR'), name='inventory_evidence_counted_nonnegative'),
            models.CheckConstraint(condition=models.Q(models.Q(('counted_quantity__isnull', True), ('expected_quantity__isnull', True)),
                models.Q(('counted_quantity__isnull', False), ('expected_quantity__isnull', False)), _connector='OR'),
                name='inventory_evidence_count_pair'),
            models.CheckConstraint(condition=models.Q(('expected_quantity__isnull', True),
                ('expected_quantity__gt', models.F('counted_quantity')), _connector='OR'),
                name='inventory_evidence_count_loss_only'),
        ]}),
    ]
