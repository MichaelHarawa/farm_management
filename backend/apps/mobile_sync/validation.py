from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

FARM_ZONE = ZoneInfo("Africa/Blantyre")


def validate_mortality(batch, data):
    from apps.finance.models import AccountingPeriod, PeriodStatus
    from apps.poultry.services.batch_lifecycle import assert_batch_in_production

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
    from apps.poultry.services.operations import validate_population_history
    validate_population_history(batch, at=at, change=-data["quantity_dead"], field="quantity_dead")
    return (day - batch.entry_date.astimezone(FARM_ZONE).date()).days
