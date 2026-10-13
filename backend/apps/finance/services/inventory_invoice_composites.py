"""Private invoice plus observed initial payment, never an enabled mobile API.

Existing unpaid-invoice and dated-settlement services own all accounting effects.
Their permanent receipts and the composite receipt commit in one transaction.
No paid dropdown, guessed funding split, legacy adoption or new journal template.
"""
import uuid

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import FinancialCommandReceipt
from ..permissions import FINANCE_WRITE_ROLES
from .financial_capture import _canonical, _fields, _lock_submission, _submission
from .financial_values import lock_financial_periods
from .inventory_capture import _day
from .inventory_invoices import _capture as invoice_capture, _child_id as purchase_child_id, _snapshot, record_inventory_invoice
from .inventory_invoice_payments import (_child_id as payment_child_id, _payment_capture,
    _uuid, record_inventory_invoice_payment)


COMMAND = "inventory.invoice.record_with_payment"


def _invoice_id(submission_id):
    return uuid.uuid5(submission_id, "inventory-invoice-initial-capture-v1")


def _payment_id(submission_id):
    return uuid.uuid5(submission_id, "inventory-invoice-initial-payment-v1")


def record_inventory_invoice_with_payment(*, submission_id, user, currency, supplier, invoice_reference,
                                         purchase_date, total_purchase_cost, lines, initial_payment, notes=""):
    """Internal atomic new invoice plus explicit partial/full initial settlement.

    Future financial adapters still need device/deployment/object authorization,
    publication and observed-reference/review policy. This is not an endpoint.
    """
    if not settings.FINANCE_INVENTORY_INVOICES:
        raise ValidationError({"inventory_invoice": "Invoice capture with initial payment is not enabled on this deployment."})
    submission_id = _uuid(submission_id, "submission_id")
    invoice = invoice_capture(currency=currency, supplier=supplier, invoice_reference=invoice_reference,
        purchase_date=_day(purchase_date, "purchase_date"), total_purchase_cost=total_purchase_cost,
        lines=lines, notes=notes)
    _fields(initial_payment, {"payment_date", "total_payment_amount", "lines", "notes"}, "initial_payment")
    payment = _payment_capture(currency=currency, payment_date=initial_payment.get("payment_date"),
        total_payment_amount=initial_payment.get("total_payment_amount"), lines=initial_payment.get("lines"),
        notes=initial_payment.get("notes", ""))
    if payment["payment_date"] < invoice["purchase_date"]:
        raise ValidationError({"payment_date": "Pre-purchase deposits require a separate verified workflow."})
    if any(line["invoice_line_index"] >= len(invoice["lines"]) for line in payment["lines"]):
        raise ValidationError({"invoice_line_index": "Select a line from this new explicit invoice."})
    capture = dict(invoice=invoice, initial_payment=payment)
    group_id, settlement_id = _invoice_id(submission_id), _payment_id(submission_id)

    def effect(actor):
        purchase_ids = {purchase_child_id(group_id, index) for index in range(len(invoice["lines"]))}
        payment_ids = {payment_child_id(settlement_id, line["invoice_line_index"]) for line in payment["lines"]}
        ids = {group_id, settlement_id, *purchase_ids, *payment_ids}
        # Nested PARENTS precede children, like independent calls to those same
        # services. Sorting parents and children together could invert that
        # order. Every planned intent still precedes ALL period/domain locks.
        for child_id in (group_id, settlement_id, *sorted(purchase_ids), *sorted(payment_ids)):
            _lock_submission(child_id)
        if FinancialCommandReceipt.objects.filter(pk__in=ids).exists():
            raise ValidationError({"inventory_invoice": "A planned invoice/payment intent already exists; retain original evidence for review, never adopt it."})
        lock_financial_periods(invoice["purchase_date"], payment["payment_date"])
        accepted_invoice, created = record_inventory_invoice(submission_id=group_id, user=actor, **invoice)
        if not created:
            raise ValidationError({"inventory_invoice": "The new invoice must be captured inside this original composite."})
        accepted_payment, created = record_inventory_invoice_payment(submission_id=settlement_id, user=actor,
            invoice_group_id=str(group_id), invoice_version=accepted_invoice["invoice_version"], **payment)
        if not created:
            raise ValidationError({"initial_payment": "The initial payment must be captured inside this original composite."})
        invoice_receipt = FinancialCommandReceipt.objects.get(pk=group_id)
        payment_receipt = FinancialCommandReceipt.objects.get(pk=settlement_id)
        if invoice_receipt.result != accepted_invoice or payment_receipt.result != accepted_payment:
            raise ValidationError({"inventory_invoice": "Original nested invoice/payment evidence requires controlled review."})
        result = dict(capture=_canonical(capture), invoice=_snapshot(invoice_receipt),
            initial_payment=_snapshot(payment_receipt))
        result["composite_version"] = checksum({"basis": "phase6-inventory-invoice-with-payment-v1", "result": result})
        fingerprint = checksum({"actor": str(actor.pk), "command": COMMAND, "payload": _canonical(capture)})
        result["composite_anchor"] = checksum({"basis": "phase6-inventory-invoice-with-payment-receipt-v1",
            "operation_id": str(submission_id), "actor_id": str(actor.pk), "command": COMMAND,
            "request_hash": fingerprint, "result": result})
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=capture, roles=FINANCE_WRITE_ROLES, effect=effect)
