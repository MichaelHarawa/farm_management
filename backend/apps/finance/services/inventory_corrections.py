"""Explicit managed stock corrections; NOT public/mobile commands yet.

Stream/intent -> dated period -> beneficiary batch -> item/pool -> locations
(sorted PK) -> lot/location stock -> original issue/evidence. Item is the mutex
for every quantity/value mutation. Returns recover the original issue's remaining
cost, never today's average. Losses use the current weighted-average pool. No
correction changes supplier debt/cash or overwrites a usage/movement.
"""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch
from apps.poultry.services.batch_lifecycle import assert_batch_in_production
from ..models import (ConsumableUsageScope, InventoryLocationStock, InventoryLotBinding,
    InventoryMovementEvidence, SharedConsumableLot, StockMovement, StockMovementType)
from ..permissions import FINANCE_WRITE_ROLES, FINANCE_MANAGEMENT_ROLES
from .financial_capture import _identifier, _submission
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .inventory_capture import (_advance, _day, _item, _location, _movement, _pool,
    _required_text, stock_quantity, ZERO, CENT)
from .ledger import post_journal


def _stock(lot_id, day, location_ids):
    binding = InventoryLotBinding.objects.filter(lot_id=lot_id).first()
    if binding is None:
        raise ValidationError({"legacy_reconciliation": "Only explicitly managed stock supports corrections."})
    item = _item(binding.item_id)
    pool = _pool(item, day)
    locations = {pk: _location(pk) for pk in sorted(set(location_ids))}
    lot = SharedConsumableLot.objects.select_for_update().get(pk=lot_id)
    if day < lot.purchase_date:
        raise ValidationError({"movement_date": "A stock movement cannot precede its purchase."})
    return binding, item, pool, lot, locations


def _location_stock(binding, location, *, create=False):
    stock = InventoryLocationStock.objects.select_for_update().filter(binding=binding, location=location).first()
    if stock is None and create:
        # Item mutex already held: no competing balance can be inserted here.
        stock = InventoryLocationStock.objects.create(binding=binding, location=location)
    return stock


def _cost(value, quantity, available):
    if quantity == available:
        return value
    with localcontext() as context:
        context.prec = 40
        return (value * quantity / available).quantize(CENT, rounding=ROUND_HALF_EVEN)


def _journal(movement, user, *, returning=False):
    if movement.total_cost == ZERO:
        return None
    account = "5000" if movement.batch_id else "6100"
    amount = movement.total_cost
    lines = ([{"account": "1200", "debit": amount, "batch_id": movement.batch_id},
              {"account": account, "credit": amount, "batch_id": movement.batch_id}]
             if returning else
             [{"account": account, "debit": amount}, {"account": "1200", "credit": amount}])
    return post_journal(posting_date=movement.movement_date,
        description=f"Inventory {movement.movement_type} {movement.item.sku}",
        source_model="finance.StockMovement", source_identifier=movement.pk,
        idempotency_key=movement.idempotency_key, user=user, lines=lines)


def record_inventory_return(*, submission_id, user, original_issue_id, location_id,
                            movement_date, quantity, reason):
    original_issue_id = _identifier(original_issue_id, "original_issue_id")
    location_id = _identifier(location_id, "location_id")
    movement_date = _day(movement_date, "movement_date")
    quantity = stock_quantity(quantity)
    reason = _required_text(reason, "reason", 255)

    def effect(actor):
        lock_financial_periods(movement_date)
        original = StockMovement.objects.select_related("usage").filter(pk=original_issue_id,
            movement_type=StockMovementType.ISSUE, idempotency_key__startswith="inventory-issue:").first()
        if original is None or original.usage_id is None:
            raise ValidationError({"original_issue": "Select the original verified inventory issue."})
        if movement_date < original.movement_date:
            raise ValidationError({"movement_date": "Return cannot precede its original issue."})
        if original.batch_id:
            batch = Batch.objects.select_for_update().get(pk=original.batch_id)
            try:
                assert_batch_in_production(batch)
            except ValueError as error:
                raise ValidationError({"batch": str(error)})
            if batch.profitability_finalized_at or batch.profitability_snapshots.filter(final=True).exists():
                raise ValidationError({"batch": "Closed/finalized batch costs require controlled review, not a stock return."})
        if (original.usage.usage_scope != (ConsumableUsageScope.BATCH_DIRECT if original.batch_id else ConsumableUsageScope.ADMINISTRATION)
                or original.usage.batch_id != original.batch_id):
            raise ValidationError({"original_issue": "The original cost beneficiary needs reconciliation."})
        binding, item, pool, lot, locations = _stock(original.lot_id, movement_date, [location_id])
        if original.item_id != item.pk or original.usage.consumable_lot_id != lot.pk:
            raise ValidationError({"original_issue": "Original item/lot evidence needs reconciliation."})
        # Re-read original immutable evidence only after the item mutex. Every
        # competing return/issue/loss now sees the preceding committed balance.
        original = StockMovement.objects.select_for_update().get(pk=original_issue_id)
        prior = list(InventoryMovementEvidence.objects.filter(original_issue=original)
            .values_list("movement__quantity", "movement__total_cost"))
        remaining = original.quantity - sum((q for q, _ in prior), Decimal("0.0000"))
        value = original.total_cost - sum((c for _, c in prior), ZERO)
        if quantity > remaining or remaining <= ZERO or value < ZERO:
            raise ValidationError({"quantity": "Return exceeds the original issue's unreturned quantity/cost."})
        cost = _cost(value, quantity, remaining)
        movement = _movement(kind=StockMovementType.RETURN, day=movement_date, item=item, lot=lot,
            destination=locations[location_id], batch=original.batch, quantity=quantity, cost=cost,
            key=f"inventory-return:{submission_id}", user=actor, reason=reason)
        InventoryMovementEvidence.objects.create(movement=movement, original_issue=original)
        journal = _journal(movement, actor, returning=True)
        stock = _location_stock(binding, locations[location_id], create=True)
        stock.quantity += quantity
        stock.save(update_fields=["quantity", "updated_at"])
        lot.quantity_available += quantity
        lot.save(update_fields=["quantity_available", "updated_at"])
        pool.quantity += quantity
        pool.carrying_value += cost
        _advance(pool, movement_date)
        return {"movement_id": str(movement.pk), "journal_id": str(journal.pk) if journal else None}

    result, created = _submission(submission_id=submission_id, user=user, command="inventory.return.record",
        payload=dict(original_issue_id=str(original_issue_id), location_id=str(location_id),
            movement_date=movement_date, quantity=quantity, reason=reason), roles=FINANCE_WRITE_ROLES, effect=effect)
    return StockMovement.objects.get(pk=result["movement_id"]), created


def record_inventory_transfer(*, submission_id, user, lot_id, from_location_id, to_location_id,
                              movement_date, quantity, reason):
    lot_id = _identifier(lot_id, "lot_id")
    from_location_id = _identifier(from_location_id, "from_location_id")
    to_location_id = _identifier(to_location_id, "to_location_id")
    if from_location_id == to_location_id:
        raise ValidationError({"location": "Choose two different stock locations."})
    movement_date = _day(movement_date, "movement_date")
    quantity = stock_quantity(quantity)
    reason = _required_text(reason, "reason", 255)

    def effect(actor):
        lock_financial_periods(movement_date)
        binding, item, pool, lot, locations = _stock(lot_id, movement_date, [from_location_id, to_location_id])
        if lot.expiry_date and movement_date > lot.expiry_date:
            raise ValidationError({"expiry_date": "Expired stock requires expiry review, not an ordinary transfer."})
        source = _location_stock(binding, locations[from_location_id])
        if source is None or quantity > source.quantity or quantity > pool.quantity or quantity > lot.quantity_available:
            raise ValidationError({"insufficient_stock": "Transfer exceeds confirmed stock at its source location."})
        destination = _location_stock(binding, locations[to_location_id], create=True)
        # The carried-cost display is evidence, not expense or a pool-value change.
        cost = _cost(pool.carrying_value, quantity, pool.quantity)
        movement = _movement(kind=StockMovementType.TRANSFER, day=movement_date, item=item, lot=lot,
            source=locations[from_location_id], destination=locations[to_location_id], quantity=quantity,
            cost=cost, key=f"inventory-transfer:{submission_id}", user=actor, reason=reason)
        InventoryMovementEvidence.objects.create(movement=movement)
        source.quantity -= quantity
        destination.quantity += quantity
        source.save(update_fields=["quantity", "updated_at"])
        destination.save(update_fields=["quantity", "updated_at"])
        _advance(pool, movement_date)
        return {"movement_id": str(movement.pk), "journal_id": None}

    result, created = _submission(submission_id=submission_id, user=user, command="inventory.transfer.record",
        payload=dict(lot_id=str(lot_id), from_location_id=str(from_location_id), to_location_id=str(to_location_id),
            movement_date=movement_date, quantity=quantity, reason=reason), roles=FINANCE_WRITE_ROLES, effect=effect)
    return StockMovement.objects.get(pk=result["movement_id"]), created


def _loss(*, submission_id, user, lot_id, location_id, movement_date, quantity, reason, kind,
          counted_quantity=None, expected_revision=None):
    lot_id = _identifier(lot_id, "lot_id")
    location_id = _identifier(location_id, "location_id")
    movement_date = _day(movement_date, "movement_date")
    reason = _required_text(reason, "reason", 255)
    adjustment = kind == StockMovementType.ADJUSTMENT
    quantity = stock_quantity(quantity) if not adjustment else None
    if adjustment:
        counted_quantity = exact_decimal(counted_quantity, scale=4, max_digits=14, field="counted_quantity")
        expected_revision = _identifier(expected_revision, "expected_revision")

    def effect(actor):
        lock_financial_periods(movement_date)
        binding, item, pool, lot, locations = _stock(lot_id, movement_date, [location_id])
        if adjustment and pool.revision != expected_revision:
            raise ValidationError({"expected_revision": "Stock changed since this count; preserve the count for review."})
        expired = lot.expiry_date and movement_date > lot.expiry_date
        if kind == StockMovementType.EXPIRY and not expired:
            raise ValidationError({"expiry_date": "Expiry requires a recorded expiry date before this movement date."})
        if kind == StockMovementType.WASTE and expired:
            raise ValidationError({"expiry_date": "Expired stock uses the explicit expiry workflow."})
        stock = _location_stock(binding, locations[location_id])
        if stock is None:
            raise ValidationError({"location": "This lot has no confirmed stock at the selected location."})
        removed = stock.quantity - counted_quantity if adjustment else quantity
        if adjustment and removed <= ZERO:
            raise ValidationError({"counted_quantity": "No loss exists, or stock increased without a verified source/valuation. Preserve evidence for review."})
        if removed > stock.quantity or removed > pool.quantity or removed > lot.quantity_available:
            raise ValidationError({"insufficient_stock": "Loss exceeds confirmed stock at this location."})
        cost = _cost(pool.carrying_value, removed, pool.quantity)
        movement = _movement(kind=kind, day=movement_date, item=item, lot=lot, source=locations[location_id],
            quantity=removed, cost=cost, key=f"inventory-{kind}:{submission_id}", user=actor, reason=reason)
        InventoryMovementEvidence.objects.create(movement=movement,
            expected_quantity=stock.quantity if adjustment else None, counted_quantity=counted_quantity if adjustment else None)
        journal = _journal(movement, actor)
        stock.quantity -= removed
        stock.save(update_fields=["quantity", "updated_at"])
        lot.quantity_available -= removed
        lot.save(update_fields=["quantity_available", "updated_at"])
        pool.quantity -= removed
        pool.carrying_value -= cost
        _advance(pool, movement_date)
        return {"movement_id": str(movement.pk), "journal_id": str(journal.pk) if journal else None}

    result, created = _submission(submission_id=submission_id, user=user, command=f"inventory.{kind}.record",
        payload=dict(lot_id=str(lot_id), location_id=str(location_id), movement_date=movement_date,
            quantity=quantity, reason=reason, counted_quantity=counted_quantity, expected_revision=expected_revision),
        roles=FINANCE_WRITE_ROLES if kind == StockMovementType.WASTE else FINANCE_MANAGEMENT_ROLES, effect=effect)
    return StockMovement.objects.get(pk=result["movement_id"]), created


def record_inventory_waste(*, submission_id, user, lot_id, location_id, movement_date, quantity, reason):
    return _loss(submission_id=submission_id, user=user, lot_id=lot_id, location_id=location_id,
        movement_date=movement_date, quantity=quantity, reason=reason, kind=StockMovementType.WASTE)


def record_inventory_expiry(*, submission_id, user, lot_id, location_id, movement_date, quantity, reason):
    return _loss(submission_id=submission_id, user=user, lot_id=lot_id, location_id=location_id,
        movement_date=movement_date, quantity=quantity, reason=reason, kind=StockMovementType.EXPIRY)


def record_inventory_count_loss(*, submission_id, user, lot_id, location_id, movement_date,
                                counted_quantity, expected_revision, reason):
    return _loss(submission_id=submission_id, user=user, lot_id=lot_id, location_id=location_id,
        movement_date=movement_date, quantity=None, reason=reason, kind=StockMovementType.ADJUSTMENT,
        counted_quantity=counted_quantity, expected_revision=expected_revision)
