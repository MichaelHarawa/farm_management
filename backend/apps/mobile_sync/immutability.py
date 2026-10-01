from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models

_pruning = ContextVar("sync_change_pruning", default=False)


@contextmanager
def change_pruning():
    token = _pruning.set(True)
    try:
        yield
    finally:
        _pruning.reset(token)


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError("Sync metadata is immutable; append a new version.")

    def bulk_update(self, *args, **kwargs):
        raise ValueError("Sync metadata is immutable.")

    def delete(self):
        if self.model._meta.model_name != "syncchange" or not _pruning.get():
            raise ValueError("Only bounded change retention may remove transported history.")
        return super().delete()


class ImmutableMetadata(models.Model):
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("Sync metadata is immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Sync metadata cannot be deleted through model APIs.")
