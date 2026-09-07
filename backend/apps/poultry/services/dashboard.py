from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.finance.models import (
    AllocationSourceType,
    CostAllocation,
    ExpenditureStatus,
    SalePayment,
    SalePaymentStatus,
)
from apps.poultry.models import (
    Batch,
    BatchWeightSample,
    BatchStatus,
    FeedUsage,
    FeedType,
    FlockAdjustmentStatus,
    InputCosts,
    Mortality,
    PaymentStatus,
    ProductType,
    Sales,
)
from apps.poultry.services.feed_metrics import bird_days_between, live_birds_at
from apps.poultry.services.growth import (
    build_growth_alert,
    get_broiler_strain_for_batch,
    get_target_weight_g,
)


BIRD_PRODUCTS = {ProductType.LIVE_CHICKEN, ProductType.DRESSED_CHICKEN}
PRODUCTION_STATUSES = {
    BatchStatus.ACTIVE,
    BatchStatus.MATURE,
    BatchStatus.SELLING,
}
ZERO = Decimal("0.00")


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _money(value) -> Decimal:
    return _decimal(value).quantize(Decimal("0.01"))


def _percentage(numerator: Decimal | int, denominator: Decimal | int):
    numerator = _decimal(numerator)
    denominator = _decimal(denominator)
    if denominator <= 0:
        return None
    return ((numerator / denominator) * Decimal("100")).quantize(Decimal("0.01"))


def _date_filters(filters) -> tuple[date, date]:
    today = timezone.localdate()
    requested_end = parse_date(filters.get("date_to", "")) if hasattr(filters, "get") else None
    requested_start = parse_date(filters.get("date_from", "")) if hasattr(filters, "get") else None
    end = requested_end or today
    start = requested_start or (end - timedelta(days=29))
    if start > end:
        start, end = end, start
    return start, end


def _aware_start(value: date) -> datetime:
    return timezone.make_aware(datetime.combine(value, time.min), timezone.get_current_timezone())


def _aware_end(value: date) -> datetime:
    return timezone.make_aware(datetime.combine(value, time.max), timezone.get_current_timezone())


def _bucket_mode(start: date, end: date) -> str:
    days = (end - start).days + 1
    return "day" if days <= 45 else "week" if days <= 180 else "month"


def _bucket_date(value: date, mode: str) -> date:
    if mode == "week":
        return value - timedelta(days=value.weekday())
    if mode == "month":
        return value.replace(day=1)
    return value


def _bucket_sequence(start: date, end: date, mode: str) -> list[date]:
    cursor = _bucket_date(start, mode)
    rows = []
    while cursor <= end:
        rows.append(cursor)
        if mode == "month":
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            cursor += timedelta(days=7 if mode == "week" else 1)
    return rows


def _latest_growth(batch, samples: list) -> dict | None:
    if not samples:
        return None
    sample = max(samples, key=lambda row: (row.sampled_at, row.pk))
    strain = get_broiler_strain_for_batch(batch)
    target = get_target_weight_g(sample.age_in_days, strain)
    alert = build_growth_alert(
        sample.age_in_days,
        sample.average_weight_g,
        target,
        sample.sample_size,
    )
    return {
        "sampled_at": sample.sampled_at,
        "sample_size": sample.sample_size,
        "age_in_days": sample.age_in_days,
        "average_weight_g": sample.average_weight_g,
        "target_weight_g": target,
        "deviation_percent": round(alert.deviation_pct, 2) if alert.deviation_pct is not None else None,
        "severity": alert.severity,
        "message": alert.message,
    }


def _cost_category(label: str, source_type: str = "") -> str:
    normalized = (label or "").lower()
    if source_type in {AllocationSourceType.PAYROLL, AllocationSourceType.AD_HOC_LABOUR}:
        return "allocated_labour"
    if source_type == AllocationSourceType.DEPRECIATION:
        return "assets_and_depreciation"
    if "chick" in normalized or "bird" in normalized:
        return "chicks"
    if "feed" in normalized:
        return "feed"
    if any(word in normalized for word in ("drug", "vacc", "medicine", "medication")):
        return "medication"
    if any(word in normalized for word in ("transport", "delivery", "fuel")):
        return "transport"
    return "other"


def _period_costs(batch_ids: list[int], start: date, end: date):
    per_batch = defaultdict(lambda: ZERO)
    per_category = defaultdict(lambda: ZERO)
    per_bucket = defaultdict(lambda: ZERO)
    mode = _bucket_mode(start, end)

    allocations = CostAllocation.objects.filter(batch_id__in=batch_ids).select_related(
        "expenditure__category", "accounting_period"
    )
    for row in allocations:
        if row.source_type == AllocationSourceType.EXPENDITURE:
            if not row.expenditure_id or row.expenditure.status != ExpenditureStatus.POSTED:
                continue
            recognized_on = row.expenditure.expenditure_date
            label = (
                row.expenditure.category.name
                if row.expenditure.category_id
                else row.expenditure.description
            )
        else:
            if not row.accounting_period_id:
                continue
            recognized_on = row.accounting_period.period_end
            label = row.get_source_type_display()
        if not start <= recognized_on <= end:
            continue
        amount = _money(row.allocated_amount)
        per_batch[row.batch_id] += amount
        per_category[_cost_category(label, row.source_type)] += amount
        per_bucket[_bucket_date(recognized_on, mode)] += amount

    # A linked expenditure is represented by CostAllocation. Only legacy,
    # unlinked input costs are added here, preventing duplicate recognition.
    legacy_inputs = InputCosts.objects.filter(
        batch_id__in=batch_ids,
        expenditure__isnull=True,
        purchase_date__date__gte=start,
        purchase_date__date__lte=end,
    )
    for row in legacy_inputs:
        amount = _money(row.direct_input_total)
        recognized_on = row.purchase_date.date()
        per_batch[row.batch_id] += amount
        per_category[_cost_category(f"{row.category} {row.item}")] += amount
        per_bucket[_bucket_date(recognized_on, mode)] += amount

    return per_batch, per_category, per_bucket


def poultry_dashboard(filters=None) -> dict:
    """Return date-consistent operating and business measures for selected flocks."""
    filters = filters or {}
    now = timezone.now()
    start, end = _date_filters(filters)
    start_at, end_at = _aware_start(start), _aware_end(end)
    mode = _bucket_mode(start, end)

    all_batches = list(Batch.objects.order_by("-entry_date", "-pk"))
    selected_ids = []
    if hasattr(filters, "getlist"):
        selected_ids = [int(value) for value in filters.getlist("batch") if str(value).isdigit()]
    elif filters.get("batch"):
        selected_ids = [int(filters["batch"])]

    bird_type = filters.get("bird_type", "all")
    stage = filters.get("stage", "production")
    feed_stage = filters.get("feed_stage", "all")
    selected_batches = [
        batch
        for batch in all_batches
        if (not selected_ids or batch.pk in selected_ids)
        and (bird_type == "all" or batch.bird_type == bird_type)
        and (
            stage == "all"
            or (stage == "production" and batch.status in PRODUCTION_STATUSES)
            or batch.status == stage
        )
    ]
    batch_ids = [batch.pk for batch in selected_batches]

    sales = list(
        Sales.objects.filter(
            batch_id__in=batch_ids,
            sale_date__date__gte=start,
            sale_date__date__lte=end,
        )
        .exclude(payment_status=PaymentStatus.CANCELLED)
        .order_by("sale_date", "pk")
    )
    mortalities = list(
        Mortality.objects.filter(
            batch_id__in=batch_ids,
            mortality_date__date__gte=start,
            mortality_date__date__lte=end,
        )
    )
    feed_queryset = FeedUsage.objects.filter(
            batch_id__in=batch_ids,
            feeding_start_date__date__gte=start,
            feeding_start_date__date__lte=end,
        )
    if feed_stage != "all":
        feed_queryset = feed_queryset.filter(feed_type=feed_stage)
    feed_records = list(feed_queryset)
    weight_samples = list(
        BatchWeightSample.objects.filter(
            batch_id__in=batch_ids,
            sampled_at__date__gte=start,
            sampled_at__date__lte=end,
        ).order_by("sampled_at", "pk")
    ) if batch_ids else []

    payments = list(
        SalePayment.objects.filter(
            sale__batch_id__in=batch_ids,
            status=SalePaymentStatus.POSTED,
            payment_date__date__gte=start,
            payment_date__date__lte=end,
        ).select_related("sale")
    )

    costs_by_batch, cost_breakdown, costs_by_bucket = _period_costs(batch_ids, start, end)

    sales_by_batch = defaultdict(lambda: ZERO)
    collections_by_batch = defaultdict(lambda: ZERO)
    sold_by_batch = defaultdict(int)
    sales_by_bucket = defaultdict(lambda: ZERO)
    collections_by_bucket = defaultdict(lambda: ZERO)
    for sale in sales:
        amount = _money(sale.sale_total)
        sales_by_batch[sale.batch_id] += amount
        sales_by_bucket[_bucket_date(sale.sale_date.date(), mode)] += amount
        if sale.product_type in BIRD_PRODUCTS:
            sold_by_batch[sale.batch_id] += sale.quantity_sold
    for payment in payments:
        collections_by_batch[payment.sale.batch_id] += _money(payment.amount)
        collections_by_bucket[_bucket_date(payment.payment_date.date(), mode)] += _money(payment.amount)

    feed_by_batch = defaultdict(lambda: Decimal("0.000"))
    feed_by_bucket = defaultdict(lambda: Decimal("0.000"))
    feed_stage_by_bucket = defaultdict(lambda: defaultdict(lambda: Decimal("0.000")))
    for feed in feed_records:
        kg = feed.quantity_kg
        key = _bucket_date(feed.feeding_start_date.date(), mode)
        feed_by_batch[feed.batch_id] += kg
        feed_by_bucket[key] += kg
        feed_stage_by_bucket[key][feed.feed_type] += kg

    mortality_by_batch = defaultdict(int)
    for mortality in mortalities:
        mortality_by_batch[mortality.batch_id] += mortality.quantity_dead

    samples_by_batch = defaultdict(list)
    for sample in weight_samples:
        samples_by_batch[sample.batch_id].append(sample)

    rows = []
    current_birds = 0
    opening_birds = 0
    positive_adjustments = 0
    for batch in selected_batches:
        current = max(live_birds_at(batch, end_at), 0)
        opening = max(live_birds_at(batch, start_at), 0)
        current_birds += current
        opening_birds += opening
        positive_adjustments += sum(
            row.quantity_change
            for row in batch.flock_adjustments.filter(
                status=FlockAdjustmentStatus.APPROVED,
                effective_at__gte=start_at,
                effective_at__lte=end_at,
                quantity_change__gt=0,
            )
        )
        age_days = max((end - batch.entry_date.date()).days, 0)
        period_cost = _money(costs_by_batch[batch.pk])
        period_sales = _money(sales_by_batch[batch.pk])
        rows.append(
            {
                "id": batch.pk,
                "batch_id": batch.batch_id,
                "bird_type": batch.bird_type,
                "status": batch.status,
                "entry_date": batch.entry_date,
                "age_days": age_days,
                "current_live_birds": current,
                "birds_sold_period": sold_by_batch[batch.pk],
                "birds_sold": sold_by_batch[batch.pk],
                "sales_period": period_sales,
                "total_sales": period_sales,
                "amount_collected": _money(collections_by_batch[batch.pk]),
                "recorded_costs_period": period_cost,
                "actual_period_result": _money(period_sales - period_cost),
                "feed_issued_period_kg": feed_by_batch[batch.pk].quantize(Decimal("0.001")),
                "mortality_period": mortality_by_batch[batch.pk],
                "mortality": mortality_by_batch[batch.pk],
                "latest_growth": _latest_growth(batch, samples_by_batch[batch.pk]),
            }
        )

    period_sales = _money(sum(sales_by_batch.values(), ZERO))
    period_collections = _money(sum((_money(row.amount) for row in payments), ZERO))
    period_sold = sum(sold_by_batch.values())
    period_deaths = sum(mortality_by_batch.values())
    period_feed = sum(feed_by_batch.values(), Decimal("0.000")).quantize(Decimal("0.001"))
    mortality_denominator = opening_birds + positive_adjustments

    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=(end - start).days)
    previous_sales = ZERO
    previous_queryset = Sales.objects.filter(
        batch_id__in=batch_ids,
        sale_date__date__gte=previous_start,
        sale_date__date__lte=previous_end,
    ).exclude(payment_status=PaymentStatus.CANCELLED)
    for sale in previous_queryset:
        previous_sales += _money(sale.sale_total)
    previous_sales = _money(previous_sales)

    buckets = _bucket_sequence(start, end, mode)
    sales_trend = [
        {
            "date": bucket,
            "sales": _money(sales_by_bucket[bucket]),
            "cash_collections": _money(collections_by_bucket[bucket]),
        }
        for bucket in buckets
    ]
    costs_profit = [
        {
            "date": bucket,
            "sales": _money(sales_by_bucket[bucket]),
            "recorded_costs": _money(costs_by_bucket[bucket]),
            "actual_period_result": _money(sales_by_bucket[bucket] - costs_by_bucket[bucket]),
        }
        for bucket in buckets
    ]
    feed_trend = [
        {
            "date": bucket,
            "feed_issued_kg": feed_by_bucket[bucket].quantize(Decimal("0.001")),
            "by_stage": {
                key: value.quantize(Decimal("0.001"))
                for key, value in feed_stage_by_bucket[bucket].items()
            },
        }
        for bucket in buckets
    ]
    growth = [
        {
            "batch": sample.batch_id,
            "batch_id": next(batch.batch_id for batch in selected_batches if batch.pk == sample.batch_id),
            "sampled_at": sample.sampled_at,
            "age_in_days": sample.age_in_days,
            "average_weight_g": sample.average_weight_g,
            "sample_size": sample.sample_size,
            "target_weight_g": get_target_weight_g(
                sample.age_in_days,
                get_broiler_strain_for_batch(next(batch for batch in selected_batches if batch.pk == sample.batch_id)),
            ),
        }
        for sample in weight_samples
    ]

    latest_sample = max(weight_samples, key=lambda row: (row.sampled_at, row.pk)) if weight_samples else None
    total_bird_days = sum(
        (bird_days_between(batch, max(start_at, batch.entry_date), end_at) for batch in selected_batches),
        Decimal("0.0000"),
    )
    feed_per_bird_day_g = (
        (period_feed * Decimal("1000") / total_bird_days).quantize(Decimal("0.01"))
        if total_bird_days > 0 and period_feed > 0
        else None
    )

    alerts = []
    for row in rows:
        if row["mortality_period"] and mortality_denominator:
            if _percentage(row["mortality_period"], mortality_denominator) >= Decimal("5.00"):
                alerts.append({"batch": row["id"], "batch_id": row["batch_id"], "message": "Period mortality needs review."})
        if row["status"] in PRODUCTION_STATUSES and row["latest_growth"] is None:
            alerts.append({"batch": row["id"], "batch_id": row["batch_id"], "message": "No weight sample exists in the selected period."})

    return {
        "generated_at": now,
        "filters": {
            "date_from": start,
            "date_to": end,
            "bird_type": bird_type,
            "stage": stage,
            "feed_stage": feed_stage,
            "batch_ids": batch_ids,
        },
        "available_feed_stages": [value for value, _ in FeedType.choices],
        "available_batches": [
            {
                "id": batch.pk,
                "batch_id": batch.batch_id,
                "bird_type": batch.bird_type,
                "status": batch.status,
            }
            for batch in all_batches
        ],
        "calculation_basis": (
            "Current birds are measured at the selected end date. Period mortality rate uses birds on farm "
            "at period start plus approved incoming adjustments. Feed is issued, not measured consumption."
        ),
        "overview": {
            "current_birds": current_birds,
            "birds_sold": period_sold,
            "sales": period_sales,
            "cash_collections": period_collections,
            "feed_issued_kg": period_feed,
            "deaths": period_deaths,
            "mortality_rate_percent": _percentage(period_deaths, mortality_denominator),
            "mortality_denominator": mortality_denominator,
            "latest_average_weight_g": latest_sample.average_weight_g if latest_sample else None,
            "latest_weight_date": latest_sample.sampled_at if latest_sample else None,
            "latest_weight_sample_size": latest_sample.sample_size if latest_sample else None,
            "feed_per_bird_day_g": feed_per_bird_day_g,
            "bird_days": total_bird_days.quantize(Decimal("0.01")),
            "feed_conversion_ratio": None,
            "feed_conversion_note": (
                "Unavailable: feed records measure feed issued, not confirmed consumption. "
                "Compatible opening and closing live-weight gain is also required."
            ),
        },
        "sales_growth": {
            "current_sales": period_sales,
            "previous_sales": previous_sales,
            "change_percent": (
                _percentage(period_sales - previous_sales, previous_sales)
                if previous_sales > 0
                else None
            ),
            "message": "No previous sales" if previous_sales == 0 else "",
            "previous_period_start": previous_start,
            "previous_period_end": previous_end,
        },
        "series": {
            "bucket": mode,
            "sales": sales_trend,
            "costs_and_profit": costs_profit,
            "feed": feed_trend,
            "growth": growth,
        },
        "cost_breakdown": {
            key: _money(value)
            for key, value in cost_breakdown.items()
        },
        "batches": rows,
        "alerts": alerts,
    }
