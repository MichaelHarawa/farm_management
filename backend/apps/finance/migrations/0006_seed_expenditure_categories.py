from django.db import migrations


class Migration(migrations.Migration):
    """Compatibility step retained because later migrations depend on 0006.

    ExpenditureCategory is created in 0007, so seeding it here would always fail
    on a new database. The data seed now runs in 0008 after the table exists.
    """

    dependencies = [
        ("finance", "0005_add_expenditure_to_costallocation"),
    ]

    operations = []
