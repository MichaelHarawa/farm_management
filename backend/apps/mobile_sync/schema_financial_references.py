"""Private positive funding-selection contract, independent of sync profiles."""
from .commands.financial_schema import UUID, DIGEST as ORIGINAL_DIGEST, MONEY as ORIGINAL_MONEY, FUNDING_CLASSIFICATIONS
from .schema import INSTANT, obj

SOURCE_TYPES = ("batch_collection", "owner_capital", "loan", "grant", "other_income", "general_farm_cash")
# Python's '$' also matches immediately before a final newline. Require exact
# digest length and a portable negative-any-character end assertion for money;
# never strip or normalize captured inputs, or mutate the older bridge schema.
DIGEST = {**ORIGINAL_DIGEST, "minLength": 64, "maxLength": 64}
MONEY = {**ORIGINAL_MONEY, "pattern": r"^(0|[1-9][0-9]{0,11})\.[0-9]{2}(?![\s\S])"}
FUNDING = obj({"funding_source": UUID, "funding_version": DIGEST, "amount": MONEY,
    "classification": {"type": "string", "enum": list(FUNDING_CLASSIFICATIONS)}}, optional=("classification",))
ROWS = {"type": "array", "minItems": 1, "maxItems": 100, "items": FUNDING}
REFERENCE = obj({"reference_id": UUID, "reference_version": DIGEST,
    "source_type": {"enum": list(SOURCE_TYPES)}, "label": {"type": "string", "minLength": 1, "maxLength": 255},
    "currency": {"const": "MWK"}, "cash_pool_id": UUID,
    "cash_pool_semantics": {"enum": ["shared_batch_collection", "source_specific"]},
    "balance_semantics": {"const": "not_a_cash_balance_or_reservation"}})
CATALOG = obj({"financial_reference_version": {"type": "integer", "const": 1}, "deployment_id": UUID,
    "device_id": UUID, "scope_revision": DIGEST, "catalog_version": DIGEST, "server_time": INSTANT,
    "access": {"const": "online_only_current_finance_writer"}, "offline_cache_seconds": {"const": 0},
    "financial_uploads": {"const": False}, "total_authorized_rows": {"type": "integer", "minimum": 0, "maximum": 1000},
    "rows": {"type": "array", "maxItems": 50, "items": REFERENCE},
    "next_cursor": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 2048}, {"type": "null"}]}})
