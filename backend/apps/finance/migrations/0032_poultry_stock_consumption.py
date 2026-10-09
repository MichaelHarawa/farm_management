import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0031_inventorymovementevidence'),
        ('poultry', '0036_alter_sales_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(name='PoultryStockItemPolicy', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('kind', models.CharField(choices=[('feed', 'Feed'), ('treatment', 'Treatment / vaccination')], max_length=16)),
            ('base_unit', models.CharField(max_length=40)),
            ('reason', models.CharField(max_length=255)),
            ('configured_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('item', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='poultry_policy', to='finance.consumableitem')),
        ]),
        migrations.CreateModel(name='PoultryStockConsumption', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('quantity_unit', models.CharField(max_length=40)),
            ('feed', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='stock_consumption', to='poultry.feedusage')),
            ('treatment', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='stock_consumption', to='poultry.drugsvaccination')),
            ('policy', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='finance.poultrystockitempolicy')),
            ('usage', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='poultry_consumption', to='finance.consumableusage')),
        ], options={'constraints': [models.CheckConstraint(condition=(
            models.Q(('feed__isnull', False), ('treatment__isnull', True)) |
            models.Q(('feed__isnull', True), ('treatment__isnull', False))), name='poultry_stock_one_observation')]}),
    ]
