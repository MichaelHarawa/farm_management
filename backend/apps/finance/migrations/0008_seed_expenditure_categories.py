from django.db import migrations


DEFAULT_CATEGORIES = (
    ("Salaries and wages", "salaries_wages", "indirect_operating_expense", 10),
    ("Feed", "feed", "direct_cost", 20),
    ("Chicks or livestock", "chicks_livestock", "direct_cost", 30),
    ("Veterinary and medication", "veterinary_medication", "direct_cost", 40),
    ("Transport", "transport", "indirect_operating_expense", 50),
    ("Utilities", "utilities", "indirect_operating_expense", 60),
    (
        "Repairs and maintenance",
        "repairs_maintenance",
        "indirect_operating_expense",
        70,
    ),
    ("Construction", "construction", "capital_expenditure", 80),
    ("Equipment", "equipment", "capital_expenditure", 90),
    ("Crop inputs", "crop_inputs", "direct_cost", 100),
    ("Loan repayment", "loan_repayment", "loan_repayment", 110),
    ("Owner withdrawal", "owner_withdrawal", "owner_withdrawal", 120),
    (
        "General farm costs",
        "general_farm_costs",
        "indirect_operating_expense",
        130,
    ),
    ("Other", "other", "other", 140),
)


def seed_expenditure_categories(apps, schema_editor):
    expenditure_category = apps.get_model("finance", "ExpenditureCategory")

    for name, code, nature, display_order in DEFAULT_CATEGORIES:
        expenditure_category.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "default_accounting_nature": nature,
                "is_active": True,
                "display_order": display_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0007_expenditurecategory_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_expenditure_categories, migrations.RunPython.noop),
    ]
