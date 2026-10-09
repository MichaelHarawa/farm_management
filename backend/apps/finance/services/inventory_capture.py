"""Unregistered Phase6 inventory purchase/issue foundations.

Only new explicitly managed lots enter the existing policy's moving weighted-
average pool. No historical import, fictional opening balance, FIFO fallback,
client cost authority or automatic financial upload. All-writer/native gates
remain prerequisites to publishing these commands.
"""
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json

from django.db import connection
from django.db.models import F, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import Batch
from apps.poultry.services.batch_lifecycle import assert_batch_in_production
from ..models import (AccountingNature, AllocationMethod, ConsumableItem,
    ConsumableUsage, ConsumableUsageScope, Expenditure, ExpenditureCategory,
    ExpenditurePaymentStatus, FinancePaymentStatus, InventoryCostingMethod,
    InventoryLocation, InventoryLocationStock, InventoryLotBinding, InventoryValuePool, InventoryMovementEvidence,
    SharedConsumableLot, StockMovement, StockMovementType)
from ..permissions import FINANCE_WRITE_ROLES
from .expenditures import post_expenditure, record_expenditure_payment
from .financial_capture import _currency, _funding_rows, _identifier, _submission, _text
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .ledger import post_journal

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def stock_quantity(value):
    return exact_decimal(value, scale=4, max_digits=14, positive=True, field="quantity")


def _day(value, field):
    day = business_date(value, field=field)
    if day > timezone.localdate():
        raise ValidationError({field: "Record the actual accounting date, not a future event."})
    return day


def _required_text(value, field, limit):
    value = _text(value, field, limit)
    if not value:
        raise ValidationError({field: "Record the physical evidence for this movement."})
    return value


def _item(item_id):
    item = ConsumableItem.objects.select_for_update().filter(pk=item_id, is_active=True).first()
    if item is None:
        raise ValidationError({"item": "Select an active inventory item."})
    if item.costing_method != InventoryCostingMethod.WEIGHTED_AVERAGE:
        raise ValidationError({"costing_method": "Only the existing weighted-average policy is verified; FIFO is unavailable."})
    return item


def _location(location_id):
    location = InventoryLocation.objects.select_for_update().filter(pk=location_id, is_active=True).first()
    if location is None:
        raise ValidationError({"location": "Select an active inventory location."})
    return location


def _pool(item, day, *, create=False):
    # The item row is the mutex before a pool exists. Legacy SKU derivation is
    # used only to REFUSE an unresolved overlap, never to bind/import old rows.
    pool = InventoryValuePool.objects.select_for_update().filter(item=item).first()
    legacy = SharedConsumableLot.objects.filter(inventory_binding__isnull=True)
    if any(lot.item.casefold() == item.name.casefold() or
           ("ITEM-" + "-".join(lot.item.upper().split())[:32]) == item.sku for lot in legacy.iterator()):
        raise ValidationError({"legacy_reconciliation": "Existing unlinked stock for this item requires an explicit opening-balance reconciliation."})
    if pool is None:
        if not create:
            raise ValidationError({"lot": "This stock has no verified valuation pool."})
        pool = InventoryValuePool.objects.create(item=item, last_movement_date=day)
    if day < pool.last_movement_date:
        raise ValidationError({"stock_chronology": "Earlier stock dates require review; the original date must not be changed automatically."})
    _check_pool(pool)
    return pool


def _check_pool(pool):
    links = InventoryLotBinding.objects.filter(item_id=pool.item_id)
    quantities = list(links.values_list("pk", "lot_id", "lot__quantity_available"))
    location_rows = list(InventoryLocationStock.objects.filter(binding__in=links).values(
        "binding_id", "binding__lot_id", "location_id", "quantity"))
    locations = {}
    for row in location_rows:
        locations[row["binding_id"]] = locations.get(row["binding_id"], ZERO) + row["quantity"]
    if any(locations.get(pk, ZERO) != quantity for pk, _, quantity in quantities) or sum((q for _, _, q in quantities), ZERO) != pool.quantity:
        raise ValidationError({"inventory_reconciliation": "Lot, location and valuation quantities disagree; preserve evidence for review."})
    if pool.carrying_value < ZERO or pool.quantity < ZERO or (pool.quantity == ZERO and pool.carrying_value != ZERO):
        raise ValidationError({"inventory_reconciliation": "Invalid inventory carrying balance requires review."})
    movements = StockMovement.objects.filter(lot_id__in=links.values('lot_id'))
    outgoing = [StockMovementType.ISSUE, StockMovementType.WASTE, StockMovementType.EXPIRY, StockMovementType.ADJUSTMENT]
    expected_locations = {}
    for direction, kinds, sign in [('to_location_id', [StockMovementType.RECEIPT, StockMovementType.RETURN, StockMovementType.TRANSFER], 1),
                                  ('from_location_id', outgoing + [StockMovementType.TRANSFER], -1)]:
        for row in movements.filter(movement_type__in=kinds).values('lot_id', direction).annotate(total=Sum('quantity')):
            key = (row['lot_id'], row[direction])
            expected_locations[key] = expected_locations.get(key, ZERO) + sign * row['total']
    actual_locations = {(row['binding__lot_id'], row['location_id']): row['quantity'] for row in location_rows}
    if any(actual_locations.get(key, ZERO) != expected_locations.get(key, ZERO)
            for key in actual_locations.keys() | expected_locations.keys()):
        raise ValidationError({"inventory_reconciliation": "Location balances differ from immutable stock movements; review is required."})
    physical_rows = movements.values('lot_id').annotate(
        received=Sum('quantity', filter=Q(movement_type__in=[StockMovementType.RECEIPT, StockMovementType.RETURN])),
        removed=Sum('quantity', filter=Q(movement_type__in=outgoing)))
    physical = {row['lot_id']: (row['received'] or ZERO) - (row['removed'] or ZERO) for row in physical_rows}
    if any(physical.get(lot_id, ZERO) != quantity for _, lot_id, quantity in quantities):
        raise ValidationError({"inventory_reconciliation": "Physical stock differs from immutable movement quantities; review is required."})
    values = movements.aggregate(receipts=Sum('total_cost', filter=Q(movement_type=StockMovementType.RECEIPT)),
        returns=Sum('total_cost', filter=Q(movement_type=StockMovementType.RETURN)),
        issues=Sum('total_cost', filter=Q(movement_type__in=outgoing)))
    corrections = movements.exclude(movement_type__in=[StockMovementType.RECEIPT, StockMovementType.ISSUE])
    if ((values['receipts'] or ZERO) + (values['returns'] or ZERO) - (values['issues'] or ZERO) != pool.carrying_value or
            corrections.filter(inventory_evidence__isnull=True).exists() or
            movements.filter(usage__isnull=False).exclude(usage__quantity_used=F('quantity')).exists() or
            movements.filter(usage__isnull=False).exclude(usage__recognized_cost=F('total_cost')).exists()):
        raise ValidationError({"inventory_reconciliation": "Movement, recognized-cost and carrying-value evidence disagree; review is required."})


def _advance(pool, day):
    pool.quantity = exact_decimal(pool.quantity, scale=4, max_digits=14, field="pool_quantity")
    pool.carrying_value = exact_decimal(pool.carrying_value, max_digits=16, field="carrying_value")
    pool.last_movement_date = day
    pool.revision += 1
    pool.save(update_fields=["quantity", "carrying_value", "last_movement_date", "revision", "updated_at"])
    _check_pool(pool)


def _movement(*, kind, day, item, lot, quantity, cost, key, user, usage=None,
              source=None, destination=None, batch=None, reason="", reference=""):
    with localcontext() as context:
        context.prec = 40
        unit_cost = exact_decimal((cost / quantity).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN),
                                  scale=6, max_digits=16, field="unit_cost")
    movement = StockMovement(movement_type=kind, movement_date=day, item=item,
        lot=lot, quantity=quantity, unit_cost=unit_cost, total_cost=cost, usage=usage,
        from_location=source, to_location=destination, batch=batch, reason=reason,
        reference=reference, idempotency_key=key, created_by=user)
    movement.full_clean()
    movement.save(_valued_cost=cost)
    return movement


def _sync_lot_payment(lot, expenditure):
    # The payable/payment ledger is the authority; never treat a dropdown as cash.
    lot.payment_status = {ExpenditurePaymentStatus.PAID: FinancePaymentStatus.PAID,
        ExpenditurePaymentStatus.PARTIAL: FinancePaymentStatus.PARTIAL}.get(
            expenditure.payment_status, FinancePaymentStatus.UNPAID)
    lot.payment_date = (expenditure.funding_allocations.order_by("allocation_date", "pk").last().allocation_date
                        if lot.payment_status == FinancePaymentStatus.PAID else None)
    lot.save(update_fields=["payment_status", "payment_date", "updated_at"])


def _invoice_key(supplier, reference):
    if not reference:
        return None
    return hashlib.sha256(json.dumps([supplier.casefold(), reference.casefold()],
        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _claim_invoice(key):
    if key is None:
        return
    # Periods -> supplier/reference mutex -> item/pool. Different item purchases
    # cannot concurrently reuse one supported invoice; the unique binding key
    # is also a database backstop. Blank references are deliberately NOT unique.
    lock_id = int.from_bytes(hashlib.sha256(b"farm-stock-invoice-v1:" + key.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
    if InventoryLotBinding.objects.filter(invoice_key=key).exists():
        raise ValidationError({"possible_duplicate": "This supplier invoice already has a managed stock purchase; review the original evidence."})


def record_inventory_purchase(*, submission_id, user, currency, item_id, location_id,
                              category_id, purchase_date, quantity, total_purchase_cost,
                              supplier, invoice_reference="", expiry_date=None, notes="",
                              funding_allocations=None, payment_date=None):
    _currency(currency)
    item_id, location_id = _identifier(item_id, "item_id"), _identifier(location_id, "location_id")
    category_id = _identifier(category_id, "category_id")
    purchase_date = _day(purchase_date, "purchase_date")
    quantity = stock_quantity(quantity)
    total_purchase_cost = exact_decimal(total_purchase_cost, positive=True, field="total_purchase_cost")
    supplier = _required_text(supplier, "supplier", 160)
    invoice_reference = _text(invoice_reference, "invoice_reference", 120)
    invoice_key = _invoice_key(supplier, invoice_reference)
    notes = _text(notes, "notes", 4000)
    expiry_date = business_date(expiry_date, field="expiry_date") if expiry_date is not None else None
    if expiry_date is not None and expiry_date < purchase_date:
        raise ValidationError({"expiry_date": "Expiry cannot precede this purchase date."})
    funding_allocations = _funding_rows(funding_allocations)
    if funding_allocations:
        if payment_date is None:
            raise ValidationError({"payment_date": "Paid inventory requires explicit dated payment evidence."})
        payment_date = _day(payment_date, "payment_date")
        if payment_date < purchase_date:
            raise ValidationError({"payment_date": "Pre-purchase deposits require a separate verified workflow."})
    elif payment_date is not None:
        raise ValidationError({"payment_date": "A date without actual funding/payment evidence is not paid status."})

    def effect(actor):
        periods = lock_financial_periods(purchase_date, *([payment_date] if funding_allocations else []))
        _claim_invoice(invoice_key)
        item = _item(item_id)
        pool = _pool(item, purchase_date, create=True)
        location = _location(location_id)
        category = ExpenditureCategory.objects.filter(pk=category_id, is_active=True, requires_item_details=True).first()
        if category is None or category.default_accounting_nature in {
                AccountingNature.CAPITAL_EXPENDITURE, AccountingNature.OWNER_WITHDRAWAL, AccountingNature.LOAN_REPAYMENT, AccountingNature.TRANSFER}:
            raise ValidationError({"category": "Select a consumable-stock purchase category, not a capital or financing category."})
        expenditure = Expenditure(expenditure_date=purchase_date, accounting_period=periods[purchase_date],
            amount=total_purchase_cost, category=category, accounting_nature=AccountingNature.INVENTORY_PURCHASE,
            description=f"Stock purchase: {item.name}"[:255], payee=supplier,
            beneficiary_type="inventory_stock", external_reference=invoice_reference, notes=notes,
            idempotency_key=f"inventory-purchase:{submission_id}", created_by=actor)
        expenditure._inventory_purchase = True
        expenditure.full_clean()
        expenditure.save()
        expenditure = post_expenditure(expenditure_id=expenditure.pk, user=actor, cost_rows=[], funding_rows=[],
            allow_unpaid=True, _inventory_purchase=True)
        with localcontext() as context:
            context.prec = 40
            unit_cost = exact_decimal((total_purchase_cost / quantity).quantize(Decimal("0.000001")), scale=6, max_digits=16, field="unit_cost")
        lot = SharedConsumableLot(item=item.name, category=item.category, purchase_date=purchase_date,
            supplier=supplier, invoice_reference=invoice_reference, quantity_purchased=quantity,
            unit_of_measurement=item.base_unit, total_purchase_cost=total_purchase_cost,
            unit_cost=unit_cost, quantity_available=quantity, expiry_date=expiry_date,
            storage_location=location.name, created_by=actor, notes=notes)
        lot.full_clean()
        lot.save()
        binding = InventoryLotBinding.objects.create(lot=lot, item=item, expenditure=expenditure, invoice_key=invoice_key)
        InventoryLocationStock.objects.create(binding=binding, location=location, quantity=quantity)
        movement = _movement(kind=StockMovementType.RECEIPT, day=purchase_date, item=item, lot=lot,
            destination=location, quantity=quantity, cost=total_purchase_cost,
            key=f"inventory-receipt:{submission_id}", user=actor, reference=invoice_reference)
        journal = post_journal(posting_date=purchase_date, description=f"Inventory purchase {expenditure.expenditure_reference}",
            source_model="finance.Expenditure", source_identifier=expenditure.pk,
            idempotency_key=f"inventory-purchase:{expenditure.pk}", user=actor,
            lines=[{"account": "1200", "debit": total_purchase_cost}, {"account": "2000", "credit": total_purchase_cost}])
        pool.quantity += quantity
        pool.carrying_value += total_purchase_cost
        _advance(pool, purchase_date)
        if funding_allocations:
            expenditure = record_expenditure_payment(expenditure_id=expenditure.pk, funding_rows=funding_allocations,
                payment_group_key=f"inventory-initial:{submission_id}", payment_date=payment_date, user=actor,
                _inventory_purchase=True)
            _sync_lot_payment(lot, expenditure)
        return {"lot_id": str(lot.pk), "expenditure_id": str(expenditure.pk),
                "movement_id": str(movement.pk), "journal_id": str(journal.pk)}

    result, created = _submission(submission_id=submission_id, command="inventory.receipt.record", user=user,
        payload=dict(currency=currency, item_id=str(item_id), location_id=str(location_id), category_id=str(category_id),
            purchase_date=purchase_date, quantity=quantity, total_purchase_cost=total_purchase_cost,
            supplier=supplier, invoice_reference=invoice_reference, expiry_date=expiry_date, notes=notes,
            funding_allocations=funding_allocations, payment_date=payment_date), roles=FINANCE_WRITE_ROLES, effect=effect)
    return SharedConsumableLot.objects.get(pk=result["lot_id"]), created


def record_inventory_issue(*, submission_id, user, lot_id, location_id, usage_date,
                           quantity, task_or_purpose, batch_id=None, usage_scope=ConsumableUsageScope.BATCH_DIRECT):
    lot_id, location_id = _identifier(lot_id, "lot_id"), _identifier(location_id, "location_id")
    batch_id = _identifier(batch_id, "batch_id") if batch_id is not None else None
    quantity = stock_quantity(quantity)
    usage_date = _day(usage_date, "usage_date")
    task_or_purpose = _required_text(task_or_purpose, "task_or_purpose", 255)
    if usage_scope not in {ConsumableUsageScope.BATCH_DIRECT, ConsumableUsageScope.ADMINISTRATION}:
        raise ValidationError({"usage_scope": "Shared/selling allocation templates are not verified yet."})
    if (usage_scope == ConsumableUsageScope.BATCH_DIRECT) != (batch_id is not None):
        raise ValidationError({"batch": "Only direct issues select a beneficiary batch; administration must not."})

    def effect(actor):
        return _issue_effect(actor=actor, submission_id=submission_id, lot_id=lot_id,
            location_id=location_id, usage_date=usage_date, quantity=quantity,
            task_or_purpose=task_or_purpose, batch_id=batch_id, usage_scope=usage_scope)

    result, created = _submission(submission_id=submission_id, command="inventory.issue.record", user=user,
        payload=dict(lot_id=str(lot_id), location_id=str(location_id), usage_date=usage_date,
            quantity=quantity, task_or_purpose=task_or_purpose, batch_id=str(batch_id) if batch_id else None,
            usage_scope=usage_scope), roles=FINANCE_WRITE_ROLES, effect=effect)
    return ConsumableUsage.objects.get(pk=result["usage_id"]), created


def _issue_effect(*, actor, submission_id, lot_id, location_id, usage_date, quantity,
                  task_or_purpose, batch_id, usage_scope):
    """Validated issue effect; call only inside a permanent submission boundary.

    Composites reuse this effect, not a second command/receipt or guessed cost.
    All periods must be locked before domain rows when composing observations.
    """
    period = lock_financial_periods(usage_date)[usage_date]
    batch = None
    if batch_id is not None:
        batch = Batch.objects.select_for_update().filter(pk=batch_id).first()
        if batch is None:
            raise ValidationError({"batch": "Choose a received, open production batch."})
        try:
            assert_batch_in_production(batch)
        except ValueError as error:
            raise ValidationError({"batch": str(error)})
        if batch.profitability_finalized_at or batch.profitability_snapshots.filter(final=True).exists():
            raise ValidationError({"batch": "Finalized batch costs require a separate correction workflow."})
        if usage_date < business_date(batch.entry_date):
            raise ValidationError({"usage_date": "Stock usage cannot precede the actual batch arrival date."})
    binding = InventoryLotBinding.objects.filter(lot_id=lot_id).first()
    if binding is None:
        raise ValidationError({"legacy_reconciliation": "Unlinked legacy lots are unavailable until explicitly reconciled."})
    item = _item(binding.item_id)
    pool = _pool(item, usage_date)
    location = _location(location_id)
    lot = SharedConsumableLot.objects.select_for_update().get(pk=lot_id)
    if lot.purchase_date > usage_date or (lot.expiry_date and usage_date > lot.expiry_date):
        raise ValidationError({"usage_date": "The original date precedes purchase or uses expired stock; review is required."})
    stock = InventoryLocationStock.objects.select_for_update().filter(binding=binding, location=location).first()
    if stock is None or quantity > stock.quantity or quantity > lot.quantity_available or quantity > pool.quantity:
        raise ValidationError({"insufficient_stock": "Quantity exceeds last confirmed stock at this location."})
    with localcontext() as context:
        context.prec = 40
        cost = pool.carrying_value if quantity == pool.quantity else (pool.carrying_value * quantity / pool.quantity).quantize(CENT, rounding=ROUND_HALF_EVEN)
    usage = ConsumableUsage(consumable_lot=lot, accounting_period=period, usage_date=usage_date,
        quantity_used=quantity, recognized_cost=cost, usage_scope=usage_scope, batch=batch,
        allocation_driver=AllocationMethod.DIRECT if batch else AllocationMethod.NONE,
        task_or_purpose=task_or_purpose, recorded_by=actor)
    usage.full_clean()
    usage.save(_valued_cost=cost)
    movement = _movement(kind=StockMovementType.ISSUE, day=usage_date, item=item, lot=lot,
        source=location, batch=batch, usage=usage, quantity=quantity, cost=cost,
        key=f"inventory-issue:{submission_id}", user=actor, reason=task_or_purpose)
    journal = None
    if cost > ZERO:
        journal = post_journal(posting_date=usage_date, description=f"Inventory issue {item.sku}",
            source_model="finance.ConsumableUsage", source_identifier=usage.pk,
            idempotency_key=f"inventory-issue:{submission_id}", user=actor,
            lines=[{"account": "5000" if batch else "6100", "debit": cost, "batch_id": batch_id},
                   {"account": "1200", "credit": cost, "batch_id": batch_id}])
    lot.quantity_available -= quantity
    lot.save(update_fields=["quantity_available", "updated_at"])
    stock.quantity -= quantity
    stock.save(update_fields=["quantity", "updated_at"])
    pool.quantity -= quantity
    pool.carrying_value -= cost
    _advance(pool, usage_date)
    return {"usage_id": str(usage.pk), "movement_id": str(movement.pk),
            "journal_id": str(journal.pk) if journal else None, "recognized_cost": str(cost)}
