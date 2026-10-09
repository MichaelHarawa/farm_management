"""Unregistered versioned non-stock draft edits and atomic posting foundations.

No financial sync API, legacy draft adoption, implicit redating or client journal.
All source fields (including original IDs/reference/time) bind the opaque version.
"""
import re

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from apps.poultry.models import Batch, BatchStatus
from ..models import (AccountingNature, Expenditure, ExpenditureCategory, ExpenditureOrigin,
    ExpenditurePaymentStatus, ExpenditureStatus, FinancialCommandReceipt, JournalEntry)
from ..permissions import FINANCE_WRITE_ROLES
from .action_audit import record_finance_action
from .expenditures import validate_cost_allocations
from .financial_capture import (_canonical, _cost_rows, _currency, _fields, _funding_rows,
    _identifier, _post_expenditure_effect, _submission, _text)
from .financial_values import business_date, exact_decimal, lock_financial_periods


EDITABLE = frozenset({"expenditure_date", "amount", "category_id", "accounting_nature",
    "description", "payee", "external_reference", "notes", "cost_allocations"})


def expenditure_draft_version(expenditure):
    """Pure version token, not authorization or a serialized financial payload."""
    return checksum({"contract": "phase6-expense-draft-v1", "source": _canonical({
        field.attname: getattr(expenditure, field.attname) for field in expenditure._meta.concrete_fields})})


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValidationError({"expected_version": "Retain the exact verified original draft version."})
    return value


def _changes(value):
    """Validate capture types before hashing; no NaN/float/arbitrary JSON money."""
    _fields(value, EDITABLE, "changes")
    normalized = dict(value)
    if "amount" in value:
        normalized["amount"] = exact_decimal(value["amount"], positive=True)
    if "category_id" in value:
        normalized["category_id"] = _identifier(value["category_id"], "category_id")
    if "expenditure_date" in value:
        normalized["expenditure_date"] = business_date(value["expenditure_date"], field="expenditure_date")
    if "cost_allocations" in value:
        normalized["cost_allocations"] = _cost_rows(value["cost_allocations"])
    if "accounting_nature" in value and value["accounting_nature"] not in {
            AccountingNature.DIRECT_COST, AccountingNature.INDIRECT_OPERATING_EXPENSE}:
        raise ValidationError({"accounting_nature": "Select a supported non-stock expense nature."})
    for field, limit in [("description", 255), ("payee", 160), ("external_reference", 120), ("notes", 4000)]:
        if field in value:
            normalized[field] = _text(value[field], field, limit)
    return normalized


def _details(expenditure, changes):
    changes = _changes(changes)
    day = business_date(changes.get("expenditure_date", expenditure.expenditure_date), field="expenditure_date")
    if day > timezone.localdate():
        raise ValidationError({"expenditure_date": "Record the actual expense date, not a future event."})
    nature = changes.get("accounting_nature", expenditure.accounting_nature)
    if nature not in {AccountingNature.DIRECT_COST, AccountingNature.INDIRECT_OPERATING_EXPENSE}:
        raise ValidationError({"accounting_nature": "Only verified non-stock direct/service or administration drafts are supported."})
    costs = _cost_rows(changes.get("cost_allocations", expenditure.cost_allocation_plan))
    if (nature == AccountingNature.DIRECT_COST and not costs) or (nature == AccountingNature.INDIRECT_OPERATING_EXPENSE and costs):
        raise ValidationError({"cost_allocations": "Direct cost requires explicit beneficiaries; administration must not have batch costs."})
    details = {"expenditure_date": day,
        "amount": exact_decimal(changes.get("amount", expenditure.amount), positive=True),
        "category_id": _identifier(changes.get("category_id", expenditure.category_id), "category_id"),
        "accounting_nature": nature, "cost_allocation_plan": _canonical(costs),
        "beneficiary_type": "multiple_poultry_batches" if len(costs) > 1 else "one_poultry_batch" if costs else "general_admin"}
    for field, limit in [("description", 255), ("payee", 160), ("external_reference", 120), ("notes", 4000)]:
        details[field] = _text(changes.get(field, getattr(expenditure, field)), field, limit)
    if not details["description"]:
        raise ValidationError({"description": "Record the actual expense description."})
    return details, costs


def _locked_draft(expenditure_id, expected_version, changes, payment_date=None):
    observed = Expenditure.objects.filter(pk=expenditure_id).first()
    if observed is None:
        raise ValidationError({"expenditure": "Select the original verified draft."})
    # Observe inputs first, lock periods -> sorted beneficiaries -> source, then
    # compare the entire source. A concurrent edit cannot slip through or move a
    # write into an unheld period; a changed source is refused before any write.
    details, costs = _details(observed, changes)
    periods = lock_financial_periods(observed.expenditure_date, details["expenditure_date"],
        *([payment_date] if payment_date is not None else []))
    batch_ids = {row["batch"] for row in costs + _cost_rows(observed.cost_allocation_plan)}
    batches = list(Batch.objects.select_for_update().filter(pk__in=batch_ids).order_by("pk"))
    expenditure = Expenditure.objects.select_for_update().get(pk=expenditure_id)
    actual_version = expenditure_draft_version(expenditure)
    if actual_version != expected_version:
        raise ValidationError({"revision_conflict": "The original draft changed; retain the proposal and review the current authorized version."})
    creation = FinancialCommandReceipt.objects.filter(command="finance.expenditure.create",
        completed_at__isnull=False, result__expenditure_id=str(expenditure_id), result__journal_id=None,
        result__has_key="draft_version").first()
    lineage = FinancialCommandReceipt.objects.filter(command__in=["finance.expenditure.create", "finance.expenditure.update"],
        completed_at__isnull=False, result__expenditure_id=str(expenditure_id), result__draft_version=actual_version).exists()
    if (creation is None or not lineage or expenditure.idempotency_key != f"financial-expense:{creation.pk}"
            or expenditure.created_by_id != creation.actor_id or expenditure.origin != ExpenditureOrigin.FINANCE):
        raise ValidationError({"legacy_reconciliation": "Only versioned Phase6 drafts with their unchanged accepted lineage are supported; do not adopt historical/externally edited drafts."})
    if (expenditure.status != ExpenditureStatus.DRAFT or expenditure.payment_status != ExpenditurePaymentStatus.UNPAID
            or expenditure.posted_at or expenditure.posted_by_id or expenditure.reversed_expenditure_id
            or expenditure.reversed_at or expenditure.reversed_by_id or expenditure.reversal_reason
            or expenditure.cost_allocations.exists() or expenditure.funding_allocations.exists()
            or JournalEntry.objects.filter(source_model="finance.Expenditure", source_identifier=str(expenditure_id)).exists()):
        raise ValidationError({"expenditure": "Only an unposted, unfunded original draft can be edited or posted; preserve existing effects for controlled review."})
    if len(batches) != len(batch_ids):
        raise ValidationError({"cost_allocations": "A selected original beneficiary no longer exists."})
    for batch in batches:
        if batch.pk in {row["batch"] for row in costs} and (
                batch.closed_at or batch.status == BatchStatus.CLOSED or batch.profitability_finalized_at
                or batch.profitability_snapshots.filter(final=True).exists()):
            raise ValidationError({"cost_allocations": "Closed/finalized batch costs require a separate controlled correction."})
    category = ExpenditureCategory.objects.select_for_update().filter(pk=details["category_id"], is_active=True).first()
    if category is None or category.requires_item_details:
        raise ValidationError({"category": "Select an active non-stock service category; itemized purchases require the inventory template."})
    if category.requires_batch_beneficiary and not costs:
        raise ValidationError({"cost_allocations": "This category requires explicit beneficiary batches."})
    # Validate a candidate without altering the original object/DB on rejection.
    for field, value in details.items():
        setattr(expenditure, field, value)
    expenditure.accounting_period = periods[details["expenditure_date"]]
    expenditure.full_clean()
    if costs:
        validate_cost_allocations(expenditure, costs)
    return expenditure, costs


def update_financial_expenditure_draft(*, submission_id, user, currency, expenditure_id,
                                     expected_version, changes, reason):
    _currency(currency)
    expenditure_id = _identifier(expenditure_id, "expenditure_id")
    expected_version = _version(expected_version)
    changes = _changes(changes)
    if not changes:
        raise ValidationError({"changes": "Select explicit draft changes."})
    reason = _text(reason, "reason", 4000)
    if not reason:
        raise ValidationError({"reason": "Record why this original draft is being changed."})

    def effect(actor):
        expenditure, _ = _locked_draft(expenditure_id, expected_version, changes)
        expenditure.save()
        version = expenditure_draft_version(expenditure)
        record_finance_action(actor=actor, action="financial_draft_updated", entity_type="finance.Expenditure",
            entity_id=expenditure.pk, reason=reason, before_data={"draft_version": expected_version},
            after_data={"draft_version": version, "changes": _canonical(changes), "submission_id": str(submission_id)})
        return {"expenditure_id": str(expenditure.pk), "draft_version": version, "journal_id": None}

    result, created = _submission(submission_id=submission_id, command="finance.expenditure.update", user=user,
        payload=dict(currency=currency, expenditure_id=str(expenditure_id), expected_version=expected_version,
            changes=changes, reason=reason), roles=FINANCE_WRITE_ROLES, effect=effect)
    return Expenditure.objects.get(pk=result["expenditure_id"]), created


def post_financial_expenditure_draft(*, submission_id, user, currency, expenditure_id,
                                   expected_version, funding_allocations=None, payment_date=None):
    _currency(currency)
    expenditure_id = _identifier(expenditure_id, "expenditure_id")
    expected_version = _version(expected_version)
    funding = _funding_rows(funding_allocations)
    if bool(funding) != (payment_date is not None):
        raise ValidationError({"payment_date": "Payment requires explicit funding splits and its actual date; an unpaid posting has neither."})
    payment_date = business_date(payment_date, field="payment_date") if payment_date is not None else None

    def effect(actor):
        expenditure, costs = _locked_draft(expenditure_id, expected_version, {}, payment_date)
        journal = _post_expenditure_effect(expenditure=expenditure, actor=actor, costs=costs,
            funding_allocations=funding, payment_date=payment_date, submission_id=submission_id)
        record_finance_action(actor=actor, action="financial_draft_posted", entity_type="finance.Expenditure",
            entity_id=expenditure.pk, before_data={"draft_version": expected_version},
            after_data={"journal_id": str(journal.pk), "submission_id": str(submission_id)})
        return {"expenditure_id": str(expenditure.pk), "journal_id": str(journal.pk), "posted_draft_version": expected_version}

    result, created = _submission(submission_id=submission_id, command="finance.expenditure.post", user=user,
        payload=dict(currency=currency, expenditure_id=str(expenditure_id), expected_version=expected_version,
            funding_allocations=funding, payment_date=payment_date), roles=FINANCE_WRITE_ROLES, effect=effect)
    return Expenditure.objects.get(pk=result["expenditure_id"]), created
