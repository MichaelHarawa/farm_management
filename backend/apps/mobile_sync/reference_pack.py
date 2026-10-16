"""Bounded private ONLINE reference bootstrap/pull. No route/native/cache grant.

Bootstrap is stateless/rebuildable, NOT a stored frozen snapshot. Every page must
reproduce the exact authorized catalog and manifest or refuse/restart. Signed
points retain their original absolute expiry across workers/restarts. Only a
complete consistent run may be used; never replace an active replica piecemeal.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone as utc_timezone
import re
import time
import uuid

from django.core import signing
from django.db.models import BigIntegerField, Case, F, Func, JSONField, Q, Subquery, TextField, Value, When
from django.db.models.functions import Cast
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError

from apps.finance.models import FundingSource
from apps.finance.permissions import has_owner_capital_access
from . import financial_references as funding, invoice_references as invoices, reference_publication as publication
from . import schema_reference_pack as wire
from .commands.financial import _gate
from .errors import SyncError
from .models import FinancialPublicationBinding, SyncChange
from .projections import canonical, checksum, json_value
from .transport import stream_ready
from .writers import sync_boundary

BASIS = "financial-reference-pack-private-v1"
TTL = 900
PAGE_ROWS, PAGE_BYTES, MAX_BYTES, SCAN_ROWS = 50, 131072, 2097152, 500
MAX_ROWS, PROOF_SECONDS = 1100, 10
SOURCE_FIELDS = ("pk", "source_type", "description", "is_active", "created_at", "batch_id", "owner_id")
VALID_ENTITY = Draft7Validator(wire.ENTITY, format_checker=FormatChecker())


def _review():
    raise SyncError("financial_reference_pack_review_required", "Published financial references require controlled review; never repair, adopt or replace original evidence automatically.", 503)


def _limit():
    raise SyncError("financial_reference_pack_limit", "Reference download exceeds its bounded proof or page budget; no partial pack is available.", 413)


def _gates():
    for name in ("MOBILE_SYNC_FINANCIAL_REFERENCE_PACKS", "MOBILE_SYNC_FINANCIAL_PUBLICATION",
            "MOBILE_SYNC_FINANCIAL_REFERENCES", "MOBILE_SYNC_FINANCIAL_READS"):
        _gate(name)


def _scope(stream, actor, session):
    return checksum({"basis": BASIS, "policy": 1, "access": funding._scope(stream, actor, session),
        "epoch": str(stream.epoch), "session": str(session.pk), "profile": wire.PACK,
        "page_rows": PAGE_ROWS, "page_bytes": PAGE_BYTES, "max_bytes": MAX_BYTES, "max_rows": MAX_ROWS,
        "types": list(publication.TYPES), "offline_cache_seconds": 0})


@contextmanager
def _boundary(actor, session, token):
    _gates()  # All missing gates refuse BEFORE auth/source SQL.
    actor, session = funding._access(actor, session, token)
    with sync_boundary():
        actor, session = funding._access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        yield stream, actor, session, scope
        actor, session = funding._access(actor, session, token)
        _gates()
        if _scope(stream_ready(), actor, session) != scope:
            raise SyncError("financial_reference_pack_scope_changed", "Current reference access changed; retain protected work and restart the download.", 409)


def _bindings(stream, actor, session):
    rows = FinancialPublicationBinding.objects.filter(entity__stream=stream, entity__entity_type__in=publication.TYPES).filter(
        Q(audience_actor__isnull=True) | Q(audience_actor=actor))
    return rows if has_owner_capital_access(actor) else rows.filter(requires_owner_access=False)


def _positive(entity):
    value = {"entity_type": entity.entity_type, "entity_uuid": str(entity.entity_uuid),
        "revision": str(entity.revision), "payload": deepcopy(entity.payload)}
    try:
        VALID_ENTITY.validate(value)
    except SchemaError:
        _review()
    if len(canonical(value).encode("utf-8")) > publication.MAX_ENTITY_BYTES:
        _limit()
    return value


def _current(stream, actor, session):
    """Complete authorized coverage or explicit refusal; NEVER baseline on read.

    Omit unbounded private funding notes in SQL. Measure projection JSON before
    fetching it and use the existing bounded original-receipt proof loader.
    """
    started = time.monotonic()
    query = FundingSource.objects.filter(source_type__in=funding.wire.SOURCE_TYPES)
    if not has_owner_capital_access(actor):
        query = query.exclude(source_type="owner_capital")
    sources = list(query.only(*SOURCE_FIELDS).order_by("pk")[:funding.MAX_CATALOG_ROWS + 1])
    if len(sources) > funding.MAX_CATALOG_ROWS:
        _limit()
    parents = invoices._bounded(invoices._owned(actor))
    expected = {(publication.wire.FUNDING_TYPE, str(row.pk)): row for row in sources}
    expected.update({(publication.wire.INVOICE_TYPE, str(row.pk)): row for row in parents})
    candidates = _bindings(stream, actor, session).filter(entity__deleted=False)
    sizes = list(candidates.annotate(size=Func(Cast("entity__payload", TextField()), function="OCTET_LENGTH",
        output_field=BigIntegerField())).order_by("pk").values_list("size", flat=True)[:MAX_ROWS + 1])
    if len(expected) > MAX_ROWS or len(sizes) > MAX_ROWS or any(size > publication.MAX_ENTITY_BYTES for size in sizes) or sum(sizes) > MAX_BYTES:
        _limit()
    if len(sizes) != len(expected):
        raise SyncError("financial_reference_pack_not_prepared", "Complete authorized reference publication must be prepared; no partial or legacy-derived pack is available.", 503)
    rows, present = [], set()
    for binding in candidates.select_related("entity__stream").order_by("entity__entity_type", "entity__entity_uuid"):
        entity = binding.entity
        key = (entity.entity_type, entity.source_pk)
        source = expected.get(key)
        if source is None or key in present or publication._match(entity, source) != entity.payload:
            _review()
        present.add(key)
        rows.append(_positive(entity))
        if time.monotonic() - started > PROOF_SECONDS:
            _limit()
    if present != set(expected):
        _review()
    if len(canonical(rows).encode("utf-8")) > MAX_BYTES:
        _limit()
    return rows


def _context(stream, actor, session, scope):
    return {"financial_reference_pack_version": 1, "pack_id": wire.PACK,
        "deployment_id": str(stream.deployment_id), "stream_epoch": str(stream.epoch),
        "actor_id": str(actor.pk), "device_id": str(session.device_id), "scope_revision": scope,
        "server_time": json_value(timezone.now()), "access": "online_only_current_finance_writer",
        "offline_cache_seconds": 0, "financial_uploads": False}


def _pages(rows):
    pages, page, size = [], [], 2
    for row in rows:
        length = len(canonical(row).encode("utf-8")) + 1
        if length > PAGE_BYTES - 8192:
            _limit()
        if page and (len(page) >= PAGE_ROWS or size + length > PAGE_BYTES - 8192):
            pages.append(page)
            page, size = [], 2
        page.append(row)
        size += length
    pages.append(page)
    return pages


def _save(point):
    return signing.dumps(point, salt=BASIS, compress=True)


def _point(scope, kind, **fields):
    issued = int(timezone.now().timestamp())
    return {"v": 1, "kind": kind, "scope": scope, "issued": issued, "expires": issued + TTL, **fields}


def _load(cursor, scope, kind, fields):
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
            raise ValueError
        point = signing.loads(cursor, salt=BASIS, max_age=TTL)
        if (not isinstance(point, dict) or set(point) != {"v", "kind", "scope", "issued", "expires", *fields}
                or type(point["v"]) is not int or point["v"] != 1 or point["kind"] != kind
                or type(point["issued"]) is not int or type(point["expires"]) is not int
                or point["expires"] != point["issued"] + TTL):
            raise ValueError
        if point["scope"] != scope:
            raise SyncError("financial_reference_pack_scope_changed", "Reference cursor belongs to another current scope; retain protected work and restart.", 409)
        now = int(timezone.now().timestamp())
        if now < point["issued"] or now >= point["expires"]:
            raise signing.SignatureExpired
        return point
    except signing.SignatureExpired:
        raise SyncError("financial_reference_pack_expired", "Reference download expired; retain original work and restart the download.", 410) from None
    except (signing.BadSignature, TypeError, ValueError):
        raise SyncError("invalid_cursor", "Use the exact original bounded financial reference cursor.") from None


def _counter(value, *, maximum):
    return type(value) is int and 0 <= value <= maximum


def _expiry(point):
    return json_value(datetime.fromtimestamp(point["expires"], utc_timezone.utc))


def begin_reference_pack(actor, session, token):
    with _boundary(actor, session, token) as (stream, actor, session, scope):
        rows = _current(stream, actor, session)
        pages = _pages(rows)
        catalog = checksum({"basis": BASIS, "scope": scope, "rows": rows})
        point = _point(scope, "snapshot", snapshot=str(uuid.uuid4()), watermark=stream.sequence, catalog=catalog, page=0)
        return {**_context(stream, actor, session, scope), "snapshot_id": point["snapshot"],
            "watermark": str(stream.sequence), "catalog_version": catalog, "expires_at": _expiry(point), "row_count": len(rows),
            "manifest": [{"page": number, "row_count": len(page), "sha256": checksum(page)} for number, page in enumerate(pages)],
            "next_page_cursor": _save(point)}


def reference_pack_page(snapshot_id, cursor, actor, session, token):
    with _boundary(actor, session, token) as (stream, actor, session, scope):
        point = _load(cursor, scope, "snapshot", {"snapshot", "watermark", "catalog", "page"})
        if (not invoices.ID.is_valid(snapshot_id) or point["snapshot"] != snapshot_id
                or not _counter(point["watermark"], maximum=stream.sequence)
                or not isinstance(point["catalog"], str) or not re.fullmatch(r"[0-9a-f]{64}", point["catalog"])
                or not _counter(point["page"], maximum=MAX_ROWS)):
            raise SyncError("invalid_cursor", "Snapshot and exact reference page cursor must match.")
        if point["watermark"] < stream.minimum_sequence:
            raise SyncError("resync_required", "Reference history was pruned; retain work and restart.", 410)
        rows = _current(stream, actor, session)
        if checksum({"basis": BASIS, "scope": scope, "rows": rows}) != point["catalog"]:
            raise SyncError("financial_reference_pack_changed", "Reference membership or values changed; preserve the active replica/work and restart staging.", 409)
        pages = _pages(rows)
        if point["page"] >= len(pages):
            raise SyncError("invalid_cursor", "Reference page is unavailable.")
        number, page = point["page"], pages[point["page"]]
        complete = number == len(pages) - 1
        delta = {key: point[key] for key in ("v", "scope", "issued", "expires")}
        delta.update(kind="changes", position=point["watermark"], upper=None, group=None, fragment=0)
        return {**_context(stream, actor, session, scope), "snapshot_id": snapshot_id, "watermark": str(point["watermark"]),
            "catalog_version": point["catalog"], "expires_at": _expiry(point), "page": number, "entities": page,
            "sha256": checksum(page), "next_page_cursor": None if complete else _save({**point, "page": number + 1}),
            "delta_cursor": _save(delta) if complete else None}


def reference_pack_changes(cursor, actor, session, token):
    with _boundary(actor, session, token) as (stream, actor, session, scope):
        point = _load(cursor, scope, "changes", {"position", "upper", "group", "fragment"})
        upper = stream.sequence if point["upper"] is None else point["upper"]
        if (not _counter(point["position"], maximum=stream.sequence) or not _counter(upper, maximum=stream.sequence)
                or upper < point["position"] or not _counter(point["fragment"], maximum=9223372036854775807)
                or (point["group"] is None) != (point["fragment"] == 0)
                or point["group"] is not None and not invoices.ID.is_valid(point["group"])):
            raise SyncError("invalid_cursor", "Retain the original reference continuation.")
        position = point["position"]
        if position < stream.minimum_sequence:
            raise SyncError("resync_required", "Reference history was pruned; retain work and restart.", 410)
        started = time.monotonic()
        _current(stream, actor, session)  # Detect missing baseline/flag-off capture before exposing ANY delta.
        active, expected_index, expected_count = point["group"], 0, 0
        if active:
            previous = SyncChange.objects.filter(stream=stream, sequence=position).values("transaction_id", "transaction_index", "transaction_count").first()
            if previous is None or str(previous["transaction_id"]) != active or previous["transaction_index"] >= previous["transaction_count"] - 1:
                _review()
            expected_index, expected_count = previous["transaction_index"] + 1, previous["transaction_count"]
        authorized = _bindings(stream, actor, session).values("entity__entity_uuid")
        # SQL CASE, not Python redaction: hidden operational/foreign invoice/owner
        # JSON is never fetched into the reference pack's row payload.
        query = SyncChange.objects.filter(stream=stream, sequence__gt=position, sequence__lte=upper).defer("payload").annotate(
            reference_payload=Case(When(entity_type__in=publication.TYPES, entity_uuid__in=Subquery(authorized), then=F("payload")),
                default=Value({}, output_field=JSONField()), output_field=JSONField())).order_by("sequence")
        changes, descriptors, size, inspected = [], {}, 0, False
        for row in query[:SCAN_ROWS].iterator(chunk_size=100):
            inspected = True
            group = str(row.transaction_id)
            if (row.sequence != position + 1 or row.transaction_count < 1 or row.transaction_index >= row.transaction_count
                    or active and (active != group or expected_index != row.transaction_index or expected_count != row.transaction_count)
                    or active is None and row.transaction_index != 0):
                _review()
            visible = row.entity_type in publication.TYPES and row.reference_payload != {}
            # Tombstones intentionally carry {}; check their immutable audience
            # separately, without fetching their original JSON.
            binding = None
            if row.entity_type in publication.TYPES:
                binding = _bindings(stream, actor, session).filter(entity__entity_uuid=row.entity_uuid).select_related("entity__stream").first()
                visible = binding is not None
            fragment_index = point["fragment"] if point["group"] == group else 0
            entry = {"sequence": str(row.sequence), "transaction_id": group, "fragment_index": fragment_index,
                "fragment_final": False, "entity_type": row.entity_type, "entity_uuid": str(row.entity_uuid), "revision": str(row.revision), "kind": row.kind}
            if visible:
                entity = binding.entity
                publication._binding(entity)
                if entity.entity_type != row.entity_type or row.revision < 1 or row.revision > entity.revision or row.batch_uuid is not None or row.in_current_pack:
                    _review()
                if row.kind == "upsert":
                    value = {"entity_type": row.entity_type, "entity_uuid": str(row.entity_uuid), "revision": str(row.revision), "payload": row.reference_payload}
                    try:
                        VALID_ENTITY.validate(value)
                    except SchemaError:
                        _review()
                    entry["payload"] = deepcopy(row.reference_payload)
                elif row.kind != "tombstone" or row.revision < 2 or row.reference_payload != {} or not entity.deleted or row.entity_type != publication.wire.FUNDING_TYPE:
                    _review()
            length, new_group = len(canonical(entry).encode("utf-8")) if visible else 0, group not in descriptors
            if time.monotonic() - started > PROOF_SECONDS:
                _limit()
            if length > PAGE_BYTES - 8192:
                _limit()
            if (visible and len(changes) >= PAGE_ROWS or new_group and len(descriptors) >= PAGE_ROWS
                    or size + length + (160 if new_group else 0) > PAGE_BYTES - 8192):
                break
            position = row.sequence
            descriptor = descriptors.setdefault(group, {"transaction_id": group, "fragment_index": fragment_index, "fragment_final": False})
            descriptor["fragment_final"] = row.transaction_index == row.transaction_count - 1
            size += length + (160 if new_group else 0)
            if visible:
                changes.append(entry)
            active = None if descriptor["fragment_final"] else group
            expected_index, expected_count = row.transaction_index + 1, row.transaction_count
        if time.monotonic() - started > PROOF_SECONDS:
            _limit()
        if not inspected and position < upper:
            _review()  # Missing unpruned history is not an empty successful run.
        complete = position == upper
        if complete and active:
            _review()
        for entry in changes:
            entry["fragment_final"] = descriptors[entry["transaction_id"]]["fragment_final"]
        next_point = {**point, "position": position, "upper": None if complete else upper, "group": active,
            "fragment": descriptors[active]["fragment_index"] + 1 if active else 0}
        return {**_context(stream, actor, session, scope), "run_watermark": str(upper), "changes": changes,
            "fragments": list(descriptors.values()), "next_cursor": _save(next_point), "run_complete": complete}
