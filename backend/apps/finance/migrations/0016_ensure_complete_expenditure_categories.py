from django.db import migrations


CATEGORIES = (
    ("Salaries and wages", "salaries_wages", "indirect_operating_expense", False, False, 10),
    ("Feed", "feed", "direct_cost", True, True, 20),
    ("Chicks or livestock", "chicks_livestock", "direct_cost", True, True, 30),
    ("Veterinary and medication", "veterinary_medication", "direct_cost", True, True, 40),
    ("Batch transport", "batch_transport", "direct_cost", True, True, 45),
    ("Transport", "transport", "indirect_operating_expense", False, False, 50),
    ("Batch utilities", "batch_utilities", "direct_cost", True, True, 55),
    ("Biosecurity", "biosecurity", "direct_cost", True, True, 56),
    ("Batch supplies", "batch_supplies", "direct_cost", True, True, 57),
    ("Utilities", "utilities", "indirect_operating_expense", False, False, 60),
    ("Repairs and maintenance", "repairs_maintenance", "indirect_operating_expense", False, False, 70),
    ("Construction", "construction", "capital_expenditure", True, False, 80),
    ("Equipment", "equipment", "capital_expenditure", True, False, 90),
    ("Crop inputs", "crop_inputs", "direct_cost", True, False, 100),
    ("Loan repayment", "loan_repayment", "loan_repayment", False, False, 110),
    ("Owner withdrawal", "owner_withdrawal", "owner_withdrawal", False, False, 120),
    ("General farm costs", "general_farm_costs", "indirect_operating_expense", False, False, 130),
    ("Other", "other", "other", True, False, 140),
)


def ensure_categories(apps, schema_editor):
    ExpenditureCategory = apps.get_model("finance", "ExpenditureCategory")
    for name, code, nature, item_details, batch_required, display_order in CATEGORIES:
        category, created = ExpenditureCategory.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "default_accounting_nature": nature,
                "requires_item_details": item_details,
                "requires_batch_beneficiary": batch_required,
                "is_active": True,
                "display_order": display_order,
            },
        )
        if not created:
            category.name = name
            category.default_accounting_nature = nature
            category.requires_item_details = item_details
            category.requires_batch_beneficiary = batch_required
            category.is_active = True
            category.display_order = display_order
            category.save(
                update_fields=[
                    "name",
                    "default_accounting_nature",
                    "requires_item_details",
                    "requires_batch_beneficiary",
                    "is_active",
                    "display_order",
                ]
            )


class Migration(migrations.Migration):
    dependencies = [("finance", "0015_fundingsource_is_active")]

    operations = [migrations.RunPython(ensure_categories, migrations.RunPython.noop)]
