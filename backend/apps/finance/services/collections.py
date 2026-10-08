from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from apps.mobile_sync.writers import sync_atomic

from apps.poultry.models import PaymentStatus, Sales

from ..models import SalePayment, SalePaymentStatus
from .financial_values import exact_decimal, lock_financial_periods


ZERO = Decimal("0.00")


def _assert_payment_replay(payment, requested):
    if any(getattr(payment, field) != value for field, value in requested.items()):
        raise ValidationError({"idempotency_key": "This receipt key is bound to different sale, amount, date or evidence."})
    return payment, False


def active_payment_total(sale: Sales) -> Decimal:
    total = sale.payments.filter(status=SalePaymentStatus.POSTED).aggregate(
        total=Sum("amount")
    )["total"]
    return Decimal(total or ZERO).quantize(Decimal("0.01"))


@sync_atomic
def sync_sale_payment_totals(sale: Sales) -> Sales:
    """Refresh the compatibility payment fields from the immutable ledger."""
    paid = active_payment_total(sale)
    total = sale.sale_total
    balance = max(total - paid, ZERO).quantize(Decimal("0.01"))
    if sale.payment_status == PaymentStatus.CANCELLED:
        status = PaymentStatus.CANCELLED
        balance = ZERO
    elif paid == ZERO:
        status = PaymentStatus.UNPAID
    elif paid >= total:
        status = PaymentStatus.PAID
    else:
        status = PaymentStatus.PARTIAL
    Sales.objects.filter(pk=sale.pk).update(
        amount_paid=paid,
        balance=balance,
        payment_status=status,
        updated_at=timezone.now(),
    )
    sale.amount_paid = paid
    sale.balance = balance
    sale.payment_status = status
    return sale


@sync_atomic
@transaction.atomic
def record_sale_payment(
    *,
    sale_id: int,
    amount: Decimal,
    payment_date,
    payment_method: str,
    created_by,
    idempotency_key: str | None = None,
    external_reference: str = "",
    received_by_name: str = "",
    notes: str = "",
) -> tuple[SalePayment, bool]:
    normalized_key = (idempotency_key or "").strip() or None
    if normalized_key and len(normalized_key) > 120:
        raise ValidationError({"idempotency_key": "Receipt submission key must not exceed 120 characters."})
    amount = exact_decimal(amount, positive=True)
    payment_date = SalePayment._meta.get_field("payment_date").to_python(payment_date)
    if payment_date is None:
        raise ValidationError({"payment_date": "An actual receipt date is required."})
    if timezone.is_naive(payment_date):
        raise ValidationError({"payment_date": "The receipt instant requires an explicit timezone."})
    requested = {"sale_id": int(sale_id), "amount": amount, "payment_date": payment_date,
                 "payment_method": payment_method, "external_reference": (external_reference or "").strip(),
                 "received_by_name": (received_by_name or "").strip(), "notes": (notes or "").strip()}
    if normalized_key:
        existing = SalePayment.objects.filter(idempotency_key=normalized_key).first()
        if existing:
            return _assert_payment_replay(existing, requested)

    # Do not lock/reject the original sale's period for a current collection.
    lock_financial_periods(payment_date, require=False, field="payment_date")
    sale = Sales.objects.select_for_update().select_related("batch").get(pk=sale_id)
    if normalized_key:
        existing = SalePayment.objects.filter(idempotency_key=normalized_key).first()
        if existing:
            return _assert_payment_replay(existing, requested)
    if sale.payment_status == PaymentStatus.CANCELLED:
        raise ValidationError({"sale": "Cancelled sales cannot receive payments."})

    paid = active_payment_total(sale)
    outstanding = (sale.sale_total - paid).quantize(Decimal("0.01"))
    if amount > outstanding:
        raise ValidationError(
            {"amount": f"Payment exceeds the outstanding balance of {outstanding}."}
        )

    try:
        with transaction.atomic():
            payment = SalePayment.objects.create(**requested, idempotency_key=normalized_key, created_by=created_by)
    except IntegrityError:
        existing = SalePayment.objects.filter(idempotency_key=normalized_key).first() if normalized_key else None
        if existing is None:
            raise
        return _assert_payment_replay(existing, requested)
    sync_sale_payment_totals(sale)

    from .profitability import ensure_batch_funding_source

    ensure_batch_funding_source(sale.batch)
    return payment, True


@sync_atomic
def record_initial_sale_payment(*, sale: Sales, amount: Decimal, created_by) -> SalePayment | None:
    amount = Decimal(amount or ZERO).quantize(Decimal("0.01"))
    if amount <= ZERO or sale.payment_status == PaymentStatus.CANCELLED:
        sync_sale_payment_totals(sale)
        return None
    payment, _ = record_sale_payment(
        sale_id=sale.pk,
        amount=amount,
        payment_date=sale.sale_date,
        payment_method=sale.payment_method,
        created_by=created_by,
        idempotency_key=f"initial-sale:{sale.sale_id}",
        received_by_name=sale.sold_by_name,
        notes="Initial payment recorded with sale.",
    )
    return payment


@sync_atomic
@transaction.atomic
def reverse_sale_payment(*, payment_id: int, reason: str, reversed_by) -> SalePayment:
    # Match normal collection's sale -> receipt order, avoiding a reciprocal
    # receipt/sale lock cycle when the sync stream is disabled on ordinary web.
    sale_id = SalePayment.objects.values_list("sale_id", flat=True).get(pk=payment_id)
    sale = Sales.objects.select_for_update().get(pk=sale_id)
    payment = (
        SalePayment.objects.select_for_update()
        .select_related("sale__batch")
        .get(pk=payment_id)
    )
    if payment.status != SalePaymentStatus.POSTED:
        raise ValidationError({"detail": "Only posted payments can be reversed."})
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": "A reversal reason is required."})

    from ..models import FundingSource, FundingSourceType
    from .profitability import cash_used_from_batch

    # Serialize payment reversals with expenditure postings against this source.
    list(
        FundingSource.objects.select_for_update().filter(
            source_type=FundingSourceType.BATCH_COLLECTION,
            batch_id=sale.batch_id,
        ).order_by("pk")
    )
    resulting_cash = active_payment_total(sale) - payment.amount
    other_batch_cash = (
        SalePayment.objects.filter(
            sale__batch_id=sale.batch_id,
            status=SalePaymentStatus.POSTED,
        )
        .exclude(sale=sale)
        .aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    batch_cash_after = Decimal(other_batch_cash) + resulting_cash
    committed_spend = cash_used_from_batch(sale.batch)
    if batch_cash_after < committed_spend:
        raise ValidationError(
            {
                "detail": (
                    "This payment cannot be reversed because posted expenditures use "
                    f"the batch cash. Cash after reversal would be {batch_cash_after}, "
                    f"while {committed_spend} is committed. Reverse or re-fund those "
                    "expenditures first."
                )
            }
        )

    payment.status = SalePaymentStatus.REVERSED
    payment.reversed_at = timezone.now()
    payment.reversed_by = reversed_by
    payment.reversal_reason = reason
    payment.save(
        update_fields=["status", "reversed_at", "reversed_by", "reversal_reason", "updated_at"]
    )
    sync_sale_payment_totals(sale)
    return payment
