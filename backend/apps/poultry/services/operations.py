"""Shared operational write boundary; no inventory, cash or cost effects.

Lock order: sync stream -> dated periods (PK order) -> batch -> source row.
Callers must not acquire domain locks before entering these services.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.mobile_sync.validation import FARM_ZONE
from apps.mobile_sync.writers import sync_atomic
from apps.poultry.models import (Batch, BatchStatus, BatchWeightSample, DrugsVaccination,
                                 FlockAdjustmentProposal)


def lock_periods(*instants):
    from apps.finance.models import AccountingPeriod, PeriodStatus
    days = [at.astimezone(FARM_ZONE).date() for at in instants]
    periods = list(AccountingPeriod.objects.select_for_update().filter(
        period_start__lte=max(days), period_end__gte=min(days)).order_by("pk"))
    if any(period.status == PeriodStatus.CLOSED for period in periods):
        raise ValidationError({"period_locked": "Original business date belongs to a closed accounting period."})


def validate_event(batch, at, field):
    from .batch_lifecycle import assert_batch_in_production
    assert_batch_in_production(batch)
    if batch.profitability_finalized_at or batch.profitability_snapshots.filter(final=True).exists():
        raise ValidationError({"period_locked": "Batch profitability is finalized."})
    if at < batch.entry_date or at > timezone.now() + timedelta(minutes=5):
        raise ValidationError({field: "Event must be after arrival and cannot be in the future."})
    return (at.astimezone(FARM_ZONE).date() - batch.entry_date.astimezone(FARM_ZONE).date()).days


def validate_population_history(batch, *, at=None, change=0, field="quantity_change"):
    """Validate all later balances, including feed and sample prerequisites.

    Events at the same timestamp net before observations, as in live_birds_at.
    Cancelled sales and eggs/manure do not consume birds. Proposals are excluded.
    """
    from collections import defaultdict
    from apps.poultry.models import FeedUsage, FlockAdjustment, Mortality, Sales
    from .batch_lifecycle import BIRD_PRODUCT_TYPES
    from .feed_metrics import actual_birds_received
    grouped = defaultdict(int)
    for event_at, qty in Mortality.objects.filter(batch=batch).values_list("mortality_date", "quantity_dead"):
        grouped[event_at] -= qty
    for event_at, qty in Sales.objects.filter(batch=batch, product_type__in=BIRD_PRODUCT_TYPES).exclude(
            payment_status="cancelled").values_list("sale_date", "quantity_sold"):
        grouped[event_at] -= qty
    for event_at, qty in FlockAdjustment.objects.filter(batch=batch, status="approved").values_list("effective_at", "quantity_change"):
        grouped[event_at] += qty
    if at is not None:
        grouped[at] += change
    observations = defaultdict(lambda: 0)
    for event_at in FeedUsage.objects.filter(batch=batch).values_list("feeding_start_date", flat=True):
        observations[event_at] = max(observations[event_at], 1)
    for event_at in DrugsVaccination.objects.filter(batch=batch).values_list("vaccination_date", flat=True):
        observations[event_at] = max(observations[event_at], 1)
    for event_at, size in BatchWeightSample.objects.filter(batch=batch).values_list("sampled_at", "sample_size"):
        observations[event_at] = max(observations[event_at], size)
    balance = actual_birds_received(batch)
    for event_at in sorted(set(grouped) | set(observations)):
        balance += grouped[event_at]
        if balance < 0 or balance < observations[event_at]:
            raise ValidationError({field: ValidationError(
                "Event would invalidate a dated flock/feed/sample balance.", code="insufficient_birds")})


@sync_atomic
@transaction.atomic
def register_batch(*, created_by, **data):
    from .batch_lifecycle import recalculate_batch_status
    if data.get("booking_date"):
        if data.get("estimated_chick_arrival_date") and data["estimated_chick_arrival_date"] < data["booking_date"]:
            raise ValidationError({"estimated_chick_arrival_date": "Arrival cannot precede booking."})
        # Older ordinary web callers used quantity for a booking. Preserve that
        # input as EXPECTED chicks only; it must never establish a received flock.
        if "expected_quantity" not in data:
            data["expected_quantity"] = data.get("quantity")
        if not data.get("expected_quantity") or data["expected_quantity"] <= 0:
            raise ValidationError({"expected_quantity": "Expected quantity must be positive."})
        # A booking is not a received flock. Confirmation alone sets arrivals.
        data.update(quantity=0, actual_quantity_received=None, status=BatchStatus.BOOKED)
    if data.get("source") == "other" and not (data.get("source_other") or "").strip():
        raise ValidationError({"source_other": "Enter the source name."})
    batch = Batch(created_by=created_by, **data)
    # The server allocates the official reference in Batch.save, not on a device.
    batch.full_clean(exclude=["batch_id"])
    batch.save()
    recalculate_batch_status(batch)
    return batch


@sync_atomic
@transaction.atomic
def mark_delivered(*, batch_id):
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    if batch.status != BatchStatus.BOOKED:
        raise ValidationError({"status": "Only booked batches can be marked delivered."})
    batch.status = BatchStatus.DELIVERED
    batch.delivery_confirmed_at = timezone.now()
    batch.save(update_fields=["status", "delivery_confirmed_at", "updated_at"])
    return batch


@sync_atomic
@transaction.atomic
def confirm_delivery(*, batch_id, entry_date, expected_maturity_date=None, quantity=None):
    from .batch_lifecycle import recalculate_batch_status
    lock_periods(entry_date)
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    if batch.status != BatchStatus.DELIVERED:
        raise ValidationError({"status": "Mark the booked chicks delivered before confirming actual arrival."})
    if entry_date > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"entry_date": "Actual arrival cannot be in the future."})
    received = quantity if quantity is not None else batch.quantity
    if received <= 0:
        raise ValidationError({"quantity": "Confirm a positive actual arrival quantity."})
    maturity = expected_maturity_date or entry_date + timedelta(days=46)
    if maturity <= entry_date:
        raise ValidationError({"expected_maturity_date": "Maturity must be after arrival."})
    batch.entry_date, batch.expected_maturity_date = entry_date, maturity
    batch.quantity = batch.actual_quantity_received = received
    batch.expected_quantity = batch.expected_quantity or received
    batch.status = BatchStatus.PLANNED
    batch.full_clean()
    batch.save()
    recalculate_batch_status(batch)
    return batch


@sync_atomic
@transaction.atomic
def record_treatment(*, batch_id, created_by, **data):
    from .feed_metrics import live_birds_at
    lock_periods(data["vaccination_date"])
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    validate_event(batch, data["vaccination_date"], "vaccination_date")
    if live_birds_at(batch, data["vaccination_date"]) <= 0:
        raise ValidationError({"vaccination_date": "No live birds at this event date."})
    if data["quantity"] <= 0:
        raise ValidationError({"quantity": "Quantity must be positive."})
    if data["drug_vaccination_type"] == "other" and not data.get("other_drug_vaccination", "").strip():
        raise ValidationError({"other_drug_vaccination": "Specify the treatment name."})
    data.setdefault("other_drug_vaccination", "")
    record = DrugsVaccination(batch=batch, created_by=created_by, **data)
    record.full_clean(exclude=["other_drug_vaccination"] if not data["other_drug_vaccination"] else [])
    record.save()
    return record


@sync_atomic
@transaction.atomic
def record_weight(*, batch_id, created_by, **data):
    from .feed_metrics import live_birds_at
    lock_periods(data["sampled_at"])
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    data["age_in_days"] = validate_event(batch, data["sampled_at"], "sampled_at")
    if data["sample_size"] > live_birds_at(batch, data["sampled_at"]):
        raise ValidationError({"sample_size": "Sample cannot exceed the dated live flock."})
    sample = BatchWeightSample(batch=batch, created_by=created_by, **data)
    sample.full_clean()
    sample.save()
    return sample


@sync_atomic
@transaction.atomic
def propose_adjustment(*, batch_id, created_by, **data):
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    # Evidence can be retained even when its original period is now closed;
    # approval rechecks all dated/period rules and can refuse it without redating.
    validate_event(batch, data["effective_at"], "effective_at")
    proposal = FlockAdjustmentProposal(batch=batch, created_by=created_by, **data)
    proposal.full_clean()
    proposal.save()
    return proposal


@sync_atomic
@transaction.atomic
def review_adjustment(*, proposal_id, reviewed_by, approve, reason):
    from .feed_metrics import create_flock_adjustment
    original = FlockAdjustmentProposal.objects.get(pk=proposal_id)
    if approve:
        lock_periods(original.effective_at)
    Batch.objects.select_for_update().get(pk=original.batch_id)
    proposal = FlockAdjustmentProposal.objects.select_for_update().get(pk=proposal_id)
    if proposal.status != "pending":
        raise ValidationError({"status": "Proposal has already been reviewed."})
    if not reason.strip():
        raise ValidationError({"reason": "Review reason is required."})
    if approve:
        proposal.adjustment = create_flock_adjustment(batch_id=proposal.batch_id, approved_by=reviewed_by,
            effective_at=proposal.effective_at, quantity_change=proposal.quantity_change, reason=proposal.reason)
    proposal.status = "approved" if approve else "rejected"
    proposal.reviewed_by, proposal.review_reason = reviewed_by, reason
    proposal.save()
    return proposal
