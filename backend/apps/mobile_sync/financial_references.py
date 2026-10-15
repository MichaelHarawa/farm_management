"""Private funding UUID catalog/resolver; NOT an upload or replicated pack.

Explicit preparation writes mapping metadata only. Reads never seed or repair
identities. Current role/device/source checks precede every lookup and are
repeated after the stream wait and before release. No balance is cached or
claimed spendable here; the existing posting service still locks dated cash.
"""
from copy import deepcopy
import re
import uuid

from django.core import signing
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError

from apps.finance.models import FundingSource, FundingSourceType
from apps.finance.permissions import FINANCE_WRITE_ROLES, has_owner_capital_access
from .commands.financial import _bound, _gate
from .errors import SyncError
from .models import SyncEntity
from .policy import permits
from .projections import canonical, checksum, json_value
from .transport import stream_ready
from .writers import sync_boundary
from . import schema_financial_references as wire


ENTITY_TYPE = "finance.funding_source"
BASIS = "mobile-financial-funding-reference-private-v1"
MAX_CATALOG_ROWS = 1000
MAX_CATALOG_BYTES = 512 * 1024
PAGE_ROWS = 50
MAX_REFERENCES = 100
ROWS = Draft7Validator(wire.ROWS, format_checker=FormatChecker())


def _access(actor, session, token):
    actor, session = _bound(actor, session, token)
    if not permits(actor, FINANCE_WRITE_ROLES):
        raise SyncError("permission_denied", "Current financial capture access is required for funding references.", 403)
    return actor, session


def _unavailable():
    # Missing, wrong deployment/type, hidden owner, inactive and deleted sources
    # have the same result. Never disclose their kind, private ID or balance.
    raise SyncError("funding_reference_unavailable", "A selected authorized funding reference is unavailable. Retain the original evidence for review.", 404)


def _review():
    raise SyncError("funding_reference_review_required", "Funding identity requires controlled review; retain the original reference, never rebind or repair it automatically.", 503)


def _id(stream, source_pk):
    return uuid.uuid5(stream.deployment_id, BASIS + ":source:" + str(source_pk))


def _identity(source):
    return checksum({"basis": BASIS, "source_pk": str(source.pk), "source_type": source.source_type,
        "created_at": json_value(source.created_at),
        "batch_pk": str(source.batch_id) if source.batch_id is not None else None,
        "owner_pk": str(source.owner_id) if source.owner_id is not None else None})


def _version(stream, source):
    # A prospective inactive/reactivated source has the same permanent UUID,
    # never a new identity. No cash/description snapshot grants posting rights.
    return checksum({"basis": BASIS + "-selection", "deployment_id": str(stream.deployment_id),
        "reference_id": str(_id(stream, source.pk)), "identity": _identity(source), "active": source.is_active})


def _sources(actor):
    # Deliberately narrower than broad finance read. Stakeholders/workers have
    # no funding-selection catalog; owner capital remains admin/director only.
    choices = list(wire.SOURCE_TYPES)
    if not has_owner_capital_access(actor):
        choices.remove(FundingSourceType.OWNER_CAPITAL)
    return FundingSource.objects.filter(is_active=True, source_type__in=choices)


def _check_mapping(mapping, stream, source):
    if (mapping.entity_type != ENTITY_TYPE or mapping.stream_id != stream.pk
            or mapping.source_pk != str(source.pk) or mapping.entity_uuid != _id(stream, source.pk)
            or mapping.deleted or mapping.batch_pk != "" or mapping.in_current_pack or mapping.revision != 1
            or mapping.payload != {"basis": BASIS, "identity": _identity(source)}):
        _review()
    if (source.source_type == FundingSourceType.BATCH_COLLECTION and source.batch_id is None
            or source.owner_id is not None and source.source_type != FundingSourceType.OWNER_CAPITAL):
        _review()


def _scope(stream, actor, session):
    return checksum({"basis": BASIS + "-scope", "deployment_id": str(stream.deployment_id),
        "actor_id": str(actor.pk), "device_id": str(session.device_id), "active": actor.is_active,
        "superuser": actor.is_superuser, "roles": sorted(actor.roles.values_list("slug", flat=True)),
        "access": "online_only_current_finance_writer", "offline_cache_seconds": 0})


def _unchanged_access(stream, actor, session, token, scope):
    actor, session = _access(actor, session, token)
    if _scope(stream, actor, session) != scope:
        raise SyncError("financial_reference_scope_changed", "Current reference access changed; retain protected work and restart selection.", 409)


def prepare_funding_references(source_ids, actor, session, token):
    """Trusted bounded setup, not client CRUD and never called on catalog GET.

    Requires a validated bound token from an authenticated upstream caller.
    Private PK strings are accepted ONLY by this internal preparation function.
    Uses existing mappings, without adding these types to operational profiles.
    Does not activate financial all-writer publication or seed business records.
    """
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    if (not isinstance(source_ids, list) or not 1 <= len(source_ids) <= MAX_REFERENCES
            or any(not isinstance(pk, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", pk)
                or int(pk) > 9223372036854775807 for pk in source_ids) or len(set(source_ids)) != len(source_ids)):
        raise SyncError("malformed_request", "Select a bounded unique set of private preparation IDs.")
    actor, session = _access(actor, session, token)
    with sync_boundary():
        actor, session = _access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        # Setup is separate from posting: no period/payable locks are held here.
        sources = list(_sources(actor).select_for_update().filter(pk__in=source_ids).order_by("pk"))
        if {str(source.pk) for source in sources} != set(source_ids):
            _unavailable()
        created = 0
        for source in sources:
            mapping = SyncEntity.objects.filter(stream=stream, entity_type=ENTITY_TYPE, source_pk=str(source.pk)).first()
            if mapping is None:
                if SyncEntity.objects.filter(stream=stream, entity_uuid=_id(stream, source.pk)).exists():
                    _review()
                mapping = SyncEntity.objects.create(stream=stream, entity_type=ENTITY_TYPE,
                    source_pk=str(source.pk), entity_uuid=_id(stream, source.pk), batch_pk="",
                    payload={"basis": BASIS, "identity": _identity(source)}, in_current_pack=False)
                created += 1
            _check_mapping(mapping, stream, source)
        _unchanged_access(stream, actor, session, token, scope)
        return {"prepared": len(sources), "created": created, "financial_uploads": False}


def _row(mapping, stream, source):
    _check_mapping(mapping, stream, source)
    if not isinstance(source.description, str) or len(source.description) > 255:
        _review()
    reference = str(mapping.entity_uuid)
    # No OwnerContributor identity/name, free-text notes, raw source/batch PK,
    # receipt/journal history or balance. Owner labels intentionally generic.
    label = (source.description.strip() if source.source_type != FundingSourceType.OWNER_CAPITAL else "")
    label = label or str(FundingSourceType(source.source_type).label) + " · " + reference[:8]
    pool = uuid.uuid5(stream.deployment_id, BASIS + ":batch-cash:" + str(source.batch_id)) if (
        source.source_type == FundingSourceType.BATCH_COLLECTION) else mapping.entity_uuid
    return {"reference_id": reference, "reference_version": _version(stream, source),
        "source_type": source.source_type, "label": label, "currency": "MWK", "cash_pool_id": str(pool),
        "cash_pool_semantics": "shared_batch_collection" if source.source_type == FundingSourceType.BATCH_COLLECTION else "source_specific",
        "balance_semantics": "not_a_cash_balance_or_reservation"}


def funding_reference_catalog(actor, session, token, *, cursor=None):
    """Private paginated ONLINE selection catalog, complete or explicit refusal.

    Reads current authorized sources; requires previously prepared identities.
    Cursor binds exact positive catalog/scope/device, not private PK/offsets.
    Every page re-reads bounded current data, so mutation forces restart rather
    than skipping/duplicating records. Never reinterpret a partial page as total.
    """
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    actor, session = _access(actor, session, token)
    with sync_boundary():
        actor, session = _access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        sources = list(_sources(actor).order_by("pk")[:MAX_CATALOG_ROWS + 1])
        if len(sources) > MAX_CATALOG_ROWS:
            raise SyncError("funding_catalog_limit", "Authorized catalog exceeds its bounded budget; request controlled scope preparation.", 413)
        mappings = {row.source_pk: row for row in SyncEntity.objects.filter(stream=stream,
            entity_type=ENTITY_TYPE, source_pk__in=[str(source.pk) for source in sources])}
        if len(mappings) != len(sources):
            raise SyncError("funding_catalog_not_prepared", "Complete authorized funding identities must be prepared before selection; no partial catalog is available.", 503)
        rows = sorted((_row(mappings[str(source.pk)], stream, source) for source in sources), key=lambda row: row["reference_id"])
        if len(canonical(rows).encode("utf-8")) > MAX_CATALOG_BYTES:
            raise SyncError("funding_catalog_limit", "Authorized catalog exceeds its byte budget; no records were truncated.", 413)
        version = checksum({"basis": BASIS + "-catalog", "scope": scope, "rows": rows})
        start = 0
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError
                point = signing.loads(cursor, salt=BASIS + "-cursor", max_age=900)
                if (set(point) != {"version", "scope", "catalog", "last"} or type(point["version"]) is not int or point["version"] != 1
                        or point["scope"] != scope or point["catalog"] != version):
                    raise ValueError
                start = next(index + 1 for index, row in enumerate(rows) if row["reference_id"] == point["last"])
            except (signing.BadSignature, TypeError, ValueError, StopIteration):
                raise SyncError("funding_catalog_changed", "Restart authorized reference paging; retain original pending work unchanged.", 409) from None
        page = rows[start:start + PAGE_ROWS]
        next_cursor = signing.dumps({"version": 1, "scope": scope, "catalog": version,
            "last": page[-1]["reference_id"]}, salt=BASIS + "-cursor") if start + len(page) < len(rows) else None
        _unchanged_access(stream, actor, session, token, scope)
        return {"financial_reference_version": 1, "deployment_id": str(stream.deployment_id),
            "device_id": str(session.device_id), "scope_revision": scope, "catalog_version": version,
            "server_time": json_value(timezone.now()),
            "access": "online_only_current_finance_writer", "offline_cache_seconds": 0,
            "financial_uploads": False, "total_authorized_rows": len(rows), "rows": page, "next_cursor": next_cursor}


def resolve_funding_references(rows, actor, session, token):
    """Strict UUID -> private domain rows, with NO posting or cash authority.

    Intended for a future adapter *inside* its outer stream transaction, before
    the existing period/payable/cash lock sequence. This function takes no early
    cash locks. Persist the external UUID command/hash and exact resolved linkage
    atomically with effects; never resolve a completed command afresh on replay.
    Current private PK bridge must not be exposed as though this is integration.
    """
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    try:
        ROWS.validate(rows)
    except SchemaError:
        raise SyncError("malformed_request", "Use strict exact-money funding UUID/version rows; retain the original command.") from None
    if len({row["funding_source"] for row in rows}) != len(rows):
        raise SyncError("malformed_request", "Select each funding reference once per payment line; never infer or combine splits.")
    observed = deepcopy(rows)
    actor, session = _access(actor, session, token)
    with sync_boundary():
        actor, session = _access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        mappings = {str(row.entity_uuid): row for row in SyncEntity.objects.filter(stream=stream,
            entity_type=ENTITY_TYPE, entity_uuid__in=[row["funding_source"] for row in observed])}
        if len(mappings) != len(observed):
            _unavailable()
        if any(not re.fullmatch(r"[1-9][0-9]{0,18}", row.source_pk)
                or int(row.source_pk) > 9223372036854775807 for row in mappings.values()):
            _review()
        sources = {str(row.pk): row for row in _sources(actor).filter(pk__in=[row.source_pk for row in mappings.values()])}
        if len(sources) != len(mappings):
            _unavailable()
        result = []
        for row in observed:
            mapping = mappings[row["funding_source"]]
            source = sources[mapping.source_pk]
            _check_mapping(mapping, stream, source)
            if row["funding_version"] != _version(stream, source):
                raise SyncError("funding_reference_changed", "Review the original source selection; do not silently replace its version or funding.", 409)
            result.append({"funding_source": str(source.pk), "amount": row["amount"],
                **({"classification": row["classification"]} if "classification" in row else {})})
        _unchanged_access(stream, actor, session, token, scope)
        return result
