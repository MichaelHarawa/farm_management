"""Separate private UUID envelope candidate; never expands operational profiles."""
from copy import deepcopy

from ..schema import obj
from ..schema_financial_references import DIGEST, MONEY, FUNDING
from . import financial_schema as legacy

COMMAND = legacy.COMMAND
UUID = {**legacy.UUID, "minLength": 36, "maxLength": 36}
INSTANT = {**legacy.INSTANT, "maxLength": 27,
    "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z(?![\s\S])"}
DATE = {**legacy.DATE, "minLength": 10, "maxLength": 10}
LINE = obj({"invoice_line_index": {"type": "integer", "minimum": 0, "maximum": 49}, "amount": MONEY,
    "funding_allocations": {"type": "array", "minItems": 1, "maxItems": 50, "items": FUNDING}})
INVOICE = obj({"invoice_group_id": UUID, "invoice_version": DIGEST, "total_payment_amount": MONEY,
    "lines": {"type": "array", "minItems": 1, "maxItems": 50, "items": LINE}})
PAYLOAD = deepcopy(legacy.PAYLOAD)
PAYLOAD["properties"].update(payment_date=DATE, total_payment_amount=MONEY,
    invoices={"type": "array", "minItems": 1, "maxItems": 10, "items": INVOICE})
OPERATION = obj({"financial_command_version": {"type": "integer", "const": 2}, "operation_id": UUID,
    "command": {"const": COMMAND}, "captured_at": INSTANT,
    "depends_on": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": UUID},
    "supersedes_operation_id": UUID, "payload": PAYLOAD}, optional=("supersedes_operation_id",))
ENVELOPE = obj({"financial_protocol_version": {"type": "integer", "const": 1},
    "deployment_id": UUID, "device_id": UUID,
    "operations": {"type": "array", "minItems": 1, "maxItems": 20, "items": OPERATION}})
RESULT = deepcopy(legacy.RESULT)
RESULT["properties"]["financial_command_version"] = {"type": "integer", "const": 2}
RESULT["properties"]["code"]["enum"] += ["funding_reference_unavailable", "funding_reference_changed",
    "invoice_reference_unavailable", "request_budget_exceeded"]
RESULT["properties"]["command_hash"] = DIGEST
RESULT["properties"]["operation_id"] = UUID
RESULT["properties"]["transaction_id"] = UUID
RESULT["properties"]["committed_at"] = INSTANT
RESULT["properties"]["financial_evidence"]["properties"].update(
    submission_id=UUID, receipt_hash=DIGEST, payment_version=DIGEST, recorded_at=INSTANT)
RESPONSE = obj({"financial_protocol_version": {"type": "integer", "const": 1},
    "deployment_id": UUID, "device_id": UUID, "server_time": INSTANT,
    "results": {"type": "array", "minItems": 1, "maxItems": 20, "items": RESULT}})
BINDING = obj({"reference_id": UUID, "reference_version": DIGEST,
    "source_pk": {"type": "string", "pattern": r"^[1-9][0-9]{0,18}(?![\s\S])"}, "identity": DIGEST})
RESOLUTION = obj({"inner_operation_id": UUID,
    "funding": {"type": "array", "minItems": 1, "maxItems": 100, "items": BINDING}})
