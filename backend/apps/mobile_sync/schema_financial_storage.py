"""Positive private evidence-only authorization; not a public capability."""
from .schema_financial_references import UUID

INSTANT = {"type": "string", "format": "date-time", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z(?![\s\S])"}
DIGEST = {"type": "string", "pattern": r"^[0-9a-f]{64}(?![\s\S])"}
GRANT = {"type": "object", "additionalProperties": False, "properties": {
    "financial_storage_version": {"const": 1},
    "profile": {"const": "financial-evidence-private-v1"},
    **{key: UUID for key in ("deployment_id", "actor_id", "device_id", "session_id", "stream_epoch")},
    "scope_revision": DIGEST,
    "server_time": INSTANT, "expires_at": INSTANT,
    "maximum_offline_seconds": {"const": 86400},
    "access": {"const": "local_evidence_only_not_posting_authority"},
    "commands": {"type": "array", "items": {"const": "inventory.supplier_payment.record"}, "minItems": 1, "maxItems": 1},
    "reference_cache_seconds": {"const": 0}, "financial_uploads": {"const": False},
}}
GRANT["required"] = list(GRANT["properties"])
