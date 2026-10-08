"""Add explicit new-stock valuation; never populate or relabel historical lots."""
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


NATURES = [('direct_cost', 'Direct Cost'), ('indirect_operating_expense', 'Indirect Operating Expense'),
    ('capital_expenditure', 'Capital Expenditure'), ('inventory_purchase', 'Inventory Purchase (cost recognized on issue)'),
    ('loan_repayment', 'Loan Repayment'), ('owner_withdrawal', 'Owner Withdrawal'), ('transfer', 'Transfer'), ('other', 'Other')]


class Migration(migrations.Migration):
    dependencies = [('finance', '0029_financialcommandreceipt')]

    operations = [
        migrations.AlterField(model_name='expenditure', name='accounting_nature',
            field=models.CharField(choices=NATURES, db_index=True, default='other', max_length=40)),
        migrations.AlterField(model_name='expenditurecategory', name='default_accounting_nature',
            field=models.CharField(choices=NATURES, default='other', max_length=40)),
        migrations.CreateModel(name='InventoryLotBinding', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('invoice_key', models.CharField(blank=True, default=None, max_length=64, null=True, unique=True)),
            ('expenditure', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_lot', to='finance.expenditure')),
            ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_lots', to='finance.consumableitem')),
            ('lot', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='inventory_binding', to='finance.sharedconsumablelot')),
        ], options={'abstract': False}),
        migrations.CreateModel(name='InventoryLocationStock', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('quantity', models.DecimalField(decimal_places=4, default=Decimal('0.0000'), max_digits=14)),
            ('location', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='lot_stock', to='finance.inventorylocation')),
            ('binding', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='location_stock', to='finance.inventorylotbinding')),
        ], options={'constraints': [
            models.UniqueConstraint(fields=('binding', 'location'), name='inventory_unique_lot_location'),
            models.CheckConstraint(condition=models.Q(('quantity__gte', 0)), name='inventory_location_quantity_nonnegative')]}),
        migrations.CreateModel(name='InventoryValuePool', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('quantity', models.DecimalField(decimal_places=4, default=Decimal('0.0000'), max_digits=14)),
            ('carrying_value', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=16)),
            ('last_movement_date', models.DateField()),
            ('revision', models.PositiveBigIntegerField(default=1)),
            ('item', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='value_pool', to='finance.consumableitem')),
        ], options={'constraints': [
            models.CheckConstraint(condition=models.Q(('quantity__gte', 0)), name='inventory_pool_quantity_nonnegative'),
            models.CheckConstraint(condition=models.Q(('carrying_value__gte', 0)), name='inventory_pool_value_nonnegative'),
            models.CheckConstraint(condition=models.Q(('quantity__gt', 0), ('carrying_value', 0), _connector='OR'), name='inventory_empty_pool_zero_value')]}),
    ]
