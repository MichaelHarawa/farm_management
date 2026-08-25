# Generated migration for Expenditure, FundingSource, FundingAllocation

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_alter_assetcategory_code'),
        ('poultry', '0027_batch_broiler_strain_batchweightsample'),  # adjust if needed
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FundingSource',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source_type', models.CharField(choices=[('batch_collection', 'Batch Sales Collections'), ('owner_capital', 'Owner Capital'), ('loan', 'Loan Funding'), ('grant', 'Grant / Subsidy'), ('other_income', 'Other Income'), ('general_farm_cash', 'General Farm Cash')], db_index=True, max_length=30)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('notes', models.TextField(blank=True, default='')),
                ('batch', models.ForeignKey(blank=True, help_text='The batch whose collected revenue is the source (for BATCH_COLLECTION).', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='funding_sources', to='poultry.batch')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Expenditure',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('usd_exchange_rate', models.DecimalField(blank=True, decimal_places=6, help_text='MWK per USD at entry time.', max_digits=16, null=True, validators=[django.db.models.deletion.PROTECT])),
                ('usd_equivalent', models.DecimalField(blank=True, decimal_places=2, help_text='USD equivalent captured for future inflation reference.', max_digits=16, null=True, validators=[django.db.models.deletion.PROTECT])),
                ('expenditure_date', models.DateField(db_index=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[django.db.models.deletion.PROTECT])),
                ('category', models.CharField(max_length=120)),
                ('accounting_nature', models.CharField(choices=[('direct_cost', 'Direct Cost'), ('indirect_operating_expense', 'Indirect Operating Expense'), ('capital_expenditure', 'Capital Expenditure'), ('loan_repayment', 'Loan Repayment'), ('owner_withdrawal', 'Owner Withdrawal'), ('transfer', 'Transfer'), ('other', 'Other')], db_index=True, default='other', max_length=40)),
                ('other_nature_detail', models.CharField(blank=True, default='', max_length=200)),
                ('description', models.CharField(max_length=255)),
                ('payee', models.CharField(blank=True, default='', max_length=160)),
                ('payment_method', models.CharField(blank=True, default='', max_length=50)),
                ('reference_number', models.CharField(blank=True, default='', max_length=120)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('posted', 'Posted'), ('void', 'Void')], db_index=True, default='draft', max_length=20)),
                ('farm_module', models.CharField(blank=True, default='', max_length=50)),
                ('notes', models.TextField(blank=True, default='')),
                ('posted_at', models.DateTimeField(blank=True, null=True)),
                ('reversal_reason', models.TextField(blank=True, default='')),
                ('accounting_period', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='expenditures', to='finance.accountingperiod')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_expenditures', to=settings.AUTH_USER_MODEL)),
                ('posted_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='posted_expenditures', to=settings.AUTH_USER_MODEL)),
                ('reversed_expenditure', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reversals', to='finance.expenditure')),
            ],
            options={
                'ordering': ['-expenditure_date', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='FundingAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[django.db.models.deletion.PROTECT])),
                ('allocation_date', models.DateField()),
                ('classification', models.CharField(choices=[('reinvestment', 'Reinvestment in Operations'), ('working_capital', 'Working Capital'), ('cost_recovery', 'Cost Recovery'), ('owner_distribution', 'Owner Distribution'), ('debt_service', 'Debt Service'), ('other', 'Other')], default='reinvestment', max_length=30)),
                ('notes', models.TextField(blank=True, default='')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_funding_allocations', to=settings.AUTH_USER_MODEL)),
                ('expenditure', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='funding_allocations', to='finance.expenditure')),
                ('funding_source', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='allocations', to='finance.fundingsource')),
            ],
            options={
                'ordering': ['-allocation_date'],
            },
        ),
        migrations.AddIndex(
            model_name='fundingsource',
            index=models.Index(fields=['source_type', 'batch'], name='finance_fun_source__e0e0e0_idx'),
        ),
        migrations.AddIndex(
            model_name='expenditure',
            index=models.Index(fields=['status', 'expenditure_date'], name='finance_exp_status__e0e0e0_idx'),
        ),
        migrations.AddIndex(
            model_name='expenditure',
            index=models.Index(fields=['accounting_nature'], name='finance_exp_account_e0e0e0_idx'),
        ),
        migrations.AddIndex(
            model_name='expenditure',
            index=models.Index(fields=['accounting_period'], name='finance_exp_account_e1e1e1_idx'),
        ),
        migrations.AddIndex(
            model_name='fundingallocation',
            index=models.Index(fields=['expenditure'], name='finance_fun_expendi_e0e0e0_idx'),
        ),
        migrations.AddIndex(
            model_name='fundingallocation',
            index=models.Index(fields=['funding_source'], name='finance_fun_funding_e0e0e0_idx'),
        ),
    ]
