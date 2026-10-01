"""Additive sync metadata; never replaces a business primary key."""
import uuid

from django.conf import settings
from django.db import models
from .immutability import ImmutableMetadata


class SyncStreamState(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    deployment_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    epoch = models.UUIDField(default=uuid.uuid4, editable=False)
    sequence = models.PositiveBigIntegerField(default=0)
    minimum_sequence = models.PositiveBigIntegerField(default=0)
    ready = models.BooleanField(default=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="sync_singleton")]


class MobileDevice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    installation_id = models.UUIDField(unique=True)
    app_version = models.CharField(max_length=40)
    device_label = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=16, default="android")
    protocol_version = models.PositiveSmallIntegerField(default=1)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True)


class MobileSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MobileDeviceAudit(ImmutableMetadata):
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=32)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SyncEntity(models.Model):
    stream = models.ForeignKey(SyncStreamState, on_delete=models.PROTECT)
    entity_type = models.CharField(max_length=40)
    source_pk = models.CharField(max_length=64)
    entity_uuid = models.UUIDField(default=uuid.uuid4)
    batch_pk = models.CharField(max_length=64)
    revision = models.PositiveBigIntegerField(default=1)
    payload = models.JSONField(default=dict)
    deleted = models.BooleanField(default=False)
    in_current_pack = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["stream", "entity_type", "source_pk"], name="sync_source_identity"),
            models.UniqueConstraint(fields=["stream", "entity_uuid"], name="sync_uuid_identity"),
        ]
        indexes = [models.Index(fields=["stream", "batch_pk"], name="sync_entity_batch")]


class SyncChange(ImmutableMetadata):
    stream = models.ForeignKey(SyncStreamState, on_delete=models.PROTECT)
    sequence = models.PositiveBigIntegerField()
    transaction_id = models.UUIDField()
    transaction_index = models.PositiveIntegerField()
    transaction_count = models.PositiveIntegerField()
    entity_type = models.CharField(max_length=40)
    entity_uuid = models.UUIDField()
    batch_uuid = models.UUIDField()
    revision = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=24)
    payload = models.JSONField(default=dict)
    in_current_pack = models.BooleanField(default=False)
    origin_operation_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["stream", "sequence"], name="sync_change_sequence")]
        indexes = [models.Index(fields=["stream", "created_at"], name="sync_change_retention")]
        ordering = ["sequence"]


class SyncOperationReceipt(ImmutableMetadata):
    stream = models.ForeignKey(SyncStreamState, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    operation_id = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    command = models.JSONField()
    outcome = models.CharField(max_length=32)
    result = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["stream", "actor", "operation_id"], name="sync_operation_identity")]


class SyncBootstrap(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stream = models.ForeignKey(SyncStreamState, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    device = models.ForeignKey(MobileDevice, on_delete=models.PROTECT)
    epoch = models.UUIDField()
    scope_revision = models.CharField(max_length=64)
    packs = models.JSONField()
    watermark = models.PositiveBigIntegerField()
    row_count = models.PositiveIntegerField()
    manifest = models.JSONField()
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class SyncBootstrapPage(ImmutableMetadata):
    snapshot = models.ForeignKey(SyncBootstrap, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()
    payload = models.JSONField()
    checksum = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "number"], name="sync_bootstrap_page")]
