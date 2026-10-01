import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings

from .errors import SyncError
from .models import SyncChange, SyncEntity

TYPES = {"Batch": "poultry.batch", "Mortality": "poultry.mortality", "FeedUsage": "poultry.feed_usage"}
CURRENT_PACK = "operational-current-v1"


def json_value(value):
    if isinstance(value, datetime):
        from datetime import timezone
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def checksum(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def project(row, batch_uuid):
    from apps.poultry.services.batch_lifecycle import calculate_batch_status, calculate_bird_balance
    name = row._meta.object_name
    if name == "Batch":
        fields = ("batch_id", "bird_type", "broiler_strain", "source", "source_other", "booking_date",
                  "estimated_chick_arrival_date", "expected_quantity", "actual_quantity_received",
                  "entry_date", "expected_maturity_date", "delivery_confirmed_at", "quantity", "closed_at")
        balance = calculate_bird_balance(row)
        payload = {field: json_value(getattr(row, field)) for field in fields}
        payload.update(status=calculate_batch_status(row), initial_birds=balance.initial_birds,
                       sold_bird_count=balance.valid_bird_units_sold, total_mortality=balance.mortality,
                       remaining_birds=balance.remaining_live_birds)
        # Adjustment count includes signed approved arrivals/removals, not a guessed initial flock.
        payload["approved_adjustment_count"] = balance.remaining_live_birds - balance.initial_birds + balance.valid_bird_units_sold + balance.mortality
    else:
        fields = (("mortality_date", "quantity_dead", "age_in_days", "suspected_cause", "description", "action_taken", "reported_by_name")
                  if name == "Mortality" else
                  ("initial_age", "feeding_start_date", "feeding_end_date", "feed_type", "feed_source", "quantity_given",
                   "unit_of_measurement", "current_number_of_birds", "population_calculation_version", "population_calculated_at", "notes", "reported_by_name"))
        payload = {field: json_value(getattr(row, field)) for field in fields}
        payload["batch_uuid"] = str(batch_uuid)
        if name == "FeedUsage":
            payload["quantity_kg"] = str(row.quantity_kg)
    payload.update(server_id=str(row.pk), created_at=json_value(row.created_at), updated_at=json_value(row.updated_at))
    if len(canonical(payload).encode()) > settings.MOBILE_SYNC_ENTITY_BYTES:
        raise SyncError("entity_too_large", "Operational record exceeds transport size; reduce permitted source text before activation.", 413)
    return payload


def wire_entity(entity):
    return {"entity_type": entity.entity_type, "entity_uuid": str(entity.entity_uuid),
            "revision": str(entity.revision), "payload": entity.payload}


def publish_batches(state):
    from apps.poultry.models import Batch, FeedUsage, Mortality
    stream = state["stream"]
    pending = []
    for batch_pk in sorted(state["batches"], key=int):
        batch = Batch.objects.filter(pk=batch_pk).first()
        batch_mapping = SyncEntity.objects.filter(stream=stream, entity_type="poultry.batch", source_pk=batch_pk).first()
        if batch is None and batch_mapping is None:
            continue
        if batch_mapping is None:
            batch_mapping = SyncEntity.objects.create(stream=stream, entity_type="poultry.batch", source_pk=batch_pk, batch_pk=batch_pk)
            batch_mapping._new = True
        batch_uuid = batch_mapping.entity_uuid
        from apps.poultry.services.batch_lifecycle import calculate_batch_status
        current = bool(batch and calculate_batch_status(batch) != "closed")
        rows = [batch] if batch else []
        if batch:
            rows += list(Mortality.objects.filter(batch_id=batch_pk).order_by("pk")[:settings.MOBILE_SYNC_GROUP_ROWS + 1])
            if len(rows) > settings.MOBILE_SYNC_GROUP_ROWS:
                raise SyncError("transaction_too_large", "Batch exceeds the supported publication row budget.", 413)
            rows += list(FeedUsage.objects.filter(batch_id=batch_pk).order_by("pk")[:settings.MOBILE_SYNC_GROUP_ROWS + 1 - len(rows)])
            if len(rows) > settings.MOBILE_SYNC_GROUP_ROWS:
                raise SyncError("transaction_too_large", "Batch exceeds the supported publication row budget.", 413)
        present = set()
        for row in rows:
            entity_type = TYPES[row._meta.object_name]
            key = (entity_type, str(row.pk))
            present.add(key)
            entity = batch_mapping if row is batch else SyncEntity.objects.filter(stream=stream, entity_type=entity_type, source_pk=str(row.pk)).first()
            new = entity is None or getattr(entity, "_new", False) or (not entity.payload and not entity.deleted)
            if entity is None:
                preferred = state["entity_ids"].get(key)
                values = {"entity_uuid": preferred} if preferred else {}
                entity = SyncEntity.objects.create(stream=stream, entity_type=entity_type, source_pk=str(row.pk), batch_pk=batch_pk, **values)
            payload = project(row, batch_uuid)
            if entity.deleted:
                raise SyncError("entity_uuid_conflict", "A tombstoned identity cannot be rebound.", 409)
            if not new and entity.payload == payload and entity.in_current_pack == current:
                continue
            if not new:
                entity.revision += 1
            was_current = entity.in_current_pack
            entity.payload, entity.in_current_pack, entity.batch_pk = payload, current, batch_pk
            entity.save()
            pending.append((entity, batch_uuid, "upsert", payload, current))
            if was_current and not current:
                pending.append((entity, batch_uuid, "evict_from_pack", {}, False))
        for entity in SyncEntity.objects.filter(stream=stream, batch_pk=batch_pk, deleted=False):
            if (entity.entity_type, entity.source_pk) in present:
                continue
            entity.deleted = True
            entity.revision += 1
            entity.payload = {}
            entity.save()
            pending.append((entity, batch_uuid, "tombstone", {}, entity.in_current_pack))
    if len(pending) > settings.MOBILE_SYNC_GROUP_ROWS or sum(len(canonical(item[3]).encode()) + 1024 for item in pending) > settings.MOBILE_SYNC_GROUP_BYTES:
        raise SyncError("transaction_too_large", "Mutation exceeds bounded sync transaction budget.", 413)
    changes = []
    for index, (entity, batch_uuid, kind, payload, current) in enumerate(pending):
        stream.sequence += 1
        changes.append(SyncChange(stream=stream, sequence=stream.sequence, transaction_id=state["transaction_id"],
                                  transaction_index=index, transaction_count=len(pending), entity_type=entity.entity_type,
                                  entity_uuid=entity.entity_uuid, batch_uuid=batch_uuid, revision=entity.revision,
                                  kind=kind, payload=payload, in_current_pack=current, origin_operation_id=state["operation_id"]))
    SyncChange.objects.bulk_create(changes)
    stream.save(update_fields=["sequence"])
    return changes
