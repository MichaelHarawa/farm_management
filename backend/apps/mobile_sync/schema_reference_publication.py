"""Private positive global reference projections; NOT an offline-access grant."""
from .schema import obj
from .commands.financial_uuid_schema import UUID
from .schema_financial_references import REFERENCE, DIGEST
from .schema_invoice_references import INVOICE

FUNDING_TYPE = "finance.funding_selection"
INVOICE_TYPE = "finance.invoice_reference"
FUNDING = obj({"financial_projection_version": {"type": "integer", "const": 1},
    "reference": REFERENCE, "available": {"type": "boolean"}, "source_version": DIGEST})
INVOICE_HEADER = obj({"financial_projection_version": {"type": "integer", "const": 1}, "invoice": INVOICE})
COUNTER = {"type": "string", "pattern": r"^[1-9][0-9]{0,18}(?![\s\S])"}
ENTITY = {"oneOf": [obj({"entity_type": {"const": name}, "entity_uuid": UUID, "revision": COUNTER,
    "payload": payload}) for name, payload in ((FUNDING_TYPE, FUNDING), (INVOICE_TYPE, INVOICE_HEADER))]}
