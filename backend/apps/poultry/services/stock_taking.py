"""Web physical counts, reconciled atomically through the flock ledger."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.mobile_sync.writers import sync_atomic
from apps.poultry.models import Batch, BirdStockTake
from .batch_lifecycle import calculate_bird_balance
from .feed_metrics import create_flock_adjustment
from .operations import lock_periods, validate_event


@sync_atomic
@transaction.atomic
def record_stock_take(*, batch_id, recorded_by, request_id, expected_live_birds,
                      physical_count, reason="", notes=""):
    reason, notes = reason.strip(), notes.strip()

    def replay():
        existing = BirdStockTake.objects.filter(batch_id=batch_id, request_id=request_id).first()
        if existing and (
            existing.expected_live_birds != expected_live_birds
            or existing.physical_count != physical_count
            or existing.reason != reason or existing.notes != notes
            or existing.recorded_by_id != recorded_by.pk
        ):
            raise ValidationError({"request_id": "This request was already used for a different count."})
        return existing

    # A retry remains successful even if this count closed the batch or period.
    existing = replay()
    if existing:
        return existing
    counted_at = timezone.now()
    lock_periods(counted_at)
    batch = Batch.objects.select_for_update().get(pk=batch_id)
    existing = replay()
    if existing:
        return existing
    validate_event(batch, counted_at, "counted_at")
    expected = calculate_bird_balance(batch).remaining_live_birds
    if expected != expected_live_birds:
        raise ValidationError({
            "expected_live_birds": (
                f"Live birds changed to {expected}. Refresh the batch and verify the physical count before saving."
            ),
        })
    record = BirdStockTake(
        batch=batch, recorded_by=recorded_by, request_id=request_id,
        counted_at=counted_at, expected_live_birds=expected, physical_count=physical_count,
        reason=reason, notes=notes,
    )
    record.full_clean()
    if record.variance:
        if not reason:
            raise ValidationError({"reason": "Explain the shortage or surplus before confirming the count."})
        record.adjustment = create_flock_adjustment(
            batch_id=batch.pk, approved_by=recorded_by, effective_at=counted_at,
            quantity_change=record.variance, reason=reason,
        )
    record.save()
    return record
