# Generated manually for the batch source field.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("poultry", "0012_alter_feedusage_feeding_end_date_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="source",
            field=models.CharField(default="Central Poultry", max_length=200),
        ),
    ]
