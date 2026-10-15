"""Explicit read-only reference API, independent of operational capabilities."""
from .schema import obj, responses
from .commands.financial_uuid_schema import UUID, INSTANT
from .schema_financial_references import DIGEST

CAPABILITIES = obj({"financial_reference_api_version": {"type": "integer", "const": 1},
    "deployment_id": UUID, "device_id": UUID, "actor_id": UUID, "server_time": INSTANT,
    "access": {"const": "online_only_current_finance_writer"}, "offline_cache_seconds": {"const": 0},
    "financial_uploads": {"const": False}, "packs": {"type": "array", "maxItems": 0},
    "profiles": obj({"funding": {"const": 1}, "original_invoices": {"const": 1}}),
    "scopes": obj({"funding": DIGEST, "original_invoices": DIGEST}),
    "limits": obj({"funding_rows": {"const": 1000}, "funding_page_rows": {"const": 50},
        "funding_catalog_bytes": {"const": 524288}, "invoice_rows": {"const": 100},
        "invoice_page_rows": {"const": 25}, "invoice_catalog_bytes": {"const": 524288},
        "invoice_detail_bytes": {"const": 65536}, "invoice_lines": {"const": 50},
        "cursor_seconds": {"const": 900}})})


def openapi_responses(success):
    def convert(value):
        if isinstance(value, dict):
            if "anyOf" in value and {"type": "null"} in value["anyOf"] and len(value["anyOf"]) == 2:
                return {**convert(next(item for item in value["anyOf"] if item != {"type": "null"})), "nullable": True}
            return {("enum" if key == "const" else key): ([item] if key == "const" else convert(item))
                for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value
    return {**responses(convert(success)), 405: obj({"detail": {"type": "string"}})}
