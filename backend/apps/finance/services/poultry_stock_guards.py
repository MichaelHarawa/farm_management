"""Protect consumed evidence, without querying new tables on legacy deployments."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from contextlib import contextmanager


DERIVED_FEED_FIELDS = frozenset({"current_number_of_birds", "population_calculation_version",
    "population_calculated_at", "updated_at"})


def guard_queryset(queryset, fields=(), *, deleting=False):
    if not settings.FINANCE_POULTRY_STOCK_LINKAGE:
        return
    label = queryset.model._meta.label_lower
    fields = set(fields)
    if label not in {"poultry.feedusage", "poultry.drugsvaccination", "finance.consumableusage", "finance.consumableitem"}:
        return
    from apps.finance.models import PoultryStockConsumption, PoultryStockItemPolicy
    ids = queryset.values("pk")
    if label == "finance.consumableitem":
        protected = deleting or bool(fields & {"base_unit", "costing_method"})
        linked = protected and PoultryStockItemPolicy.objects.filter(item_id__in=ids).exists()
    else:
        field = {"poultry.feedusage": "feed_id", "poultry.drugsvaccination": "treatment_id",
                 "finance.consumableusage": "usage_id"}[label]
        protected = deleting or label != "poultry.feedusage" or bool(fields - DERIVED_FEED_FIELDS)
        linked = protected and PoultryStockConsumption.objects.filter(**{f"{field}__in": ids}).exists()
    if linked:
        raise ValidationError("Stock-backed consumption evidence/units are immutable; use a controlled linked correction.")


def guard_instance(instance, update_fields=None):
    if not settings.FINANCE_POULTRY_STOCK_LINKAGE or instance._state.adding or not instance.pk:
        return
    label = instance._meta.label_lower
    if label not in {"poultry.feedusage", "poultry.drugsvaccination", "finance.consumableusage", "finance.consumableitem"}:
        return
    fields = [field.attname for field in instance._meta.concrete_fields if not field.primary_key]
    if update_fields is not None:
        fields = [field.attname for field in instance._meta.concrete_fields
                  if field.name in update_fields or field.attname in update_fields]
    old = type(instance).objects.select_for_update().filter(pk=instance.pk).values(*fields).first()
    changed = [field for field in fields if old is not None and getattr(instance, field) != old[field]]
    # ConsumableUsage.save recomputes cost in the legacy path: even an apparently
    # unchanged save must not reprice an already consumed managed issue.
    if label == "finance.consumableusage":
        changed = fields
    if changed:
        guard_queryset(type(instance).objects.filter(pk=instance.pk), changed)


class PoultryProtectedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if not settings.FINANCE_POULTRY_STOCK_LINKAGE:
            return super().update(**kwargs)
        with transaction.atomic():
            ids = list(self.select_for_update().order_by("pk").values_list("pk", flat=True)[:10001])
            if len(ids) > 10000:
                raise ValidationError("Stock-protected writes require bounded transactions.")
            guard_queryset(self.filter(pk__in=ids), kwargs)
            return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        guard_queryset(self.filter(pk__in=[obj.pk for obj in objs]), fields)
        return super().bulk_update(objs, fields, **kwargs)

    def delete(self):
        guard_queryset(self, deleting=True)
        return super().delete()

    def _raw_delete(self, using):
        guard_queryset(self, deleting=True)
        return super()._raw_delete(using)


@contextmanager
def stock_save_boundary(instance, update_fields=None):
    if not settings.FINANCE_POULTRY_STOCK_LINKAGE:
        yield
        return
    with transaction.atomic():
        guard_instance(instance, update_fields)
        yield
