"""Bound explicitly journaled owner capital without adopting legacy receipts.

Reserved identities and existing journals work with rollout flags off. This
private creation boundary is not device/actor authorization or a correction API;
privileged SQL and unbound low-level ORM writes remain outside these guarantees.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Cast

from apps.mobile_sync.writers import model_boundary


RECEIPT_PREFIX = "financial-owner:"
JOURNAL_PREFIX = "financial-owner-receipt:"
MESSAGE = "Managed owner-capital evidence requires its atomic contribution workflow or a controlled source-linked correction."
OWNER_METADATA = frozenset({"display_name", "notes", "is_active", "updated_at"})
_posting = ContextVar("financial_owner_capital_posting", default=False)


@contextmanager
def owner_capital_posting_boundary():
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError("Owner-capital effects require an atomic command transaction.")
    token = _posting.set(True)
    try:
        yield
    finally:
        _posting.reset(token)


def managed_owner_receipts(rows):
    from ..models import JournalEntry
    originals = JournalEntry.objects.using(rows.db).filter(
        source_model="finance.FundingReceipt", idempotency_key__startswith=JOURNAL_PREFIX)
    return rows.annotate(owner_guard_pk=Cast("pk", models.CharField())).filter(
        Q(idempotency_key__startswith=RECEIPT_PREFIX)
        | Q(owner_guard_pk__in=originals.values("source_identifier")))


def require_owner_capital_command(key):
    if (key or "").startswith(RECEIPT_PREFIX) and not _posting.get():
        raise ValidationError(MESSAGE)


def managed_owner_sources(rows):
    from ..models import FundingReceipt
    return rows.filter(pk__in=managed_owner_receipts(
        FundingReceipt.objects.using(rows.db).all()).values("funding_source_id"))


def _parent(value):
    value = getattr(value, "pk", value)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError("Capital evidence requires an explicit parent, not an expression.")
    return value


def _fixed_rows(rows):
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[:10001])
    if len(ids) > 10000:
        raise ValidationError("Capital evidence writes require bounded transactions.")
    return rows.model.objects.using(rows.db).filter(pk__in=ids)


def _lock_sources(ids, using):
    from ..models import FundingSource
    list(FundingSource.objects.using(using).select_for_update().filter(
        pk__in=ids - {None}).order_by("pk").values_list("pk", flat=True))


def lock_funding_rows(rows, target_source=None):
    """Source before receipt, matching normal capital/loan posting order."""
    fixed = _fixed_rows(rows)
    if rows.model._meta.model_name == "fundingreceipt":
        sources = set(fixed.values_list("funding_source_id", flat=True))
        if target_source is not None:
            sources.add(_parent(target_source))
        _lock_sources(sources, rows.db)
    list(fixed.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
    if rows.model._meta.model_name == "fundingreceipt" and set(
            fixed.values_list("funding_source_id", flat=True)) - sources:
        raise ValidationError("Receipt source changed while waiting; retain the evidence for review.")
    return fixed


def guard_owner_receipt_creation(instance, using):
    from ..models import FundingSource, FundingReceipt
    key = instance.idempotency_key or ""
    source = FundingSource.objects.using(using).filter(pk=instance.funding_source_id).first()
    if key.startswith(RECEIPT_PREFIX):
        if not _posting.get() or source is None or source.source_type != "owner_capital" or source.owner_id is None:
            raise ValidationError(MESSAGE)
        existing = FundingReceipt.objects.using(using).filter(funding_source_id=source.pk)
        if existing.exclude(pk__in=managed_owner_receipts(existing).values("pk")).exists():
            raise ValidationError("This owner source has legacy receipt evidence; explicit reconciliation is required, not adoption.")
    elif managed_owner_sources(FundingSource.objects.using(using).filter(pk=instance.funding_source_id)).exists():
        raise ValidationError(MESSAGE)


def guard_owner_receipt_rebinding(rows, changes):
    if rows.model._meta.model_name != "fundingreceipt":
        return
    if "idempotency_key" in changes:
        key = changes["idempotency_key"]
        if not (key is None or isinstance(key, str)) or (key or "").startswith(RECEIPT_PREFIX):
            raise ValidationError("Existing receipts cannot adopt a reserved capital identity.")
    if "funding_source" in changes or "funding_source_id" in changes:
        from ..models import FundingSource
        target = _parent(changes.get("funding_source_id", changes.get("funding_source")))
        if managed_owner_sources(FundingSource.objects.using(rows.db).filter(pk=target)).exists():
            raise ValidationError(MESSAGE)


def owner_journal_history(rows):
    from ..models import FundingReceipt
    receipts = managed_owner_receipts(FundingReceipt.objects.using(rows.db).all())
    ids = receipts.annotate(owner_receipt_id=Cast("pk", models.CharField())).values("owner_receipt_id")
    return rows.filter(Q(idempotency_key__startswith=JOURNAL_PREFIX)
        | Q(source_model="finance.FundingReceipt", source_identifier__in=ids)
        | Q(reversal_of__idempotency_key__startswith=JOURNAL_PREFIX)
        | Q(reversal_of__source_model="finance.FundingReceipt", reversal_of__source_identifier__in=ids))


def new_owner_journal(instance, using):
    if instance._meta.model_name != "journalentry":
        return False
    if (instance.idempotency_key or "").startswith(JOURNAL_PREFIX):
        return True
    if instance.source_model == "finance.FundingReceipt":
        from ..models import FundingReceipt
        return managed_owner_receipts(FundingReceipt.objects.using(using).annotate(
            owner_receipt_id=Cast("pk", models.CharField())).filter(owner_receipt_id=instance.source_identifier)).exists()
    return False


def owner_journal_authorized(instance, using):
    if not _posting.get():
        return False
    from ..models import JournalEntry, FundingReceipt
    if instance._meta.model_name == "journalline":
        parent = owner_journal_history(JournalEntry.objects.using(using).filter(pk=instance.journal_entry_id)).first()
        return parent is not None and parent.status == "draft"
    if instance.source_model != "finance.FundingReceipt":
        return False
    receipt = managed_owner_receipts(FundingReceipt.objects.using(using).annotate(
        owner_receipt_id=Cast("pk", models.CharField())).filter(owner_receipt_id=instance.source_identifier)).first()
    return receipt is not None and instance.idempotency_key == f"{JOURNAL_PREFIX}{receipt.pk}"


def protected_owner_rows(rows):
    label = rows.model._meta.model_name
    from ..models import FundingReceipt, FundingSource
    if label == "ownercontributor":
        sources = managed_owner_sources(FundingSource.objects.using(rows.db).all())
        return rows.filter(pk__in=sources.values("owner_id")).exists()
    return rows.filter(receipt_id__in=managed_owner_receipts(
        FundingReceipt.objects.using(rows.db).all()).values("pk")).exists()


def _guard_rows(rows, fields=(), *, deleting=False):
    if rows.model._meta.model_name == "ownercontributor" and not deleting and not set(fields) - OWNER_METADATA:
        return
    if protected_owner_rows(rows):
        raise ValidationError(MESSAGE)


def _lock_receipts(ids, using):
    from ..models import FundingReceipt
    return lock_funding_rows(FundingReceipt.objects.using(using).filter(pk__in=ids - {None}))


def _lock_rows(rows, target=None):
    fixed = _fixed_rows(rows)
    if rows.model._meta.model_name == "ownerreceiptdesignation":
        parents = set(fixed.values_list("receipt_id", flat=True))
        if target is not None:
            parents.add(_parent(target))
        _lock_receipts(parents, rows.db)
    list(fixed.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
    if rows.model._meta.model_name == "ownerreceiptdesignation" and set(fixed.values_list("receipt_id", flat=True)) - parents:
        raise ValidationError("Designation parent changed while waiting; retain its evidence for review.")
    return fixed


def _guard_target(receipt_id, using, *, creating=False):
    from ..models import FundingReceipt
    if managed_owner_receipts(FundingReceipt.objects.using(using).filter(pk=receipt_id)).exists():
        if not creating or not _posting.get():
            raise ValidationError(MESSAGE)


class OwnerCapitalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with model_boundary(), transaction.atomic(using=self.db):
            target = kwargs.get("receipt_id", kwargs.get("receipt"))
            rows = _lock_rows(self, target)
            _guard_rows(rows, kwargs)
            if target is not None:
                _guard_target(_parent(target), self.db)
            return models.QuerySet.update(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        with model_boundary(), transaction.atomic(using=self.db):
            if {"receipt", "receipt_id"} & set(fields):
                raise ValidationError("Bulk designation rebinding requires controlled review.")
            _guard_rows(_lock_rows(self.filter(pk__in=[obj.pk for obj in objs])), fields)
            return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if len(objs) > 10000 or kwargs.get("update_conflicts"):
            raise ValidationError("Capital evidence bulk creation must be bounded and cannot upsert history.")
        with model_boundary(), transaction.atomic(using=self.db):
            _guard_rows(_lock_rows(self.filter(pk__in=[obj.pk for obj in objs if obj.pk is not None])), deleting=True)
            if self.model._meta.model_name == "ownerreceiptdesignation":
                _lock_receipts({obj.receipt_id for obj in objs}, self.db)
                for obj in objs:
                    _guard_target(obj.receipt_id, self.db, creating=True)
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        with model_boundary(), transaction.atomic(using=self.db):
            rows = _lock_rows(self)
            _guard_rows(rows, deleting=True)
            return models.QuerySet.delete(rows)

    def _raw_delete(self, using):
        with model_boundary(), transaction.atomic(using=using):
            rows = _lock_rows(self.using(using))
            _guard_rows(rows, deleting=True)
            return models.QuerySet._raw_delete(rows, using)


class OwnerCapitalProtectedModel(models.Model):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        if self._meta.model_name == "ownerreceiptdesignation" and (
                not self.pk or not type(self).objects.filter(pk=self.pk).exists()):
            _guard_target(self.receipt_id, self._state.db or "default", creating=True)

    def save_base(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with model_boundary(), transaction.atomic(using=using):
            rows = type(self).objects.using(using).filter(pk=self.pk)
            old = rows.values().first() if self.pk else None
            if self._meta.model_name == "ownerreceiptdesignation":
                parents = {self.receipt_id} | ({old["receipt_id"]} if old else set())
                _lock_receipts(parents, using)
            old = rows.select_for_update().values().first() if self.pk else None
            if old and self._meta.model_name == "ownerreceiptdesignation" and old["receipt_id"] not in parents:
                raise ValidationError("Designation parent changed while waiting; retain its evidence for review.")
            if old:
                fields = kwargs.get("update_fields")
                changed = [field.attname for field in self._meta.concrete_fields
                    if (fields is None or field.name in fields or field.attname in fields)
                    and getattr(self, field.attname) != old[field.attname]]
                if kwargs.get("raw") or self._meta.model_name == "ownerreceiptdesignation":
                    changed = [field.attname for field in self._meta.concrete_fields]
                _guard_rows(rows, changed)
                if self._meta.model_name == "ownerreceiptdesignation" and self.receipt_id != old["receipt_id"]:
                    _guard_target(self.receipt_id, using)
            elif self._meta.model_name == "ownerreceiptdesignation":
                _guard_target(self.receipt_id, using, creating=True)
            return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with model_boundary(), transaction.atomic(using=using):
            _guard_rows(_lock_rows(type(self).objects.using(using).filter(pk=self.pk)), deleting=True)
            return super().delete(*args, **kwargs)
