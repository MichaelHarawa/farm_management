"""Private dated multi-line invoice settlement, NOT a route or sync capability.

Every selected line has its observed amount and explicit funding split. Reuse
the original supplier-payment service, with permanent composite/child evidence
in one transaction. Never apportion cash, adopt a legacy invoice, alter its
original capture, or post another expense/inventory journal for the header.
"""
from decimal import Decimal, localcontext
import re
import uuid

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import Expenditure, FinancialCommandReceipt, FundingAllocation, JournalEntry
from ..permissions import FINANCE_WRITE_ROLES
from .expenditures import _validate_payment_rows
from .financial_capture import (_canonical, _currency, _fields, _funding_rows,
    _lock_submission, _submission, _text, record_financial_supplier_payment)
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .inventory_invoices import (COMMAND as INVOICE_COMMAND, MAX_LINES, _child_id as purchase_child_id,
    _refuse, _snapshot, require_invoice_membership)
from .payable_evidence import _row


COMMAND = "inventory.invoice.pay"


def _uuid(value, field):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({field: "A stable UUID is required."})


def _child_id(submission_id, index):
    return uuid.uuid5(submission_id, "inventory-invoice-payment-line-v1:" + str(index))


def _capture(*, currency, invoice_group_id, invoice_version, payment_date, total_payment_amount, lines, notes):
    _currency(currency)
    group_id = _uuid(invoice_group_id, "invoice_group_id")
    if not isinstance(invoice_version, str) or not re.fullmatch(r"[0-9a-f]{64}", invoice_version):
        raise ValidationError({"invoice_version": "Retain the original accepted invoice version."})
    day = business_date(payment_date, field="payment_date")
    if day > timezone.localdate():
        raise ValidationError({"payment_date": "Record the actual payment date, not a future event."})
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValidationError({"lines": f"Select 1 to {MAX_LINES} explicit original invoice lines."})
    observed, indexes = [], set()
    with localcontext() as context:
        context.prec = 40
        for line in lines:
            _fields(line, {"invoice_line_index", "amount", "funding_allocations"}, "lines")
            index = line.get("invoice_line_index")
            if type(index) is not int or not 0 <= index < MAX_LINES or index in indexes:
                raise ValidationError({"invoice_line_index": "Select each original zero-based line index once."})
            indexes.add(index)
            amount = exact_decimal(line.get("amount"), positive=True)
            rows = _funding_rows(line.get("funding_allocations"))
            if not rows or sum((row["amount"] for row in rows), Decimal("0.00")) != amount:
                raise ValidationError({"funding_allocations": "Each line's explicit funding splits must equal its observed payment amount."})
            observed.append(dict(invoice_line_index=index, amount=amount, funding_allocations=rows))
        total = exact_decimal(total_payment_amount, positive=True, field="total_payment_amount")
        if sum((line["amount"] for line in observed), Decimal("0.00")) != total:
            raise ValidationError({"total_payment_amount": "Payment total must equal the explicit line amounts exactly; never infer a split."})
    return dict(currency=currency, invoice_group_id=str(group_id), invoice_version=invoice_version,
        payment_date=day, total_payment_amount=total, lines=observed, notes=_text(notes, "notes", 4000))


def _invoice(group_id, version):
    parent = FinancialCommandReceipt.objects.filter(pk=group_id, command=INVOICE_COMMAND,
        completed_at__isnull=False).first()
    if (parent is None or not isinstance(parent.result, dict)
            or parent.result.get("invoice_group_id") != str(group_id)
            or parent.result.get("invoice_version") != version):
        _refuse()
    child = FinancialCommandReceipt.objects.filter(pk=purchase_child_id(group_id, 0),
        command="inventory.receipt.record", completed_at__isnull=False).first()
    if child is None or not isinstance(child.result, dict) or child.result.get("invoice_group_id") != str(group_id):
        _refuse()
    require_invoice_membership(child)  # All original sibling sources and whole journals.
    return parent


def _effects(expenditure_id, child_id):
    allocations = list(FundingAllocation.objects.filter(expenditure_id=expenditure_id,
        payment_group_key=f"financial-payment:{child_id}").order_by("pk"))
    if not allocations:
        raise ValidationError({"inventory_invoice_payment": "Original line payment evidence is missing."})
    effects = []
    for allocation in allocations:
        journal = JournalEntry.objects.get(idempotency_key=f"expenditure-payment:{allocation.pk}")
        effects.append(dict(allocation=_row(allocation), journal=_row(journal),
            journal_lines=[_row(line) for line in journal.lines.order_by("pk")]))
    return effects


def record_inventory_invoice_payment(*, submission_id, user, currency, invoice_group_id, invoice_version,
                                     payment_date, total_payment_amount, lines, notes=""):
    """Internal atomic partial/full settlement of an already accepted invoice.

    This is not initial paid capture or a fresh-online approval endpoint. A
    future adapter must enforce device/deployment/object scope and freshness.
    """
    if not settings.FINANCE_INVENTORY_INVOICES:
        raise ValidationError({"inventory_invoice_payment": "Multi-item invoice settlement is not enabled on this deployment."})
    submission_id = _uuid(submission_id, "submission_id")
    capture = _capture(currency=currency, invoice_group_id=invoice_group_id, invoice_version=invoice_version,
        payment_date=payment_date, total_payment_amount=total_payment_amount, lines=lines, notes=notes)

    def effect(actor):
        ids = [_child_id(submission_id, line["invoice_line_index"]) for line in capture["lines"]]
        # Claim every planned child before period/payable/cash locks. A concurrent
        # independent caller cannot hold our child intent while waiting on us.
        for child_id in sorted(ids):
            _lock_submission(child_id)
        if FinancialCommandReceipt.objects.filter(pk__in=ids).exists():
            raise ValidationError({"inventory_invoice_payment": "A planned child intent already exists; preserve it for review, never adopt it."})
        lock_financial_periods(capture["payment_date"], field="payment_date")
        parent = _invoice(capture["invoice_group_id"], capture["invoice_version"])
        children = parent.result["children"]
        if any(line["invoice_line_index"] >= len(children) for line in capture["lines"]):
            raise ValidationError({"invoice_line_index": "Select a line from this original accepted invoice."})
        expenditures = {index: int(child["result"]["expenditure_id"]) for index, child in enumerate(children)}
        # One PK order, including unselected siblings, before any shared cash
        # family locks; all per-line services keep their ordinary proof/limits.
        locked = list(Expenditure.objects.select_for_update().filter(pk__in=expenditures.values())
            .order_by("pk").values_list("pk", flat=True))
        if set(locked) != set(expenditures.values()):
            _refuse()
        parent = _invoice(capture["invoice_group_id"], capture["invoice_version"])
        rows = [row for line in capture["lines"] for row in line["funding_allocations"]]
        _validate_payment_rows(rows, capture["total_payment_amount"], allow_less=False,
            user=actor, payment_date=capture["payment_date"])
        settlements = []
        for line in sorted(capture["lines"], key=lambda value: value["invoice_line_index"]):
            index = line["invoice_line_index"]
            child_id = _child_id(submission_id, index)
            _, created = record_financial_supplier_payment(submission_id=child_id, user=actor, currency=currency,
                expenditure_id=expenditures[index], payment_date=capture["payment_date"],
                funding_allocations=line["funding_allocations"])
            if not created:
                raise ValidationError({"inventory_invoice_payment": "A planned child was not created atomically."})
            receipt = FinancialCommandReceipt.objects.get(pk=child_id)
            settlements.append(dict(invoice_line_index=index, receipt=_snapshot(receipt),
                effects=_effects(expenditures[index], child_id)))
        result = dict(capture=_canonical(capture), original_invoice=_snapshot(parent), settlements=settlements)
        result["payment_version"] = checksum({"basis": "phase6-inventory-invoice-payment-v1", "result": result})
        fingerprint = checksum({"actor": str(actor.pk), "command": COMMAND, "payload": _canonical(capture)})
        result["payment_anchor"] = checksum({"basis": "phase6-inventory-invoice-payment-receipt-v1",
            "operation_id": str(submission_id), "actor_id": str(actor.pk), "command": COMMAND,
            "request_hash": fingerprint, "result": result})
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=capture, roles=FINANCE_WRITE_ROLES, effect=effect)
