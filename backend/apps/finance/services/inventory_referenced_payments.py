"""Private observed supplier payment across accepted invoices; NOT a route.

One actual transaction reference owns one atomic set of explicit invoice-line
settlements. Permanent parent/child receipts retain the evidence. Duplicate
reference protection is scoped to this private command family, not certification
of legacy/unreferenced payments or other outgoing-cash writers. Those need
reconciliation before a financial adapter can advertise the capability.
"""
from decimal import Decimal, localcontext
import hashlib
import uuid

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.db.models.fields.json import KT
from django.db.models.functions import Lower, Trim
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import Expenditure, FinancialCommandReceipt
from ..permissions import FINANCE_WRITE_ROLES
from .expenditures import _validate_payment_rows
from .financial_capture import _canonical, _fields, _lock_submission, _submission
from .financial_values import exact_decimal, lock_financial_periods
from .inventory_capture import _required_text
from .inventory_invoices import _refuse, _snapshot
from .inventory_invoice_payments import (_capture as invoice_payment_capture, _child_id,
    _invoice, _uuid, record_inventory_invoice_payment)


COMMAND = "inventory.supplier_payment.record"
MAX_INVOICES = 10
MAX_PAYMENT_LINES = 50


def _settlement_id(submission_id, invoice_group_id):
    return uuid.uuid5(submission_id, "inventory-referenced-settlement-v1:" + invoice_group_id)


def _capture(*, currency, payee, payment_method, external_reference, payment_date,
             total_payment_amount, invoices, notes):
    if not isinstance(payment_method, str) or payment_method not in {"cash", "mobile_money", "bank_transfer"}:
        raise ValidationError({"payment_method": "Record an actual cash, mobile-money or bank-transfer payment, not credit or a promise."})
    payee = _required_text(payee, "payee", 160)
    reference = _required_text(external_reference, "external_reference", 120)
    if not isinstance(invoices, list) or not 1 <= len(invoices) <= MAX_INVOICES:
        raise ValidationError({"invoices": f"Select 1 to {MAX_INVOICES} explicit accepted invoices for this observed payment."})
    captures, groups, line_count = [], set(), 0
    for invoice in invoices:
        _fields(invoice, {"invoice_group_id", "invoice_version", "total_payment_amount", "lines"}, "invoices")
        captured = invoice_payment_capture(currency=currency, invoice_group_id=invoice.get("invoice_group_id"),
            invoice_version=invoice.get("invoice_version"), payment_date=payment_date,
            total_payment_amount=invoice.get("total_payment_amount"), lines=invoice.get("lines"), notes="")
        if captured["invoice_group_id"] in groups:
            raise ValidationError({"invoices": "Select each accepted invoice once; combine its explicit lines without guessing a split."})
        groups.add(captured["invoice_group_id"])
        line_count += len(captured["lines"])
        captures.append(captured)
    if line_count > MAX_PAYMENT_LINES:
        raise ValidationError({"lines": f"An observed payment supports at most {MAX_PAYMENT_LINES} explicitly selected lines across all invoices."})
    total = exact_decimal(total_payment_amount, field="total_payment_amount", positive=True)
    with localcontext() as context:
        context.prec = 40
        if sum((invoice["total_payment_amount"] for invoice in captures), Decimal("0.00")) != total:
            raise ValidationError({"total_payment_amount": "The observed transaction total must equal all explicit invoice payment amounts exactly."})
    from .financial_capture import _text
    return dict(currency=currency, payee=payee, payment_method=payment_method, external_reference=reference,
        payment_date=captures[0]["payment_date"], total_payment_amount=total, invoices=captures,
        notes=_text(notes, "notes", 4000))


def _claim_reference(reference):
    """Within the transaction: periods -> reference mutex -> payables -> cash.

    Reference matching is deliberately possible-duplicate review, not proof of a
    duplicate, fake replay or global bank/account identity. Method/date/payee
    changes cannot silently bypass the same retained observed reference.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT lower(trim(%s::text))", [reference])
        normalized = cursor.fetchone()[0]
        key = checksum({"basis": "phase6-inventory-outgoing-reference-v1", "reference": normalized})
        lock_id = int.from_bytes(hashlib.sha256(("farm-inventory-payment-reference-v1:" + key).encode()).digest()[:8], "big", signed=True)
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
    # Both retained key and actual capture are checked. Incomplete evidence also
    # requires review; change-log cleanup never releases a financial reference.
    recorded = FinancialCommandReceipt.objects.filter(command=COMMAND).annotate(
        normalized_reference=Lower(Trim(KT("result__capture__external_reference"))))
    if recorded.filter(Q(result__reference_key=key) | Q(normalized_reference=normalized)).exists():
        raise ValidationError({"possible_duplicate": "This observed payment reference is already retained. Recover the original submission or request review; no additional payment was posted."})
    return key


def record_referenced_inventory_payment(*, submission_id, user, currency, payee, payment_method,
        external_reference, payment_date, total_payment_amount, invoices, notes=""):
    """Atomic dated payment to one explicit supplier, over original invoices.

    Fresh online/device/deployment/object authorization is a future adapter gate.
    No inferred funding, initial invoice capture, legacy grouping or journal input.
    """
    if not settings.FINANCE_INVENTORY_INVOICES:
        raise ValidationError({"inventory_supplier_payment": "Referenced invoice settlement is not enabled on this deployment."})
    submission_id = _uuid(submission_id, "submission_id")
    capture = _capture(currency=currency, payee=payee, payment_method=payment_method,
        external_reference=external_reference, payment_date=payment_date,
        total_payment_amount=total_payment_amount, invoices=invoices, notes=notes)

    def effect(actor):
        parent_ids = [_settlement_id(submission_id, invoice["invoice_group_id"]) for invoice in capture["invoices"]]
        child_ids = [_child_id(parent_id, line["invoice_line_index"])
            for parent_id, invoice in zip(parent_ids, capture["invoices"]) for line in invoice["lines"]]
        # Nested parents before leaves, all before ANY period/reference/domain
        # locks. Independent planned-parent/leaf callers cannot invert this order.
        for intent in sorted(parent_ids):
            _lock_submission(intent)
        for intent in sorted(child_ids):
            _lock_submission(intent)
        if FinancialCommandReceipt.objects.filter(pk__in=parent_ids + child_ids).exists():
            raise ValidationError({"inventory_supplier_payment": "A planned settlement already has independent evidence; preserve it for review, never adopt it."})
        lock_financial_periods(capture["payment_date"], field="payment_date")
        reference_key = _claim_reference(capture["external_reference"])
        payable_ids = set()
        for invoice in capture["invoices"]:
            original = _invoice(invoice["invoice_group_id"], invoice["invoice_version"])
            if original.result["capture"]["supplier"].casefold() != capture["payee"].casefold():
                raise ValidationError({"payee": "Every original invoice must identify this explicit supplier. Do not infer or merge counterparty aliases."})
            children = original.result["children"]
            if any(line["invoice_line_index"] >= len(children) for line in invoice["lines"]):
                raise ValidationError({"invoice_line_index": "Select a line from each original accepted invoice."})
            payable_ids.update(int(child["result"]["expenditure_id"]) for child in children)
        locked = list(Expenditure.objects.select_for_update().filter(pk__in=payable_ids)
            .order_by("pk").values_list("pk", flat=True))
        if set(locked) != payable_ids:
            _refuse()
        rows = [row for invoice in capture["invoices"] for line in invoice["lines"]
            for row in line["funding_allocations"]]
        # Combined cash families/aliases and owner authority are verified BEFORE
        # any nested payment. Each original service also rechecks its own payable.
        _validate_payment_rows(rows, capture["total_payment_amount"], allow_less=False,
            user=actor, payment_date=capture["payment_date"])
        payments = []
        for invoice in sorted(capture["invoices"], key=lambda value: value["invoice_group_id"]):
            parent_id = _settlement_id(submission_id, invoice["invoice_group_id"])
            result, created = record_inventory_invoice_payment(submission_id=parent_id, user=actor, **invoice)
            receipt = FinancialCommandReceipt.objects.get(pk=parent_id)
            if not created or receipt.result != result:
                raise ValidationError({"inventory_supplier_payment": "Every settlement must be created atomically from this observed payment."})
            payments.append(dict(invoice_group_id=invoice["invoice_group_id"], receipt=_snapshot(receipt)))
        result = dict(capture=_canonical(capture), reference_key=reference_key, payments=payments)
        result["payment_version"] = checksum({"basis": "phase6-inventory-referenced-payment-v1", "result": result})
        fingerprint = checksum({"actor": str(actor.pk), "command": COMMAND, "payload": _canonical(capture)})
        result["payment_anchor"] = checksum({"basis": "phase6-inventory-referenced-payment-receipt-v1",
            "operation_id": str(submission_id), "actor_id": str(actor.pk), "command": COMMAND,
            "request_hash": fingerprint, "result": result})
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=capture, roles=FINANCE_WRITE_ROLES, effect=effect)
