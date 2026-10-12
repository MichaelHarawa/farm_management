"""Private writer boundaries for managed drafts/payables and payment evidence.

Existing keys/journals identify managed history with rollout flags off, without
querying additive Phase6 tables. This is not device authorization, legacy
adoption or protection from privileged SQL/unbound low-level ORM imports.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Cast

from apps.mobile_sync.writers import model_boundary


_mode = ContextVar("managed_expenditure_effect", default=None)
SOURCE_PREFIXES = ("financial-expense:", "inventory-purchase:")
PAYMENT_PREFIXES = ("financial-initial:", "financial-payment:", "inventory-initial:")
MESSAGE = "Managed expenditure/payment evidence requires its versioned atomic workflow or a controlled source-linked correction."
DRAFT_FIELDS = frozenset({"expenditure_date", "amount", "category", "category_id", "accounting_period",
    "accounting_period_id", "accounting_nature", "description", "payee", "external_reference", "notes",
    "cost_allocation_plan", "beneficiary_type", "usd_equivalent", "updated_at"})
POST_FIELDS = frozenset({"status", "posted_by", "posted_by_id", "posted_at", "payment_status", "updated_at"})
PAYMENT_FIELDS = frozenset({"payment_status", "updated_at"})


@contextmanager
def expenditure_effect_boundary(mode):
    if mode not in {"create", "edit", "post", "payment"} or not transaction.get_connection().in_atomic_block:
        raise ValidationError("Expenditure effects require an explicit atomic command transaction.")
    token = _mode.set(mode)
    try:
        yield
    finally:
        _mode.reset(token)


def _journals(using):
    from ..models import JournalEntry
    return JournalEntry.objects.using(using).all()


def managed_expenditures(rows):
    sources = _journals(rows.db).filter(source_model="finance.Expenditure").filter(
        Q(idempotency_key__startswith="financial-expenditure:") | Q(idempotency_key__startswith="inventory-purchase:"))
    return rows.annotate(expense_guard_pk=Cast("pk", models.CharField())).filter(
        Q(idempotency_key__startswith="financial-expense:") | Q(idempotency_key__startswith="inventory-purchase:")
        | Q(expense_guard_pk__in=sources.values("source_identifier")))


def protected_expenditure_rows(rows):
    from ..models import Expenditure
    if rows.model._meta.model_name == "expenditure":
        return managed_expenditures(rows).exists()
    return rows.filter(expenditure_id__in=managed_expenditures(
        Expenditure.objects.using(rows.db).all()).values("pk")).exists()


def require_expenditure_effect(expenditure, mode):
    if managed_expenditures(type(expenditure).objects.filter(pk=expenditure.pk)).exists() and _mode.get() != mode:
        raise ValidationError(MESSAGE)


def _guard(rows, fields=(), *, deleting=False):
    if not protected_expenditure_rows(rows):
        return
    fields = set(fields)
    label = rows.model._meta.model_name
    if not deleting and label == "costallocation" and not fields - {"locked", "updated_at"}:
        # Period lock/unlock metadata does not rewrite the allocation economics.
        return
    if not deleting and label == "expenditure":
        mode = _mode.get()
        allowed = {"edit": DRAFT_FIELDS, "post": POST_FIELDS, "payment": PAYMENT_FIELDS}.get(mode)
        if allowed is not None and not fields - allowed:
            managed = managed_expenditures(rows)
            expected_status = "posted" if mode == "payment" else "draft"
            if mode == "post" and not fields - PAYMENT_FIELDS:
                return
            if not managed.exclude(status=expected_status).exists():
                return
    raise ValidationError(MESSAGE)


def _parent(value):
    value = getattr(value, "pk", value)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError("Expenditure rebinding requires an explicit parent, not an expression.")
    return value


def _lock_parents(ids, using):
    from ..models import Expenditure
    list(Expenditure.objects.using(using).select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))


def _lock_rows(rows, target=None):
    ids = list(rows.order_by("pk").values_list("pk", flat=True)[:10001])
    if len(ids) > 10000:
        raise ValidationError("Expenditure-protected writes require bounded transactions.")
    fixed = rows.model.objects.using(rows.db).filter(pk__in=ids)
    if rows.model._meta.model_name != "expenditure":
        parents = set(fixed.values_list("expenditure_id", flat=True))
        if target is not None:
            parents.add(_parent(target))
        _lock_parents(parents - {None}, rows.db)
    list(fixed.select_for_update(of=("self",)).order_by("pk").values_list("pk", flat=True))
    if rows.model._meta.model_name != "expenditure" and set(fixed.values_list("expenditure_id", flat=True)) - parents:
        raise ValidationError("Expenditure parent changed while waiting; retain the intent for review.")
    return fixed


def _target(expenditure_id, using, *, creating=False, label=None):
    from ..models import Expenditure
    parent = managed_expenditures(Expenditure.objects.using(using).filter(pk=expenditure_id)).first()
    if parent:
        permitted = creating and ((label == "costallocation" and _mode.get() == "post" and parent.status == "draft")
            or (label == "fundingallocation" and _mode.get() == "payment" and parent.status == "posted"))
        if not permitted:
            raise ValidationError(MESSAGE)


def _new(instance, using):
    label = instance._meta.model_name
    if label == "expenditure":
        if (instance.idempotency_key or "").startswith(SOURCE_PREFIXES) and _mode.get() != "create":
            raise ValidationError("Reserved expenditure identities require an atomic create command.")
        if instance.reversed_expenditure_id:
            _target(instance.reversed_expenditure_id, using)
    else:
        _target(instance.expenditure_id, using, creating=True, label=label)
        if label == "fundingallocation" and (instance.payment_group_key or "").startswith(PAYMENT_PREFIXES) and _mode.get() != "payment":
            raise ValidationError("Reserved supplier-payment identities require an atomic payment command.")


class ExpenditureEvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with model_boundary(), transaction.atomic(using=self.db):
            target = kwargs.get("expenditure_id", kwargs.get("expenditure"))
            rows = _lock_rows(self, target)
            _guard(rows, kwargs)
            if target is not None:
                _target(_parent(target), self.db)
            for name, prefixes in (("idempotency_key", SOURCE_PREFIXES), ("payment_group_key", PAYMENT_PREFIXES)):
                if name in kwargs and (not (kwargs[name] is None or isinstance(kwargs[name], str))
                        or (kwargs[name] or "").startswith(prefixes)):
                    raise ValidationError("Ordinary edits cannot reserve financial identities.")
            if "reversed_expenditure" in kwargs or "reversed_expenditure_id" in kwargs:
                _target(_parent(kwargs.get("reversed_expenditure_id", kwargs.get("reversed_expenditure"))), self.db)
            return models.QuerySet.update(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        with model_boundary(), transaction.atomic(using=self.db):
            if {"expenditure", "expenditure_id", "idempotency_key", "payment_group_key", "reversed_expenditure", "reversed_expenditure_id"} & set(fields):
                raise ValidationError("Bulk financial identity/parent rebinding requires review.")
            _guard(_lock_rows(self.filter(pk__in=[obj.pk for obj in objs])), fields)
            return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if len(objs) > 10000 or kwargs.get("update_conflicts"):
            raise ValidationError("Expenditure bulk writes must be bounded and cannot upsert history.")
        with model_boundary(), transaction.atomic(using=self.db):
            _guard(_lock_rows(self.filter(pk__in=[obj.pk for obj in objs if obj.pk is not None])), deleting=True)
            if self.model._meta.model_name != "expenditure":
                _lock_parents({obj.expenditure_id for obj in objs} - {None}, self.db)
            for obj in objs:
                _new(obj, self.db)
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        with model_boundary(), transaction.atomic(using=self.db):
            rows = _lock_rows(self)
            _guard(rows, deleting=True)
            return models.QuerySet.delete(rows)

    def _raw_delete(self, using):
        with model_boundary(), transaction.atomic(using=using):
            rows = _lock_rows(self.using(using))
            _guard(rows, deleting=True)
            return models.QuerySet._raw_delete(rows, using)


class ExpenditureProtectedModel(models.Model):
    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        using = self._state.db or "default"
        if not self.pk or not type(self).objects.using(using).filter(pk=self.pk).exists():
            _new(self, using)

    def save_base(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with model_boundary(), transaction.atomic(using=using):
            rows = type(self).objects.using(using).filter(pk=self.pk)
            old = rows.values().first() if self.pk else None
            if self._meta.model_name != "expenditure":
                parents = {self.expenditure_id} | ({old["expenditure_id"]} if old else set())
                _lock_parents(parents - {None}, using)
            old = rows.select_for_update().values().first() if self.pk else None
            if old and self._meta.model_name != "expenditure" and old["expenditure_id"] not in parents:
                raise ValidationError("Expenditure parent changed while waiting; retain the intent for review.")
            if old:
                fields = kwargs.get("update_fields")
                changed = [field.attname for field in self._meta.concrete_fields
                    if (fields is None or field.name in fields or field.attname in fields)
                    and getattr(self, field.attname) != old[field.attname]]
                if kwargs.get("raw") or (fields is None and _mode.get() is None):
                    changed = [field.attname for field in self._meta.concrete_fields]
                _guard(rows, changed)
                if self._meta.model_name != "expenditure" and self.expenditure_id != old["expenditure_id"]:
                    _target(self.expenditure_id, using)
                elif self._meta.model_name == "expenditure" and self.idempotency_key != old["idempotency_key"]:
                    if (self.idempotency_key or "").startswith(SOURCE_PREFIXES):
                        raise ValidationError("Existing expenditures cannot be adopted as managed history.")
                if self._meta.model_name == "fundingallocation" and self.payment_group_key != old["payment_group_key"]:
                    if (self.payment_group_key or "").startswith(PAYMENT_PREFIXES):
                        raise ValidationError("Existing funding rows cannot be adopted as managed payments.")
                if self._meta.model_name == "expenditure" and self.reversed_expenditure_id != old["reversed_expenditure_id"]:
                    _target(self.reversed_expenditure_id, using)
            else:
                _new(self, using)
            return super().save_base(*args, **kwargs)

    def delete(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or "default"
        with model_boundary(), transaction.atomic(using=using):
            _guard(_lock_rows(type(self).objects.using(using).filter(pk=self.pk)), deleting=True)
            return super().delete(*args, **kwargs)


def expenditure_journal_history(rows):
    from ..models import FundingAllocation, Expenditure
    allocations = FundingAllocation.objects.using(rows.db).filter(expenditure_id__in=managed_expenditures(
        Expenditure.objects.using(rows.db).all()).values("pk")).annotate(expense_guard_pk=Cast("pk", models.CharField()))
    direct = Q(idempotency_key__startswith="financial-expenditure:") | Q(idempotency_key__startswith="inventory-purchase:")
    payments = Q(source_model="finance.FundingAllocation", source_identifier__in=allocations.values("expense_guard_pk"))
    return rows.filter(direct | payments | Q(reversal_of__idempotency_key__startswith="financial-expenditure:")
        | Q(reversal_of__idempotency_key__startswith="inventory-purchase:")
        | Q(reversal_of__source_model="finance.FundingAllocation", reversal_of__source_identifier__in=allocations.values("expense_guard_pk")))


def expenditure_journal_authorized(instance, using):
    if instance._meta.model_name == "journalline":
        parent = expenditure_journal_history(_journals(using).filter(pk=instance.journal_entry_id)).first()
        return parent is not None and parent.status == "draft" and _mode.get() in {"post", "payment"}
    if (instance.idempotency_key or "").startswith(("financial-expenditure:", "inventory-purchase:")):
        return _mode.get() == "post"
    return new_expenditure_journal(instance, using) and _mode.get() == "payment"


def new_expenditure_journal(instance, using):
    if instance._meta.model_name != "journalentry":
        return False
    key = instance.idempotency_key or ""
    if key.startswith(("financial-expenditure:", "inventory-purchase:")):
        return True
    from ..models import FundingAllocation
    if instance.source_model == "finance.FundingAllocation":
        return protected_expenditure_rows(FundingAllocation.objects.using(using).annotate(
            expense_guard_pk=Cast("pk", models.CharField())).filter(expense_guard_pk=instance.source_identifier))
    return False
