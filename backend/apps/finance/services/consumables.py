from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from ..models import (
    AccountingPeriod,
    ConsumableItem,
    ConsumableUsage,
    InventoryLocation,
    PeriodStatus,
    SharedConsumableLot,
    StockMovement,
    StockMovementType,
)
from .ledger import post_journal


def _item_for_lot(lot: SharedConsumableLot) -> ConsumableItem:
    sku = "ITEM-" + "-".join(lot.item.upper().split())[:32]
    item, _ = ConsumableItem.objects.get_or_create(
        sku=sku,
        defaults={"name": lot.item, "category": lot.category, "base_unit": lot.unit_of_measurement},
    )
    return item


def _location_for_lot(lot: SharedConsumableLot) -> InventoryLocation:
    label = lot.storage_location.strip() or "Main Store"
    code = "-".join(label.upper().split())[:40]
    location, _ = InventoryLocation.objects.get_or_create(code=code, defaults={"name": label})
    return location


@transaction.atomic
def record_consumable_receipt(*, created_by=None, **data) -> SharedConsumableLot:
    lot = SharedConsumableLot(**data, created_by=created_by)
    lot.full_clean(exclude=["unit_cost", "quantity_available"])
    lot.save()
    item = _item_for_lot(lot)
    location = _location_for_lot(lot)
    StockMovement.objects.create(
        movement_type=StockMovementType.RECEIPT,
        movement_date=lot.purchase_date,
        item=item,
        lot=lot,
        to_location=location,
        quantity=lot.quantity_purchased,
        unit_cost=lot.unit_cost,
        total_cost=lot.total_purchase_cost,
        reference=lot.invoice_reference,
        idempotency_key=f"consumable-lot:{lot.pk}:receipt",
        created_by=created_by,
    )
    post_journal(
        posting_date=lot.purchase_date,
        description=f"Consumable receipt: {lot.item}",
        source_model="finance.SharedConsumableLot",
        source_identifier=lot.pk,
        idempotency_key=f"consumable-lot:{lot.pk}:receipt",
        user=created_by,
        lines=[{"account": "1200", "debit": lot.total_purchase_cost}, {"account": "2000", "credit": lot.total_purchase_cost}],
    )
    return lot


@transaction.atomic
def record_consumable_usage(*, recorded_by=None, **data) -> ConsumableUsage:
    period: AccountingPeriod = data["accounting_period"]
    if period.status == PeriodStatus.CLOSED:
        raise ValueError("Closed accounting periods cannot receive consumable usage.")

    lot = SharedConsumableLot.objects.select_for_update().get(
        pk=data["consumable_lot"].pk
    )
    quantity_used = Decimal(data["quantity_used"])

    if quantity_used > lot.quantity_available:
        raise ValueError("Consumable usage cannot exceed available stock.")

    usage = ConsumableUsage(
        **{
            **data,
            "consumable_lot": lot,
            "recorded_by": recorded_by,
        }
    )
    usage.recognized_cost = (quantity_used * lot.unit_cost).quantize(
        Decimal("0.01")
    )
    usage.full_clean()
    usage.save()

    item = _item_for_lot(lot)
    location = _location_for_lot(lot)
    movement = StockMovement.objects.create(
        movement_type=StockMovementType.ISSUE,
        movement_date=usage.usage_date,
        item=item,
        lot=lot,
        usage=usage,
        from_location=location,
        batch=usage.batch,
        quantity=quantity_used,
        unit_cost=lot.unit_cost,
        total_cost=usage.recognized_cost,
        reference=f"USAGE-{usage.pk}",
        reason=usage.task_or_purpose,
        idempotency_key=f"consumable-usage:{usage.pk}:issue",
        created_by=recorded_by,
    )
    debit_account = "5000" if usage.batch_id or usage.usage_scope in {"batch_direct", "shared_production"} else "6100"
    post_journal(
        posting_date=usage.usage_date,
        description=f"Consumable issue: {lot.item}",
        source_model="finance.ConsumableUsage",
        source_identifier=usage.pk,
        idempotency_key=movement.idempotency_key,
        user=recorded_by,
        lines=[
            {"account": debit_account, "debit": usage.recognized_cost, "batch_id": usage.batch_id},
            {"account": "1200", "credit": usage.recognized_cost, "batch_id": usage.batch_id},
        ],
    )

    lot.quantity_available = (lot.quantity_available - quantity_used).quantize(
        Decimal("0.0001")
    )
    lot.save(update_fields=["quantity_available", "updated_at"])

    return usage
