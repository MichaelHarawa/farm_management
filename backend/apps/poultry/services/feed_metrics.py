from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from statistics import median

from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Max, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import (
    Batch,
    BatchStatus,
    FeedUsage,
    FlockAdjustment,
    FlockAdjustmentStatus,
    Mortality,
    InputCosts,
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


def _historical_feed_rate(batch: Batch) -> tuple[Decimal | None, int]:
    comparable = list(
        Batch.objects.filter(
            bird_type=batch.bird_type,
            status=BatchStatus.CLOSED,
        ).exclude(pk=batch.pk)
    )
    total_kg = Decimal("0.000")
    total_bird_days = Decimal("0.0000")
    included = 0
    for historical in comparable:
        records = list(
            historical.feed_usage_row.order_by("feeding_start_date", "pk")
        )
        if not records:
            continue
        exposure_end = max(row.feeding_end_date for row in records)
        bird_days = bird_days_between(
            historical,
            historical.entry_date,
            exposure_end,
        )
        if bird_days <= 0:
            continue
        total_kg += sum((row.quantity_kg for row in records), Decimal("0.000"))
        total_bird_days += bird_days
        included += 1
    if total_bird_days <= 0:
        return None, 0
    return (total_kg / total_bird_days).quantize(Decimal("0.000001")), included


def _historical_sale_price(batch: Batch) -> tuple[Decimal | None, int]:
    rows = Sales.objects.filter(
        batch__bird_type=batch.bird_type,
        batch__status=BatchStatus.CLOSED,
        product_type__in=BIRD_PRODUCTS,
    ).exclude(
        payment_status=PaymentStatus.CANCELLED
    ).exclude(batch=batch)
    aggregate = rows.aggregate(
        quantity=Sum("quantity_sold"),
        revenue=Sum(
            ExpressionWrapper(
                F("quantity_sold") * F("unit_price"),
                output_field=DecimalField(max_digits=18, decimal_places=2),
            )
        ),
    )
    quantity = int(aggregate["quantity"] or 0)
    if quantity <= 0:
        current_rows = Sales.objects.filter(
            batch=batch,
            product_type__in=BIRD_PRODUCTS,
        ).exclude(payment_status=PaymentStatus.CANCELLED)
        aggregate = current_rows.aggregate(
            quantity=Sum("quantity_sold"),
            revenue=Sum(
                ExpressionWrapper(
                    F("quantity_sold") * F("unit_price"),
                    output_field=DecimalField(max_digits=18, decimal_places=2),
                )
            ),
        )
        quantity = int(aggregate["quantity"] or 0)
    if quantity <= 0:
        return (
            Decimal(batch.target_selling_price).quantize(Decimal("0.01"))
            if batch.target_selling_price
            else None,
            0,
        )
    return (
        (Decimal(aggregate["revenue"] or 0) / Decimal(quantity)).quantize(
            Decimal("0.01")
        ),
        quantity,
    )


def _feed_cost_per_kg(batch: Batch) -> tuple[Decimal | None, int]:
    batch_ids = list(
        Batch.objects.filter(
            Q(pk=batch.pk)
            | Q(bird_type=batch.bird_type, status=BatchStatus.CLOSED)
        ).values_list("pk", flat=True)
    )
    feed_cost_expression = ExpressionWrapper(
        F("quantity") * F("unit") * F("unit_cost"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    total_cost = InputCosts.objects.filter(
        batch_id__in=batch_ids,
    ).filter(
        Q(category__icontains="feed") | Q(item__icontains="feed")
    ).aggregate(total=Sum(feed_cost_expression))["total"] or Decimal("0.00")
    usages = list(FeedUsage.objects.filter(batch_id__in=batch_ids))
    total_kg = sum((row.quantity_kg for row in usages), Decimal("0.000"))
    if total_cost <= 0 or total_kg <= 0:
        return None, 0
    return (
        (Decimal(total_cost) / total_kg).quantize(Decimal("0.01")),
        len(set(row.batch_id for row in usages)),
    )


def _typical_bag_size_kg(batch: Batch) -> Decimal:
    quantities = [
        row.quantity_kg
        for row in FeedUsage.objects.filter(batch__bird_type=batch.bird_type)
        if Decimal("20") <= row.quantity_kg <= Decimal("100")
    ]
    if not quantities:
        return Decimal("50.00")
    counts: dict[Decimal, int] = defaultdict(int)
    for quantity in quantities:
        counts[quantity] += 1
    return max(counts, key=lambda value: (counts[value], value)).quantize(
        Decimal("0.01")
    )


def _historical_finish_age_days(batch: Batch) -> tuple[int, int]:
    rows = (
        Sales.objects.filter(
            batch__bird_type=batch.bird_type,
            batch__status=BatchStatus.CLOSED,
            product_type__in=BIRD_PRODUCTS,
        )
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .exclude(batch=batch)
        .values("batch_id", "batch__entry_date")
        .annotate(last_sale=Max("sale_date"))
    )
    ages = [
        max((row["last_sale"].date() - row["batch__entry_date"].date()).days, 28)
        for row in rows
        if row["last_sale"]
    ]
    if not ages:
        return 42, 0
    return int(median(ages)), len(ages)


def sell_by_recommendation(batch: Batch) -> dict:
    """Advisory sell-by estimate from recorded feed and sales evidence.

    It deliberately reports unavailable inputs instead of manufacturing a result.
    The projection is a management aid, not a biological or market guarantee.
    """

    today = timezone.localdate()
    current_live = max(live_birds_at(batch, timezone.now()), 0)
    current_summary = feed_summary(batch)
    current_rate = current_summary["feed_per_bird_day_kg"]
    historical_rate, historical_feed_batches = _historical_feed_rate(batch)
    recommended_rate = current_rate or historical_rate
    average_sale_price, historical_sale_quantity = _historical_sale_price(batch)
    feed_cost_per_kg, feed_cost_batch_count = _feed_cost_per_kg(batch)
    bag_size = _typical_bag_size_kg(batch)
    finish_age, finish_batch_count = _historical_finish_age_days(batch)
    age_days = max((today - batch.entry_date.date()).days, 0)
    historical_target = batch.entry_date.date() + timedelta(days=max(finish_age, 28))
    latest_feed_end = batch.feed_usage_row.aggregate(
        latest=Max("feeding_end_date")
    )["latest"]
    coverage_boundary = max(
        today,
        latest_feed_end.date() if latest_feed_end else today,
    )
    if age_days < 28:
        sell_by = max(batch.entry_date.date() + timedelta(days=28), historical_target)
    else:
        sell_by = min(max(historical_target, today), coverage_boundary)
    days_to_finish = max((sell_by - today).days, 0)
    birds_per_day = (
        ceil(current_live / max(days_to_finish, 1)) if current_live else 0
    )

    missing = []
    if recommended_rate is None:
        missing.append("feed consumption rate")
    if feed_cost_per_kg is None:
        missing.append("feed cost per kilogram")
    if average_sale_price is None:
        missing.append("historical bird selling price")

    projection_days = 7
    projected_feed_kg = None
    bags_to_avoid = None
    avoidable_cost = None
    projected_net = None
    projected_loss = None
    current_net = None
    if not missing and current_live:
        projected_feed_kg = (
            Decimal(recommended_rate)
            * Decimal(current_live)
            * Decimal(projection_days)
        ).quantize(Decimal("0.01"))
        bags_to_avoid = ceil(projected_feed_kg / bag_size)
        avoidable_cost = (
            Decimal(bags_to_avoid) * bag_size * Decimal(feed_cost_per_kg)
        ).quantize(Decimal("0.01"))
        from apps.finance.services.profitability import batch_profitability

        current_net = Decimal(
            batch_profitability(batch).get("management_net_position", 0)
        ).quantize(Decimal("0.01"))
        projected_net = (current_net - avoidable_cost).quantize(Decimal("0.01"))
        projected_loss = max(-projected_net, Decimal("0.00"))

    status = (
        "complete"
        if current_live == 0
        else "insufficient_data"
        if missing
        else "ready"
    )
    return {
        "status": status,
        "recommended_sell_by": sell_by if current_live else None,
        "current_age_days": age_days,
        "current_live_birds": current_live,
        "birds_to_sell_per_day": birds_per_day,
        "average_historical_selling_price": average_sale_price,
        "current_feed_rate_kg_per_bird_day": current_rate,
        "historical_feed_rate_kg_per_bird_day": historical_rate,
        "recommended_feed_rate_kg_per_bird_day": recommended_rate,
        "typical_bag_size_kg": bag_size,
        "feed_cost_per_kg": feed_cost_per_kg,
        "projection_days": projection_days,
        "projected_extra_feed_kg": projected_feed_kg,
        "bags_to_avoid": bags_to_avoid,
        "avoidable_feed_purchase_cost": avoidable_cost,
        "current_management_net_position": current_net,
        "projected_net_after_extra_feed": projected_net,
        "projected_loss_after_extra_feed": projected_loss,
        "missing_inputs": missing,
        "evidence": {
            "historical_feed_batch_count": historical_feed_batches,
            "historical_sale_quantity": historical_sale_quantity,
            "feed_cost_batch_count": feed_cost_batch_count,
            "historical_finish_batch_count": finish_batch_count,
            "historical_finish_age_days": finish_age,
        },
        "basis": (
            "Sell-by guidance compares this batch's dated feed-per-bird-day rate with "
            "completed batches of the same bird type. The extra-feed estimate projects "
            "seven days at the recommended run rate and the observed all-in feed cost. "
            "Historical selling price is quantity-weighted. Review health, live weight, "
            "buyer demand, and current quotations before acting."
        ),
    }
