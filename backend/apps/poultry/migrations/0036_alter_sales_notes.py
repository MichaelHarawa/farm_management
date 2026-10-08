from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("poultry", "0035_flockadjustmentproposal")]
    operations = [migrations.AlterField(model_name="sales", name="notes", field=models.TextField(blank=True))]
