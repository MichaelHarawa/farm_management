"""Explicit privileged-SQL corruption for reconciliation tests, never a writer.

Application edits must now refuse these mutations. Keep the independent
reconciliation tests by injecting damage only into an owned disposable test DB.
"""
from django.db import connection, models


def corrupt_inventory(model, pk, **values):
    if not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_"):
        raise AssertionError("Corruption injection requires the owned disposable mobile test database.")
    quote = connection.ops.quote_name
    fields = [model._meta.get_field(name) for name in values]
    with connection.cursor() as cursor:
        cursor.execute("UPDATE " + quote(model._meta.db_table) + " SET " +
            ", ".join(quote(field.column) + " = %s" for field in fields) +
            " WHERE " + quote(model._meta.pk.column) + " = %s", [*values.values(), pk])


def corrupt_inventory_insert(instance):
    if (not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_")
            or not instance._state.adding or instance.pk is not None):
        raise AssertionError("Unbound insertion requires the owned disposable mobile test database.")
    # Explicit low-level ORM insertion emulates a privileged import outside the
    # application model API, rather than granting a production write bypass.
    models.Model.save_base(instance, force_insert=True)
    return instance
