from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("poultry", "0021_drugsvaccination_timely_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="drugsvaccination",
            name="drug_category",
            field=models.CharField(
                choices=[
                    ("vaccination", "Vaccination"),
                    ("drug", "Drug"),
                    ("antibiotic", "Antibiotic"),
                    ("vitamin", "Vitamin"),
                    ("dewormer", "Dewormer"),
                    ("other", "Other"),
                ],
                default="vaccination",
                max_length=200,
            ),
        ),
    ]
