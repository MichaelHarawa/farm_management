from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.poultry.models import Batch, BatchStatus, Mortality, PaymentStatus, ProductType, Sales

from ..models import AccountingPeriod, BirdDaySnapshot, PeriodStatus


CALCULATION_VERSION = "bird-days-v1"
BIRD_PRODUCTS = {ProductType.LIVE_CHICKEN, ProductType.DRESSED_CHICKEN}


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _event_totals_by_date(model, date_field: str, quantity_field: str, filters):
    rows = (
        model.objects.filter(**filters)
        .values(f"{date_field}__date")
        .annotate(total=Sum(quantity_field))
    )
    totals = defaultdict(int)
    for row in rows:
        totals[row[f"{date_field}__date"]] = row["total"] or 0
    return totals


def _batch_end_date(batch: Batch, period: AccountingPeriod) -> date:
    if batch.status == BatchStatus.CLOSED and batch.closed_at:
        return min(batch.closed_at.date(), period.period_end)
    if period.status == PeriodStatus.OPEN:
        return min(period.period_end, timezone.localdate())
    return period.period_end


def calculate_batch_bird_days(
    batch: Batch,
    period: AccountingPeriod,
) -> dict[str, Decimal | int | date]:
    start = max(batch.entry_date.date(), period.period_start)
    end = _batch_end_date(batch, period)

    if start > end:
        return {
            "active_days": 0,
            "opening_live_birds": 0,
            "mortality": 0,
            "valid_bird_units_sold": 0,
            "closing_live_birds": 0,
            "bird_days": Decimal("0.0000"),
        }

    prior_sales = (
        Sales.objects.filter(
            batch=batch,
            product_type__in=BIRD_PRODUCTS,
            sale_date__date__lt=start,
        )
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .aggregate(total=Sum("quantity_sold"))["total"]
        or 0
    )
    prior_mortality = (
        Mortality.objects.filter(batch=batch, mortality_date__date__lt=start).aggregate(
            total=Sum("quantity_dead")
        )["total"]
        or 0
    )
    opening = batch.quantity - prior_sales - prior_mortality
    if opening < 0:
        raise ValueError(f"{batch} has a negative opening live-bird balance.")

    daily_sales = _event_totals_by_date(
        Sales,
        "sale_date",
        "quantity_sold",
        {
            "batch": batch,
            "product_type__in": BIRD_PRODUCTS,
            "sale_date__date__gte": start,
            "sale_date__date__lte": end,
        },
    )
    cancelled_sales = _event_totals_by_date(
        Sales,
        "sale_date",
        "quantity_sold",
        {
            "batch": batch,
            "product_type__in": BIRD_PRODUCTS,
            "payment_status": PaymentStatus.CANCELLED,
            "sale_date__date__gte": start,
            "sale_date__date__lte": end,
        },
    )
    for event_date, quantity in cancelled_sales.items():
        daily_sales[event_date] -= quantity

    daily_mortality = _event_totals_by_date(
        Mortality,
        "mortality_date",
        "quantity_dead",
        {
            "batch": batch,
            "mortality_date__date__gte": start,
            "mortality_date__date__lte": end,
        },
    )

    bird_days = Decimal("0.0000")
    active_days = 0
    current_opening = opening
    period_sales = 0
    period_mortality = 0

    for day in _date_range(start, end):
        sold_today = daily_sales[day]
        mortality_today = daily_mortality[day]
        closing = current_opening - sold_today - mortality_today
        if closing < 0:
            raise ValueError(f"{batch} has a negative live-bird balance on {day}.")

        daily_average = (Decimal(current_opening) + Decimal(closing)) / Decimal("2")
        bird_days += daily_average
        active_days += 1
        period_sales += sold_today
        period_mortality += mortality_today
        current_opening = closing

    return {
        "active_days": active_days,
        "opening_live_birds": opening,
        "mortality": period_mortality,
        "valid_bird_units_sold": period_sales,
        "closing_live_birds": current_opening,
        "bird_days": bird_days.quantize(Decimal("0.0001")),
    }


def recalculate_bird_day_snapshots(
    period: AccountingPeriod,
) -> list[BirdDaySnapshot]:
    if period.status == PeriodStatus.CLOSED:
        raise ValueError("Closed accounting periods cannot be recalculated.")

    batches = Batch.objects.filter(
        entry_date__date__lte=period.period_end,
    ).filter(
        models.Q(closed_at__isnull=True)
        | models.Q(closed_at__date__gte=period.period_start)
    )

    snapshots: list[BirdDaySnapshot] = []
    for batch in batches:
        metrics = calculate_batch_bird_days(batch, period)
        if metrics["active_days"] == 0:
            continue

        snapshot, _ = BirdDaySnapshot.objects.update_or_create(
            accounting_period=period,
            batch=batch,
            calculation_version=CALCULATION_VERSION,
            defaults={
                **metrics,
                "calculated_at": timezone.now(),
            },
        )
        snapshots.append(snapshot)

    return snapshots
