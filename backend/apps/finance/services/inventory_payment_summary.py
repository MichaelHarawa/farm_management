"""Private bounded payment-receipt view, NOT a sync profile or API route.

Only explicitly accepted referenced supplier payments qualify. Verify their
original invoice, nested/leaf receipts and actual payment GL before selecting
positive summary fields. Never return internal receipts or funding/owner data,
guess current balances, write a mapping/change, or repair evidence on read.
Fresh device/deployment/object authorization and publication remain adapter gates.
"""
from collections import Counter
from datetime import date
from decimal import Decimal, localcontext

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.mobile_sync.policy import permits
from apps.mobile_sync.projections import canonical, checksum
from ..models import FinancialCommandReceipt, FundingClassification, JournalEntry, JournalStatus
from ..permissions import FINANCE_READ_ROLES
from .financial_capture import _canonical, _funding_rows, _text
from .financial_values import business_date, exact_decimal
from .inventory_capture import _required_text
from .inventory_invoices import _snapshot
from . import inventory_invoice_payments as settlements
from . import inventory_referenced_payments as payments


MAX_SUMMARY_BYTES = 16384
MAX_VERIFIED_FUNDING_ROWS = 100
MESSAGE = "Original accepted supplier-payment evidence is unavailable or inconsistent; preserve it for controlled review."


class _SummaryLimit(Exception):
    pass


def _need(condition):
    if not condition:
        raise ValidationError({"payment_summary": MESSAGE})


def _reader(user):
    try:
        actor = get_user_model().objects.get(pk=user.pk)
    except (AttributeError, ObjectDoesNotExist):
        raise PermissionDenied("Current role cannot read financial payment evidence.")
    if not permits(actor, FINANCE_READ_ROLES):
        raise PermissionDenied("Current role cannot read financial payment evidence.")
    return actor


def _sealed(receipt, prefix):
    result = receipt.result
    payload_hash = checksum({"actor": str(receipt.actor_id), "command": receipt.command,
        "payload": result["capture"]})
    core = {key: value for key, value in result.items() if key not in {"payment_version", "payment_anchor"}}
    _need(receipt.request_hash == payload_hash and result["payment_version"] == checksum({
        "basis": prefix + "-v1", "result": core}))
    _need(result["payment_anchor"] == checksum({"basis": prefix + "-receipt-v1",
        "operation_id": str(receipt.pk), "actor_id": str(receipt.actor_id),
        "command": receipt.command, "request_hash": receipt.request_hash,
        "result": {key: value for key, value in result.items() if key != "payment_anchor"}}))


def _money(value):
    amount = exact_decimal(value, positive=True)
    _need(isinstance(value, str) and _canonical(amount) == value)
    return amount


def _stable_capture(capture):
    """Validate accepted canonical evidence, NOT today's new-command policy.

    Never substitute today's date or reapply a future-date heuristic to an
    already accepted historical payment. Current incoming-command validation
    remains entirely unchanged in the posting services.
    """
    _need(capture["currency"] == "MWK" and capture["payment_method"] in {"cash", "mobile_money", "bank_transfer"}
        and _required_text(capture["payee"], "payee", 160) == capture["payee"]
        and _required_text(capture["external_reference"], "external_reference", 120) == capture["external_reference"]
        and _text(capture["notes"], "notes", 4000) == capture["notes"]
        and _canonical(business_date(capture["payment_date"])) == capture["payment_date"]
        and isinstance(capture["invoices"], list) and 1 <= len(capture["invoices"]) <= payments.MAX_INVOICES)
    groups, count = set(), 0
    with localcontext() as context:
        context.prec = 40
        total = Decimal("0.00")
        for invoice in capture["invoices"]:
            _need(isinstance(invoice, dict) and set(invoice) == {"currency", "invoice_group_id",
                "invoice_version", "payment_date", "total_payment_amount", "lines", "notes"})
            group = str(payments._uuid(invoice["invoice_group_id"], "invoice_group_id"))
            from .payable_evidence import _digest
            _need(group == invoice["invoice_group_id"] and group not in groups and _digest(invoice["invoice_version"])
                and invoice["currency"] == capture["currency"] and invoice["payment_date"] == capture["payment_date"]
                and invoice["notes"] == "" and isinstance(invoice["lines"], list)
                and 1 <= len(invoice["lines"]) <= settlements.MAX_LINES)
            groups.add(group)
            subtotal, indexes = Decimal("0.00"), set()
            for line in invoice["lines"]:
                _need(isinstance(line, dict) and set(line) == {"invoice_line_index", "amount", "funding_allocations"})
                index = line["invoice_line_index"]
                _need(type(index) is int and 0 <= index < settlements.MAX_LINES and index not in indexes)
                indexes.add(index)
                amount = _money(line["amount"])
                _need(_canonical(_funding_rows(line["funding_allocations"])) == line["funding_allocations"]
                    and sum((Decimal(row["amount"]) for row in line["funding_allocations"]), Decimal("0.00")) == amount)
                subtotal += amount
                count += 1
            _need(subtotal == _money(invoice["total_payment_amount"]))
            total += subtotal
        _need(count <= payments.MAX_PAYMENT_LINES and total == _money(capture["total_payment_amount"]))


def _line_effects(expenditure_id, leaf_id, observed, captured, actor_id, payment_day):
    actual = settlements._effects(expenditure_id, leaf_id)
    _need(actual == observed)
    expected = Counter((str(row["funding_source"]), row["amount"],
        row.get("classification") or FundingClassification.REINVESTMENT) for row in captured)
    found = Counter()
    for effect in actual:
        allocation, journal = effect["allocation"], effect["journal"]
        amount = Decimal(allocation["amount"])
        source_id = allocation["funding_source_id"]
        found[(str(source_id), allocation["amount"], allocation["classification"])] += 1
        _need(str(allocation["expenditure_id"]) == str(expenditure_id)
            and allocation["allocation_date"] == payment_day
            and allocation["payment_group_key"] == f"financial-payment:{leaf_id}"
            and allocation["created_by_id"] == str(actor_id))
        entry = JournalEntry.objects.select_related("accounting_period").get(pk=journal["id"])
        _need(entry.status == JournalStatus.POSTED and entry.source_model == "finance.FundingAllocation"
            and entry.source_identifier == str(allocation["id"])
            and entry.idempotency_key == f"expenditure-payment:{allocation['id']}"
            and entry.posting_date.isoformat() == payment_day
            and entry.created_by_id == actor_id and entry.posted_by_id == actor_id and entry.posted_at
            and not entry.reversal_of_id and not entry.reversed_by_id and not entry.reversed_at
            and not entry.reversal_reason and not JournalEntry.objects.filter(reversal_of=entry).exists()
            and entry.accounting_period.period_start <= entry.posting_date <= entry.accounting_period.period_end)
        lines = Counter((line.account.code, line.debit, line.credit, line.batch_id, line.funding_source_id)
            for line in entry.lines.select_related("account"))
        _need(lines == Counter([("2000", amount, Decimal("0.00"), None, source_id),
            ("1000", Decimal("0.00"), amount, None, source_id)]))
    _need(found == expected)


def _summary(receipt):
    result = receipt.result
    _need(isinstance(result, dict) and set(result) == {
        "capture", "reference_key", "payments", "payment_version", "payment_anchor"})
    capture = result["capture"]
    _need(isinstance(capture, dict) and set(capture) == {"currency", "payee", "payment_method",
        "external_reference", "payment_date", "total_payment_amount", "invoices", "notes"})
    _stable_capture(capture)
    _sealed(receipt, "phase6-inventory-referenced-payment")
    # Proof work is explicitly bounded, not silently truncated. Full physical
    # evidence remains in its original permanent receipt for controlled review.
    if sum(len(line["funding_allocations"]) for invoice in capture["invoices"]
            for line in invoice["lines"]) > MAX_VERIFIED_FUNDING_ROWS:
        raise _SummaryLimit()
    with transaction.get_connection().cursor() as cursor:
        cursor.execute("SELECT lower(trim(%s::text))", [capture["external_reference"]])
        normalized = cursor.fetchone()[0]
    _need(result["reference_key"] == checksum({"basis": "phase6-inventory-outgoing-reference-v1", "reference": normalized}))
    invoices = sorted(capture["invoices"], key=lambda row: row["invoice_group_id"])
    _need(isinstance(result["payments"], list) and len(result["payments"]) == len(invoices))
    headers = []
    for invoice, observed in zip(invoices, result["payments"]):
        _need(set(observed) == {"invoice_group_id", "receipt"}
            and observed["invoice_group_id"] == invoice["invoice_group_id"])
        parent_id = payments._settlement_id(receipt.pk, invoice["invoice_group_id"])
        parent = FinancialCommandReceipt.objects.get(pk=parent_id, command=settlements.COMMAND,
            actor_id=receipt.actor_id, completed_at__isnull=False)
        _need(_snapshot(parent) == observed["receipt"] and set(parent.result) == {
            "capture", "original_invoice", "settlements", "payment_version", "payment_anchor"}
            and parent.result["capture"] == invoice)
        _sealed(parent, "phase6-inventory-invoice-payment")
        original = settlements._invoice(invoice["invoice_group_id"], invoice["invoice_version"])
        _need(parent.result["original_invoice"] == _snapshot(original)
            and original.result["capture"]["supplier"].casefold() == capture["payee"].casefold()
            and date.fromisoformat(capture["payment_date"]) >= date.fromisoformat(original.result["capture"]["purchase_date"]))
        selected = sorted(invoice["lines"], key=lambda row: row["invoice_line_index"])
        _need(isinstance(parent.result["settlements"], list) and len(parent.result["settlements"]) == len(selected))
        lines = []
        for line, settled in zip(selected, parent.result["settlements"]):
            index = line["invoice_line_index"]
            _need(set(settled) == {"invoice_line_index", "receipt", "effects"}
                and settled["invoice_line_index"] == index)
            expenditure_id = original.result["children"][index]["result"]["expenditure_id"]
            leaf_id = settlements._child_id(parent_id, index)
            leaf = FinancialCommandReceipt.objects.get(pk=leaf_id, command="finance.expenditure.pay",
                actor_id=receipt.actor_id, completed_at__isnull=False)
            payload = dict(currency=capture["currency"], expenditure_id=expenditure_id,
                payment_date=capture["payment_date"], funding_allocations=line["funding_allocations"])
            _need(_snapshot(leaf) == settled["receipt"] and leaf.result == {"expenditure_id": expenditure_id}
                and leaf.request_hash == checksum({"actor": str(receipt.actor_id), "command": leaf.command, "payload": payload}))
            _line_effects(expenditure_id, leaf_id, settled["effects"], line["funding_allocations"],
                receipt.actor_id, capture["payment_date"])
            lines.append(dict(line_index=index, amount=line["amount"]))
        headers.append(dict(invoice_id=invoice["invoice_group_id"], invoice_version=invoice["invoice_version"],
            amount=invoice["total_payment_amount"], lines=lines))
    summary = dict(summary_version=1, operation_id=str(receipt.pk), payment_version=result["payment_version"],
        recorded_at=_canonical(receipt.completed_at), evidence_status="accepted_original_payment",
        balance_semantics="historical_payment_not_current_balance", currency=capture["currency"],
        payment_date=capture["payment_date"], amount=capture["total_payment_amount"], payee=capture["payee"],
        payment_method=capture["payment_method"], external_reference=capture["external_reference"],
        note_available=bool(capture["notes"]), invoices=headers)
    if len(canonical(summary).encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise _SummaryLimit()
    return summary


def supplier_payment_summary(*, operation_id, user):
    """Private finance-reader candidate, not device/scope/cache authorization.

    All roles receive the same positive common fields, never owner identities,
    funding source IDs/classifications/balances, free-text notes or raw journals.
    A future financial adapter must separately authorize this shared single-farm
    read and map invoice receipt UUIDs; these are not SyncEntity mappings.
    """
    if not settings.FINANCE_INVENTORY_INVOICES:
        raise ValidationError({"payment_summary": "Financial payment summaries are not enabled on this deployment."})
    if connection.vendor != "postgresql":
        raise ValidationError({"database": "Financial payment summaries require the verified PostgreSQL backend."})
    _reader(user)  # No financial lookup for a denied current principal.
    identifier = payments._uuid(operation_id, "operation_id")
    with transaction.atomic():
        try:
            receipt = FinancialCommandReceipt.objects.get(pk=identifier, command=payments.COMMAND,
                completed_at__isnull=False)
            summary = _summary(receipt)
        except _SummaryLimit:
            raise ValidationError({"payment_summary_limit": "Payment evidence exceeds the bounded summary limit; preserve the complete original for controlled detail review."})
        except (ObjectDoesNotExist, AttributeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise ValidationError({"payment_summary": MESSAGE})
        _reader(user)  # Recheck after potentially expensive/waiting proof reads.
        return summary
