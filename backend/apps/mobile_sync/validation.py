from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

FARM_ZONE = ZoneInfo("Africa/Blantyre")


def validate_mortality(batch, data):
    from apps.finance.models import AccountingPeriod, PeriodStatus
    from apps.poultry.models import FeedUsage, FlockAdjustment, Mortality, Sales
    from apps.poultry.services.batch_lifecycle import BIRD_PRODUCT_TYPES, assert_batch_in_production

    assert_batch_in_production(batch)
    at = data["mortality_date"]
    if at < batch.entry_date or at > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"mortality_date": "Event must be after arrival and cannot be in the future."})
    if batch.profitability_finalized_at or batch.profitability_snapshots.filter(final=True).exists():
        raise ValidationError({"period_locked": "Batch profitability is finalized."})
    day = at.astimezone(FARM_ZONE).date()
    periods = list(AccountingPeriod.objects.select_for_update().filter(period_start__lte=day, period_end__gte=day).order_by("pk"))
    if any(period.status == PeriodStatus.CLOSED for period in periods):
        raise ValidationError({"period_locked": "Original business date belongs to a closed accounting period."})
    grouped = defaultdict(int)
    for event_at, quantity in Mortality.objects.filter(batch=batch).values_list("mortality_date", "quantity_dead"):
        grouped[event_at] -= quantity
    for event_at, quantity in Sales.objects.filter(batch=batch, product_type__in=BIRD_PRODUCT_TYPES).exclude(payment_status="cancelled").values_list("sale_date", "quantity_sold"):
        grouped[event_at] -= quantity
    for event_at, quantity in FlockAdjustment.objects.filter(batch=batch, status="approved").values_list("effective_at", "quantity_change"):
        grouped[event_at] += quantity
    grouped[at] -= data["quantity_dead"]
    feed_dates = set(FeedUsage.objects.filter(batch=batch).values_list("feeding_start_date", flat=True))
    balance = batch.actual_quantity_received or batch.quantity
    for event_at in sorted(set(grouped) | feed_dates):
        balance += grouped[event_at]
        if balance < 0 or (event_at in feed_dates and balance <= 0):
            raise ValidationError({"quantity_dead": ValidationError(
                "Mortality would invalidate a dated flock/feed balance.", code="insufficient_birds")})
    return (day - batch.entry_date.astimezone(FARM_ZONE).date()).days
