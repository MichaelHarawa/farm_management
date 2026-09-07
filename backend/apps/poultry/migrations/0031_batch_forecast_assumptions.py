from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("poultry", "0030_dated_feed_population_and_arrival_fields")]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="forecast_mortality_rate_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Expected mortality percentage among birds currently remaining.",
                max_digits=5,
                null=True,
                validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="estimated_remaining_feed_cost",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Feed cost still expected before the batch finishes.",
                max_digits=14,
                null=True,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="estimated_remaining_other_cost",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Other batch and shared costs still expected before completion.",
                max_digits=14,
                null=True,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
    ]
