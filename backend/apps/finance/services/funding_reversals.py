"""Unregistered, management-only loan correction foundation; no online API grant.

Append a dated source event and opposite journal, never edit the original receipt.
Only exact verified new-template evidence can be corrected. No legacy adoption.
"""
from datetime import date, datetime
from decimal import Decimal
import uuid

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import (FinancialCommandReceipt, FundingReceipt, FundingReceiptReversal,
    FundingReceiptStatus, FundingSource, FundingSourceType, JournalEntry, JournalStatus)
from ..permissions import FINANCE_MANAGEMENT_ROLES
from .action_audit import record_finance_action
from .financial_capture import _canonical, _currency, _identifier, _submission, _text
from .financial_values import business_date, lock_financial_periods
from .funding_capture import funding_source_version
from .funding_receipt_guards import MANAGED_PREFIX, funding_journal_reversal_boundary
from .ledger import reverse_journal
from .selling_cost_settlement import _dated_source_cash

ZERO = Decimal("0.00")


def funding_receipt_version(receipt):
    return checksum(_canonical({"basis": "phase6-funding-receipt-v1",
        "receipt": {field.attname: getattr(receipt, field.attname) for field in receipt._meta.concrete_fields},
        "source_binding": funding_source_version(receipt.funding_source)}))


def _verified_receipt(receipt):
    try:
        if not (receipt.idempotency_key or "").startswith(MANAGED_PREFIX):
            raise ValueError
        intent = uuid.UUID(receipt.idempotency_key[len(MANAGED_PREFIX):])
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"receipt": "Only original verified loan receipts can be corrected; historical evidence requires reconciliation."})
    anchor = FinancialCommandReceipt.objects.filter(pk=intent, command="finance.funding_receipt.record",
        completed_at__isnull=False, actor_id=receipt.created_by_id).first()
    if anchor is None:
        raise ValidationError({"receipt": "Original permanent receipt evidence is missing; review is required."})
    result = anchor.result
    fields = {"currency", "funding_source_id", "source_version", "amount", "receipt_date", "counterparty",
        "payment_method", "reference", "notes", "source_type", "receipt_id", "journal_id"}
    source = receipt.funding_source
    if (not isinstance(result, dict) or set(result) != fields or result["receipt_id"] != str(receipt.pk)
            or result["currency"] != "MWK" or result["amount"] != str(receipt.amount)
            or result["receipt_date"] != _canonical(receipt.receipt_date)
            or result["reference"] != receipt.reference or result["notes"] != receipt.notes
            or result["funding_source_id"] != str(receipt.funding_source_id)
            or result["source_version"] != funding_source_version(source)
            or result["source_type"] != FundingSourceType.LOAN or source.source_type != FundingSourceType.LOAN
            or source.batch_id is not None or source.owner_id is not None
            or receipt.status != FundingReceiptStatus.POSTED):
        raise ValidationError({"receipt": "Original source/economic evidence changed; controlled review is required."})
    payload = {key: value for key, value in result.items() if key not in {"receipt_id", "journal_id"}}
    request = {key: value for key, value in payload.items() if key != "source_type"}
    if (checksum(payload) != receipt.request_fingerprint or anchor.request_hash != checksum({
            "actor": str(anchor.actor_id), "command": anchor.command, "payload": request})):
        raise ValidationError({"receipt": "Original hashes do not match; controlled review is required."})
    journal_id = _identifier(result["journal_id"], "journal_id")
    # Checking the absent reverse one-to-one introduces an outer join. Lock
    # only the verified journal row, not PostgreSQL's nullable joined side.
    journal = JournalEntry.objects.select_for_update(of=("self",)).filter(pk=journal_id,
        source_model="finance.FundingReceipt", source_identifier=str(receipt.pk),
        idempotency_key=f"financial-funding-receipt:{receipt.pk}", status=JournalStatus.POSTED,
        posting_date=business_date(receipt.receipt_date), reversal_of__isnull=True,
        reversal_entry__isnull=True).first()
    if journal is None:
        raise ValidationError({"journal": "Original unreversed loan journal is missing; review is required."})
    lines = [(line.account.code, line.debit, line.credit, line.batch_id, line.funding_source_id)
        for line in journal.lines.select_related("account")]
    expected = [("1000", receipt.amount, ZERO, None, receipt.funding_source_id),
                ("2200", ZERO, receipt.amount, None, receipt.funding_source_id)]
    if len(lines) != 2 or set(lines) != set(expected):
        raise ValidationError({"journal": "Original full cash/loan journal differs; review is required."})
    return journal


def reverse_financial_funding_receipt(*, submission_id, user, currency, receipt_id,
        source_version, reversal_date, reason):
    if not getattr(settings, "FINANCE_FUNDING_REVERSALS", False):
        raise ValidationError({"capability_unavailable": "Controlled funding reversal is not enabled on this migrated deployment."})
    _currency(currency)
    receipt_id = _identifier(receipt_id, "receipt_id")
    if not isinstance(reversal_date, date) or isinstance(reversal_date, datetime) or reversal_date > timezone.localdate():
        raise ValidationError({"reversal_date": "Record an actual explicit accounting date, not a future date or instant."})
    reason = _text(reason, "reason", 2000)
    if not reason:
        raise ValidationError({"reason": "A specific correction reason is required."})
    if not isinstance(source_version, str) or len(source_version) != 64 or any(char not in "0123456789abcdef" for char in source_version):
        raise ValidationError({"source_version": "An exact confirmed original-receipt version is required."})

    def effect(actor):
        lock_financial_periods(reversal_date)
        candidate = FundingReceipt.objects.filter(pk=receipt_id).first()
        if candidate is None:
            raise ValidationError({"receipt": "Select the original received-funding record."})
        source = FundingSource.objects.select_for_update().get(pk=candidate.funding_source_id)
        receipt = FundingReceipt.objects.select_for_update().get(pk=receipt_id)
        if receipt.funding_source_id != source.pk:
            raise ValidationError({"receipt": "Receipt source binding changed; review is required."})
        receipt.funding_source = source
        if (source_version != funding_receipt_version(receipt)
                or reversal_date < business_date(receipt.receipt_date)):
            raise ValidationError({"source_version": "Original receipt changed or reversal precedes receipt; retain evidence for review."})
        if FundingReceiptReversal.objects.filter(receipt=receipt).exists():
            raise ValidationError({"already_reversed": "This receipt already has its original controlled reversal. Recover that operation; do not create another."})
        journal = _verified_receipt(receipt)
        # Inactive sources may still need correction. This is not permission to
        # spend them. Future income cannot fund a backdated reversal, and all
        # committed later cash uses/reversals remain reserved conservatively.
        if _dated_source_cash(source, reversal_date) < receipt.amount:
            raise ValidationError({"insufficient_cash": "This receipt's full cash is no longer available on the correction date; retain original evidence for controlled review."})
        with funding_journal_reversal_boundary(journal.pk):
            opposite = reverse_journal(journal, posting_date=reversal_date, reason=reason, user=actor)
            reversal = FundingReceiptReversal.objects.create(receipt=receipt, funding_source=source,
                original_journal=journal, reversal_journal=opposite, submission_id=submission_id,
                source_version=source_version, amount=receipt.amount, reversal_date=reversal_date,
                reason=reason, created_by=actor)
        result = _canonical({"receipt_id": str(receipt.pk), "reversal_id": str(reversal.pk),
            "original_journal_id": str(journal.pk), "reversal_journal_id": str(opposite.pk),
            "funding_source_id": str(source.pk), "source_version": source_version,
            "amount": receipt.amount, "reversal_date": reversal_date, "reason": reason})
        record_finance_action(actor=actor, action="funding_receipt_reversed", entity_type="finance.FundingReceiptReversal",
            entity_id=reversal.pk, after_data={**result, "submission_id": str(submission_id)})
        return result

    result, created = _submission(submission_id=submission_id, command="finance.funding_receipt.reverse", user=user,
        payload=dict(currency=currency, receipt_id=str(receipt_id), source_version=source_version,
            reversal_date=reversal_date, reason=reason), roles=FINANCE_MANAGEMENT_ROLES, effect=effect)
    return FundingReceiptReversal.objects.get(pk=result["reversal_id"]), created
