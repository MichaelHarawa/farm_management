"""Executable private positive contract; independent of ignored docs artifacts."""


def supplier_payment_summary_schema():
    """Return a fresh schema; no registry/profile is expanded or advertised."""
    digest = {"$ref": "#/definitions/digest"}
    money = {"$ref": "#/definitions/money"}
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "urn:farm:private:supplier-payment-summary:candidate:v1",
        "title": "Private supplier-payment summary candidate; not a published sync profile",
        "type": "object", "additionalProperties": False,
        "required": ["summary_version", "operation_id", "payment_version", "recorded_at", "evidence_status",
            "balance_semantics", "currency", "payment_date", "amount", "payee", "payment_method", "external_reference", "note_available", "invoices"],
        "properties": {
            "summary_version": {"const": 1},
            "operation_id": {"type": "string", "format": "uuid"},
            "payment_version": digest,
            "recorded_at": {"type": "string", "format": "date-time"},
            "evidence_status": {"const": "accepted_original_payment"},
            "balance_semantics": {"const": "historical_payment_not_current_balance"},
            "currency": {"const": "MWK"},
            "payment_date": {"type": "string", "format": "date"},
            "amount": money,
            "payee": {"type": "string", "minLength": 1, "maxLength": 160},
            "payment_method": {"enum": ["cash", "mobile_money", "bank_transfer"]},
            "external_reference": {"type": "string", "minLength": 1, "maxLength": 120},
            "note_available": {"type": "boolean"},
            "invoices": {"type": "array", "minItems": 1, "maxItems": 10,
                "items": {"type": "object", "additionalProperties": False,
                    "required": ["invoice_id", "invoice_version", "amount", "lines"],
                    "properties": {"invoice_id": {"type": "string", "format": "uuid"},
                        "invoice_version": digest, "amount": money,
                        "lines": {"type": "array", "minItems": 1, "maxItems": 50,
                            "items": {"type": "object", "additionalProperties": False,
                                "required": ["line_index", "amount"],
                                "properties": {"line_index": {"type": "integer", "minimum": 0, "maximum": 49}, "amount": money}}}}}},
        },
        "definitions": {"digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "money": {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,15})\.[0-9]{2}$", "not": {"const": "0.00"}}},
    }
