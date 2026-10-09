"""Unregistered Phase6 composites: observation + one valued stock consumption.

No mobile capability, legacy auto-link, duplicate input cost or client valuation.
The internal flag is off until explicitly enabled in a migrated test deployment.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.validation import FARM_ZONE
from apps.poultry.models import Batch, FeedType, FeedSource, DrugCategory, DrugVaccinationType
from apps.poultry.services.feed_metrics import record_feed_usage
from apps.poultry.services.operations import lock_periods, record_treatment
from ..models import (AccountingPeriod, ConsumableUsageScope,
    InventoryLotBinding, PoultryStockConsumption, PoultryStockItemPolicy, PoultryStockKind)
from ..permissions import FINANCE_MANAGEMENT_ROLES, FINANCE_WRITE_ROLES
from .financial_capture import _identifier, _submission, _text
from .financial_values import business_date, lock_financial_periods
from .inventory_capture import _item, _issue_effect, _required_text, stock_quantity


def _enabled():
    if not settings.FINANCE_POULTRY_STOCK_LINKAGE:
        raise ValidationError({"stock_linkage": "Stock-backed poultry foundations are not enabled on this deployment."})


def _instant(value, field):
    if not isinstance(value, datetime) or timezone.is_naive(value) or value > timezone.now() + timedelta(minutes=5):
        raise ValidationError({field: "Record the actual timezone-aware observation instant."})
    return value


def _whole(value, field):
    if type(value) is not int or not 0 < value <= 2147483647:
        raise ValidationError({field: "Record a positive whole quantity in the explicit unit."})
    return value


def _choice(value, choices, field):
    if value not in choices:
        raise ValidationError({field: "Select a supported observed value."})
    return value


def configure_poultry_stock_item(*, submission_id, user, item_id, kind, reason):
    """Fresh management-only master setup; a future adapter must be online-only."""
    _enabled()
    item_id = _identifier(item_id, "item_id")
    kind = _choice(kind, PoultryStockKind.values, "kind")
    reason = _required_text(reason, "reason", 255)

    def effect(actor):
        item = _item(item_id)
        if PoultryStockItemPolicy.objects.filter(item=item).exists():
            raise ValidationError({"item": "This item already has an immutable classification; review the original setup."})
        policy = PoultryStockItemPolicy.objects.create(item=item, kind=kind, base_unit=item.base_unit,
            reason=reason, configured_by=actor)
        return {"policy_id": str(policy.pk)}

    result, created = _submission(submission_id=submission_id, command="inventory.poultry_item.configure",
        user=user, payload=dict(item_id=str(item_id), kind=kind, reason=reason), roles=FINANCE_MANAGEMENT_ROLES, effect=effect)
    return PoultryStockItemPolicy.objects.get(pk=result["policy_id"]), created


def _capture(*, submission_id, user, batch_id, lot_id, location_id, kind, data, unit):
    _enabled()
    batch_id = _identifier(batch_id, "batch_id")
    lot_id = _identifier(lot_id, "lot_id")
    location_id = _identifier(location_id, "location_id")
    instants = ([data["feeding_start_date"], data["feeding_end_date"]] if kind == PoultryStockKind.FEED
                else [data["vaccination_date"]])
    day = business_date(instants[0])

    def effect(actor):
        # Lock the union of financial UTC and farm-display period ranges once,
        # in PK order, BEFORE batch/item/pool/source locks. Later service locks
        # only reacquire held rows; crossing midnight cannot invert this order.
        days = [business_date(at) for at in instants] + [at.astimezone(FARM_ZONE).date() for at in instants]
        list(AccountingPeriod.objects.select_for_update().filter(
            period_start__lte=max(days), period_end__gte=min(days)).order_by("pk"))
        lock_financial_periods(day)
        lock_periods(*instants)
        batch = Batch.objects.select_for_update().filter(pk=batch_id).first()
        if batch is None:
            raise ValidationError({"batch": "Select the original production batch."})
        binding = InventoryLotBinding.objects.filter(lot_id=lot_id).first()
        if binding is None:
            raise ValidationError({"legacy_reconciliation": "Only a verified managed lot can back a new observation."})
        item = _item(binding.item_id)
        policy = PoultryStockItemPolicy.objects.filter(item=item, kind=kind).first()
        if policy is None or policy.base_unit != item.base_unit:
            raise ValidationError({"item": "Current explicit poultry classification and unit evidence are required; names/categories are not guessed."})
        quantity = Decimal(data["quantity_given"] if kind == PoultryStockKind.FEED else data["quantity"])
        if kind == PoultryStockKind.FEED:
            if policy.base_unit not in {"g", "kg"}:
                raise ValidationError({"unit": "Verified grams/kilograms only; no assumed bag weight."})
            if unit != policy.base_unit:
                quantity *= Decimal("0.001") if unit == "g" else Decimal("1000")
        elif unit != policy.base_unit:
            raise ValidationError({"quantity_unit": "Treatment quantity uses the explicit item base unit; no guessed strength/volume conversion."})
        quantity = stock_quantity(quantity)
        if kind == PoultryStockKind.FEED:
            record = record_feed_usage(batch_id=batch_id, created_by=actor, **data)
        else:
            evidence = f"\nStock-backed quantity: {data['quantity']} {unit}."
            description = _text(data["description"] + evidence, "description", 4000)
            record = record_treatment(batch_id=batch_id, created_by=actor, **{**data, "description": description})
        effect_result = _issue_effect(actor=actor, submission_id=submission_id, lot_id=lot_id,
            location_id=location_id, usage_date=day, quantity=quantity, batch_id=batch_id,
            usage_scope=ConsumableUsageScope.BATCH_DIRECT,
            task_or_purpose=f"Stock-backed poultry {kind}: {record.pk}")
        consumption = PoultryStockConsumption.objects.create(usage_id=effect_result["usage_id"],
            policy=policy, quantity_unit=unit, **({"feed": record} if kind == PoultryStockKind.FEED else {"treatment": record}))
        return {**effect_result, "consumption_id": str(consumption.pk), "observation_id": str(record.pk), "kind": kind}

    result, created = _submission(submission_id=submission_id, command=f"poultry.{kind}.record_stock_backed",
        user=user, roles=FINANCE_WRITE_ROLES, effect=effect,
        payload=dict(batch_id=str(batch_id), lot_id=str(lot_id), location_id=str(location_id),
            kind=kind, observation=data, quantity_unit=unit))
    return PoultryStockConsumption.objects.select_related("feed", "treatment", "usage").get(pk=result["consumption_id"]), created


def record_stock_backed_feed(*, submission_id, user, batch_id, lot_id, location_id,
                            feeding_start_date, feeding_end_date, feed_type, feed_source,
                            quantity_given, unit_of_measurement, notes, reported_by_name):
    data = dict(feeding_start_date=_instant(feeding_start_date, "feeding_start_date"),
        feeding_end_date=_instant(feeding_end_date, "feeding_end_date"),
        feed_type=_choice(feed_type, FeedType.values, "feed_type"),
        feed_source=_choice(feed_source, FeedSource.values, "feed_source"),
        quantity_given=_whole(quantity_given, "quantity_given"),
        unit_of_measurement=_choice(unit_of_measurement, {"g", "kg"}, "unit_of_measurement"),
        notes=_text(notes, "notes", 4000), reported_by_name=_required_text(reported_by_name, "reported_by_name", 200))
    return _capture(submission_id=submission_id, user=user, batch_id=batch_id, lot_id=lot_id,
        location_id=location_id, kind=PoultryStockKind.FEED, data=data, unit=unit_of_measurement)


def record_stock_backed_treatment(*, submission_id, user, batch_id, lot_id, location_id,
                                 vaccination_date, drug_category, drug_vaccination_type, quantity,
                                 quantity_unit, description, timely_status, reported_by_name, other_drug_vaccination=""):
    data = dict(vaccination_date=_instant(vaccination_date, "vaccination_date"),
        drug_category=_choice(drug_category, DrugCategory.values, "drug_category"),
        drug_vaccination_type=_choice(drug_vaccination_type, DrugVaccinationType.values, "drug_vaccination_type"),
        other_drug_vaccination=_text(other_drug_vaccination, "other_drug_vaccination", 200),
        quantity=_whole(quantity, "quantity"), description=_required_text(description, "description", 3900),
        timely_status=_required_text(timely_status, "timely_status", 200),
        reported_by_name=_required_text(reported_by_name, "reported_by_name", 200))
    return _capture(submission_id=submission_id, user=user, batch_id=batch_id, lot_id=lot_id,
        location_id=location_id, kind=PoultryStockKind.TREATMENT, data=data,
        unit=_required_text(quantity_unit, "quantity_unit", 40))
