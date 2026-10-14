"""Positive, separate online-only financial receipt read contract."""
from copy import deepcopy

from apps.finance.services.inventory_payment_summary_schema import supplier_payment_summary_schema
from .schema import UUID, INSTANT, obj, responses


VERSION = {"const": 1}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
CONTEXT = {"financial_read_version": VERSION, "deployment_id": UUID, "device_id": UUID,
    "scope_revision": DIGEST, "server_time": INSTANT,
    "access": {"const": "online_only_original_actor"}, "offline_cache_seconds": {"const": 0}}
STATUS_FIELDS = {"operation_id": UUID, "identity_kind": {"const": "financial_command_receipt"},
    "command": {"const": "inventory.supplier_payment.record"},
    "outcome": {"const": "accepted"}, "evidence": {"const": "immutable_completed_receipt"},
    "receipt_hash": DIGEST, "payment_version": DIGEST, "recorded_at": INSTANT,
    "balance_semantics": {"const": "historical_acceptance_not_current_balance"},
    "recovery_action": {"const": "retain_original_id_do_not_resubmit"}}
STATUS = obj({**CONTEXT, **STATUS_FIELDS})
CAPABILITIES = obj({**CONTEXT, "reads": obj({
    "supplier_payment_status": {"const": True}, "supplier_payment_summary": {"const": True}}),
    "financial_uploads": {"const": False}, "packs": {"type": "array", "maxItems": 0},
    "limits": obj({"summary_bytes": {"const": 16384}, "summary_invoices": {"const": 10},
        "summary_lines": {"const": 50}, "summary_funding_rows": {"const": 100},
        "receipt_proof_bytes": {"const": 8 * 1024 * 1024}})})


def summary_schema():
    # Inline the private schema's local definitions; a nested JSON/OpenAPI
    # document must not resolve its #/definitions against the outer envelope.
    private = supplier_payment_summary_schema()

    def expand(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return deepcopy(private["definitions"][value["$ref"].split("/")[-1]])
            return {key: expand(item) for key, item in value.items()
                if key not in {"$schema", "$id", "definitions", "title"}}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return obj({**CONTEXT, "summary": expand(private)})


SUMMARY = summary_schema()


def openapi_responses(success):
    # Keep the executable Draft7 contract exact, but OpenAPI 3.0 Schema Objects
    # use one-value enums rather than JSON Schema's unsupported const keyword.
    def convert(value):
        if isinstance(value, dict):
            return {("enum" if key == "const" else key): ([item] if key == "const" else convert(item))
                for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return responses(convert(success))
