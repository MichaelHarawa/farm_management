"""Explicit non-owner funding templates, deliberately not registered/published.

The existing chart/report policy supports loans (1000/2200). Grant/other-income
recognition and general-cash opening/transfer policy are not inferred from enums.
"""
from datetime import datetime, timedelta
import hashlib

from django.conf import settings
from django.db import connection
from django.db.models import Q, Value
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import FundingReceipt, FundingSource, FundingSourceType, JournalEntry
from ..permissions import FINANCE_WRITE_ROLES
from .action_audit import record_finance_action
from .financial_capture import _canonical, _currency, _identifier, _submission, _text
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .funding_receipt_guards import MANAGED_PREFIX, funding_posting_boundary
from .ledger import post_journal


def funding_source_version(source):
    """Economic binding only; activity is independently checked on new effects."""
    return checksum({"basis": "phase6-funding-source-v1", "id": str(source.pk),
        "source_type": source.source_type, "batch_id": str(source.batch_id) if source.batch_id else None,
        "owner_id": str(source.owner_id) if source.owner_id else None})


def lock_funding_reference(reference):
    """Incoming cash evidence shares a normalized, cross-source intent mutex."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT lower(trim(%s::text))", [reference])
        normalized = cursor.fetchone()[0]
        key = int.from_bytes(hashlib.sha256(
            ("farm-funding-reference-v1:" + normalized).encode()).digest()[:8], "big", signed=True)
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
    return normalized


def record_financial_funding_receipt(*, submission_id, user, currency, funding_source_id,
        source_version, amount, receipt_date, counterparty, payment_method, reference, notes=""):
    if not getattr(settings, "FINANCE_FUNDING_RECEIPTS", False):
        raise ValidationError({"capability_unavailable": "Financial funding capture is not enabled on this deployment."})
    _currency(currency)
    funding_source_id = _identifier(funding_source_id, "funding_source_id")
    amount = exact_decimal(amount, positive=True)
    if not isinstance(receipt_date, datetime) or timezone.is_naive(receipt_date) or receipt_date > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"receipt_date": "Record an actual timezone-aware receipt instant, not a future date."})
    receipt_date = receipt_date.astimezone(timezone.get_default_timezone())
    counterparty = _text(counterparty, "counterparty", 200)
    reference = _text(reference, "reference", 120)
    notes = _text(notes, "notes", 4000)
    if not counterparty or not reference:
        raise ValidationError({"evidence": "Record the lender and its actual receipt/transaction reference; never invent a reference."})
    if not isinstance(payment_method, str) or payment_method not in {"cash", "mobile_money", "bank_transfer"}:
        raise ValidationError({"payment_method": "Record cash, mobile money or bank transfer, not credit or a cash promise."})
    if not isinstance(source_version, str) or len(source_version) != 64 or any(char not in "0123456789abcdef" for char in source_version):
        raise ValidationError({"source_version": "An exact confirmed funding-source version is required."})
    payload = dict(currency=currency, funding_source_id=str(funding_source_id), source_version=source_version,
        amount=amount, receipt_date=receipt_date, counterparty=counterparty, payment_method=payment_method,
        reference=reference, notes=notes)

    def effect(actor):
        # Serialize reference checks across sources AND accounting periods. This
        # is an intent mutex (not a row lock), before period/source locks. The DB
        # normalizes Unicode identically to the duplicate query below.
        normalized_reference = lock_funding_reference(reference)
        if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
            from ..models import SaleCostPaymentReversal
            if SaleCostPaymentReversal.objects.annotate(normalized_reference=Lower(Trim("external_reference"))).filter(
                    normalized_reference=normalized_reference).exists():
                raise ValidationError({"possible_duplicate": "That incoming-cash reference already identifies a sale-cost refund; retain evidence for review."})
        lock_financial_periods(receipt_date)
        source = FundingSource.objects.select_for_update().filter(pk=funding_source_id).first()
        if source is None or not source.is_active:
            raise ValidationError({"funding_source": "Select a current active funding source."})
        if source_version != funding_source_version(source):
            raise ValidationError({"source_version": "Funding-source binding changed; retain the evidence for review."})
        if source.source_type != FundingSourceType.LOAN or source.owner_id is not None or source.batch_id is not None:
            raise ValidationError({"capability_unavailable": "Only explicit non-owner, non-batch loan receipts have a verified posting template. Other funding types require policy review."})
        # Old and new receipts both reserve supported source-scoped references.
        # PostgreSQL applies the SAME trim/lower normalization to both operands.
        # Reversed references remain reserved; a new UUID cannot undo deduplication.
        if FundingReceipt.objects.filter(funding_source=source).annotate(
                normalized_reference=Lower(Trim("reference"))).filter(normalized_reference=Lower(Value(reference))).exists():
            raise ValidationError({"duplicate_reference": "This funding source already has that receipt reference. Recover the original submission or request review; no new cash was posted."})
        # Identical evidence on another source may be a source-alias mistake, not
        # proof of a duplicate. Refuse automatic posting, never return fake replay.
        if FundingReceipt.objects.filter(amount=amount, receipt_date=receipt_date).exclude(funding_source=source).annotate(
                normalized_reference=Lower(Trim("reference"))).filter(normalized_reference=Lower(Value(reference))).exists():
            raise ValidationError({"possible_duplicate": "Matching receipt evidence exists on another source; retain this evidence for authorized review."})
        if FundingReceipt.objects.filter(funding_source=source).exclude(idempotency_key__startswith=MANAGED_PREFIX).exists():
            raise ValidationError({"source_review_required": "This source has legacy receipt evidence without the verified template. Reconcile it explicitly; no automatic adoption or backfill."})
        receipt_payload = {**payload, "source_type": source.source_type}
        with funding_posting_boundary():
            receipt = FundingReceipt.objects.create(funding_source=source, amount=amount, receipt_date=receipt_date,
                reference=reference, notes=notes, created_by=actor,
                idempotency_key=f"{MANAGED_PREFIX}{submission_id}", request_fingerprint=checksum(_canonical(receipt_payload)))
        journal = post_journal(posting_date=business_date(receipt_date), description="Loan funding received",
            source_model="finance.FundingReceipt", source_identifier=receipt.pk,
            idempotency_key=f"financial-funding-receipt:{receipt.pk}", user=actor,
            lines=[{"account": "1000", "debit": amount, "funding_source_id": source.pk},
                   {"account": "2200", "credit": amount, "funding_source_id": source.pk}])
        result = _canonical({**receipt_payload, "receipt_id": str(receipt.pk), "journal_id": str(journal.pk)})
        record_finance_action(actor=actor, action="funding_receipt_recorded", entity_type="finance.FundingReceipt",
            entity_id=receipt.pk, after_data={**result, "submission_id": str(submission_id)})
        return result

    result, created = _submission(submission_id=submission_id, command="finance.funding_receipt.record", user=user,
        payload=payload, roles=FINANCE_WRITE_ROLES, effect=effect)
    return FundingReceipt.objects.get(pk=result["receipt_id"]), created


def is_managed_funding_journal(entry_id):
    """A GL-only reversal would leave spendable source cash unchanged."""
    # Also protect the opposite journal: reversing only it would restore the GL
    # without restoring source cash. No new table is queried on old deployments.
    return JournalEntry.objects.filter(pk=entry_id).filter(
        Q(source_model="finance.FundingReceipt", idempotency_key__startswith="financial-funding-receipt:")
        | Q(reversal_of__source_model="finance.FundingReceipt",
            reversal_of__idempotency_key__startswith="financial-funding-receipt:")).exists()
