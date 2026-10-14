"""Private supplier-payment bridge contract, NOT a published wire profile.

Funding source PK strings are private service references. Public adapters must
resolve authorized financial UUID references/catalogs before enabling uploads.
"""
from ..schema import obj


COMMAND = "inventory.supplier_payment.record"
UUID = {"type": "string", "format": "uuid", "pattern": r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"}
DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
MONEY = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,11})\.[0-9]{2}$", "not": {"const": "0.00"}}
INSTANT = {"type": "string", "format": "date-time",
    "pattern": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"}
DATE = {"type": "string", "format": "date"}
IDENTIFIER = {"type": "string", "pattern": "^[1-9][0-9]{0,18}$"}
FUNDING_CLASSIFICATIONS = ("reinvestment", "working_capital", "cost_recovery", "owner_distribution",
    "owner_capital_return", "owner_drawing", "owner_compensation", "debt_service", "other")
FUNDING = obj({"funding_source": IDENTIFIER, "amount": MONEY,
    "classification": {"enum": list(FUNDING_CLASSIFICATIONS)}}, optional=("classification",))
LINE = obj({"invoice_line_index": {"type": "integer", "minimum": 0, "maximum": 49}, "amount": MONEY,
    "funding_allocations": {"type": "array", "minItems": 1, "maxItems": 50, "items": FUNDING}})
INVOICE = obj({"invoice_group_id": UUID, "invoice_version": DIGEST, "total_payment_amount": MONEY,
    "lines": {"type": "array", "minItems": 1, "maxItems": 50, "items": LINE}})
PAYLOAD = obj({"currency": {"const": "MWK"}, "payee": {"type": "string", "minLength": 1, "maxLength": 160},
    "payment_method": {"enum": ["cash", "mobile_money", "bank_transfer"]},
    "external_reference": {"type": "string", "minLength": 1, "maxLength": 120}, "payment_date": DATE,
    "total_payment_amount": MONEY, "invoices": {"type": "array", "minItems": 1, "maxItems": 10, "items": INVOICE},
    "notes": {"type": "string", "maxLength": 4000}})
OPERATION = obj({"financial_command_version": {"type": "integer", "const": 1}, "operation_id": UUID,
    "command": {"const": COMMAND}, "captured_at": INSTANT,
    "depends_on": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": UUID},
    "supersedes_operation_id": UUID, "payload": PAYLOAD}, optional=("supersedes_operation_id",))

FIELDS = ("payment_date", "total_payment_amount", "payee", "external_reference", "invoices", "funding_allocations")
FIELD_MESSAGE = "Review this captured field; retain the original evidence."
REVIEW_MESSAGE = "Keep the original financial evidence; review the outcome before any further action."
ACCEPTED_MESSAGE = "Observed supplier payment recorded once; original evidence retained."
FINANCIAL_EVIDENCE = obj({"submission_id": UUID, "receipt_hash": DIGEST, "payment_version": DIGEST,
    "recorded_at": INSTANT, "basis": {"const": "immutable_completed_financial_receipt_not_current_balance"}})
RESULT = obj({"financial_command_version": {"type": "integer", "const": 1}, "operation_id": UUID,
    "command": {"const": COMMAND}, "command_hash": DIGEST,
    "outcome": {"enum": ["accepted", "replayed", "validation_failed", "permission_denied", "period_locked", "conflict", "dependency_blocked", "retry_later"]},
    "code": {"enum": ["accepted", "idempotency_mismatch", "permission_denied", "period_locked", "invalid_business_event",
        "possible_duplicate", "insufficient_cash_or_payable", "invalid_supersession", "supersession_already_accepted", "future_capture",
        "dependency_blocked", "dependency_profile_mismatch", "command_unavailable"]},
    "message": {"enum": [REVIEW_MESSAGE, ACCEPTED_MESSAGE]},
    "field_errors": obj({key: {"const": FIELD_MESSAGE} for key in FIELDS}, optional=FIELDS),
    "recovery_action": {"enum": ["recover_original_operation", "review_and_supersede", "wait_for_dependency", "retry_unchanged", "retain_receipt_never_resubmit"]},
    "financial_evidence": FINANCIAL_EVIDENCE, "transaction_id": UUID, "committed_at": INSTANT},
    optional=("financial_evidence", "transaction_id", "committed_at"))
