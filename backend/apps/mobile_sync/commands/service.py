from copy import deepcopy
from datetime import datetime, timedelta
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.mobile_sync.authentication import check_binding
from apps.mobile_sync.errors import SyncError
from apps.mobile_sync.models import SyncEntity, SyncOperationReceipt
from apps.mobile_sync.policy import permits
from apps.mobile_sync.projections import checksum, json_value, publish_batches, wire_entity
from apps.mobile_sync.writers import sync_boundary
from .registry import REGISTRY


def normalized(value):
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    return json_value(value)


def order_operations(operations):
    by_id = {str(operation["operation_id"]): operation for operation in operations}
    if len(by_id) != len(operations):
        raise SyncError("duplicate_operation", "Each operation ID must appear once per request.")
    ordered, visiting, visited = [], set(), set()

    def visit(key):
        if key in visiting:
            raise SyncError("dependency_cycle", "Operation dependencies contain a cycle.")
        if key in visited:
            return
        visiting.add(key)
        for dependency in by_id[key]["depends_on"]:
            if str(dependency) in by_id:
                visit(str(dependency))
        visiting.remove(key)
        visited.add(key)
        ordered.append(by_id[key])
    for key in by_id:
        visit(key)
    return ordered


def outcome(command, status, code, message, fields=None):
    return {"operation_id": str(command["operation_id"]), "outcome": status, "code": code,
            "message": message, "field_errors": fields or {},
            "recovery_action": "wait_for_dependency" if status == "dependency_blocked" else "review_and_supersede"}


def execute(command, actor, session, token, *, mode="queued", version=1):
    with sync_boundary(operation_id=command["operation_id"]) as state:
        actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
        # Recheck under stream lock: revocation/role writes cannot race receipt replay.
        session = check_binding(token, actor.pk)
        if session is None:
            raise SyncError("device_required", "Bound mobile session required.", 403)
        stream = state["stream"]
        immutable = normalized(command)
        immutable["depends_on"] = sorted(immutable["depends_on"])
        request_hash = checksum({"deployment_id": str(stream.deployment_id), "actor_id": str(actor.pk),
                                 "device_id": str(session.device_id), "operation": immutable})
        existing = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=command["operation_id"]).first()
        if existing:
            if existing.device_id != session.device_id:
                raise SyncError("foreign_device", "Receipt belongs to another device.", 403)
            if existing.request_hash != request_hash:
                result = outcome(command, "conflict", "idempotency_mismatch", "Operation ID is bound to different content.")
                result["recovery_action"] = "query_original_operation"
                return result
            result = deepcopy(existing.result)
            if existing.outcome == "accepted":
                result["outcome"] = "replayed"
            return result
        spec = REGISTRY.get((command["entity_type"], command["action"], command["payload_version"]))
        if spec is None:
            return outcome(command, "validation_failed", "command_unavailable", "Command is unavailable.")
        if spec.mode != mode:
            return outcome(command, "validation_failed", "online_confirmation_required", "This action requires an explicit foreground online confirmation.")
        dependencies = list(SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                                                               operation_id__in=command["depends_on"]))
        if len(dependencies) != len(command["depends_on"]) or any(row.outcome != "accepted" for row in dependencies):
            return outcome(command, "dependency_blocked", "dependency_blocked", "A prerequisite is missing or not accepted.")
        state["dependencies"] = dependencies
        result = None
        if not permits(actor, spec.roles):
            result = outcome(command, "permission_denied", "permission_denied", "Current role cannot capture this event.")
        if command.get("supersedes_operation_id"):
            predecessor = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                operation_id=command["supersedes_operation_id"]).first()
            if predecessor is None or predecessor.outcome == "accepted":
                result = outcome(command, "conflict", "invalid_supersession", "Only an owned terminal rejection can be superseded.")
        if result is None and command["captured_at"] > timezone.now() + timedelta(minutes=5):
            result = outcome(command, "validation_failed", "future_capture", "Capture timestamp cannot be in the future.")
        if result is None and not spec.mutates_existing and SyncEntity.objects.filter(stream=stream, entity_uuid=command["entity_uuid"]).exists():
            result = outcome(command, "conflict", "entity_uuid_conflict", "Entity identity already exists.")
        if result is None:
            try:
                with transaction.atomic():
                    record, batch_mapping = spec.handler(command, actor, state)
                    changes = publish_batches(state)
                    state["changes"].extend(changes)
                    state["batches"].clear()
                    mapping = SyncEntity.objects.get(stream=stream, entity_type=command["entity_type"], source_pk=str(record.pk))
                    if batch_mapping is None:
                        batch_mapping = mapping
                    batch_mapping.refresh_from_db()
                    result = outcome(command, "accepted", "accepted", "Event recorded once.")
                    entities = [wire_entity(batch_mapping, version)]
                    if mapping.pk != batch_mapping.pk:
                        entities.append(wire_entity(mapping, version))
                    result.update(canonical_entities=entities,
                                  entity_mappings=[{"entity_type": mapping.entity_type, "entity_uuid": str(mapping.entity_uuid),
                                                    "server_id": mapping.source_pk, "revision": str(mapping.revision)}],
                                  transaction_id=str(state["transaction_id"]), committed_at=json_value(timezone.now()),
                                  recovery_action="reconcile_and_pull")
            except (DjangoValidationError, DRFValidationError, ValueError, SyncError) as error:
                # Savepoint rolls back source effects AND versions/change rows.
                # Python state must also be restored after PostgreSQL rollback.
                stream.refresh_from_db()
                state["batches"].clear()
                state["changes"].clear()
                state["entity_ids"].clear()
                fields = getattr(error, "message_dict", None) or getattr(error, "detail", None) or {"detail": str(error)}
                fields = normalized(fields)
                locked = "period_locked" in fields
                insufficient = any(item.code == "insufficient_birds" for errors in getattr(error, "error_dict", {}).values() for item in errors)
                conflict_code = error.detail.get("code") if isinstance(error, SyncError) and error.status_code == 409 else None
                status = "period_locked" if locked else "conflict" if insufficient or conflict_code else "validation_failed"
                code = "period_locked" if locked else "insufficient_birds" if insufficient else conflict_code or "invalid_business_event"
                result = outcome(command, status, code, "Event requires correction or review.", fields)
        SyncOperationReceipt.objects.create(stream=stream, actor=actor, device=session.device, operation_id=command["operation_id"],
            request_hash=request_hash, command=immutable, outcome=result["outcome"], result=result,
            committed_at=timezone.now() if result["outcome"] == "accepted" else None)
        return result
