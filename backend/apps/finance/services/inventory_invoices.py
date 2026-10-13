"""Private unpaid multi-item invoices; not a route or financial sync profile.

The permanent parent receipt is immutable invoice evidence. Existing purchase
services retain one lot/payable/source journal per line. One first-line binding
owns the existing unique invoice key; siblings are explicitly parent-linked in
sealed receipts, not unrelated blank-reference purchases. No legacy adoption,
tax/discount apportionment, inferred unit cost, cash effect or new schema.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, localcontext
import re
import uuid

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import FinancialCommandReceipt, InventoryLotBinding
from ..permissions import FINANCE_WRITE_ROLES
from .financial_capture import _canonical, _currency, _fields, _identifier, _submission, _text
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .inventory_units import captured_unit, unit_payload


COMMAND = "inventory.invoice.record"
MAX_LINES = 50
MESSAGE = "Original multi-item supplier invoice evidence is missing, ambiguous or changed; preserve the whole invoice for controlled review."
_building = ContextVar("inventory_invoice_building", default=None)


def _refuse():
    raise ValidationError({"inventory_invoice": MESSAGE})


def _child_id(group_id, position):
    return uuid.uuid5(uuid.UUID(str(group_id)), "inventory-invoice-line-v1:" + str(position))


def _version(result):
    return checksum({"basis": "phase6-inventory-invoice-v1",
        "invoice": {key: value for key, value in result.items() if key not in {"invoice_version", "invoice_anchor"}}})


def _anchor(result, group_id, actor_id, request_hash):
    return checksum({"basis": "phase6-inventory-invoice-receipt-v1", "operation_id": str(group_id),
        "command": COMMAND, "actor_id": str(actor_id), "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "invoice_anchor"}})


def _snapshot(receipt):
    return {"operation_id": str(receipt.pk), "actor_id": str(receipt.actor_id),
        "request_hash": receipt.request_hash, "completed_at": _canonical(receipt.completed_at),
        "result": receipt.result}


@contextmanager
def _line_boundary(*, group_id, actor_id, invoice_key, position, line_count):
    token = _building.set(dict(group_id=str(group_id), actor_id=str(actor_id), invoice_key=invoice_key,
        position=position, line_count=line_count))
    try:
        yield
    finally:
        _building.reset(token)


def purchase_invoice_context(submission_id, invoice_key, actor_id):
    """Private construction context, NEVER a client-supplied bypass option."""
    scope = _building.get()
    if scope is None:
        return {}, invoice_key, False
    if (str(submission_id) != str(_child_id(scope["group_id"], scope["position"]))
            or invoice_key != scope["invoice_key"] or str(actor_id) != scope["actor_id"]):
        _refuse()
    return {"invoice_group_id": scope["group_id"], "invoice_line_index": scope["position"]}, (
        invoice_key if scope["position"] == 0 else None), True


def _line(value):
    from .inventory_capture import stock_quantity
    _fields(value, {"item_id", "location_id", "category_id", "quantity", "total_purchase_cost",
        "expiry_date", "notes", "quantity_unit", "unit_conversion_id"}, "lines")
    row = {field: _identifier(value.get(field), field) for field in ("item_id", "location_id", "category_id")}
    row.update(quantity=stock_quantity(value.get("quantity")),
        total_purchase_cost=exact_decimal(value.get("total_purchase_cost"), positive=True, field="total_purchase_cost"),
        expiry_date=business_date(value["expiry_date"], field="expiry_date") if value.get("expiry_date") is not None else None,
        notes=_text(value.get("notes", ""), "notes", 4000))
    row.update(unit_payload(captured_unit(value.get("quantity_unit")), value.get("unit_conversion_id")))
    # Current purchase hashes use string IDs, not JSON numbers.
    return {key: str(item) if key in {"item_id", "location_id", "category_id"} else item for key, item in row.items()}


def _purchase_payload(capture, row, group_id, position):
    return {**row, "currency": capture["currency"], "supplier": capture["supplier"],
        "invoice_reference": capture["invoice_reference"], "purchase_date": capture["purchase_date"],
        "funding_allocations": [], "payment_date": None,
        "invoice_group_id": str(group_id), "invoice_line_index": position}


def _capture(*, currency, supplier, invoice_reference, purchase_date, total_purchase_cost, lines, notes):
    from .inventory_capture import _required_text
    _currency(currency)
    if not isinstance(lines, list) or not 2 <= len(lines) <= MAX_LINES:
        raise ValidationError({"lines": f"Record 2 to {MAX_LINES} explicit inventory item lines."})
    rows = [_line(row) for row in lines]
    total = exact_decimal(total_purchase_cost, positive=True, field="total_purchase_cost")
    with localcontext() as context:
        context.prec = 40
        if sum((row["total_purchase_cost"] for row in rows), Decimal("0.00")) != total:
            raise ValidationError({"total_purchase_cost": "Invoice total must equal all explicit line costs exactly; do not infer a split or round it."})
    return dict(currency=currency, supplier=_required_text(supplier, "supplier", 160),
        invoice_reference=_required_text(invoice_reference, "invoice_reference", 120),
        purchase_date=business_date(purchase_date, field="purchase_date"), total_purchase_cost=total,
        notes=_text(notes, "notes", 4000), lines=rows)


def record_inventory_invoice(*, submission_id, user, currency, supplier, invoice_reference,
                             purchase_date, total_purchase_cost, lines, notes=""):
    """Internal all-or-nothing UNPAID invoice with explicit line costs."""
    if not settings.FINANCE_INVENTORY_INVOICES:
        raise ValidationError({"inventory_invoice": "Multi-item invoice capture is not enabled on this deployment."})
    from .inventory_capture import _claim_invoice, _day, _invoice_key, _item, _location, record_inventory_purchase
    try:
        submission_id = uuid.UUID(str(submission_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"submission_id": "A stable UUID submission ID is required."})
    capture = _capture(currency=currency, supplier=supplier, invoice_reference=invoice_reference,
        purchase_date=_day(purchase_date, "purchase_date"), total_purchase_cost=total_purchase_cost,
        lines=lines, notes=notes)
    supplier, invoice_reference, purchase_date, rows = (capture[key] for key in
        ("supplier", "invoice_reference", "purchase_date", "lines"))
    key = _invoice_key(supplier, invoice_reference)

    def effect(actor):
        lock_financial_periods(purchase_date)
        _claim_invoice(key)
        ids = [_child_id(submission_id, position) for position in range(len(rows))]
        if FinancialCommandReceipt.objects.filter(pk__in=ids).exists():
            _refuse()  # Never attach a pre-existing independent effect to an invoice.
        # Period -> invoice mutex -> all items sorted -> all locations sorted.
        # Nested line services retain their ordinary item/pool/location checks.
        for item_id in sorted({int(row["item_id"]) for row in rows}):
            _item(item_id)
        for location_id in sorted({int(row["location_id"]) for row in rows}):
            _location(location_id)
        children = []
        for position, row in enumerate(rows):
            with _line_boundary(group_id=submission_id, actor_id=actor.pk, invoice_key=key,
                    position=position, line_count=len(rows)):
                _, created = record_inventory_purchase(submission_id=ids[position], user=actor,
                    currency=currency, supplier=supplier, invoice_reference=invoice_reference,
                    purchase_date=purchase_date, **row)
                if not created:
                    _refuse()
                child = FinancialCommandReceipt.objects.get(pk=ids[position])
                if (child.actor_id != actor.pk or child.request_hash != checksum({"actor": str(actor.pk),
                        "command": "inventory.receipt.record", "payload": _canonical(_purchase_payload(capture, row, submission_id, position))})):
                    _refuse()
                children.append(_snapshot(child))
        result = {"invoice_group_id": str(submission_id), "invoice_key": key,
            "capture": _canonical(capture), "children": children}
        result["invoice_version"] = _version(result)
        fingerprint = checksum({"actor": str(actor.pk), "command": COMMAND, "payload": _canonical(capture)})
        result["invoice_anchor"] = _anchor(result, submission_id, actor.pk, fingerprint)
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=capture, roles=FINANCE_WRITE_ROLES, effect=effect)


def require_invoice_membership(receipt):
    """Before new stock/payment effects; original proof remains valid flag-off."""
    result = receipt.result
    if "invoice_group_id" not in result and "invoice_line_index" not in result:
        if receipt.command == "inventory.receipt.record" and FinancialCommandReceipt.objects.filter(
                command=COMMAND, result__children__contains=[{"operation_id": str(receipt.pk)}]).exists():
            _refuse()  # Removing linkage cannot turn an invoice line into an independent purchase.
        return
    group_id, position = result.get("invoice_group_id"), result.get("invoice_line_index")
    try:
        group_id = str(uuid.UUID(group_id))
        if type(position) is not int or not 0 <= position < MAX_LINES or receipt.pk != _child_id(group_id, position):
            _refuse()
    except (TypeError, ValueError, AttributeError):
        _refuse()
    scope = _building.get()
    if scope is not None and scope["group_id"] == group_id:
        # Only the enclosing new atomic invoice can prove a preceding sibling
        # while its final parent receipt is not yet committed. Not a read adapter.
        if str(receipt.actor_id) != scope["actor_id"] or position >= scope["line_count"]:
            _refuse()
        return
    parent = FinancialCommandReceipt.objects.filter(pk=group_id, command=COMMAND,
        completed_at__isnull=False, actor_id=receipt.actor_id).first()
    if parent is None or not isinstance(parent.result, dict):
        _refuse()
    invoice = parent.result
    if set(invoice) != {"invoice_group_id", "invoice_key", "capture", "children", "invoice_version", "invoice_anchor"}:
        _refuse()
    capture, children = invoice["capture"], invoice["children"]
    if (invoice["invoice_group_id"] != group_id or not isinstance(capture, dict)
            or set(capture) != {"currency", "supplier", "invoice_reference", "purchase_date", "total_purchase_cost", "notes", "lines"}
            or not isinstance(children, list) or not 2 <= len(children) <= MAX_LINES
            or not isinstance(capture["lines"], list) or len(capture["lines"]) != len(children)
            or not re.fullmatch(r"[0-9a-f]{64}", parent.request_hash)
            or parent.request_hash != checksum({"actor": str(parent.actor_id), "command": COMMAND, "payload": capture})
            or invoice["invoice_version"] != _version(invoice)
            or invoice["invoice_anchor"] != _anchor(invoice, parent.pk, parent.actor_id, parent.request_hash)):
        _refuse()
    if _canonical(_capture(**capture)) != capture:
        _refuse()
    parents = list(FinancialCommandReceipt.objects.filter(command=COMMAND,
        result__children__contains=[{"operation_id": str(receipt.pk)}]).values_list("pk", flat=True)[:2])
    if len(parents) != 1 or str(parents[0]) != group_id:
        _refuse()
    from .inventory_capture import _invoice_key
    if invoice["invoice_key"] != _invoice_key(capture["supplier"], capture["invoice_reference"]):
        _refuse()
    ids = [_child_id(group_id, index) for index in range(len(children))]
    stored = {str(row.pk): row for row in FinancialCommandReceipt.objects.filter(pk__in=ids,
        command="inventory.receipt.record", actor_id=parent.actor_id, completed_at__isnull=False)}
    if len(stored) != len(children):
        _refuse()
    from .payable_evidence import verified_payable
    for index, (observed, line) in enumerate(zip(children, capture["lines"])):
        child = stored[str(ids[index])]
        if (observed != _snapshot(child) or child.result.get("invoice_group_id") != group_id
                or child.result.get("invoice_line_index") != index
                or child.request_hash != checksum({"actor": str(parent.actor_id), "command": "inventory.receipt.record",
                    "payload": _purchase_payload(capture, line, group_id, index)})):
            _refuse()
        binding = InventoryLotBinding.objects.select_related("expenditure").filter(lot_id=child.result.get("lot_id")).first()
        if (binding is None or binding.invoice_key != (invoice["invoice_key"] if index == 0 else None)
                or not verified_payable(binding.expenditure, _invoice_group=False)):
            _refuse()
