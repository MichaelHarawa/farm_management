from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0014_reconcile_input_costs"),
    ]

    operations = [
        migrations.AddField(
            model_name="fundingsource",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
    ]
