"""Positive private reference-pack transport, NOT the full financial profile."""
from .schema import obj
from .schema_reference_publication import ENTITY, COUNTER, FUNDING_TYPE, INVOICE_TYPE
from .commands.financial_uuid_schema import UUID, INSTANT
from .schema_financial_references import DIGEST

PACK = "financial-references-private-v1"
ZERO_COUNTER = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,18})(?![\s\S])"}
CURSOR = {"type": "string", "minLength": 1, "maxLength": 4096}
NULL_CURSOR = {"anyOf": [CURSOR, {"type": "null"}]}
CONTEXT = {"financial_reference_pack_version": {"type": "integer", "const": 1}, "pack_id": {"const": PACK},
    "deployment_id": UUID, "stream_epoch": UUID, "device_id": UUID, "actor_id": UUID,
    "scope_revision": DIGEST, "server_time": INSTANT, "access": {"const": "online_only_current_finance_writer"},
    "offline_cache_seconds": {"const": 0}, "financial_uploads": {"const": False}}
PAGE_DESCRIPTOR = obj({"page": {"type": "integer", "minimum": 0},
    "row_count": {"type": "integer", "minimum": 0, "maximum": 50}, "sha256": DIGEST})
MANIFEST = obj({**CONTEXT, "snapshot_id": UUID, "watermark": ZERO_COUNTER, "catalog_version": DIGEST,
    "expires_at": INSTANT, "row_count": {"type": "integer", "minimum": 0, "maximum": 1100},
    "manifest": {"type": "array", "minItems": 1, "maxItems": 1100, "items": PAGE_DESCRIPTOR}, "next_page_cursor": CURSOR})
PAGE = obj({**CONTEXT, "snapshot_id": UUID, "watermark": ZERO_COUNTER, "catalog_version": DIGEST,
    "expires_at": INSTANT, "page": {"type": "integer", "minimum": 0}, "sha256": DIGEST,
    "entities": {"type": "array", "maxItems": 50, "items": ENTITY},
    "next_page_cursor": NULL_CURSOR, "delta_cursor": NULL_CURSOR})
FRAGMENT = obj({"transaction_id": UUID, "fragment_index": {"type": "integer", "minimum": 0},
    "fragment_final": {"type": "boolean"}})
CHANGES = []
for variant in ENTITY["oneOf"]:
    fields = variant["properties"]
    common = {**{name: fields[name] for name in ("entity_type", "entity_uuid", "revision")},
        "sequence": COUNTER, **FRAGMENT["properties"]}
    CHANGES.append(obj({**common, "kind": {"const": "upsert"}, "payload": fields["payload"]}))
    if fields["entity_type"]["const"] == FUNDING_TYPE:
        CHANGES.append(obj({**common, "revision": {"allOf": [COUNTER, {"not": {"const": "1"}}]}, "kind": {"const": "tombstone"}}))
DELTA = obj({**CONTEXT, "run_watermark": ZERO_COUNTER,
    "changes": {"type": "array", "maxItems": 50, "items": {"oneOf": CHANGES}},
    "fragments": {"type": "array", "maxItems": 50, "items": FRAGMENT},
    "next_cursor": CURSOR, "run_complete": {"type": "boolean"}})
