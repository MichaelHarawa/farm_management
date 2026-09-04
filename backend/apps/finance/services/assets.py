from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import models, transaction

from ..models import (
    Asset,
    AssetCapitalizedCost,
    AssetEventType,
    AssetLifecycleEvent,
    AssetStatus,
    ReplacementReserveTransaction,
    ReserveTransactionType,
    SharedExpense,
)
from .depreciation import asset_recovery_summary, money


def projected_future_replacement_cost(
    current_cost: Decimal,
    annual_inflation_rate_percent: Decimal,
    years: Decimal,
) -> Decimal:
    growth = Decimal("1.00") + annual_inflation_rate_percent / Decimal("100")
    return money(current_cost * (growth ** years))


@transaction.atomic
def link_capital_expense_to_asset(
    *,
    asset: Asset,
    expense: SharedExpense,
    amount: Decimal,
    created_by=None,
    notes: str = "",
) -> AssetCapitalizedCost:
    if not expense.is_capital_expenditure:
        raise ValueError("Only capital-expenditure expenses can be linked to assets.")

    link = AssetCapitalizedCost(
        asset=asset,
        expense=expense,
        capitalized_amount=amount,
        created_by=created_by,
        notes=notes,
    )
    link.full_clean()
    link.save()
    AssetLifecycleEvent.objects.create(
        asset=asset,
        event_type=AssetEventType.CAPITALIZED_COST,
        event_date=expense.expense_date,
        reason=notes,
        details={"expense_id": expense.pk, "amount": str(amount)},
        created_by=created_by,
    )
    return link


@transaction.atomic
def impair_asset(*, asset: Asset, amount: Decimal, event_date=None, reason: str = "", user=None) -> Asset:
    if amount < Decimal("0.00"):
        raise ValueError("Impairment amount cannot be negative.")
    asset.recognized_impairment_amount = money(
        asset.recognized_impairment_amount + amount
    )
    asset.status = AssetStatus.IMPAIRED
    asset.full_clean()
    asset.save(update_fields=["recognized_impairment_amount", "status", "updated_at"])
    AssetLifecycleEvent.objects.create(
        asset=asset,
        event_type=AssetEventType.IMPAIRMENT,
        event_date=event_date or date.today(),
        reason=reason,
        details={"amount": str(money(amount))},
        created_by=user,
    )
    return asset


@transaction.atomic
def dispose_asset(
    *,
    asset: Asset,
    disposal_date: date,
    proceeds: Decimal = Decimal("0.00"),
    reason: str = "",
    user=None,
) -> Asset:
    recovery = asset_recovery_summary(asset)
    asset.status = AssetStatus.DISPOSED
    asset.disposal_date = disposal_date
    asset.disposal_proceeds = proceeds
    asset.disposal_gain_loss = money(proceeds - recovery["carrying_amount"])
    asset.full_clean()
    asset.save(
        update_fields=[
            "status",
            "disposal_date",
            "disposal_proceeds",
            "disposal_gain_loss",
            "updated_at",
        ]
    )
    AssetLifecycleEvent.objects.create(
        asset=asset,
        event_type=AssetEventType.DISPOSAL,
        event_date=disposal_date,
        reason=reason,
        details={
            "proceeds": str(money(proceeds)),
            "carrying_amount": str(recovery["carrying_amount"]),
            "gain_loss": str(asset.disposal_gain_loss),
        },
        created_by=user,
    )
    return asset


@transaction.atomic
def transfer_asset(*, asset: Asset, event_date: date, location: str, custodian: str, reason: str, user=None):
    before = {"location": asset.location, "custodian": asset.custodian}
    asset.location = location
    asset.custodian = custodian
    asset.save(update_fields=["location", "custodian", "updated_at"])
    AssetLifecycleEvent.objects.create(
        asset=asset,
        event_type=AssetEventType.TRANSFER,
        event_date=event_date,
        reason=reason,
        details={"before": before, "after": {"location": location, "custodian": custodian}},
        created_by=user,
    )
    return asset


def reserve_balance(asset: Asset | None = None) -> Decimal:
    queryset = ReplacementReserveTransaction.objects.all()
    if asset:
        queryset = queryset.filter(asset=asset)

    contributions = money(
        queryset.filter(transaction_type=ReserveTransactionType.CONTRIBUTION).aggregate(
            total=models.Sum("amount")
        )["total"]
    )
    returns = money(
        queryset.filter(transaction_type=ReserveTransactionType.RETURN).aggregate(
            total=models.Sum("amount")
        )["total"]
    )
    withdrawals = money(
        queryset.filter(transaction_type=ReserveTransactionType.WITHDRAWAL).aggregate(
            total=models.Sum("amount")
        )["total"]
    )
    return money(contributions + returns - withdrawals)
