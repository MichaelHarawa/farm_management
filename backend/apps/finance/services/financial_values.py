"""Exact financial inputs and dated locks shared by financial command boundaries.

No rounding of captured money, implicit currency conversion or changed dates.
Call dated locks inside an atomic transaction, before batch/source/lot locks.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ..models import AccountingPeriod, PeriodStatus


def exact_decimal(value, *, field="amount", scale=2, max_digits=14, positive=False):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError({field: "Use an exact decimal string, not a floating-point number."})
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or (positive and amount == 0):
            raise ValueError
        quantum = Decimal(1).scaleb(-scale)
        if amount >= Decimal(10) ** (max_digits - scale) or amount != amount.quantize(quantum):
            raise ValueError
        return amount.quantize(quantum)
    except (InvalidOperation, ValueError):
        raise ValidationError({field: f"Enter a {'positive' if positive else 'non-negative'} finite amount with at most {scale} decimal places."})


def business_date(value, *, field="posting_date"):
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            raise ValidationError({field: "An instant requires an explicit timezone."})
        # Preserve the existing financial reporting calendar (settings.TIME_ZONE,
        # UTC in this deployment). Africa/Blantyre is the mobile DISPLAY calendar, not
        # authorization to change historical monthly cash/report date filters.
        # Explicit accounting Date inputs below are never converted.
        return value.astimezone(timezone.get_default_timezone()).date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValidationError({field: "Enter an explicit calendar date."})


def lock_financial_periods(*values, require=True, field="posting_date"):
    """Lock covering rows in PK order; evaluate actual payment/event dates.

    Legacy collections can have no period (require=False). That exception never
    allows a closed period and is not used for new financial posting templates.
    """
    days = sorted({business_date(value, field=field) for value in values})
    if not days:
        return {}
    selection = Q()
    for day in days:
        selection |= Q(period_start__lte=day, period_end__gte=day)
    periods = list(AccountingPeriod.objects.select_for_update().filter(selection).order_by("pk"))
    result = {}
    for day in days:
        matches = [period for period in periods if period.period_start <= day <= period.period_end]
        if any(period.status == PeriodStatus.CLOSED for period in matches):
            raise ValidationError({"period_locked": f"Original business date {day} belongs to a closed accounting period."})
        if require and not matches:
            raise ValidationError({field: f"Create an accounting period covering {day}."})
        if require and len(matches) > 1:
            raise ValidationError({field: f"Overlapping accounting periods for {day} require review."})
        result[day] = max(matches, key=lambda period: (period.period_start, period.pk)) if matches else None
    return result
