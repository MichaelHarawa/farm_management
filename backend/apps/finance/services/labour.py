from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ..models import (
    AccountingNature,
    AdHocLabourPayment,
    Expenditure,
    ExpenditureCategory,
    ExpenditureOrigin,
    ExpenditurePaymentStatus,
    ExpenditureStatus,
    LabourWorkflowStatus,
)
from .expenditures import funded_total, record_expenditure_payment, reverse_expenditure
from .ledger import post_journal


@transaction.atomic
def approve_labour(*, labour_id: int, user) -> AdHocLabourPayment:
    labour = AdHocLabourPayment.objects.select_for_update().get(pk=labour_id)
    if labour.workflow_status != LabourWorkflowStatus.DRAFT:
        raise ValidationError({"detail": "Only draft labour can be approved."})
    labour.workflow_status = LabourWorkflowStatus.APPROVED
    labour.approved_by = user
    labour.approved_at = timezone.now()
    labour.save(update_fields=["workflow_status", "approved_by", "approved_at", "updated_at"])
    return labour


@transaction.atomic
def post_labour(*, labour_id: int, user) -> AdHocLabourPayment:
    # Lock only the labour row; nullable batch/period joins cannot be locked by PostgreSQL.
    labour = AdHocLabourPayment.objects.select_for_update().get(pk=labour_id)
    if labour.workflow_status != LabourWorkflowStatus.APPROVED:
        raise ValidationError({"detail": "Approve labour before posting it."})
    if labour.accounting_period and labour.accounting_period.status == "closed":
        raise ValidationError({"accounting_period": "Closed periods reject labour postings."})
    category, _ = ExpenditureCategory.objects.get_or_create(
        code="casual_labour",
        defaults={
            "name": "Casual labour",
            "default_accounting_nature": AccountingNature.DIRECT_COST,
            "display_order": 35,
        },
    )
    nature = (
        AccountingNature.DIRECT_COST
        if labour.batch_id or labour.cost_scope in {"batch_direct", "shared_production"}
        else AccountingNature.INDIRECT_OPERATING_EXPENSE
    )
    expenditure = Expenditure.objects.create(
        expenditure_date=labour.work_date,
        accounting_period=labour.accounting_period,
        amount=labour.payment_amount,
        category=category,
        accounting_nature=nature,
        description=f"Casual labour: {labour.task_description}",
        payee=labour.worker_name,
        status=ExpenditureStatus.POSTED,
        payment_status=ExpenditurePaymentStatus.UNPAID,
        origin=ExpenditureOrigin.FINANCE,
        beneficiary_type="one_poultry_batch" if labour.batch_id else "farm_cost_scope",
        beneficiary_detail=labour.batch.batch_id if labour.batch_id else labour.get_cost_scope_display(),
        idempotency_key=f"labour:{labour.pk}:posting",
        posted_by=user,
        posted_at=timezone.now(),
        created_by=user,
    )
    labour.expenditure = expenditure
    labour.workflow_status = LabourWorkflowStatus.POSTED
    labour.posted_at = timezone.now()
    labour.payment_status = "unpaid"
    labour.save(update_fields=["expenditure", "workflow_status", "posted_at", "payment_status", "updated_at"])
    post_journal(
        posting_date=labour.work_date,
        description=f"Casual labour payable: {labour.task_description}",
        source_model="finance.Expenditure",
        source_identifier=str(expenditure.pk),
        idempotency_key=f"expenditure:{expenditure.pk}",
        user=user,
        lines=[
            {"account": "5000" if labour.batch_id else "6100", "debit": labour.payment_amount, "batch_id": labour.batch_id},
            {"account": "2000", "credit": labour.payment_amount},
        ],
    )
    return labour


@transaction.atomic
def pay_labour(*, labour_id: int, funding_rows, payment_group_key: str, payment_date, user):
    labour = AdHocLabourPayment.objects.select_for_update().get(pk=labour_id)
    if labour.workflow_status not in {LabourWorkflowStatus.POSTED, LabourWorkflowStatus.PARTIALLY_PAID}:
        raise ValidationError({"detail": "Only posted labour payables can be paid."})
    record_expenditure_payment(
        expenditure_id=labour.expenditure_id,
        funding_rows=funding_rows,
        payment_group_key=payment_group_key,
        payment_date=payment_date,
        user=user,
    )
    labour.expenditure.refresh_from_db()
    paid = funded_total(labour.expenditure)
    labour.workflow_status = (
        LabourWorkflowStatus.PAID if paid >= labour.payment_amount else LabourWorkflowStatus.PARTIALLY_PAID
    )
    labour.payment_status = "paid" if paid >= labour.payment_amount else "partial"
    labour.payment_date = payment_date or timezone.localdate()
    labour.save(update_fields=["workflow_status", "payment_status", "payment_date", "updated_at"])
    return labour


@transaction.atomic
def reverse_labour(*, labour_id: int, reason: str, user):
    labour = AdHocLabourPayment.objects.select_for_update().get(pk=labour_id)
    if labour.workflow_status not in {
        LabourWorkflowStatus.POSTED,
        LabourWorkflowStatus.PARTIALLY_PAID,
        LabourWorkflowStatus.PAID,
    }:
        raise ValidationError({"detail": "Only posted labour can be reversed."})
    reverse_expenditure(expenditure_id=labour.expenditure_id, reason=reason, user=user)
    labour.workflow_status = LabourWorkflowStatus.REVERSED
    labour.payment_status = "reversed"
    labour.reversed_at = timezone.now()
    labour.reversed_by = user
    labour.reversal_reason = reason
    labour.save(update_fields=[
        "workflow_status", "payment_status", "reversed_at", "reversed_by", "reversal_reason", "updated_at"
    ])
    return labour
