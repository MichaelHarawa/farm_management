"""Private positive original-invoice selection; no balances or cache grant."""
from .commands.financial_uuid_schema import UUID, INSTANT, DATE
from .schema_financial_references import DIGEST, MONEY
from .schema import obj

QUANTITY = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,11})\.[0-9]{4}(?![\s\S])", "not": {"const": "0.0000"}}
TEXT = {"type": "string", "minLength": 1, "maxLength": 160, "pattern": r"^\S(?:[\s\S]*\S)?(?![\s\S])"}
INVOICE = obj({"invoice_group_id": UUID, "invoice_version": DIGEST,
    "supplier": TEXT, "invoice_reference": {**TEXT, "maxLength": 120}, "purchase_date": DATE,
    "currency": {"const": "MWK"}, "original_total_purchase_cost": MONEY,
    "line_count": {"type": "integer", "minimum": 2, "maximum": 50}, "recorded_at": INSTANT,
    "evidence": {"const": "immutable_original_invoice"},
    "balance_semantics": {"const": "original_purchase_not_current_outstanding"}})
LINE = obj({"invoice_line_index": {"type": "integer", "minimum": 0, "maximum": 49},
    "original_item_name": TEXT, "original_location_name": TEXT,
    "captured_quantity": QUANTITY, "captured_unit": {**TEXT, "maxLength": 40},
    "base_quantity": QUANTITY, "base_unit": {**TEXT, "maxLength": 40},
    "original_line_cost": MONEY, "expiry_date": {"anyOf": [DATE, {"type": "null"}]}})
CONTEXT = {"invoice_reference_version": {"type": "integer", "const": 1}, "deployment_id": UUID,
    "device_id": UUID, "scope_revision": DIGEST, "server_time": INSTANT,
    "access": {"const": "online_only_original_actor_finance_writer"}, "offline_cache_seconds": {"const": 0},
    "financial_uploads": {"const": False}}
CATALOG = obj({**CONTEXT, "catalog_version": DIGEST,
    "total_authorized_rows": {"type": "integer", "minimum": 0, "maximum": 100},
    "rows": {"type": "array", "maxItems": 25, "items": INVOICE},
    "next_cursor": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 2048}, {"type": "null"}]}})
DETAIL = obj({**CONTEXT, "detail_version": DIGEST, "invoice": INVOICE,
    "lines": {"type": "array", "minItems": 2, "maxItems": 50, "items": LINE},
    "proof": {"const": "original_invoice_sources_and_purchase_journals"},
    "label_semantics": {"const": "original_purchase_names_and_values"},
    "payment_authority": {"const": "none_revalidate_payables_and_cash_on_posting"}})
