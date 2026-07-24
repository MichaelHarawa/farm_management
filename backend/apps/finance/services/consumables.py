from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from ..models import (
    AccountingPeriod,
    ConsumableUsage,
    PeriodStatus,
    SharedConsumableLot,
)


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

    lot.quantity_available = (lot.quantity_available - quantity_used).quantize(
        Decimal("0.0001")
    )
    lot.save(update_fields=["quantity_available", "updated_at"])

    return usage
