from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum

from ..models import (
    AccountingPeriod,
    Asset,
    AssetDepreciationEntry,
    AssetProductionScope,
    AssetStatus,
    AssetUsageRecord,
    CostAllocation,
    DepreciationMethod,
    PeriodStatus,
)


CENT = Decimal("0.01")


def money(value: Decimal | int | None) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def overlap_days(start: date, end: date, period: AccountingPeriod) -> int:
    eligible_start = max(start, period.period_start)
    eligible_end = min(end, period.period_end)
    if eligible_end < eligible_start:
        return 0
    return (eligible_end - eligible_start).days + 1


def period_day_count(period: AccountingPeriod) -> int:
    return calendar.monthrange(period.period_start.year, period.period_start.month)[1]


def cumulative_depreciation(asset: Asset, *, before_period: AccountingPeriod | None = None) -> Decimal:
    queryset = asset.depreciation_entries.all()
    if before_period:
        queryset = queryset.filter(accounting_period__period_start__lt=before_period.period_start)
    return money(queryset.aggregate(total=Sum("period_depreciation"))["total"])


def opening_carrying_amount(asset: Asset, period: AccountingPeriod) -> Decimal:
    return money(
        asset.total_capitalized_cost
        - cumulative_depreciation(asset, before_period=period)
        - asset.recognized_impairment_amount
    )


def straight_line_depreciation(asset: Asset, period: AccountingPeriod) -> Decimal:
    if not asset.available_for_use_date:
        return Decimal("0.00")

    stop_date = asset.disposal_date or period.period_end
    eligible_days = overlap_days(asset.available_for_use_date, stop_date, period)
    if eligible_days <= 0:
        return Decimal("0.00")

    full_month_depreciation = asset.depreciable_amount / Decimal(asset.useful_life_months)
    return money(
        full_month_depreciation
        * Decimal(eligible_days)
        / Decimal(period_day_count(period))
    )


def units_of_production_depreciation(asset: Asset, period: AccountingPeriod) -> Decimal:
    if not asset.estimated_total_lifetime_units:
        return Decimal("0.00")

    actual_units = money(
        AssetUsageRecord.objects.filter(asset=asset, accounting_period=period).aggregate(
            total=Sum("quantity")
        )["total"]
    )
    unit_depreciation = asset.depreciable_amount / asset.estimated_total_lifetime_units
    return money(actual_units * unit_depreciation)


def period_depreciation(asset: Asset, period: AccountingPeriod) -> Decimal:
    if asset.status in {AssetStatus.DRAFT, AssetStatus.RETIRED}:
        return Decimal("0.00")
    if asset.status == AssetStatus.DISPOSED and asset.disposal_date and asset.disposal_date < period.period_start:
        return Decimal("0.00")

    if asset.depreciation_method == DepreciationMethod.UNITS_OF_PRODUCTION:
        depreciation = units_of_production_depreciation(asset, period)
    else:
        depreciation = straight_line_depreciation(asset, period)

    already_depreciated = cumulative_depreciation(asset, before_period=period)
    remaining_depreciable = max(
        asset.depreciable_amount - already_depreciated,
        Decimal("0.00"),
    )
    return min(money(depreciation), money(remaining_depreciable))


@transaction.atomic
def generate_depreciation_for_period(
    period: AccountingPeriod,
    *,
    generated_by=None,
) -> list[AssetDepreciationEntry]:
    if period.status == PeriodStatus.CLOSED:
        raise ValueError("Closed accounting periods cannot generate depreciation.")

    entries: list[AssetDepreciationEntry] = []
    assets = Asset.objects.select_related("asset_category").exclude(status=AssetStatus.DRAFT)

    for asset in assets:
        depreciation = period_depreciation(asset, period)
        if depreciation <= Decimal("0.00"):
            continue

        existing = AssetDepreciationEntry.objects.filter(
            asset=asset,
            accounting_period=period,
        ).first()
        if existing and existing.locked:
            entries.append(existing)
            continue

        opening = opening_carrying_amount(asset, period)
        closing = money(opening - depreciation)
        defaults = {
            "opening_carrying_amount": opening,
            "depreciation_method_snapshot": asset.depreciation_method,
            "useful_life_snapshot": asset.useful_life_months,
            "residual_value_snapshot": asset.residual_value,
            "period_depreciation": depreciation,
            "impairment_amount": Decimal("0.00"),
            "closing_carrying_amount": closing,
            "generated_by": generated_by,
        }
        entry, _ = AssetDepreciationEntry.objects.update_or_create(
            asset=asset,
            accounting_period=period,
            defaults=defaults,
        )
        entries.append(entry)

    return entries


def asset_recovery_summary(asset: Asset) -> dict:
    depreciation = cumulative_depreciation(asset)
    reserve_balance = money(
        asset.reserve_transactions.aggregate(total=Sum("amount"))["total"]
    )
    carrying_amount = money(
        asset.total_capitalized_cost
        - depreciation
        - asset.recognized_impairment_amount
    )
    return {
        "asset": str(asset.pk),
        "asset_code": asset.asset_code,
        "gross_cost": asset.total_capitalized_cost,
        "accumulated_depreciation": depreciation,
        "recognized_impairment": asset.recognized_impairment_amount,
        "carrying_amount": carrying_amount,
        "reserve_balance": reserve_balance,
        "unrecovered_amount": max(carrying_amount - reserve_balance, Decimal("0.00")),
    }
