from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("poultry", "0031_batch_forecast_assumptions")]

    operations = [
        migrations.AddField(
            model_name="sales",
            name="receivable_follow_up_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Person responsible for following up an outstanding sale balance.",
                max_length=200,
            ),
        ),
    ]
