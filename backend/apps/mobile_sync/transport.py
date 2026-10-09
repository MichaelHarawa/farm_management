from datetime import timedelta
import time
import uuid

from django.conf import settings
from django.core import signing
from django.utils import timezone

from .errors import SyncError
from .models import SyncBootstrap, SyncBootstrapPage, SyncChange, SyncEntity, SyncStreamState
from .policy import scope_revision
from .profiles import operational_profile
from .projections import (CURRENT_PACK, POULTRY_PACK, LEGACY_TYPES, pack_version, public_payload,
                          canonical, checksum, json_value, wire_entity)
from .writers import sync_boundary

CURSOR_SALT = "farm-mobile-sync-v1"


def stream_ready():
    stream = SyncStreamState.objects.filter(pk=1).first()
    if not stream or not stream.ready:
        raise SyncError("sync_not_ready", "Run migration and seed_sync before enabling devices.", 503)
    return stream


def cursor_base(stream, user, device, packs):
    return {"deployment": str(stream.deployment_id), "epoch": str(stream.epoch), "actor": str(user.pk),
            "device": str(device.pk), "scope": scope_revision(user, pack_version(packs)), "packs": packs, "protocol": 1}


def encode(value):
    return signing.dumps(value, salt=CURSOR_SALT, compress=True)


def decode(value, stream, user, device):
    if not value or len(value) > 16384:
        raise SyncError("invalid_cursor", "Bounded opaque cursor required.")
    try:
        data = signing.loads(value, salt=CURSOR_SALT, max_age=90 * 86400)
    except signing.SignatureExpired as error:
        raise SyncError("resync_required", "Cursor expired.", 410) from error
    except signing.BadSignature as error:
        raise SyncError("invalid_cursor", "Invalid cursor.") from error
    expected = cursor_base(stream, user, device, data.get("packs"))
    if pack_version(data.get("packs")) == 2 and not settings.MOBILE_SYNC_POULTRY_V2:
        raise SyncError("unsupported_protocol", "Poultry projection 2 is not enabled.", 409)
    if any(data.get(key) != expected[key] for key in expected):
        raise SyncError("scope_reset_required", "Deployment, epoch or access scope changed.", 409)
    return data


def validate_packs(packs, stream):
    if len(packs) != len(set(packs)):
        raise SyncError("invalid_pack", "Packs must be unique.")
    for pack in packs:
        if (pack == POULTRY_PACK or pack.startswith("batch-v2:")) and not settings.MOBILE_SYNC_POULTRY_V2:
            raise SyncError("invalid_pack", "Poultry projection 2 is not enabled.")
        if pack in {CURRENT_PACK, POULTRY_PACK}:
            continue
        prefix = "batch-v2:" if pack.startswith("batch-v2:") else "batch:"
        if not pack.startswith(prefix):
            raise SyncError("invalid_pack", "Pack is unavailable.")
        try:
            entity_uuid = uuid.UUID(pack[len(prefix):])
        except ValueError as error:
            raise SyncError("invalid_pack", "Invalid batch pack identity.") from error
        if pack[len(prefix):] != str(entity_uuid) or not SyncEntity.objects.filter(stream=stream, entity_type="poultry.batch", entity_uuid=entity_uuid, deleted=False).exists():
            raise SyncError("invalid_pack", "Batch pack is unavailable.")
    return sorted(packs)


def included(entity, packs, batch_uuid):
    if entity.entity_type not in operational_profile(pack_version(packs)).entities:
        return False
    legacy = entity.entity_type in LEGACY_TYPES
    return ((POULTRY_PACK in packs or CURRENT_PACK in packs and legacy) and entity.in_current_pack) or (
        f"batch-v2:{batch_uuid}" in packs or f"batch:{batch_uuid}" in packs and legacy)


def create_bootstrap(user, device, packs):
    started = time.monotonic()
    with sync_boundary() as state:
        stream = stream_ready()
        packs = validate_packs(packs, stream)
        scope = scope_revision(user, pack_version(packs))
        # A completed or lost-response download can request the same immutable
        # content again. Reuse only this actor/device's unexpired snapshot at
        # the current epoch/scope/watermark and exact pack set. No TTL extension,
        # stale-content reuse, cross-device access or quota increase.
        existing = SyncBootstrap.objects.filter(
            stream=stream, actor=user, device=device, epoch=stream.epoch,
            scope_revision=scope, watermark=stream.sequence, packs=packs,
            expires_at__gt=timezone.now(),
        ).order_by("created_at", "pk").first()
        if existing is not None:
            return existing
        if SyncBootstrap.objects.filter(stream=stream, actor=user, expires_at__gt=timezone.now()).count() >= settings.MOBILE_SYNC_ACTIVE_SNAPSHOTS_PER_USER:
            raise SyncError("snapshot_limit", "Active snapshot quota reached; resume an existing snapshot or wait for expiry.", 429)
        batches = list(SyncEntity.objects.filter(stream=stream, entity_type="poultry.batch", deleted=False).values_list("source_pk", "entity_uuid")[:settings.MOBILE_SYNC_SNAPSHOT_ROWS + 1])
        if len(batches) > settings.MOBILE_SYNC_SNAPSHOT_ROWS:
            raise SyncError("snapshot_budget_exceeded", "Batch identity scan exceeds this deployment's snapshot budget.", 413)
        batch_ids = {source_pk: str(entity_uuid) for source_pk, entity_uuid in batches}
        pages, page, row_count = [], [], 0
        page_bytes = total_bytes = 0
        for scanned, entity in enumerate(SyncEntity.objects.filter(stream=stream, deleted=False).order_by("entity_type", "pk").iterator(chunk_size=500), 1):
            if scanned > settings.MOBILE_SYNC_SNAPSHOT_ROWS or time.monotonic() - started > 20:
                raise SyncError("snapshot_budget_exceeded", "Snapshot scan exceeds supported request budget.", 413)
            if not included(entity, packs, batch_ids.get(entity.batch_pk)):
                continue
            item = wire_entity(entity) if pack_version(packs) == 1 else wire_entity(entity, 2)
            size = len(canonical(item).encode())
            total_bytes += size + 2
            if total_bytes > settings.MOBILE_SYNC_SNAPSHOT_BYTES:
                raise SyncError("snapshot_budget_exceeded", "Snapshot exceeds supported storage/memory budget; reduce requested packs.", 413)
            if page and (len(page) >= settings.MOBILE_SYNC_PAGE_ROWS or page_bytes + size > settings.MOBILE_SYNC_PAGE_BYTES - 32768):
                pages.append(page)
                page, page_bytes = [], 0
            page.append(item)
            page_bytes += size
            row_count += 1
            if row_count > settings.MOBILE_SYNC_SNAPSHOT_ROWS or time.monotonic() - started > 20:
                raise SyncError("snapshot_budget_exceeded", "Snapshot exceeds supported request budget; reduce requested packs.", 413)
        pages.append(page)  # Empty farm has one genuine empty page.
        manifest = [{"page": number, "row_count": len(rows), "sha256": checksum(rows)} for number, rows in enumerate(pages)]
        snapshot = SyncBootstrap.objects.create(stream=stream, actor=user, device=device, epoch=stream.epoch,
            scope_revision=scope, packs=packs, watermark=stream.sequence, row_count=row_count,
            manifest=manifest, expires_at=timezone.now() + timedelta(hours=24))
        SyncBootstrapPage.objects.bulk_create([SyncBootstrapPage(snapshot=snapshot, number=number, payload=rows, checksum=manifest[number]["sha256"])
                                               for number, rows in enumerate(pages)])
    return snapshot


def owned_snapshot(snapshot_id, user, device):
    stream = stream_ready()
    snapshot = SyncBootstrap.objects.filter(pk=snapshot_id, stream=stream, actor=user, device=device).first()
    if snapshot is None:
        raise SyncError("snapshot_not_found", "Snapshot is unavailable.", 404)
    if snapshot.expires_at <= timezone.now():
        raise SyncError("resync_required", "Snapshot expired; restart staging without removing pending work.", 410)
    if snapshot.epoch != stream.epoch or snapshot.scope_revision != scope_revision(user, pack_version(snapshot.packs)):
        raise SyncError("scope_reset_required", "Snapshot scope or epoch changed.", 409)
    return snapshot, stream


def bootstrap_manifest(snapshot, stream, user, device):
    base = cursor_base(stream, user, device, snapshot.packs)
    return {"snapshot_id": str(snapshot.pk), "deployment_id": str(stream.deployment_id), "stream_epoch": str(stream.epoch),
            "scope_revision": snapshot.scope_revision, "watermark": str(snapshot.watermark), "expires_at": json_value(snapshot.expires_at),
            "packs": snapshot.packs, "row_count": snapshot.row_count, "manifest": snapshot.manifest,
            "next_page_cursor": encode({**base, "kind": "page", "snapshot": str(snapshot.pk), "page": 0})}


def bootstrap_page(snapshot, stream, user, device, cursor):
    data = decode(cursor, stream, user, device)
    if data.get("kind") != "page" or data.get("snapshot") != str(snapshot.pk) or data.get("packs") != snapshot.packs:
        raise SyncError("invalid_cursor", "Cursor is not for this snapshot.")
    page = snapshot.pages.filter(number=data["page"]).first()
    if page is None:
        raise SyncError("invalid_cursor", "Page is unavailable.")
    # Never silently rewrite a frozen page/checksum. Refuse a malformed or
    # wider-contract snapshot, leaving the client's replica/outbox intact.
    profile = operational_profile(pack_version(snapshot.packs))
    for item in page.payload:
        if item.get("entity_type") not in profile.entities or item != {
                "entity_type": item.get("entity_type"), "entity_uuid": item.get("entity_uuid"),
                "revision": item.get("revision"),
                "payload": public_payload(item["entity_type"], item.get("payload"), profile.version)}:
            raise SyncError("invalid_projection", "Frozen snapshot is outside its projection profile; retain pending work and restart staging.", 503)
    final = page.number == len(snapshot.manifest) - 1
    base = cursor_base(stream, user, device, snapshot.packs)
    response = {"snapshot_id": str(snapshot.pk), "page": page.number, "entities": page.payload, "sha256": page.checksum,
                "page_complete": final, "next_page_cursor": None if final else encode({**data, "page": page.number + 1})}
    if final:
        response["delta_cursor"] = encode({**base, "kind": "changes", "position": snapshot.watermark, "upper": None, "group": None, "fragment": 0})
    return response


def pull_changes(user, device, cursor, limit):
    stream = stream_ready()
    data = decode(cursor, stream, user, device)
    if data.get("kind") != "changes":
        raise SyncError("invalid_cursor", "Change cursor required.")
    if data["position"] < stream.minimum_sequence:
        raise SyncError("resync_required", "Required history was pruned.", 410)
    upper = stream.sequence if data["upper"] is None else data["upper"]
    position = data["position"]
    changes, fragments, descriptors = [], [], {}
    size = 0
    rows = SyncChange.objects.filter(stream=stream, sequence__gt=position, sequence__lte=upper)[:settings.MOBILE_SYNC_SCAN_ROWS].iterator(chunk_size=500)
    inspected = False
    profile = operational_profile(pack_version(data["packs"]))
    for row in rows:
        inspected = True
        group = str(row.transaction_id)
        legacy = row.entity_type in LEGACY_TYPES
        archive_packs = [p for p in data["packs"] if p == f"batch-v2:{row.batch_uuid}" or legacy and p == f"batch:{row.batch_uuid}"]
        current_packs = [p for p in data["packs"] if p == POULTRY_PACK or legacy and p == CURRENT_PACK]
        archive = bool(archive_packs)
        current = bool(current_packs) and (row.in_current_pack or row.kind == "evict_from_pack")
        visible = row.entity_type in profile.entities and ((archive and row.kind != "evict_from_pack") or current)
        fragment_index = data["fragment"] if data["group"] == group else 0
        entry = {"sequence": str(row.sequence), "transaction_id": group, "fragment_index": fragment_index,
                 "fragment_final": False, "entity_type": row.entity_type, "entity_uuid": str(row.entity_uuid),
                 "revision": str(row.revision), "kind": row.kind,
                 "pack_ids": (current_packs if current else []) + (archive_packs if archive and row.kind != "evict_from_pack" else [])}
        if visible and row.kind == "upsert":
            entry["payload"] = public_payload(row.entity_type, row.payload, pack_version(data["packs"]))
        if row.origin_operation_id:
            entry["origin_operation_id"] = str(row.origin_operation_id)
        entry_size = len(canonical(entry).encode()) if visible else 0
        new_descriptor = group not in descriptors
        descriptor_size = 160 if new_descriptor else 0
        if (visible and len(changes) >= limit) or (
            size + descriptor_size + (entry_size if visible else 0) > settings.MOBILE_SYNC_PAGE_BYTES - 32768
        ) or (new_descriptor and len(descriptors) >= settings.MOBILE_SYNC_PAGE_ROWS):
            break
        position = row.sequence  # Also advances over hidden-only history.
        descriptor = descriptors.setdefault(group, {"transaction_id": group, "fragment_index": fragment_index, "fragment_final": False})
        size += descriptor_size
        descriptor["fragment_final"] = row.transaction_index == row.transaction_count - 1
        if visible:
            changes.append(entry)
            size += entry_size
    if not inspected:
        position = upper
    fragments = list(descriptors.values())
    for entry in changes:
        entry["fragment_final"] = descriptors[entry["transaction_id"]]["fragment_final"]
    complete = position >= upper
    unfinished = fragments[-1] if fragments and not fragments[-1]["fragment_final"] else None
    next_data = {**data, "position": position, "upper": None if complete else upper,
                 "group": unfinished["transaction_id"] if unfinished else None,
                 "fragment": unfinished["fragment_index"] + 1 if unfinished else 0}
    return {"deployment_id": str(stream.deployment_id), "stream_epoch": str(stream.epoch), "scope_revision": data["scope"],
            "run_watermark": str(upper), "changes": changes, "fragments": fragments,
            "next_cursor": encode(next_data), "run_complete": complete, "server_time": json_value(timezone.now())}
