"""Private global reference publisher. No route/pack/native offline grant.

Capture supported source writers under the EXISTING stream-before-domain lock.
Final projections and all operational/global changes share ONE group/count and
commit, never on_commit. Per-source first-before fingerprints handle caught
savepoint rollbacks, create/delete no-ops and changed-queryset predicates.
"""
from copy import deepcopy
import re
import uuid

from django.conf import settings
from django.db import connection
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError

from apps.finance.models import FinancialCommandReceipt, FundingSource, FundingSourceType
from apps.finance.permissions import has_owner_capital_access
from apps.finance.services.inventory_invoices import COMMAND as INVOICE_COMMAND
from . import financial_references as funding, invoice_references as invoices, schema_reference_publication as wire
from .commands.financial import _gate
from .errors import SyncError
from .models import FinancialPublicationBinding, SyncEntity
from .projections import canonical, checksum
from .transport import stream_ready
from .writers import current_writer, sync_boundary

BASIS = "financial-reference-publication-private-v1"
TYPES = (wire.FUNDING_TYPE, wire.INVOICE_TYPE)
MAX_DIRTY = 100
MAX_ENTITY_BYTES = 65536
VALIDATORS = {wire.FUNDING_TYPE: Draft7Validator(wire.FUNDING, format_checker=FormatChecker()),
    wire.INVOICE_TYPE: Draft7Validator(wire.INVOICE_HEADER, format_checker=FormatChecker())}


def enabled():
    return getattr(settings, "MOBILE_SYNC_FINANCIAL_PUBLICATION", False)


def _review():
    raise SyncError("financial_publication_review_required", "Original financial reference publication needs controlled review; never repair, rebind or adopt it automatically.", 503)


def _state(using="default"):
    _gate("MOBILE_SYNC_FINANCIAL_PUBLICATION")
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    state = current_writer()
    if using != "default" or state is None or not connection.in_atomic_block:
        raise SyncError("financial_publication_boundary_required", "Financial publication requires the original stream-before-domain transaction on the verified database.", 503)
    return state


def _fingerprint(source):
    return checksum({"identity": funding._identity(source), "description": source.description, "active": source.is_active}) if source else None


def _dirty(state, key, before):
    dirty = state.setdefault("financial_dirty", {})
    if key not in dirty:
        if len(dirty) >= MAX_DIRTY:
            raise SyncError("financial_publication_limit", "Financial reference mutation exceeds its bounded transaction budget; nothing may be partially published.", 413)
        dirty[key] = before


def touch_sources(rows):
    """Before guarded queryset update/raw-delete; materialize only bounded IDs."""
    if not enabled() or rows.model._meta.model_name != "fundingsource":
        return
    state = _state(rows.db)
    sources = list(rows.order_by("pk")[:MAX_DIRTY + 1])
    if len(sources) > MAX_DIRTY:
        raise SyncError("financial_publication_limit", "Use a bounded financial source transaction.", 413)
    for source in sources:
        _dirty(state, (wire.FUNDING_TYPE, str(source.pk)), _fingerprint(source))


def before_source(instance, using, raw=False):
    if not enabled():
        return
    state = _state(using)
    if raw:
        _review()
    if instance.pk is not None:
        old = FundingSource.objects.using(using).filter(pk=instance.pk).first()
        _dirty(state, (wire.FUNDING_TYPE, str(instance.pk)), _fingerprint(old))


def after_source(instance, using, created):
    if enabled() and created:
        _dirty(_state(using), (wire.FUNDING_TYPE, str(instance.pk)), None)


def before_invoice(instance, using, raw=False):
    if enabled() and instance.command == INVOICE_COMMAND:
        _state(using)
        if raw:
            _review()


def after_invoice(instance, using):
    if enabled() and instance.command == INVOICE_COMMAND:
        _dirty(_state(using), (wire.INVOICE_TYPE, str(instance.pk)), None)


def _uuid(stream, kind, source_pk):
    return uuid.uuid5(stream.deployment_id, BASIS + ":" + kind + ":" + source_pk)


def _anchor(entity, identity, actor_id, owner):
    return checksum({"basis": BASIS, "deployment_id": str(entity.stream.deployment_id),
        "entity_type": entity.entity_type, "entity_uuid": str(entity.entity_uuid), "source_pk": entity.source_pk,
        "identity": identity, "actor_id": str(actor_id) if actor_id else None, "owner": owner, "profile": 1})


def _binding(entity):
    bound = FinancialPublicationBinding.objects.filter(entity=entity).first()
    if (bound is None or bound.profile_version != 1 or entity.entity_type not in TYPES
            or entity.batch_pk != "" or entity.in_current_pack or entity.revision < 1
            or entity.entity_uuid != _uuid(entity.stream, entity.entity_type, entity.source_pk)
            or not re.fullmatch(r"[0-9a-f]{64}", bound.source_identity)
            or bound.anchor != _anchor(entity, bound.source_identity, bound.audience_actor_id, bound.requires_owner_access)
            or entity.entity_type == wire.FUNDING_TYPE and bound.audience_actor_id is not None
            or entity.entity_type == wire.INVOICE_TYPE and (bound.audience_actor_id is None or bound.requires_owner_access)):
        _review()
    return bound


def _funding_mapping(stream, source, *, create):
    mapping = SyncEntity.objects.filter(stream=stream, entity_type=funding.ENTITY_TYPE, source_pk=str(source.pk)).first()
    if mapping is None:
        if not create or SyncEntity.objects.filter(stream=stream, entity_uuid=funding._id(stream, source.pk)).exists():
            _review()
        mapping = SyncEntity.objects.create(stream=stream, entity_type=funding.ENTITY_TYPE, source_pk=str(source.pk),
            entity_uuid=funding._id(stream, source.pk), batch_pk="", in_current_pack=False,
            payload={"basis": funding.BASIS, "identity": funding._identity(source)})
    funding._check_mapping(mapping, stream, source)
    return mapping


def _project(stream, kind, source, *, create_mapping=False):
    if kind == wire.FUNDING_TYPE:
        if source.source_type not in funding.wire.SOURCE_TYPES:
            _review()  # Never auto-publish a future/unknown finance type.
        mapping = _funding_mapping(stream, source, create=create_mapping)
        payload = {"financial_projection_version": 1, "reference": funding._row(mapping, stream, source),
            "available": source.is_active, "source_version": _fingerprint(source)}
        identity, actor, owner = funding._identity(source), None, source.source_type == FundingSourceType.OWNER_CAPITAL
    else:
        row = invoices._row(source)
        payload = {"financial_projection_version": 1, "invoice": row}
        identity, actor, owner = checksum({"receipt_hash": source.request_hash, "invoice": row}), source.actor_id, False
    try:
        VALIDATORS[kind].validate(payload)
    except SchemaError:
        _review()
    if len(canonical(payload).encode("utf-8")) > MAX_ENTITY_BYTES:
        raise SyncError("financial_publication_limit", "Financial reference exceeds its bounded projection budget.", 413)
    return payload, identity, actor, owner


def _create(stream, kind, source, *, allow_mapping):
    source_pk = str(source.pk)
    if SyncEntity.objects.filter(stream=stream, entity_uuid=_uuid(stream, kind, source_pk)).exists():
        _review()
    payload, identity, actor, owner = _project(stream, kind, source, create_mapping=allow_mapping)
    entity = SyncEntity.objects.create(stream=stream, entity_type=kind, source_pk=source_pk,
        entity_uuid=_uuid(stream, kind, source_pk), batch_pk="", in_current_pack=False, payload=payload)
    FinancialPublicationBinding.objects.create(entity=entity, source_identity=identity, audience_actor_id=actor,
        requires_owner_access=owner, anchor=_anchor(entity, identity, actor, owner))
    return entity


def _match(entity, source):
    bound = _binding(entity)
    payload, identity, actor, owner = _project(entity.stream, entity.entity_type, source)
    if (bound.source_identity != identity or bound.audience_actor_id != actor or bound.requires_owner_access != owner or entity.deleted):
        _review()
    return payload


def collect(state):
    """Called once by the common publisher BEFORE its one group is inserted."""
    if not enabled():
        return []
    if state is not _state():
        _review()
    stream, pending = state["stream"], []
    seeds = set(SyncEntity.objects.filter(stream=stream, pk__in=state.get("financial_seeded", set())).values_list("pk", flat=True))
    dirty = dict(state.get("financial_dirty", {}))
    for entity in SyncEntity.objects.filter(stream=stream, pk__in=seeds):
        dirty.setdefault((entity.entity_type, entity.source_pk), "seeded")
    if len(dirty) > MAX_DIRTY:
        raise SyncError("financial_publication_limit", "Financial reference group exceeds its bounded transaction budget.", 413)
    for (kind, source_pk), before in sorted(dirty.items()):
        entity = SyncEntity.objects.filter(stream=stream, entity_type=kind, source_pk=source_pk).first()
        if kind == wire.FUNDING_TYPE:
            source = FundingSource.objects.filter(pk=source_pk).first()
            after = _fingerprint(source)
            if before == after and (entity is None or entity.pk not in seeds):
                continue  # Includes caught savepoint rollback and notes-only/no-op writes.
        else:
            rows = invoices._bounded(FinancialCommandReceipt.objects.filter(pk=source_pk, command=INVOICE_COMMAND, completed_at__isnull=False))
            source = rows[0] if rows else None
        if source is None:
            if entity is None:
                continue  # Rolled-back creation; no phantom projection.
            _binding(entity)
            if kind == wire.INVOICE_TYPE:
                _review()  # Managed invoice deletion is not a supported writer.
            if entity.deleted:
                continue
            entity.deleted, entity.payload = True, {}
            entity.revision += 1
            entity.save(update_fields=["deleted", "payload", "revision"])
            pending.append((entity, None, "tombstone", {}, False))
            continue
        if entity is None:
            if kind == wire.FUNDING_TYPE and before is not None:
                _review()  # Existing rows need explicit controlled baseline, never automatic adoption.
            entity = _create(stream, kind, source, allow_mapping=kind == wire.FUNDING_TYPE)
        else:
            if (kind == wire.FUNDING_TYPE and entity.pk not in seeds
                    and entity.payload.get("source_version") != before):
                _review()  # Do not silently bridge a missed flag-off capture gap.
            payload = _match(entity, source)
            if payload == entity.payload and entity.pk not in seeds:
                continue
            if entity.pk not in seeds:
                entity.revision += 1
            entity.payload = payload
            entity.save(update_fields=["payload", "revision"])
        pending.append((entity, None, "upsert", deepcopy(entity.payload), False))
    return pending


def initialize_reference_publication(source_ids, invoice_ids, actor, session, token):
    """Trusted bounded metadata baseline. No HTTP route, legacy money or repair.

    A validated JWT is a caller prerequisite. Explicit source IDs are private
    setup IDs; invoice IDs must be original-actor managed receipt identities.
    Metadata and its change group commit together; caught savepoint rollback
    cannot leave a queued 'seed' that recreates rolled-back metadata later.
    """
    _gate("MOBILE_SYNC_FINANCIAL_PUBLICATION")
    if (not isinstance(source_ids, list) or not isinstance(invoice_ids, list)
            or not 1 <= len(source_ids) + len(invoice_ids) <= MAX_DIRTY
            or len(set(map(str, source_ids))) != len(source_ids) or len(set(map(str, invoice_ids))) != len(invoice_ids)
            or any(not isinstance(pk, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", pk) or int(pk) > 9223372036854775807 for pk in source_ids)):
        raise SyncError("malformed_request", "Use bounded unique explicit original setup identities.")
    try:
        for value in invoice_ids:
            invoices.ID.validate(value)
    except SchemaError:
        raise SyncError("malformed_request", "Retain canonical original invoice UUIDs.") from None
    actor, session = funding._access(actor, session, token)
    with sync_boundary() as state:
        _state()
        actor, session = funding._access(actor, session, token)
        stream = stream_ready()
        scope = funding._scope(stream, actor, session)
        sources = list(FundingSource.objects.select_for_update().filter(pk__in=source_ids).order_by("pk"))
        if len(sources) != len(source_ids) or any(source.source_type not in funding.wire.SOURCE_TYPES
                or source.source_type == FundingSourceType.OWNER_CAPITAL and not has_owner_capital_access(actor) for source in sources):
            funding._unavailable()
        receipts = invoices._bounded(invoices._owned(actor).filter(pk__in=invoice_ids))
        if len(receipts) != len(invoice_ids):
            invoices._unavailable()
        created = 0
        for kind, source in [(wire.FUNDING_TYPE, source) for source in sources] + [(wire.INVOICE_TYPE, receipt) for receipt in receipts]:
            entity = SyncEntity.objects.filter(stream=stream, entity_type=kind, source_pk=str(source.pk)).first()
            if entity is None:
                entity = _create(stream, kind, source, allow_mapping=kind == wire.FUNDING_TYPE)
                state.setdefault("financial_seeded", set()).add(entity.pk)
                created += 1
            elif _match(entity, source) != entity.payload:
                _review()  # A missed capture/flag-off gap needs explicit epoch/reconciliation design.
        funding._unchanged_access(stream, actor, session, token, scope)
        return {"prepared": len(sources) + len(receipts), "created": created, "financial_uploads": False}


def read_reference_projection(entity_id, actor, session, token):
    """Private current-bound positive read, not a pack/download/offline grant."""
    _gate("MOBILE_SYNC_FINANCIAL_PUBLICATION")
    actor, session = funding._access(actor, session, token)
    with sync_boundary():
        _state()
        actor, session = funding._access(actor, session, token)
        stream = stream_ready()
        scope = funding._scope(stream, actor, session)
        try:
            invoices.ID.validate(entity_id)
        except SchemaError:
            raise SyncError("malformed_request", "Use the original publication UUID.") from None
        entity = SyncEntity.objects.filter(stream=stream, entity_uuid=entity_id, entity_type__in=TYPES).first()
        if entity is None:
            funding._unavailable()
        bound = _binding(entity)
        if (bound.audience_actor_id is not None and bound.audience_actor_id != actor.pk
                or bound.requires_owner_access and not has_owner_capital_access(actor)):
            funding._unavailable()
        if entity.deleted:
            result = {"entity_type": entity.entity_type, "entity_uuid": str(entity.entity_uuid), "revision": str(entity.revision), "deleted": True}
        else:
            if entity.entity_type == wire.FUNDING_TYPE:
                source = FundingSource.objects.filter(pk=entity.source_pk).first()
            else:
                rows = invoices._bounded(invoices._owned(actor).filter(pk=entity.source_pk))
                source = rows[0] if rows else None
            if source is None or _match(entity, source) != entity.payload:
                _review()  # Never serve stale missed-publication data as confirmed.
            result = {"entity_type": entity.entity_type, "entity_uuid": str(entity.entity_uuid), "revision": str(entity.revision), "payload": deepcopy(entity.payload)}
        funding._unchanged_access(stream, actor, session, token, scope)
        return result
