"""Read-only effects of explicitly managed stock corrections.

Use existing StockMovement fields so ordinary reports also work before the new
additive evidence table is migrated. No discovery/import/write/backfill on read.
Historical legacy enum rows are not retroactively assigned this new policy.
"""
from django.db.models import Q, Sum

from ..models import StockMovement, StockMovementType
from .financial_values import exact_decimal


def stock_returns():
    return StockMovement.objects.filter(movement_type=StockMovementType.RETURN,
        idempotency_key__startswith="inventory-return:")


def stock_losses():
    return StockMovement.objects.filter(
        Q(movement_type=StockMovementType.WASTE, idempotency_key__startswith="inventory-waste:")
        | Q(movement_type=StockMovementType.EXPIRY, idempotency_key__startswith="inventory-expiry:")
        | Q(movement_type=StockMovementType.ADJUSTMENT, idempotency_key__startswith="inventory-adjustment:"))


def movement_cost(rows):
    return exact_decimal(rows.aggregate(total=Sum("total_cost"))["total"] or "0.00", max_digits=20)
