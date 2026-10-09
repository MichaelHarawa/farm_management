"""Stream-before-domain boundary and ORM guards for the published entity set.

No on_commit publisher: projections, revisions and changes are written before
the same transaction commits. Unknown atomic writers fail closed instead of
silently taking domain locks before stream. Privileged raw SQL requires reset.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import uuid

from django.conf import settings
from django.db import connection, models, transaction

_current = ContextVar("mobile_sync_writer", default=None)


def capture_enabled():
    return settings.MOBILE_SYNC_CAPTURE


def current_writer():
    return _current.get()


class UnsafeSyncWrite(RuntimeError):
    pass


@contextmanager
def sync_boundary(*, operation_id=None):
    if not capture_enabled():
        yield None
        return
    parent = current_writer()
    if parent is not None:
        yield parent
        return
    from .models import SyncStreamState
    from .projections import publish_batches

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '20s'")
        stream = SyncStreamState.objects.select_for_update().get(pk=1)
        state = {"stream": stream, "batches": set(), "transaction_id": uuid.uuid4(),
                 "operation_id": operation_id, "entity_ids": {}, "changes": []}
        token = _current.set(state)
        try:
            yield state
            if not connection.needs_rollback:
                state["changes"].extend(publish_batches(state))
        finally:
            _current.reset(token)


def sync_atomic(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with model_boundary():
            return function(*args, **kwargs)
    return wrapped


def guarded_model_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with model_boundary():
            return function(*args, **kwargs)
    return wrapped


@contextmanager
def model_boundary():
    if capture_enabled() and current_writer() is None and connection.in_atomic_block:
        raise UnsafeSyncWrite("Registered atomic writer must enter sync_boundary before domain locks.")
    with sync_boundary():
        yield


def touch(instance):
    state = current_writer()
    if state is not None and instance.pk is not None:
        state["batches"].add(str(instance.pk if instance._meta.model_name == "batch" else instance.batch_id))


class TrackedQuerySet(models.QuerySet):
    def _raw_delete(self, using):
        from apps.finance.services.poultry_stock_guards import guard_queryset
        guard_queryset(self, deleting=True)
        if capture_enabled() and current_writer() is None:
            raise UnsafeSyncWrite("Unscoped raw deletion of a registered model is unsupported.")
        return super()._raw_delete(using)

    def update(self, **kwargs):
        from apps.finance.services.poultry_stock_guards import guard_queryset
        guard_queryset(self, kwargs)
        if not capture_enabled():
            return super().update(**kwargs)
        with model_boundary():
            rows = list(self[:10001])
            if len(rows) > 10000:
                raise UnsafeSyncWrite("Bulk writer exceeds 10,000 rows; use bounded stream transactions.")
            for row in rows:
                touch(row)
            result = super().update(**kwargs)
            for row in self.model.objects.filter(pk__in=[row.pk for row in rows]):
                touch(row)
            return result

    def delete(self):
        from apps.finance.services.poultry_stock_guards import guard_queryset
        guard_queryset(self, deleting=True)
        if not capture_enabled():
            return super().delete()
        with model_boundary():
            rows = list(self[:10001])
            if len(rows) > 10000:
                raise UnsafeSyncWrite("Delete exceeds bounded stream transaction size.")
            for row in rows:
                touch(row)
            return super().delete()

    def bulk_create(self, *args, **kwargs):
        if capture_enabled():
            raise UnsafeSyncWrite("bulk_create is unsupported for registered models; use explicit service saves.")
        return super().bulk_create(*args, **kwargs)

    def bulk_update(self, *args, **kwargs):
        if settings.FINANCE_POULTRY_STOCK_LINKAGE:
            # Bound the check to submitted objects rather than the whole table.
            from apps.finance.services.poultry_stock_guards import guard_queryset
            objs = tuple(args[0] if args else kwargs["objs"])
            fields = args[1] if len(args) > 1 else kwargs["fields"]
            guard_queryset(self.filter(pk__in=[obj.pk for obj in objs]), fields)
            if args:
                args = (objs, *args[1:])
            else:
                kwargs["objs"] = objs
        if capture_enabled():
            raise UnsafeSyncWrite("bulk_update is unsupported for registered models; use guarded update/save.")
        return super().bulk_update(*args, **kwargs)


class SyncTrackedModel(models.Model):
    objects = TrackedQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        with model_boundary():
            if self.pk and hasattr(self, "batch_id"):
                old = type(self).objects.filter(pk=self.pk).first()
                if old:
                    touch(old)
            result = super().save(*args, **kwargs)
            touch(self)
            return result

    def delete(self, *args, **kwargs):
        with model_boundary():
            touch(self)
            return super().delete(*args, **kwargs)

    def save_base(self, *args, **kwargs):
        with model_boundary():
            from apps.finance.services.poultry_stock_guards import stock_save_boundary
            with stock_save_boundary(self, kwargs.get("update_fields")):
                result = super().save_base(*args, **kwargs)
                touch(self)
                return result
