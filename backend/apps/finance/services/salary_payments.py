from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch

from ..models import (
    AccountingNature,
    AllocationMethod,
    AllocationSourceType,
    CostAllocation,
    Expenditure,
    ExpenditureCategory,
    ExpenditureOrigin,
    ExpenditurePaymentStatus,
    ExpenditureStatus,
    FinancePaymentStatus,
    FundingSource,
    PayrollEntry,
    PayrollLiability,
    PayrollPayment,
    PayrollPaymentFunding,
    PayrollPaymentStatus,
)
from .profitability import available_funding_source_cash


ZERO = Decimal("0.00")


def money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({"amount": "Enter a valid monetary amount."})


def ensure_salary_expense(entry: PayrollEntry, *, user=None) -> Expenditure:
    if entry.expenditure_id:
        if entry.expenditure.amount != entry.total_employer_cost:
            entry.expenditure.amount = entry.total_employer_cost
            entry.expenditure.save(update_fields=["amount", "updated_at"])
        return entry.expenditure
    category = ExpenditureCategory.objects.filter(name="Salaries and wages").first()
    if category is None:
        category, _ = ExpenditureCategory.objects.get_or_create(
            code="salaries",
            defaults={
                "name": "Salaries and wages",
                "default_accounting_nature": AccountingNature.INDIRECT_OPERATING_EXPENSE,
                "display_order": 25,
            },
        )
    expenditure = Expenditure.objects.create(
        expenditure_date=entry.accounting_period.period_end,
        accounting_period=entry.accounting_period,
        amount=entry.total_employer_cost,
        category=category,
        accounting_nature=AccountingNature.INDIRECT_OPERATING_EXPENSE,
        description=f"Payroll cost: {entry.employee} ({entry.accounting_period})",
        status=ExpenditureStatus.POSTED,
        payment_status=ExpenditurePaymentStatus.UNPAID,
        origin=ExpenditureOrigin.FINANCE,
        beneficiary_type="payroll_allocation",
        posted_by=user,
        posted_at=timezone.now(),
        created_by=user,
    )
    entry.expenditure = expenditure
    entry.save(update_fields=["expenditure", "updated_at"])
    return expenditure


def sync_entry_status(entry: PayrollEntry) -> None:
    paid = entry.amount_paid
    if paid >= entry.net_salary_payable and entry.net_salary_payable > ZERO:
        state = FinancePaymentStatus.PAID
    elif paid > ZERO:
        state = FinancePaymentStatus.PARTIAL
    elif entry.payments.filter(status=PayrollPaymentStatus.REVERSED).exists():
        state = FinancePaymentStatus.REVERSED
    else:
        state = FinancePaymentStatus.UNPAID
    latest = entry.payments.filter(status=PayrollPaymentStatus.POSTED).order_by(
        "-payment_date", "-pk"
    ).first()
    PayrollEntry.objects.filter(pk=entry.pk).update(
        payment_status=state,
        payment_date=latest.payment_date if latest else None,
    )
    entry.payment_status = state
    entry.payment_date = latest.payment_date if latest else None
    if entry.expenditure_id:
        expenditure_state = {
            FinancePaymentStatus.PAID: ExpenditurePaymentStatus.PAID,
            FinancePaymentStatus.PARTIAL: ExpenditurePaymentStatus.PARTIAL,
        }.get(state, ExpenditurePaymentStatus.UNPAID)
        Expenditure.objects.filter(pk=entry.expenditure_id).update(
            payment_status=expenditure_state
        )


@transaction.atomic
def set_salary_cost_allocations(*, payroll_entry_id: int, rows, user) -> PayrollEntry:
    entry = PayrollEntry.objects.select_for_update().select_related("accounting_period").get(
        pk=payroll_entry_id
    )
    if entry.accounting_period.status == "closed":
        raise ValidationError({"detail": "Closed-period payroll cannot be changed."})
    if not isinstance(rows, list) or not rows:
        raise ValidationError({"cost_allocations": "Add at least one cost beneficiary."})
    normalized, total, batch_ids = [], ZERO, set()
    for row in rows:
        beneficiary = row.get("beneficiary_type", "batch")
        amount = money(row.get("amount"))
        if amount <= ZERO:
            raise ValidationError({"cost_allocations": "Allocation amounts must be positive."})
        batch_id = None
        if beneficiary == "batch":
            try:
                batch_id = int(row.get("batch"))
            except (TypeError, ValueError):
                raise ValidationError({"cost_allocations": "A batch allocation requires a batch."})
            if batch_id in batch_ids:
                raise ValidationError({"cost_allocations": "Combine duplicate batch allocations."})
            batch_ids.add(batch_id)
        elif beneficiary != "administration":
            raise ValidationError({"cost_allocations": "Use batch or administration."})
        total += amount
        normalized.append({"beneficiary_type": beneficiary, "batch": batch_id, "amount": str(amount)})
    if set(Batch.objects.filter(pk__in=batch_ids).values_list("pk", flat=True)) != batch_ids:
        raise ValidationError({"cost_allocations": "An allocated batch does not exist."})
    if total != money(entry.total_employer_cost):
        raise ValidationError(
            {"cost_allocations": f"Salary cost allocations must total {entry.total_employer_cost}."}
        )
    CostAllocation.objects.filter(payroll_entry=entry, locked=False).delete()
    batch_total = ZERO
    for row in normalized:
        if row["beneficiary_type"] != "batch":
            continue
        amount = money(row["amount"])
        batch_total += amount
        CostAllocation.objects.create(
            accounting_period=entry.accounting_period,
            batch_id=row["batch"],
            source_type=AllocationSourceType.PAYROLL,
            payroll_entry=entry,
            allocation_method=AllocationMethod.MANUAL_WITH_REASON,
            driver_quantity=amount,
            total_driver_quantity=total,
            allocation_percentage=(amount * Decimal("100") / total).quantize(Decimal("0.0001")),
            allocated_amount=amount,
            manual_reason="Explicit payroll beneficiary allocation.",
            generated_by=user,
        )
    entry.cost_allocation_plan = normalized
    entry.production_percentage = (batch_total * Decimal("100") / total).quantize(Decimal("0.01"))
    entry.administration_percentage = Decimal("100.00") - entry.production_percentage
    entry.selling_percentage = ZERO
    entry.save(update_fields=["cost_allocation_plan", "production_percentage", "administration_percentage", "selling_percentage", "updated_at"])
    ensure_salary_expense(entry, user=user)
    return entry


@transaction.atomic
def record_salary_payment(*, payroll_entry_id: int, amount, payment_date, payment_method: str,
                          funding_rows, idempotency_key: str, external_reference: str, user):
    entry = PayrollEntry.objects.select_for_update().get(pk=payroll_entry_id)
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError({"idempotency_key": "A submission key is required."})
    existing = PayrollPayment.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.payroll_entry_id != entry.pk:
            raise ValidationError({"idempotency_key": "This submission key is already in use."})
        return existing
    amount = money(amount)
    if amount <= ZERO or amount > entry.outstanding_salary:
        raise ValidationError({"amount": f"Payment must be positive and not exceed {entry.outstanding_salary}."})
    if isinstance(payment_date, str):
        try:
            payment_date = date.fromisoformat(payment_date)
        except ValueError:
            raise ValidationError({"payment_date": "Enter a valid payment date."})
    if not payment_method.strip():
        raise ValidationError({"payment_method": "Payment method is required."})
    if not isinstance(funding_rows, list) or not funding_rows:
        raise ValidationError({"funding_allocations": "Select at least one funding source."})
    totals = {}
    for row in funding_rows:
        try:
            source_id = int(row.get("funding_source"))
        except (TypeError, ValueError, AttributeError):
            raise ValidationError({"funding_allocations": "Each funding row requires a source."})
        row_amount = money(row.get("amount"))
        if row_amount <= ZERO:
            raise ValidationError({"funding_allocations": "Funding amounts must be positive."})
        totals[source_id] = totals.get(source_id, ZERO) + row_amount
    if sum(totals.values(), ZERO) != amount:
        raise ValidationError({"funding_allocations": "Funding allocations must equal the payment amount."})
    sources = {s.pk: s for s in FundingSource.objects.select_for_update().filter(pk__in=totals)}
    if set(sources) != set(totals):
        raise ValidationError({"funding_allocations": "A selected funding source does not exist."})
    for source_id, required in totals.items():
        available = available_funding_source_cash(sources[source_id])
        if required > available:
            raise ValidationError({"funding_allocations": f"{sources[source_id]} has only {available} available."})
    payment = PayrollPayment.objects.create(
        payroll_entry=entry,
        amount=amount,
        payment_date=payment_date,
        payment_method=payment_method.strip(),
        external_reference=(external_reference or "").strip(),
        idempotency_key=key,
        posted_by=user,
    )
    PayrollPaymentFunding.objects.bulk_create([
        PayrollPaymentFunding(payment=payment, funding_source_id=source_id, amount=value)
        for source_id, value in totals.items()
    ])
    ensure_salary_expense(entry, user=user)
    sync_entry_status(entry)
    return payment


@transaction.atomic
def reverse_salary_payment(*, payment_id: int, reason: str, user) -> PayrollPayment:
    payment = PayrollPayment.objects.select_for_update().select_related("payroll_entry").get(pk=payment_id)
    if payment.status == PayrollPaymentStatus.REVERSED:
        return payment
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reversal reason is required."})
    payment.status = PayrollPaymentStatus.REVERSED
    payment.reversed_at = timezone.now()
    payment.reversed_by = user
    payment.reversal_reason = reason
    payment.save(update_fields=["status", "reversed_at", "reversed_by", "reversal_reason", "updated_at"])
    sync_entry_status(payment.payroll_entry)
    return payment


def create_deduction_liability(entry: PayrollEntry) -> None:
    PayrollLiability.objects.update_or_create(
        payroll_entry=entry,
        defaults={"amount": entry.deductions},
    )
