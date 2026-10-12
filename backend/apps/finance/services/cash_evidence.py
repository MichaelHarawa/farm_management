"""Original managed incoming-cash proof, never a legacy cash adoption policy.

Seal only new atomic accepted results. Replay/read never stamps old evidence.
Source labels, owner display metadata, collection summaries and period lock
state are not cash economics. Privileged SQL is outside the writer guarantees;
inconsistent stored evidence requires review instead of a fabricated balance.
"""
from collections import Counter
from decimal import Decimal
import re
import uuid

from django.conf import settings
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from apps.poultry.models import PaymentStatus
from ..models import (FinancialCommandReceipt, FundingReceipt, FundingReceiptStatus,
    FundingSourceType, JournalEntry, JournalStatus, OwnerDesignationStatus,
    SalePayment, SalePaymentStatus)
from .financial_values import business_date


CASH_COMMANDS = frozenset({"poultry.sale.record", "finance.sale_receipt.record",
    "finance.owner_contribution.record", "finance.funding_receipt.record"})
ZERO = Decimal("0.00")
MAX_CASH_EVIDENCE = 1000
MESSAGE = "Original managed incoming cash/receipt/journal evidence does not match; preserve it for controlled review."


def _refuse():
    raise ValidationError({"funding_allocations": MESSAGE})


def _row(instance, exclude=()):
    from .financial_capture import _canonical
    return _canonical({field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields if field.attname not in exclude})


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _intent(row, prefix, submission_id):
    key = row.idempotency_key or ""
    try:
        if not key.startswith(prefix) or uuid.UUID(key[len(prefix):]) != submission_id:
            _refuse()
    except (ValueError, TypeError, AttributeError):
        _refuse()


def _linked_loan_reversal(row, journal, lines):
    """Verify the one append-only correction before normalizing original status.

    Its amount remains reserved by dated_source_cash. This is not permission
    to spend a reversed receipt, and never queries an additive table with its
    rollout flag off.
    """
    if not getattr(settings, "FINANCE_FUNDING_REVERSALS", False):
        _refuse()
    from .funding_reversals import funding_receipt_version
    from ..models import FundingReceiptReversal
    reversal = FundingReceiptReversal.objects.select_related("reversal_journal").filter(
        receipt=row, original_journal=journal).first()
    if reversal is None:
        _refuse()
    opposite = reversal.reversal_journal
    expected_result = {"receipt_id": str(row.pk), "reversal_id": str(reversal.pk),
        "original_journal_id": str(journal.pk), "reversal_journal_id": str(opposite.pk),
        "funding_source_id": str(row.funding_source_id), "source_version": reversal.source_version,
        "amount": str(row.amount), "reversal_date": reversal.reversal_date.isoformat(), "reason": reversal.reason}
    anchors = list(FinancialCommandReceipt.objects.filter(command="finance.funding_receipt.reverse",
        completed_at__isnull=False, result__reversal_id=str(reversal.pk)).order_by("pk")[:2])
    if len(anchors) != 1:
        _refuse()
    anchor = anchors[0]
    request = {"currency": "MWK", "receipt_id": str(row.pk), "source_version": reversal.source_version,
        "reversal_date": reversal.reversal_date.isoformat(), "reason": reversal.reason}
    if (anchor.pk != reversal.submission_id or anchor.actor_id != reversal.created_by_id
            or anchor.result != expected_result or anchor.request_hash != checksum({
                "actor": str(anchor.actor_id), "command": anchor.command, "payload": request})
            or reversal.source_version != funding_receipt_version(row) or reversal.amount != row.amount
            or reversal.funding_source_id != row.funding_source_id or not reversal.reason
            or reversal.reversal_date < business_date(row.receipt_date)
            or journal.reversed_by_id != reversal.created_by_id or not journal.reversed_at
            or journal.reversal_reason != reversal.reason):
        _refuse()
    expected = [(line.account.code, line.credit, line.debit, line.batch_id,
        line.funding_source_id, f"Reversal of line {line.pk}") for line in lines]
    actual = [(line.account.code, line.debit, line.credit, line.batch_id,
        line.funding_source_id, line.memo) for line in opposite.lines.select_related("account")]
    period = opposite.accounting_period
    if (opposite.status != JournalStatus.POSTED or opposite.reversal_of_id != journal.pk
            or opposite.idempotency_key != f"reversal:{journal.pk}"
            or opposite.source_model != "finance.JournalEntry" or opposite.source_identifier != str(journal.pk)
            or opposite.posting_date != reversal.reversal_date
            or not period.period_start <= opposite.posting_date <= period.period_end
            or opposite.description != f"Reversal of {journal.reference}: {reversal.reason}"[:255]
            or opposite.created_by_id != reversal.created_by_id or opposite.posted_by_id != reversal.created_by_id
            or not opposite.posted_at or opposite.reversed_by_id or opposite.reversed_at or opposite.reversal_reason
            or JournalEntry.objects.filter(reversal_of=opposite).exists() or Counter(actual) != Counter(expected)):
        _refuse()


def _journal(journal, *, model, identifier, key, day, actor_id, expected, loan=None):
    period = journal.accounting_period
    if (journal.source_model != model or journal.source_identifier != str(identifier)
            or journal.idempotency_key != key or journal.posting_date != day
            or not period.period_start <= day <= period.period_end
            or journal.created_by_id != actor_id or journal.posted_by_id != actor_id
            or not journal.posted_at or journal.reversal_of_id):
        _refuse()
    lines = list(journal.lines.select_related("account").order_by("pk"))
    if Counter((line.account.code, line.debit, line.credit, line.batch_id,
                line.funding_source_id) for line in lines) != Counter(expected):
        _refuse()
    if journal.status == JournalStatus.REVERSED and loan is not None:
        _linked_loan_reversal(loan, journal, lines)
    elif (journal.status != JournalStatus.POSTED or journal.reversed_by_id or journal.reversed_at
            or journal.reversal_reason or JournalEntry.objects.filter(reversal_of=journal).exists()):
        _refuse()
    # A verified linked reversal changes only these original journal controls.
    # All original lines, identity, dates, actor, captions and capture remain bound.
    original = _row(journal, {"updated_at", "reversed_by_id", "reversed_at", "reversal_reason"})
    original["status"] = JournalStatus.POSTED
    return {"journal": original, "lines": [dict(_row(line, {"updated_at"}),
        account_code=line.account.code) for line in lines]}


def _version(row, *, submission_id, command, actor_id, result):
    if row.amount <= ZERO or row.created_by_id != actor_id or row.reversed_by_id or row.reversed_at or row.reversal_reason:
        _refuse()
    source = parent = designations = None
    if isinstance(row, SalePayment):
        from .financial_capture import financial_sale_version
        initial = command == "poultry.sale.record"
        if command not in {"poultry.sale.record", "finance.sale_receipt.record"} or row.status != SalePaymentStatus.POSTED:
            _refuse()
        _intent(row, "sale-initial:" if initial else "financial-receipt:", submission_id)
        sale = row.sale
        if sale.payment_status == PaymentStatus.CANCELLED or row.payment_date < sale.sale_date:
            _refuse()
        journal = JournalEntry.objects.filter(idempotency_key=f"sale-receipt:{row.pk}").first()
        sale_journal = JournalEntry.objects.filter(idempotency_key=f"financial-sale:{sale.pk}").first()
        if journal is None or sale_journal is None or result.get("payment_id") != str(row.pk):
            _refuse()
        if initial:
            if (result.get("sale_id") != str(sale.pk) or result.get("sale_version") != financial_sale_version(sale)
                    or not isinstance(result.get("journal_ids"), list)
                    or str(journal.pk) not in result["journal_ids"] or str(sale_journal.pk) not in result["journal_ids"]
                    or sale.created_by_id != actor_id):
                _refuse()
            parent_anchor = None
        else:
            anchors = list(FinancialCommandReceipt.objects.filter(command="poultry.sale.record",
                completed_at__isnull=False, result__sale_id=str(sale.pk)).order_by("pk")[:2])
            if (result.get("journal_id") != str(journal.pk) or len(anchors) != 1
                    or not _digest(anchors[0].request_hash) or anchors[0].actor_id != sale.created_by_id
                    or anchors[0].result.get("sale_version") != financial_sale_version(sale)
                    or not isinstance(anchors[0].result.get("journal_ids"), list)
                    or str(sale_journal.pk) not in anchors[0].result.get("journal_ids", [])):
                _refuse()
            parent_anchor = _row(anchors[0])
        parent = {"sale_version": financial_sale_version(sale), "receipt": parent_anchor,
            **_journal(sale_journal, model="poultry.Sales", identifier=sale.pk,
                key=f"financial-sale:{sale.pk}", day=business_date(sale.sale_date), actor_id=sale.created_by_id,
                expected=[("1100", sale.sale_total, ZERO, sale.batch_id, None),
                          ("4000", ZERO, sale.sale_total, sale.batch_id, None)])}
        cash = _journal(journal, model="finance.SalePayment", identifier=row.pk,
            key=f"sale-receipt:{row.pk}", day=business_date(row.payment_date), actor_id=actor_id,
            expected=[("1000", row.amount, ZERO, sale.batch_id, None),
                      ("1100", ZERO, row.amount, sale.batch_id, None)])
    else:
        from .funding_capture import funding_source_version
        from .financial_capture import _canonical
        owner = command == "finance.owner_contribution.record"
        if command not in {"finance.owner_contribution.record", "finance.funding_receipt.record"} or row.status != FundingReceiptStatus.POSTED:
            _refuse()
        _intent(row, "financial-owner:" if owner else "financial-funding:", submission_id)
        funding = row.funding_source
        if (funding.batch_id is not None or funding.source_type != (
                FundingSourceType.OWNER_CAPITAL if owner else FundingSourceType.LOAN)
                or (owner and not funding.owner_id) or (not owner and funding.owner_id)):
            _refuse()
        source = {"binding": funding_source_version(funding)}
        if not owner:
            payload = {key: value for key, value in result.items()
                if key not in {"receipt_id", "journal_id", "cash_version", "cash_anchor"}}
            if (payload.get("currency") != "MWK" or payload.get("amount") != str(row.amount)
                    or payload.get("receipt_date") != _canonical(row.receipt_date)
                    or payload.get("reference") != row.reference or payload.get("notes") != row.notes
                    or payload.get("funding_source_id") != str(funding.pk)
                    or payload.get("source_version") != source["binding"]
                    or payload.get("source_type") != FundingSourceType.LOAN
                    or checksum(payload) != row.request_fingerprint):
                _refuse()
        if owner:
            source["owner_public_id"] = str(funding.owner.public_id)
            rows = list(row.owner_designations.order_by("pk"))
            if (sum((item.amount for item in rows), ZERO) > row.amount
                    or any(item.amount <= ZERO or item.status != OwnerDesignationStatus.POSTED
                        or item.created_by_id != actor_id or item.reversed_at or item.reversed_by_id
                        or item.reversal_reason for item in rows)):
                _refuse()
            designations = [_row(item, {"updated_at"}) for item in rows]
        journal = JournalEntry.objects.filter(idempotency_key=f"financial-{'owner' if owner else 'funding'}-receipt:{row.pk}").first()
        if journal is None or result.get("receipt_id") != str(row.pk) or result.get("journal_id") != str(journal.pk):
            _refuse()
        cash = _journal(journal, model="finance.FundingReceipt", identifier=row.pk,
            key=f"financial-{'owner' if owner else 'funding'}-receipt:{row.pk}",
            day=business_date(row.receipt_date), actor_id=actor_id, loan=None if owner else row,
            expected=[("1000", row.amount, ZERO, None, funding.pk),
                      ("3000" if owner else "2200", ZERO, row.amount, None, funding.pk)])
    return checksum({"basis": "phase6-original-incoming-cash-v1", "cash_row": _row(row, {"updated_at"}),
        "cash_journal": cash, "source": source, "sale": parent, "designations": designations})


def _anchor(result, *, submission_id, command, actor_id, request_hash):
    return checksum({"basis": "phase6-incoming-cash-receipt-v1", "submission_id": str(submission_id),
        "command": command, "actor_id": str(actor_id), "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "cash_anchor"}})


def seal_cash_result(result, *, submission_id, command, actor_id, request_hash):
    """Only _submission calls this, before inserting a NEW permanent receipt."""
    if command not in CASH_COMMANDS or (command == "poultry.sale.record" and not result.get("payment_id")):
        return result
    row = (SalePayment.objects.select_related("sale").get(pk=result["payment_id"])
        if command in {"poultry.sale.record", "finance.sale_receipt.record"}
        else FundingReceipt.objects.select_related("funding_source__owner").get(pk=result["receipt_id"]))
    sealed = {**result, "cash_version": _version(row, submission_id=submission_id,
        command=command, actor_id=actor_id, result=result)}
    sealed["cash_anchor"] = _anchor(sealed, submission_id=submission_id, command=command,
        actor_id=actor_id, request_hash=request_hash)
    return sealed


def require_cash_receipt(row):
    sale = isinstance(row, SalePayment)
    candidates = list(FinancialCommandReceipt.objects.filter(command__in=(
        {"poultry.sale.record", "finance.sale_receipt.record"} if sale else
        {"finance.owner_contribution.record", "finance.funding_receipt.record"}),
        completed_at__isnull=False, **{f"result__{'payment_id' if sale else 'receipt_id'}": str(row.pk)}).order_by("pk")[:2])
    if len(candidates) != 1:
        _refuse()
    receipt = candidates[0]
    result = receipt.result
    if (not _digest(receipt.request_hash) or not _digest(result.get("cash_version"))
            or result.get("cash_anchor") != _anchor(result, submission_id=receipt.pk,
                command=receipt.command, actor_id=receipt.actor_id, request_hash=receipt.request_hash)
            or result["cash_version"] != _version(row, submission_id=receipt.pk,
                command=receipt.command, actor_id=receipt.actor_id, result=result)):
        _refuse()


def require_managed_incoming_cash(sources):
    """Review bounded original managed receipts in every selected shared pool.

    Verify all managed receipts, including future ones, before making a new
    managed payment; a damaged source is not partially trusted. Legacy rows
    are neither stamped nor adopted: their existing policy is a separate gate.
    Journal markers also catch erased row keys and detached/missing cash rows.
    The caller already holds the source-family cash locks. No extra Batch or
    nullable parent FOR UPDATE lock is acquired here.
    """
    sources = tuple(sources)
    batches = {source.batch_id for source in sources if source.source_type == FundingSourceType.BATCH_COLLECTION}
    ids = {source.pk for source in sources if source.source_type != FundingSourceType.BATCH_COLLECTION}
    for model, scope, journal_scope, prefixes, keys in (
        (SalePayment, Q(sale__batch_id__in=batches), Q(lines__batch_id__in=batches),
            ("sale-receipt:",), Q(idempotency_key__startswith="sale-initial:") | Q(idempotency_key__startswith="financial-receipt:")),
        (FundingReceipt, Q(funding_source_id__in=ids), Q(lines__funding_source_id__in=ids),
            ("financial-owner-receipt:", "financial-funding-receipt:"),
            Q(idempotency_key__startswith="financial-owner:") | Q(idempotency_key__startswith="financial-funding:"))):
        marker = Q()
        for prefix in prefixes:
            marker |= Q(idempotency_key__startswith=prefix)
        journals = list(JournalEntry.objects.filter(marker & journal_scope).order_by("pk").values_list(
            "source_identifier", flat=True).distinct()[:MAX_CASH_EVIDENCE + 1])
        if len(journals) > MAX_CASH_EVIDENCE or any(not identifier.isdecimal() for identifier in journals):
            _refuse()
        journal_ids = {int(identifier) for identifier in journals}
        related = ["sale"] if model is SalePayment else ["funding_source__owner"]
        rows = list(model.objects.filter((scope & keys) | Q(pk__in=journal_ids)).select_related(
            *related).order_by("pk")[:MAX_CASH_EVIDENCE + 1])
        if len(rows) > MAX_CASH_EVIDENCE or not journal_ids.issubset({row.pk for row in rows}):
            _refuse()
        for row in rows:
            if (model is SalePayment and row.sale.batch_id not in batches
                    or model is FundingReceipt and row.funding_source_id not in ids):
                _refuse()
            require_cash_receipt(row)
