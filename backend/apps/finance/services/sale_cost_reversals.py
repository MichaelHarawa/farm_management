"""Unregistered full-payment refund foundation, not a mobile upload capability.

An actual refund returns each original split to its original cash source and
reopens the payable. It does not cancel the original selling expense. Earlier
receipts lacking complete accepted payment evidence are never adopted.
"""
from datetime import date, datetime
from decimal import Decimal
import uuid

from django.conf import settings
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from apps.poultry.models import Batch, PaymentStatus, Sales, SaleSellingCost
from ..models import (FinancialCommandReceipt, FundingClassification, FundingReceipt, FundingSource,
    FundingSourceType, JournalEntry, JournalStatus, SaleCostPayment, SaleCostPaymentReversal)
from ..permissions import FINANCE_MANAGEMENT_ROLES
from .action_audit import record_finance_action
from .financial_capture import _canonical, _currency, _identifier, _submission, _text
from .financial_values import lock_financial_periods
from .funding_capture import lock_funding_reference
from .ledger import reverse_journal
from .sale_cost_reversal_guards import sale_cost_reversal_boundary
from .selling_cost_settlement import _verified_liability, sale_cost_payment_version

ZERO = Decimal("0.00")


def sale_cost_payment_group_version(anchor, payments):
    return checksum(_canonical({"basis": "phase6-sale-cost-payment-group-v1", "submission_id": anchor.pk,
        "actor_id": anchor.actor_id, "request_hash": anchor.request_hash, "result": anchor.result,
        "payments": [sale_cost_payment_version(row) for row in payments]}))


def _review():
    raise ValidationError({"original_payment": "Complete original payment/request/source/journal evidence does not match; controlled review is required. No historical adoption."})


def _verified_group(anchor, payments, cost):
    result = anchor.result
    keys = {"selling_cost_id", "payment_ids", "journal_ids", "source_version", "original_request", "payment_versions"}
    if not isinstance(result, dict) or set(result) != keys or not payments or len(payments) > 50:
        _review()
    request = result["original_request"]
    request_keys = {"currency", "selling_cost_id", "payment_date", "funding_allocations", "payee",
        "payment_method", "external_reference", "notes"}
    if (not isinstance(request, dict) or set(request) != request_keys or request["currency"] != "MWK"
            or request["selling_cost_id"] != str(cost.pk) or result["selling_cost_id"] != str(cost.pk)
            or anchor.request_hash != checksum({"actor": str(anchor.actor_id), "command": anchor.command, "payload": request})
            or result["payment_ids"] != [str(row.pk) for row in payments]
            or result["payment_versions"] != [sale_cost_payment_version(row) for row in payments]
            or not isinstance(result["journal_ids"], list) or len(result["journal_ids"]) != len(payments)
            or not all(isinstance(pk, str) for pk in result["journal_ids"])
            or len(set(result["journal_ids"])) != len(payments)
            or not isinstance(request["funding_allocations"], list) or len(request["funding_allocations"]) != len(payments)):
        _review()
    liability, version = _verified_liability(cost)
    if result["source_version"] != version:
        _review()
    journals = []
    for index, payment in enumerate(payments):
        row = request["funding_allocations"][index]
        if (not isinstance(row, dict) or not {"funding_source", "amount"} <= set(row)
                or set(row) - {"funding_source", "amount", "classification"}
                or str(row["funding_source"]) != str(payment.funding_source_id) or row["amount"] != str(payment.amount)
                or (row.get("classification") or FundingClassification.REINVESTMENT) != payment.classification
                or payment.classification not in (FundingClassification.REINVESTMENT,
                    FundingClassification.WORKING_CAPITAL, FundingClassification.COST_RECOVERY)
                or payment.split_index != index or payment.created_by_id != anchor.actor_id
                or payment.selling_cost_id != cost.pk or payment.payable_journal_id != liability.pk
                or payment.source_version != version
                or payment.funding_source.source_type == FundingSourceType.OWNER_CAPITAL
                or payment.payment_method != request["payment_method"] or payment.payee != request["payee"]
                or payment.external_reference != request["external_reference"] or payment.notes != request["notes"]
                or payment.payment_date.isoformat() != request["payment_date"]):
            _review()
        journal_id = _identifier(result["journal_ids"][index], "original_journal_id")
        journal = JournalEntry.objects.select_for_update(of=("self",)).filter(pk=journal_id,
            status=JournalStatus.POSTED, source_model="finance.SaleCostPayment", source_identifier=str(payment.pk),
            idempotency_key=f"sale-cost-payment:{payment.pk}", posting_date=payment.payment_date,
            reversal_of__isnull=True, reversal_entry__isnull=True).first()
        if journal is None:
            _review()
        actual = [(line.account.code, line.debit, line.credit, line.batch_id, line.funding_source_id)
            for line in journal.lines.select_related("account")]
        expected = [("2000", payment.amount, ZERO, cost.sale.batch_id, payment.funding_source_id),
                    ("1000", ZERO, payment.amount, None, payment.funding_source_id)]
        if len(actual) != 2 or set(actual) != set(expected):
            _review()
        journals.append(journal)
    return journals


def refund_sale_cost_payment(*, submission_id, user, currency, original_submission_id, source_version,
        refund_date, refund_method, external_reference, reason):
    if not getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
        raise ValidationError({"capability_unavailable": "Sale-cost refunds require their migrated isolated deployment gate."})
    _currency(currency)
    try:
        original_submission_id = uuid.UUID(str(original_submission_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"original_submission_id": "Select the exact original payment submission."})
    if (not isinstance(refund_date, date) or isinstance(refund_date, datetime)
            or refund_date > timezone.localdate()):
        raise ValidationError({"refund_date": "Record an actual explicit refund date, not a future date or instant."})
    if not isinstance(refund_method, str) or refund_method not in {"cash", "mobile_money", "bank_transfer"}:
        raise ValidationError({"refund_method": "Record the actual cash refund method, not credit or a promise."})
    external_reference = _text(external_reference, "external_reference", 120)
    reason = _text(reason, "reason", 2000)
    if not external_reference or not reason:
        raise ValidationError({"evidence": "Record the actual refund transaction reference and specific reason; do not invent evidence."})
    if not isinstance(source_version, str) or len(source_version) != 64 or any(char not in "0123456789abcdef" for char in source_version):
        raise ValidationError({"source_version": "An exact confirmed original payment-group version is required."})

    def effect(actor):
        normalized_reference = lock_funding_reference(external_reference)
        lock_financial_periods(refund_date)
        anchor = FinancialCommandReceipt.objects.filter(pk=original_submission_id,
            command="finance.sale_cost.pay", completed_at__isnull=False).first()
        candidates = list(SaleCostPayment.objects.filter(submission_id=original_submission_id).order_by("split_index"))
        if anchor is None or not candidates or len(candidates) > 50:
            _review()
        if SaleCostPaymentReversal.objects.filter(payment__in=candidates).exists():
            raise ValidationError({"already_refunded": "This payment already has a source-linked refund. Recover that original operation; do not create another."})
        sources = list(FundingSource.objects.filter(pk__in=[row.funding_source_id for row in candidates]))
        source_bindings = {row.pk: (row.source_type, row.batch_id, row.owner_id) for row in sources}
        candidate_cost = SaleSellingCost.objects.filter(pk=candidates[0].selling_cost_id).select_related("sale").first()
        if candidate_cost is None:
            _review()
        batches = {candidate_cost.sale.batch_id} | {row.batch_id for row in sources if row.batch_id}
        list(Batch.objects.select_for_update().filter(pk__in=batches).order_by("pk"))
        sale = Sales.objects.select_for_update().get(pk=candidate_cost.sale_id)
        cost = SaleSellingCost.objects.select_for_update().get(pk=candidate_cost.pk)
        if (cost.sale_id != candidate_cost.sale_id or sale.batch_id != candidate_cost.sale.batch_id
                or sale.payment_status == PaymentStatus.CANCELLED):
            _review()
        cost.sale = sale
        aliases = FundingSource.objects.filter(source_type=FundingSourceType.BATCH_COLLECTION,
            batch_id__in=batches).values_list("pk", flat=True)
        locked_sources = {row.pk: row for row in FundingSource.objects.select_for_update().filter(
            pk__in=set(source_bindings) | set(aliases)).order_by("pk")}
        for pk, binding in source_bindings.items():
            row = locked_sources.get(pk)
            if row is None or binding != (row.source_type, row.batch_id, row.owner_id):
                _review()
        payments = list(SaleCostPayment.objects.select_for_update().filter(
            submission_id=original_submission_id).order_by("split_index"))
        if [row.pk for row in payments] != [row.pk for row in candidates]:
            _review()
        for payment in payments:
            payment.funding_source = locked_sources[payment.funding_source_id]
        if source_version != sale_cost_payment_group_version(anchor, payments):
            _review()
        if SaleCostPaymentReversal.objects.filter(payment__in=payments).exists():
            raise ValidationError({"already_refunded": "The original payment was refunded while this request waited. Recover its original operation."})
        if any(refund_date < row.payment_date for row in payments):
            raise ValidationError({"refund_date": "A refund cannot precede the original actual payment."})
        journals = _verified_group(anchor, payments, cost)
        if (SaleCostPaymentReversal.objects.annotate(ref=Lower(Trim("external_reference"))).filter(ref=normalized_reference).exists()
                or FundingReceipt.objects.annotate(ref=Lower(Trim("reference"))).filter(ref=normalized_reference).exists()):
            raise ValidationError({"possible_duplicate": "That incoming-cash reference is already recorded. Retain evidence for review; no new cash posted."})
        refund_ids, opposite_ids = [], []
        for payment, journal in zip(payments, journals):
            with sale_cost_reversal_boundary(journal.pk):
                opposite = reverse_journal(journal, posting_date=refund_date, reason=reason, user=actor)
                refund = SaleCostPaymentReversal.objects.create(payment=payment, funding_source=payment.funding_source,
                    original_journal=journal, reversal_journal=opposite, submission_id=submission_id,
                    split_index=payment.split_index, source_version=source_version, amount=payment.amount,
                    refund_date=refund_date, refund_method=refund_method, external_reference=external_reference,
                    reason=reason, created_by=actor)
            refund_ids.append(str(refund.pk))
            opposite_ids.append(str(opposite.pk))
        result = _canonical({"original_submission_id": str(original_submission_id), "selling_cost_id": str(cost.pk),
            "payment_ids": [str(row.pk) for row in payments], "refund_ids": refund_ids,
            "original_journal_ids": [str(row.pk) for row in journals], "reversal_journal_ids": opposite_ids,
            "source_version": source_version, "amount": sum((row.amount for row in payments), ZERO),
            "refund_date": refund_date, "refund_method": refund_method, "external_reference": external_reference, "reason": reason})
        record_finance_action(actor=actor, action="sale_selling_cost_payment_refunded", entity_type="poultry.SaleSellingCost",
            entity_id=cost.pk, after_data={**result, "submission_id": str(submission_id)})
        return result

    result, created = _submission(submission_id=submission_id, command="finance.sale_cost.refund", user=user,
        payload=dict(currency=currency, original_submission_id=str(original_submission_id), source_version=source_version,
            refund_date=refund_date, refund_method=refund_method, external_reference=external_reference, reason=reason),
        roles=FINANCE_MANAGEMENT_ROLES, effect=effect)
    return list(SaleCostPaymentReversal.objects.filter(pk__in=result["refund_ids"]).order_by("split_index")), created
