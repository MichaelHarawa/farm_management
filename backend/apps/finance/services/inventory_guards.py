"""Application writer boundaries for explicitly managed stock, not legacy adoption.

Existing models detect managed history using StockMovement (present before the
Phase6 tables), even with capture flags off. Only private, transactional domain
effects may change balances. This is not protection from privileged SQL/imports.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Upper

from .poultry_stock_guards import PoultryProtectedQuerySet


_posting = ContextVar("managed_inventory_posting", default=False)
ITEM_IDENTITY = frozenset({"sku", "name", "base_unit", "costing_method"})
USAGE_LOCK_FIELDS = frozenset({"locked", "updated_at"})


@contextmanager
def inventory_posting_boundary():
    """Private permission within a service's durable source/GL transaction."""
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError("Inventory effects require an atomic command transaction.")
    token = _posting.set(True)
    try:
        yield
    finally:
        _posting.reset(token)


def _receipts():
    from ..models import StockMovement
    return StockMovement.objects.filter(idempotency_key__startswith="inventory-receipt:")


def guard_inventory_queryset(queryset, fields=(), *, deleting=False):
    label = queryset.model._meta.model_name
    if label == "consumableitem":
        protected = (deleting or bool(set(fields) & ITEM_IDENTITY)) and _receipts().filter(
            item_id__in=queryset.values("pk")).exists()
    elif label == "sharedconsumablelot":
        protected = _receipts().filter(lot_id__in=queryset.values("pk")).exists()
        if not deleting and _posting.get():
            # Internal balance/payment status writes do not edit supplier evidence.
            protected = protected and bool(set(fields) - {"quantity_available", "payment_status",
                "payment_date", "updated_at"})
    elif label == "consumableusage":
        if not deleting and not (set(fields) - USAGE_LOCK_FIELDS):
            return
        from ..models import StockMovement
        protected = StockMovement.objects.filter(usage_id__in=queryset.values("pk"),
            idempotency_key__startswith="inventory-issue:").exists()
    else:
        return
    if protected:
        raise ValidationError("Managed inventory evidence/identity is immutable; use a controlled stock workflow.")


def _guard_new_lot(lot):
    if _posting.get():
        return
    from ..models import ConsumableItem
    sku = "ITEM-" + "-".join(lot.item.upper().split())[:32]
    # Same item mutex as purchase/issue: legacy receipt creation cannot race a
    # first managed purchase. These names only REFUSE overlap, never bind stock.
    items = list(ConsumableItem.objects.select_for_update().filter(
        Q(name__iexact=lot.item) | Q(sku=sku)).order_by("pk").values_list("pk", flat=True))
    if _receipts().filter(item_id__in=items).exists():
        raise ValidationError("This item has managed stock; ordinary lot creation requires reconciliation.")


def _guard_new_usage(usage):
    if not _posting.get() and _receipts().filter(lot_id=usage.consumable_lot_id).exists():
        raise ValidationError("Managed stock usage requires one valued issue, movement and journal transaction.")


@contextmanager
def inventory_save_boundary(instance, update_fields=None):
    with transaction.atomic():
        rows = type(instance).objects.filter(pk=instance.pk)
        old = rows.select_for_update().values().first() if instance.pk else None
        if old:
            fields = [field.attname for field in instance._meta.concrete_fields
                if update_fields is None or field.name in update_fields or field.attname in update_fields]
            changed = [field for field in fields if getattr(instance, field) != old[field]]
            # Legacy save recomputes lot/usage costs. Even unchanged full saves
            # must not reprice already posted evidence or spoof an existing PK.
            if instance._meta.model_name in {"sharedconsumablelot", "consumableusage"}:
                changed = fields
            guard_inventory_queryset(rows, changed)
            if instance._meta.model_name == "sharedconsumablelot" and old['item'] != instance.item:
                _guard_new_lot(instance)
            elif (instance._meta.model_name == "consumableusage"
                    and old['consumable_lot_id'] != instance.consumable_lot_id):
                _guard_new_usage(instance)
        elif instance._meta.model_name == "sharedconsumablelot":
            _guard_new_lot(instance)
        elif instance._meta.model_name == "consumableusage":
            _guard_new_usage(instance)
        yield


def _locked_rows(queryset):
    ids = list(queryset.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True)[:10001])
    if len(ids) > 10000:
        raise ValidationError("Stock-protected writes require bounded transactions.")
    return queryset.model.objects.using(queryset.db).filter(pk__in=ids)


class InventoryProtectedQuerySet(PoultryProtectedQuerySet):
    def update(self, **kwargs):
        with transaction.atomic():
            rows = _locked_rows(self)
            guard_inventory_queryset(rows, kwargs)
            if self.model._meta.model_name == "sharedconsumablelot" and 'item' in kwargs:
                from types import SimpleNamespace
                if not isinstance(kwargs['item'], str):
                    raise ValidationError("Lot identity changes require explicit reviewed text, not a bulk expression.")
                _guard_new_lot(SimpleNamespace(item=kwargs['item']))
            elif self.model._meta.model_name == "consumableusage":
                from types import SimpleNamespace
                target = kwargs.get('consumable_lot_id', kwargs.get('consumable_lot'))
                if target is not None:
                    target = getattr(target, 'pk', target)
                    if not isinstance(target, (int, str)):
                        raise ValidationError("Stock usage cannot be rebound through a bulk expression.")
                    _guard_new_usage(SimpleNamespace(consumable_lot_id=target))
            return PoultryProtectedQuerySet.update(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        with transaction.atomic():
            rows = _locked_rows(self.filter(pk__in=[obj.pk for obj in objs]))
            guard_inventory_queryset(rows, fields)
            return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if kwargs.get("update_conflicts"):
            raise ValidationError("Inventory upserts cannot bypass source/valuation review.")
        with transaction.atomic():
            # Sorted candidate-item locking also bounds mixed ordinary imports.
            if len(objs) > 10000:
                raise ValidationError("Stock-protected writes require bounded transactions.")
            if self.model._meta.model_name == "sharedconsumablelot":
                from ..models import ConsumableItem
                names = [obj.item for obj in objs]
                skus = ["ITEM-" + "-".join(name.upper().split())[:32] for name in names]
                list(ConsumableItem.objects.select_for_update().annotate(
                    inventory_upper_name=Upper("name")).filter(
                    Q(inventory_upper_name__in=[name.upper() for name in names]) | Q(sku__in=skus)).order_by("pk"))
                for obj in objs:
                    _guard_new_lot(obj)
            elif self.model._meta.model_name == "consumableusage":
                for obj in objs:
                    _guard_new_usage(obj)
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        with transaction.atomic():
            rows = _locked_rows(self)
            guard_inventory_queryset(rows, deleting=True)
            return PoultryProtectedQuerySet.delete(rows)

    def _raw_delete(self, using):
        with transaction.atomic(using=using):
            rows = _locked_rows(self)
            guard_inventory_queryset(rows, deleting=True)
            return PoultryProtectedQuerySet._raw_delete(rows, using)


class InventoryProtectedModel(models.Model):
    class Meta:
        abstract = True

    def save_base(self, *args, **kwargs):
        with inventory_save_boundary(self, kwargs.get("update_fields")):
            return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            rows = _locked_rows(type(self).objects.filter(pk=self.pk))
            guard_inventory_queryset(rows, deleting=True)
            return super().delete(*args, **kwargs)


class InventoryStateQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if not _posting.get():
            raise ValidationError("Inventory balances require the atomic valued movement workflow.")
        return super().update(**kwargs)

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Inventory balances cannot be imported through bulk creation.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Inventory balances cannot be edited through bulk update.")

    def delete(self):
        raise ValidationError("Inventory balance/source history cannot be deleted.")

    def _raw_delete(self, using):
        raise ValidationError("Inventory balance/source history cannot be deleted.")


class InventoryStateModel(models.Model):
    class Meta:
        abstract = True

    def save_base(self, *args, **kwargs):
        if not _posting.get() or kwargs.get("raw"):
            raise ValidationError("Inventory balances/bindings require the atomic stock workflow.")
        return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Inventory balance/source history cannot be deleted.")


def guard_new_movement(movement):
    if _posting.get():
        return
    from ..models import ConsumableItem
    list(ConsumableItem.objects.select_for_update().filter(pk=movement.item_id))
    if ((movement.idempotency_key or "").startswith("inventory-")
            or _receipts().filter(Q(lot_id=movement.lot_id) | Q(item_id=movement.item_id)).exists()):
        raise ValidationError("Managed stock movements require the explicit source/valuation transaction.")


def require_inventory_posting():
    if not _posting.get():
        raise ValidationError("Managed stock evidence requires its atomic movement transaction.")


def is_managed_inventory_journal(journal_id):
    """GL-only reversal cannot change stock/payable/cash source history."""
    from django.db.models.functions import Cast
    from ..models import FundingAllocation, JournalEntry
    allocations = FundingAllocation.objects.filter(
        expenditure__idempotency_key__startswith="inventory-purchase:").annotate(
            source_text=Cast('pk', models.CharField())).values('source_text')
    original = (Q(source_model="finance.Expenditure", idempotency_key__startswith="inventory-purchase:")
        | Q(source_model="finance.ConsumableUsage", idempotency_key__startswith="inventory-issue:")
        | Q(source_model="finance.StockMovement", idempotency_key__startswith="inventory-")
        | Q(source_model="finance.FundingAllocation", idempotency_key__startswith="expenditure-payment:",
            source_identifier__in=allocations))
    opposite = (Q(reversal_of__source_model="finance.Expenditure", reversal_of__idempotency_key__startswith="inventory-purchase:")
        | Q(reversal_of__source_model="finance.ConsumableUsage", reversal_of__idempotency_key__startswith="inventory-issue:")
        | Q(reversal_of__source_model="finance.StockMovement", reversal_of__idempotency_key__startswith="inventory-")
        | Q(reversal_of__source_model="finance.FundingAllocation", reversal_of__idempotency_key__startswith="expenditure-payment:",
            reversal_of__source_identifier__in=allocations))
    return JournalEntry.objects.filter(pk=journal_id).filter(original | opposite).exists()
