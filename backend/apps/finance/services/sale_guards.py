"""Writer boundaries for explicitly journaled sales, not historical adoption.

Detect protected history through existing sale/payment/journal tables even with
all rollout gates off. Privileged SQL and unbound ORM imports are outside these
application guarantees. The private boundary is not device/API authorization.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Cast

from apps.mobile_sync.writers import TrackedQuerySet, model_boundary


_posting = ContextVar("financial_sale_posting", default=False)
SUMMARY_FIELDS = frozenset({"amount_paid", "balance", "payment_status", "updated_at"})
PAYMENT_KEYS = Q(idempotency_key__startswith="financial-receipt:") | Q(idempotency_key__startswith="sale-initial:")
JOURNAL_PREFIXES = ("financial-sale:", "sale-receipt:", "sale-selling-cost:")
MESSAGE = "Posted sale/cash evidence is immutable; a controlled source-linked correction is required."


@contextmanager
def sale_posting_boundary():
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError("Financial sale effects require an atomic command transaction.")
    token = _posting.set(True)
    try:
        yield
    finally:
        _posting.reset(token)


def _journal_sources(model, prefix, using):
    from ..models import JournalEntry
    return JournalEntry.objects.using(using).filter(source_model=model, idempotency_key__startswith=prefix).values("source_identifier")


def _managed_payments(rows):
    # Keys protect evidence before its journal is inserted in the same command.
    return rows.annotate(sale_guard_pk=Cast("pk", models.CharField())).filter(
        PAYMENT_KEYS | Q(sale_guard_pk__in=_journal_sources("finance.SalePayment", "sale-receipt:", rows.db)))


def managed_sales(rows):
    from ..models import SalePayment
    from apps.poultry.models import SaleSellingCost
    costs = SaleSellingCost.objects.using(rows.db).annotate(sale_guard_pk=Cast("pk", models.CharField())).filter(
        sale_guard_pk__in=_journal_sources("poultry.SaleSellingCost", "sale-selling-cost:", rows.db))
    return rows.annotate(sale_guard_pk=Cast("pk", models.CharField())).filter(
        Q(sale_guard_pk__in=_journal_sources("poultry.Sales", "financial-sale:", rows.db))
        | Q(pk__in=_managed_payments(SalePayment.objects.using(rows.db).all()).values("sale_id"))
        | Q(pk__in=costs.values("sale_id")))


def protected_sale_rows(rows):
    """Positive proof used by model guards and read-only admin permissions."""
    label = rows.model._meta.model_name
    if label == "sales":
        return managed_sales(rows).exists()
    from apps.poultry.models import Sales
    parent_ids = managed_sales(Sales.objects.using(rows.db).all()).values("pk")
    if label == "salepayment":
        return _managed_payments(rows).exists() or rows.filter(sale_id__in=parent_ids).exists()
    if label == "salesellingcost":
        return rows.annotate(sale_guard_pk=Cast("pk", models.CharField())).filter(
            Q(sale_id__in=parent_ids)
            | Q(sale_guard_pk__in=_journal_sources("poultry.SaleSellingCost", "sale-selling-cost:", rows.db))).exists()
    return False


def _guard_rows(rows, fields=(), *, deleting=False):
    if (rows.model._meta.model_name == "sales" and not deleting and _posting.get()
            and not (set(fields) - SUMMARY_FIELDS)):
        return
    if protected_sale_rows(rows):
        raise ValidationError(MESSAGE)


def _parent_id(value):
    value = getattr(value, "pk", value)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError("Sale evidence requires an explicit parent, not a bulk expression.")
    return value


def _lock_parents(ids, *, using):
    from apps.poultry.models import Sales
    return list(Sales.objects.using(using).select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))


def _guard_target(sale_id, *, using, existing=False):
    from apps.poultry.models import Sales
    if (existing or not _posting.get()) and managed_sales(Sales.objects.using(using).filter(pk=sale_id)).exists():
        raise ValidationError("This sale requires its atomic financial receipt/cost workflow; ordinary additions/rebinding are unavailable.")


def _guard_new(instance, *, using):
    if instance._meta.model_name == "salepayment" and not _posting.get() and (
            (instance.idempotency_key or "").startswith(("financial-receipt:", "sale-initial:"))):
        raise ValidationError("Reserved sale receipt keys require the atomic financial posting boundary.")
    if instance._meta.model_name != "sales":
        _guard_target(instance.sale_id, using=using)


def _locked_rows(rows, target=None):
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[:10001])
    if len(ids) > 10000:
        raise ValidationError("Sale-protected writes require bounded transactions.")
    fixed = rows.model.objects.using(rows.db).filter(pk__in=ids)
    if rows.model._meta.model_name != "sales":
        parents = set(fixed.values_list("sale_id", flat=True))
        if target is not None:
            parents.add(_parent_id(target))
        _lock_parents(parents, using=rows.db)
    list(fixed.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
    if rows.model._meta.model_name != "sales" and set(fixed.values_list("sale_id", flat=True)) - parents:
        raise ValidationError("Sale parent changed while waiting; retain the intent and retry after review.")
    return fixed


class SaleEvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with model_boundary(), transaction.atomic(using=self.db):
            target = kwargs.get("sale_id", kwargs.get("sale"))
            rows = _locked_rows(self, target)
            _guard_rows(rows, kwargs)
            if target is not None:
                _guard_target(_parent_id(target), using=self.db, existing=True)
            if "idempotency_key" in kwargs and self.model._meta.model_name == "salepayment":
                key = kwargs["idempotency_key"]
                if not (key is None or isinstance(key, str)) or (key or "").startswith(("financial-receipt:", "sale-initial:")):
                    raise ValidationError("Ordinary edits cannot reserve financial receipt keys.")
            return super(SaleEvidenceQuerySet, rows).update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        # One atomic refusal must precede any batch update.
        with model_boundary(), transaction.atomic(using=self.db):
            if {"sale", "sale_id", "idempotency_key"} & set(fields):
                raise ValidationError("Bulk rebinding/updating receipt keys requires controlled review.")
            _guard_rows(_locked_rows(self.filter(pk__in=[obj.pk for obj in objs])), fields)
            return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if len(objs) > 10000 or kwargs.get("update_conflicts"):
            raise ValidationError("Sale evidence bulk creation must be bounded and cannot upsert history.")
        with model_boundary(), transaction.atomic(using=self.db):
            _lock_parents({obj.sale_id for obj in objs}, using=self.db)
            for obj in objs:
                _guard_new(obj, using=self.db)
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        with model_boundary(), transaction.atomic(using=self.db):
            rows = _locked_rows(self)
            _guard_rows(rows, deleting=True)
            return super(SaleEvidenceQuerySet, rows).delete()

    def _raw_delete(self, using):
        with model_boundary(), transaction.atomic(using=using):
            rows = _locked_rows(self.using(using))
            _guard_rows(rows, deleting=True)
            return super(SaleEvidenceQuerySet, rows)._raw_delete(using)


class FinancialSaleQuerySet(SaleEvidenceQuerySet, TrackedQuerySet):
    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if len(objs) > 10000 or kwargs.get("update_conflicts"):
            raise ValidationError("Sale bulk creation cannot upsert existing financial history.")
        # Lock submitted existing IDs to catch PK-spoofing/ignore-conflicts.
        with model_boundary(), transaction.atomic(using=self.db):
            _guard_rows(_locked_rows(self.filter(pk__in=[obj.pk for obj in objs if obj.pk is not None])), deleting=True)
            return TrackedQuerySet.bulk_create(self, objs, **kwargs)


class SaleFinancialProtectedModel(models.Model):
    class Meta:
        abstract = True

    def save_base(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with model_boundary(), transaction.atomic(using=using):
            rows = type(self).objects.using(using).filter(pk=self.pk)
            old = rows.values().first() if self.pk else None
            if self._meta.model_name != "sales":
                parents = {self.sale_id} | ({old["sale_id"]} if old else set())
                _lock_parents(parents, using=using)
            old = rows.select_for_update().values().first() if self.pk else None
            if old and self._meta.model_name != "sales" and old["sale_id"] not in parents:
                raise ValidationError("Sale parent changed while waiting; retain the intent and retry after review.")
            if old:
                fields = kwargs.get("update_fields")
                changed = [field.attname for field in self._meta.concrete_fields
                    if (fields is None or field.name in fields or field.attname in fields)
                    and getattr(self, field.attname) != old[field.attname]]
                # Do not let full saves or raw imports re-run legacy derived math.
                if fields is None and not _posting.get():
                    changed = [field.attname for field in self._meta.concrete_fields]
                _guard_rows(rows, changed)
                if self._meta.model_name != "sales" and self.sale_id != old["sale_id"]:
                    _guard_target(self.sale_id, using=using, existing=True)
                if self._meta.model_name == "salepayment" and self.idempotency_key != old["idempotency_key"]:
                    _guard_new(self, using=using)
            else:
                _guard_new(self, using=using)
            return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with model_boundary(), transaction.atomic():
            _guard_rows(_locked_rows(type(self).objects.filter(pk=self.pk)), deleting=True)
            return super().delete(*args, **kwargs)


def _journal_history(rows):
    predicate = Q()
    for prefix in JOURNAL_PREFIXES:
        predicate |= Q(idempotency_key__startswith=prefix) | Q(reversal_of__idempotency_key__startswith=prefix)
    return rows.filter(predicate)


def _protected_journal_rows(rows):
    if rows.model._meta.model_name == 'journalentry':
        return _journal_history(rows).exists()
    from ..models import JournalEntry
    return rows.filter(journal_entry_id__in=_journal_history(JournalEntry.objects.using(rows.db).all()).values('pk')).exists()


def _lock_journal_rows(rows, target=None):
    ids = list(rows.order_by('pk').values_list('pk', flat=True)[:10001])
    if len(ids) > 10000:
        raise ValidationError('Journal-protected writes require bounded transactions.')
    fixed = rows.model.objects.using(rows.db).filter(pk__in=ids)
    if rows.model._meta.model_name == 'journalline':
        from ..models import JournalEntry
        parents = set(fixed.values_list('journal_entry_id', flat=True))
        if target is not None:
            parents.add(_parent_id(target))
        list(JournalEntry.objects.using(rows.db).select_for_update().filter(pk__in=parents).order_by('pk'))
    list(fixed.select_for_update(of=('self',)).order_by('pk').values_list('pk', flat=True))
    if rows.model._meta.model_name == 'journalline' and set(fixed.values_list('journal_entry_id', flat=True)) - parents:
        raise ValidationError('Journal parent changed while waiting; controlled review is required.')
    return fixed


def _guard_journal_target(instance, using):
    from ..models import JournalEntry
    if instance._meta.model_name == 'journalentry':
        if ((instance.idempotency_key or '').startswith(JOURNAL_PREFIXES)
                or _journal_history(JournalEntry.objects.using(using).filter(pk=instance.reversal_of_id)).exists()):
            if not _posting.get():
                raise ValidationError('Reserved sale journals require their atomic source command.')
    else:
        parent = _journal_history(JournalEntry.objects.using(using).filter(pk=instance.journal_entry_id)).first()
        if parent and (not _posting.get() or parent.status != 'draft'):
            raise ValidationError('Posted sale journal lines cannot be appended or rebound.')


class SaleJournalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with transaction.atomic(using=self.db):
            target = kwargs.get('journal_entry_id', kwargs.get('journal_entry'))
            rows = _lock_journal_rows(self, target)
            if _protected_journal_rows(rows):
                raise ValidationError(MESSAGE)
            # No expression/upsert can reclassify an existing legacy journal.
            if 'idempotency_key' in kwargs:
                key = kwargs['idempotency_key']
                if not isinstance(key, str) or key.startswith(JOURNAL_PREFIXES):
                    raise ValidationError('Journal key edits cannot reserve financial sale identities.')
            if 'reversal_of' in kwargs or 'reversal_of_id' in kwargs:
                from ..models import JournalEntry
                value = kwargs.get('reversal_of_id', kwargs.get('reversal_of'))
                original = _parent_id(value) if value is not None else None
                if _journal_history(JournalEntry.objects.using(self.db).filter(pk=original)).exists():
                    raise ValidationError(MESSAGE)
            if target is not None:
                from types import SimpleNamespace
                _guard_journal_target(SimpleNamespace(_meta=self.model._meta, journal_entry_id=_parent_id(target)), self.db)
            return models.QuerySet.update(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        with transaction.atomic(using=self.db):
            if {'journal_entry', 'journal_entry_id', 'idempotency_key', 'reversal_of', 'reversal_of_id'} & set(fields):
                raise ValidationError('Bulk journal rebinding requires controlled review.')
            if _protected_journal_rows(_lock_journal_rows(self.filter(pk__in=[obj.pk for obj in objs]))):
                raise ValidationError(MESSAGE)
            return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if len(objs) > 10000 or kwargs.get('update_conflicts'):
            raise ValidationError('Journal evidence must be bounded and cannot upsert history.')
        with transaction.atomic(using=self.db):
            if self.model._meta.model_name == 'journalline':
                from ..models import JournalEntry
                list(JournalEntry.objects.using(self.db).select_for_update().filter(
                    pk__in={obj.journal_entry_id for obj in objs}).order_by('pk'))
            for obj in objs:
                _guard_journal_target(obj, self.db)
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        with transaction.atomic(using=self.db):
            rows = _lock_journal_rows(self)
            if _protected_journal_rows(rows):
                raise ValidationError(MESSAGE)
            return models.QuerySet.delete(rows)

    def _raw_delete(self, using):
        with transaction.atomic(using=using):
            rows = _lock_journal_rows(self.using(using))
            if _protected_journal_rows(rows):
                raise ValidationError(MESSAGE)
            return models.QuerySet._raw_delete(rows, using)


class SaleJournalProtectedModel(models.Model):
    class Meta:
        abstract = True

    def save_base(self, *args, **kwargs):
        using = kwargs.get('using') or self._state.db or 'default'
        with transaction.atomic(using=using):
            rows = _lock_journal_rows(type(self).objects.using(using).filter(pk=self.pk),
                self.journal_entry_id if self._meta.model_name == 'journalline' else None)
            old = rows.values().first() if self.pk else None
            if old and _protected_journal_rows(rows):
                fields = set(kwargs.get('update_fields') or ())
                if not (self._meta.model_name == 'journalentry' and old['status'] == 'draft'
                        and self.status == 'posted' and _posting.get() and not kwargs.get('raw')
                        and fields and not fields - {'status', 'posted_by', 'posted_by_id', 'posted_at', 'updated_at'}):
                    raise ValidationError(MESSAGE)
            elif old and self._meta.model_name == 'journalentry' and (self.idempotency_key or '').startswith(JOURNAL_PREFIXES):
                raise ValidationError('An existing journal cannot be adopted as sale evidence.')
            elif not old or self._meta.model_name == 'journalline' or self.reversal_of_id != old['reversal_of_id']:
                _guard_journal_target(self, using)
            return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if _protected_journal_rows(_lock_journal_rows(type(self).objects.filter(pk=self.pk))):
                raise ValidationError(MESSAGE)
            return super().delete(*args, **kwargs)


def is_managed_sale_journal(journal_id):
    from ..models import JournalEntry
    sources = (Q(source_model="poultry.Sales", idempotency_key__startswith="financial-sale:")
        | Q(source_model="finance.SalePayment", idempotency_key__startswith="sale-receipt:")
        | Q(source_model="poultry.SaleSellingCost", idempotency_key__startswith="sale-selling-cost:"))
    opposites = (Q(reversal_of__source_model="poultry.Sales", reversal_of__idempotency_key__startswith="financial-sale:")
        | Q(reversal_of__source_model="finance.SalePayment", reversal_of__idempotency_key__startswith="sale-receipt:")
        | Q(reversal_of__source_model="poultry.SaleSellingCost", reversal_of__idempotency_key__startswith="sale-selling-cost:"))
    return JournalEntry.objects.filter(pk=journal_id).filter(sources | opposites).exists()
