"""Original post-purchase stock/usage/correction/GL proof, not public sync.

Seal only NEW atomic accepted results. Earlier versionless evidence is retained
for controlled review, never adopted on read/replay. Derived usage period locks
and dated feed populations are not original stock economics. Privileged SQL is
outside writer guarantees; damaged proof refuses a new effect, not repair.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import ObjectDoesNotExist, ValidationError as DomainValidationError
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import (AllocationMethod, ConsumableUsageScope, FinancialCommandReceipt,
    InventoryLotBinding, InventoryMovementEvidence, JournalEntry, JournalStatus,
    PoultryStockConsumption, StockMovement, StockMovementType)


ISSUE_COMMANDS = frozenset({"inventory.issue.record", "poultry.feed.record_stock_backed",
    "poultry.treatment.record_stock_backed"})
CORRECTION_COMMANDS = {f"inventory.{kind}.record": kind for kind in (
    StockMovementType.RETURN, StockMovementType.TRANSFER, StockMovementType.WASTE,
    StockMovementType.EXPIRY, StockMovementType.ADJUSTMENT)}
COMMANDS = ISSUE_COMMANDS | CORRECTION_COMMANDS.keys()
ZERO = Decimal("0.00")
MAX_POOL_MOVEMENTS = 10000
MESSAGE = "Original versioned stock movement/usage/correction/journal evidence does not match; preserve it for controlled review."


def _refuse():
    raise ValidationError({"inventory_reconciliation": MESSAGE})


def _row(instance, exclude=()):
    from .financial_capture import _canonical
    return _canonical({field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields if field.attname not in exclude})


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _version(movement, *, submission_id, command, actor_id, result):
    issue = command in ISSUE_COMMANDS
    kind = StockMovementType.ISSUE if issue else CORRECTION_COMMANDS.get(command)
    if (kind is None or movement.movement_type != kind or movement.created_by_id != actor_id
            or movement.idempotency_key != f"inventory-{kind}:{submission_id}"
            or movement.quantity <= ZERO or movement.total_cost < ZERO
            or not InventoryLotBinding.objects.filter(lot_id=movement.lot_id,
                item_id=movement.item_id).exists()):
        _refuse()
    usage, evidence, poultry = None, None, None
    if issue:
        usage = movement.usage
        if (usage is None or result.get("usage_id") != str(usage.pk)
                or Decimal(result.get("recognized_cost", "NaN")) != movement.total_cost
                or usage.recognized_cost != movement.total_cost or usage.quantity_used != movement.quantity
                or usage.consumable_lot_id != movement.lot_id or usage.batch_id != movement.batch_id
                or usage.usage_date != movement.movement_date or usage.recorded_by_id != actor_id
                or usage.usage_scope != (ConsumableUsageScope.BATCH_DIRECT if movement.batch_id else ConsumableUsageScope.ADMINISTRATION)
                or usage.allocation_driver != (AllocationMethod.DIRECT if movement.batch_id else AllocationMethod.NONE)
                or not usage.accounting_period.period_start <= usage.usage_date <= usage.accounting_period.period_end
                or not movement.from_location_id or movement.to_location_id
                or InventoryMovementEvidence.objects.filter(movement=movement).exists()):
            _refuse()
        consumption = PoultryStockConsumption.objects.select_related("policy", "feed", "treatment").filter(usage=usage).first()
        if command == "inventory.issue.record":
            if consumption is not None:
                _refuse()
        else:
            expected_kind = "feed" if command == "poultry.feed.record_stock_backed" else "treatment"
            if (consumption is None or result.get("consumption_id") != str(consumption.pk)
                    or result.get("kind") != expected_kind):
                _refuse()
            observation = consumption.feed if expected_kind == "feed" else consumption.treatment
            if observation is None or result.get("observation_id") != str(observation.pk):
                _refuse()
            consumption.clean()
            poultry = {"consumption": _row(consumption, {"updated_at"}),
                "policy": _row(consumption.policy, {"updated_at"}),
                "observation": _row(observation, {"updated_at", "current_number_of_birds",
                    "population_calculation_version", "population_calculated_at"})}
    else:
        if movement.usage_id:
            _refuse()
        evidence = InventoryMovementEvidence.objects.filter(movement=movement).first()
        if evidence is None:
            _refuse()
        evidence.clean()
        if kind == StockMovementType.RETURN:
            if movement.from_location_id or not movement.to_location_id:
                _refuse()
        elif (not movement.from_location_id or movement.batch_id
                or (kind == StockMovementType.TRANSFER and (not movement.to_location_id
                    or movement.to_location_id == movement.from_location_id))
                or (kind != StockMovementType.TRANSFER and movement.to_location_id)):
            _refuse()
    journals = list(JournalEntry.objects.filter(idempotency_key=movement.idempotency_key)[:2])
    has_journal = kind != StockMovementType.TRANSFER and movement.total_cost > ZERO
    if not has_journal:
        if journals or result.get("journal_id") is not None:
            _refuse()
        journal, lines = None, []
    else:
        if len(journals) != 1 or result.get("journal_id") != str(journals[0].pk):
            _refuse()
        journal = journals[0]
        if (journal.status != JournalStatus.POSTED or journal.posting_date != movement.movement_date
                or journal.source_model != ("finance.ConsumableUsage" if issue else "finance.StockMovement")
                or journal.source_identifier != str(usage.pk if issue else movement.pk)
                or journal.created_by_id != actor_id or journal.posted_by_id != actor_id or not journal.posted_at
                or journal.reversal_of_id or journal.reversed_by_id or journal.reversed_at or journal.reversal_reason
                or JournalEntry.objects.filter(reversal_of=journal).exists()
                or not journal.accounting_period.period_start <= movement.movement_date <= journal.accounting_period.period_end
                or (issue and journal.accounting_period_id != usage.accounting_period_id)):
            _refuse()
        cost, batch_id = movement.total_cost, movement.batch_id
        cost_account = "5000" if batch_id else "6100"
        expected = ([("1200", cost, ZERO, batch_id, None), (cost_account, ZERO, cost, batch_id, None)]
            if kind == StockMovementType.RETURN else
            [(cost_account, cost, ZERO, batch_id, None), ("1200", ZERO, cost, batch_id, None)])
        lines = list(journal.lines.select_related("account").order_by("pk"))
        if Counter((line.account.code, line.debit, line.credit, line.batch_id,
                line.funding_source_id) for line in lines) != Counter(expected):
            _refuse()
    from .inventory_units import require_quantity_definition
    counted = kind == StockMovementType.ADJUSTMENT
    require_quantity_definition(result.get("stock_quantity_evidence"), movement.item,
        evidence.counted_quantity if counted else movement.quantity,
        field="counted_quantity" if counted else "quantity")
    return checksum({"basis": "phase6-original-stock-movement-v1",
        "movement": _row(movement, {"updated_at"}),
        "usage": _row(usage, {"locked", "updated_at"}) if usage else None,
        "correction": _row(evidence, {"updated_at"}) if evidence else None,
        "poultry": poultry, "journal": _row(journal, {"updated_at"}) if journal else None,
        "lines": [{**_row(line, {"updated_at"}), "account_code": line.account.code} for line in lines]})


def _anchor(result, *, submission_id, command, actor_id, request_hash):
    return checksum({"basis": "phase6-stock-movement-receipt-v1", "submission_id": str(submission_id),
        "command": command, "actor_id": str(actor_id), "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "stock_anchor"}})


def seal_stock_result(result, *, submission_id, command, actor_id, request_hash):
    """Before NEW permanent receipt insertion, after the full composite succeeds."""
    if command not in COMMANDS:
        return result
    movement = StockMovement.objects.get(pk=result["movement_id"])
    sealed = {**result, "stock_version": _version(movement, submission_id=submission_id,
        command=command, actor_id=actor_id, result=result)}
    sealed["stock_anchor"] = _anchor(sealed, submission_id=submission_id, command=command,
        actor_id=actor_id, request_hash=request_hash)
    return sealed


def verified_stock_movement(movement):
    candidates = list(FinancialCommandReceipt.objects.filter(command__in=COMMANDS,
        completed_at__isnull=False, result__movement_id=str(movement.pk)).order_by("pk")[:2])
    if len(candidates) != 1:
        return False
    receipt = candidates[0]
    result = receipt.result
    if (not isinstance(result, dict) or not _digest(receipt.request_hash)
            or not _digest(result.get("stock_version")) or not _digest(result.get("stock_anchor"))
            or result["stock_anchor"] != _anchor(result, submission_id=receipt.pk,
                command=receipt.command, actor_id=receipt.actor_id, request_hash=receipt.request_hash)):
        return False
    try:
        return result["stock_version"] == _version(movement, submission_id=receipt.pk,
            command=receipt.command, actor_id=receipt.actor_id, result=result)
    except (ValidationError, DomainValidationError, ObjectDoesNotExist, InvalidOperation, TypeError, ValueError):
        return False


def require_pool_movement_proof(pool):
    """Under existing item/pool mutex, before NEW effects, never in _advance."""
    movements = list(StockMovement.objects.filter(item_id=pool.item_id)
        .exclude(movement_type=StockMovementType.RECEIPT).order_by("pk")[:MAX_POOL_MOVEMENTS + 1])
    if len(movements) > MAX_POOL_MOVEMENTS:
        raise ValidationError({"inventory_reconciliation": "This valuation pool exceeds the supported movement-proof review bound; do not value only a partial history."})
    if any(not verified_stock_movement(movement) for movement in movements):
        _refuse()
