import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0032_poultry_stock_consumption"),
        ("poultry", "0036_alter_sales_notes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.CreateModel(
        name="SaleCostPayment",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("source_version", models.CharField(max_length=64)),
            ("submission_id", models.UUIDField(db_index=True)),
            ("split_index", models.PositiveSmallIntegerField()),
            ("amount", models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(Decimal("0.01"))])),
            ("payment_date", models.DateField(db_index=True)),
            ("payment_method", models.CharField(choices=[("cash", "Cash"), ("mobile_money", "Mobile Money"), ("bank_transfer", "Bank Transfer")], max_length=20)),
            ("classification", models.CharField(choices=[("reinvestment", "Reinvestment in Operations"), ("working_capital", "Working Capital"), ("cost_recovery", "Cost Recovery"), ("owner_distribution", "Owner Profit Distribution"), ("owner_capital_return", "Return of Owner Capital"), ("owner_drawing", "Owner Drawing"), ("owner_compensation", "Owner Compensation"), ("debt_service", "Debt Service"), ("other", "Other")], max_length=30)),
            ("payee", models.CharField(max_length=200)),
            ("external_reference", models.CharField(blank=True, default="", max_length=120)),
            ("notes", models.TextField(blank=True, default="")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_sale_cost_payments", to=settings.AUTH_USER_MODEL)),
            ("funding_source", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_cost_payments", to="finance.fundingsource")),
            ("payable_journal", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_cost_settlements", to="finance.journalentry")),
            ("selling_cost", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="poultry.salesellingcost")),
        ],
        options={"ordering": ["payment_date", "created_at", "pk"], "constraints": [
            models.UniqueConstraint(fields=("submission_id", "split_index"), name="sale_cost_payment_split_unique"),
            models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="sale_cost_payment_positive"),
            models.CheckConstraint(condition=models.Q(("split_index__lt", 50)), name="sale_cost_payment_bounded_split"),
        ]},
    )]
