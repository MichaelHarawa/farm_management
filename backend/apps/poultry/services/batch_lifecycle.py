from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.poultry.models import (
    Batch,
    BatchStatus,
    Mortality,
    PaymentStatus,
    ProductType,
    Sales,
)


BIRD_PRODUCT_TYPES = {
    ProductType.LIVE_CHICKEN,
    ProductType.DRESSED_CHICKEN,
}


@dataclass(frozen=True)
class BirdBalance:
    initial_birds: int
    valid_bird_units_sold: int
    mortality: int
    remaining_live_birds: int


def valid_sales_queryset(batch: Batch | int):
    batch_id = batch.pk if isinstance(batch, Batch) else batch
    return Sales.objects.filter(batch_id=batch_id).exclude(
        payment_status=PaymentStatus.CANCELLED
    )


def valid_bird_sales_queryset(batch: Batch | int):
    return valid_sales_queryset(batch).filter(product_type__in=BIRD_PRODUCT_TYPES)


def valid_revenue_sales_queryset(batch: Batch | int):
    return valid_sales_queryset(batch)


def valid_bird_units_sold(batch: Batch | int) -> int:
    return (
        valid_bird_sales_queryset(batch).aggregate(total=Sum("quantity_sold"))[
            "total"
        ]
        or 0
    )


def recorded_mortality(batch: Batch | int) -> int:
    batch_id = batch.pk if isinstance(batch, Batch) else batch
    return (
        Mortality.objects.filter(batch_id=batch_id).aggregate(
            total=Sum("quantity_dead")
        )["total"]
        or 0
    )


def calculate_bird_balance(batch: Batch | int) -> BirdBalance:
    batch_obj = Batch.objects.get(pk=batch) if isinstance(batch, int) else batch
    sold = valid_bird_units_sold(batch_obj)
    mortality = recorded_mortality(batch_obj)
    remaining = batch_obj.quantity - sold - mortality

    return BirdBalance(
        initial_birds=batch_obj.quantity,
        valid_bird_units_sold=sold,
        mortality=mortality,
        remaining_live_birds=remaining,
    )


def calculate_batch_status(batch: Batch) -> str:
    balance = calculate_bird_balance(batch)
    today = timezone.localdate()

    if balance.remaining_live_birds <= 0:
        return BatchStatus.CLOSED

    if balance.valid_bird_units_sold > 0:
        return BatchStatus.SELLING

    if batch.entry_date.date() > today:
        return BatchStatus.PLANNED

    if batch.expected_maturity_date.date() <= today:
        return BatchStatus.MATURE

    return BatchStatus.ACTIVE


def recalculate_batch_status(batch: Batch, *, save: bool = True) -> Batch:
    status = calculate_batch_status(batch)
    changed_fields: list[str] = []

    if batch.status != status:
        batch.status = status
        changed_fields.append("status")

    if status == BatchStatus.CLOSED and batch.closed_at is None:
        batch.closed_at = timezone.now()
        batch.closure_reason = (
            batch.closure_reason or "All live birds have been sold or recorded."
        )
        changed_fields.extend(["closed_at", "closure_reason"])

    if status != BatchStatus.CLOSED and batch.closed_at is not None:
        batch.closed_at = None
        batch.closure_reason = ""
        changed_fields.extend(["closed_at", "closure_reason"])

    if save and changed_fields:
        batch.save(update_fields=[*set(changed_fields), "updated_at"])

    return batch


def assert_non_negative_bird_balance(batch: Batch) -> BirdBalance:
    balance = calculate_bird_balance(batch)
    if balance.remaining_live_birds < 0:
        raise ValueError("This transaction would oversell the batch.")
    return balance


def create_sale_with_lifecycle(*, batch_id: int, created_by, **data) -> Sales:
    with transaction.atomic():
        batch = Batch.objects.select_for_update().get(pk=batch_id)
        sale = Sales(batch=batch, created_by=created_by, **data)
        if not sale.sale_id:
            sale.sale_id = sale.next_sale_id()
        sale.balance = sale.calculated_balance
        sale.payment_status = sale.normalized_payment_status
        sale.full_clean()
        sale.save()
        assert_non_negative_bird_balance(batch)
        recalculate_batch_status(batch)
        return sale


def create_mortality_with_lifecycle(*, batch_id: int, created_by, **data) -> Mortality:
    with transaction.atomic():
        batch = Batch.objects.select_for_update().get(pk=batch_id)
        mortality = Mortality(batch=batch, created_by=created_by, **data)
        mortality.full_clean()
        mortality.save()
        assert_non_negative_bird_balance(batch)
        recalculate_batch_status(batch)
        return mortality


def sale_amount(sale: Sales) -> Decimal:
    if sale.payment_status == PaymentStatus.CANCELLED:
        return Decimal("0.00")
    return sale.sale_total
