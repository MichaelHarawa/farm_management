from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from ..models import FinanceActionEvent


def _json_value(value):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def record_finance_action(
    *,
    actor,
    action: str,
    entity_type: str,
    entity_id: str | int = "",
    before_data: dict | None = None,
    after_data: dict | None = None,
    reason: str = "",
) -> FinanceActionEvent:
    return FinanceActionEvent.objects.create(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id or ""),
        before_data=_json_value(before_data or {}),
        after_data=_json_value(after_data or {}),
        reason=(reason or "").strip(),
    )
