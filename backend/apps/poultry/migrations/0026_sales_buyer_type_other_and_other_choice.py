from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("poultry", "0025_batch_delivery_confirmed_at_alter_batch_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="sales",
            name="buyer_type_other",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AlterField(
            model_name="sales",
            name="buyer_type",
            field=models.CharField(
                choices=[
                    ("market_vendor", "Market Vendor"),
                    ("retail", "Retail"),
                    ("retail_supply", "Retail Supply"),
                    ("bulk_order", "Bulk Order"),
                    ("other", "Other"),
                ],
                max_length=20,
            ),
        ),
    ]
