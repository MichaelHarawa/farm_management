from django.db import migrations


SYSTEM_ROLES = (
    ("admin", "Admin"),
    ("director", "Director"),
    ("farm_manager", "Farm Manager"),
    ("farm_supervisor", "Farm Supervisor"),
    ("general_worker", "General Worker"),
    ("stake_holder", "Stake Holder"),
)


def seed_system_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for slug, name in SYSTEM_ROLES:
        Role.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "is_system": True},
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_accountauditevent")]

    operations = [migrations.RunPython(seed_system_roles, migrations.RunPython.noop)]
