from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import (
    Batch,
    BatchStatus,
    FeedUsage,
    FlockAdjustment,
    FlockAdjustmentStatus,
    Mortality,
    PaymentStatus,
    ProductType,
    Sales,
)


CALCULATION_VERSION = "dated-flock-events-v1"
BIRD_PRODUCTS = {ProductType.LIVE_CHICKEN, ProductType.DRESSED_CHICKEN}
SAME_TIMESTAMP_ORDERING = (
    "Approved flock adjustments, mortality, and bird sales effective at the same "
    "timestamp are applied before feed issued at that timestamp."
)


def actual_birds_received(batch: Batch) -> int:
    return batch.actual_quantity_received or batch.quantity


def batch_has_arrived(batch: Batch) -> bool:
    return batch.status not in {BatchStatus.BOOKED, BatchStatus.PLANNED}


def live_birds_at(batch: Batch, event_at: datetime) -> int:
    if not batch_has_arrived(batch) or event_at < batch.entry_date:
        return 0
    mortality = Mortality.objects.filter(
        batch=batch,
        mortality_date__lte=event_at,
    ).aggregate(total=Sum("quantity_dead"))["total"] or 0
    sold = Sales.objects.filter(
        batch=batch,
        sale_date__lte=event_at,
        product_type__in=BIRD_PRODUCTS,
    ).exclude(payment_status=PaymentStatus.CANCELLED).aggregate(
        total=Sum("quantity_sold")
    )["total"] or 0
    adjustments = FlockAdjustment.objects.filter(
        batch=batch,
        effective_at__lte=event_at,
        status=FlockAdjustmentStatus.APPROVED,
    ).aggregate(total=Sum("quantity_change"))["total"] or 0
    return actual_birds_received(batch) + adjustments - mortality - sold


def recalculate_feed_event_populations(batch: Batch) -> list[FeedUsage]:
    records = list(batch.feed_usage_row.order_by("feeding_start_date", "pk"))
    calculated_at = timezone.now()
    for record in records:
        live_birds = max(live_birds_at(batch, record.feeding_start_date), 0)
        FeedUsage.objects.filter(pk=record.pk).update(
            current_number_of_birds=live_birds,
            population_calculation_version=CALCULATION_VERSION,
            population_calculated_at=calculated_at,
        )
        record.current_number_of_birds = live_birds
        record.population_calculation_version = CALCULATION_VERSION
        record.population_calculated_at = calculated_at
    return records


@transaction.atomic
def record_feed_usage(*, batch_id: int, created_by, **data) -> FeedUsage:
    from .batch_lifecycle import assert_batch_in_production

    batch = Batch.objects.select_for_update().get(pk=batch_id)
    assert_batch_in_production(batch)
    data.pop("current_number_of_birds", None)
    live_birds = live_birds_at(batch, data["feeding_start_date"])
    if live_birds <= 0:
        raise ValidationError(
            {"feeding_start_date": "Feed cannot be issued when the dated live-bird balance is zero."}
        )
    record = FeedUsage(
        batch=batch,
        created_by=created_by,
        current_number_of_birds=live_birds,
        population_calculation_version=CALCULATION_VERSION,
        population_calculated_at=timezone.now(),
        **data,
    )
    record.full_clean()
    record.save()
    return record


@transaction.atomic
def create_flock_adjustment(*, batch_id: int, approved_by, **data) -> FlockAdjustment:
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    adjustment = FlockAdjustment(batch=batch, approved_by=approved_by, **data)
    adjustment.full_clean()
    adjustment.save()
    if live_birds_at(batch, adjustment.effective_at) < 0:
        raise ValidationError({"quantity_change": "This adjustment would make the flock negative."})
    recalculate_feed_event_populations(batch)
    return adjustment


def _timed_population_events(batch: Batch, start: datetime, end: datetime):
    grouped: dict[datetime, int] = defaultdict(int)
    for row in Mortality.objects.filter(
        batch=batch, mortality_date__gt=start, mortality_date__lte=end
    ).values("mortality_date", "quantity_dead"):
        grouped[row["mortality_date"]] -= row["quantity_dead"]
    for row in Sales.objects.filter(
        batch=batch,
        sale_date__gt=start,
        sale_date__lte=end,
        product_type__in=BIRD_PRODUCTS,
    ).exclude(payment_status=PaymentStatus.CANCELLED).values("sale_date", "quantity_sold"):
        grouped[row["sale_date"]] -= row["quantity_sold"]
    for row in FlockAdjustment.objects.filter(
        batch=batch,
        effective_at__gt=start,
        effective_at__lte=end,
        status=FlockAdjustmentStatus.APPROVED,
    ).values("effective_at", "quantity_change"):
        grouped[row["effective_at"]] += row["quantity_change"]
    return sorted(grouped.items())


def bird_days_between(batch: Batch, start: datetime, end: datetime) -> Decimal:
    if end <= start:
        return Decimal("0.0000")
    current = live_birds_at(batch, start)
    cursor = start
    bird_days = Decimal("0")
    for event_at, change in _timed_population_events(batch, start, end):
        seconds = Decimal(str((event_at - cursor).total_seconds()))
        bird_days += Decimal(max(current, 0)) * seconds / Decimal("86400")
        current += change
        cursor = event_at
    seconds = Decimal(str((end - cursor).total_seconds()))
    bird_days += Decimal(max(current, 0)) * seconds / Decimal("86400")
    return bird_days.quantize(Decimal("0.0001"))


def feed_summary(batch: Batch) -> dict:
    records = list(batch.feed_usage_row.order_by("feeding_start_date", "pk"))
    total_kg = sum((record.quantity_kg for record in records), Decimal("0.000"))
    arrived = batch_has_arrived(batch)
    started = actual_birds_received(batch) if arrived else 0
    current = max(live_birds_at(batch, timezone.now()), 0) if arrived else 0
    stage_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.000"))
    for record in records:
        stage_totals[record.feed_type] += record.quantity_kg
    if records and arrived:
        exposure_end = max(record.feeding_end_date for record in records)
        bird_days = bird_days_between(batch, batch.entry_date, exposure_end)
    else:
        bird_days = Decimal("0.0000")
    return {
        "total_feed_kg": total_kg.quantize(Decimal("0.001")),
        "initial_birds": started,
        "current_live_birds": current,
        "feed_per_bird_started_kg": (
            (total_kg / Decimal(started)).quantize(Decimal("0.0001")) if started else None
        ),
        "bird_days": bird_days,
        "feed_per_bird_day_kg": (
            (total_kg / bird_days).quantize(Decimal("0.000001")) if bird_days else None
        ),
        "stage_feed_kg": {
            key: value.quantize(Decimal("0.001")) for key, value in stage_totals.items()
        },
        "same_timestamp_ordering": SAME_TIMESTAMP_ORDERING,
        "calculation_version": CALCULATION_VERSION,
    }
