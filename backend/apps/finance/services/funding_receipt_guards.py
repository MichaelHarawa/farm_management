"""Keep explicitly posted funding evidence immutable, including when capture is off.

Only the new reserved key namespace is protected. No old receipt is adopted,
converted or rewritten. Privileged SQL remains outside application guarantees.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


MANAGED_PREFIX = "financial-funding:"
_posting = ContextVar("financial_funding_posting", default=False)
_linked_journal_reversal = ContextVar("linked_funding_journal_reversal", default=None)
SOURCE_BINDING_FIELDS = {"source_type", "batch", "batch_id", "owner", "owner_id"}


@contextmanager
def funding_journal_reversal_boundary(journal_id):
    """Private permission for one original journal inside its source transaction."""
    token = _linked_journal_reversal.set(journal_id)
    try:
        yield
    finally:
        _linked_journal_reversal.reset(token)


def linked_funding_reversal_allowed(journal_id):
    return journal_id is not None and _linked_journal_reversal.get() == journal_id


@contextmanager
def funding_posting_boundary():
    token = _posting.set(True)
    try:
        yield
    finally:
        _posting.reset(token)


def _managed(queryset):
    return queryset.filter(idempotency_key__startswith=MANAGED_PREFIX)


def guard_funding_queryset(queryset, fields=(), *, deleting=False):
    if queryset.model._meta.model_name == "fundingreceipt":
        protected = _managed(queryset).exists()
    else:
        if not deleting and not (set(fields) & SOURCE_BINDING_FIELDS):
            return
        from ..models import FundingReceipt
        protected = _managed(FundingReceipt.objects.filter(funding_source_id__in=queryset.values("pk"))).exists()
        if not protected:
            from apps.poultry.models import Sales
            from .sale_guards import managed_sales
            protected = queryset.filter(source_type="batch_collection", batch_id__in=
                managed_sales(Sales.objects.using(queryset.db).all()).values("batch_id")).exists()
        if not protected:
            from ..models import JournalLine
            protected = JournalLine.objects.filter(funding_source_id__in=queryset.values("pk"),
                journal_entry__source_model="finance.SaleCostPayment",
                journal_entry__idempotency_key__startswith="sale-cost-payment:").exists()
    if protected:
        raise ValidationError("Posted funding evidence/source binding is immutable; a controlled source-linked correction is required.")


class FundingProtectedQuerySet(models.QuerySet):
    def update(self, **kwargs):
        with transaction.atomic():
            ids = list(self.select_for_update().order_by("pk").values_list("pk", flat=True)[:10001])
            if len(ids) > 10000:
                raise ValidationError("Funding-protected writes require bounded transactions.")
            rows = self.filter(pk__in=ids)
            guard_funding_queryset(rows, kwargs)
            return models.QuerySet.update(rows, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        objs = tuple(objs)
        guard_funding_queryset(self.filter(pk__in=[obj.pk for obj in objs]), fields)
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        objs = tuple(objs)
        if self.model._meta.model_name != "fundingreceipt":
            if kwargs.get("update_conflicts"):
                raise ValidationError("Funding-source upserts cannot bypass economic-binding review.")
            return super().bulk_create(objs, **kwargs)
        with transaction.atomic():
            if any((obj.idempotency_key or "").startswith(MANAGED_PREFIX) for obj in objs):
                raise ValidationError("Managed funding receipts require the atomic financial posting boundary.")
            from ..models import FundingReceipt, FundingSource, FundingSourceType
            source_ids = {obj.funding_source_id for obj in objs}
            sources = list(FundingSource.objects.select_for_update().filter(pk__in=source_ids).order_by("pk"))
            if ((getattr(settings, "FINANCE_FUNDING_RECEIPTS", False)
                    and any(source.source_type == FundingSourceType.LOAN for source in sources))
                    or _managed(FundingReceipt.objects.filter(funding_source_id__in=source_ids)).exists()):
                raise ValidationError("Managed loan sources require the verified financial receipt boundary.")
            return super().bulk_create(objs, **kwargs)

    def delete(self):
        guard_funding_queryset(self, deleting=True)
        return super().delete()

    def _raw_delete(self, using):
        guard_funding_queryset(self, deleting=True)
        return super()._raw_delete(using)


@contextmanager
def funding_save_boundary(instance, update_fields=None):
    with transaction.atomic():
        rows = type(instance).objects.filter(pk=instance.pk)
        old = rows.select_for_update().values().first() if instance.pk else None
        if instance._meta.model_name == "fundingreceipt":
            if old and (old["idempotency_key"] or "").startswith(MANAGED_PREFIX):
                raise ValidationError("Posted funding evidence is immutable; controlled source-linked reversal is unavailable.")
            if (instance.idempotency_key or "").startswith(MANAGED_PREFIX) and not _posting.get():
                raise ValidationError("Managed funding receipts require the atomic financial posting boundary.")
            if old is None and not _posting.get():
                from ..models import FundingSource, FundingSourceType, FundingReceipt
                source = FundingSource.objects.select_for_update().filter(pk=instance.funding_source_id).first()
                if source and ((getattr(settings, "FINANCE_FUNDING_RECEIPTS", False)
                        and source.source_type == FundingSourceType.LOAN)
                        or _managed(FundingReceipt.objects.filter(funding_source=source)).exists()):
                    raise ValidationError("This loan source requires the verified financial receipt boundary; ordinary receipt creation is unavailable.")
        elif old:
            changed = [field.attname for field in instance._meta.concrete_fields
                if (update_fields is None or field.name in update_fields or field.attname in update_fields)
                and getattr(instance, field.attname) != old[field.attname]]
            guard_funding_queryset(rows, changed)
        yield
