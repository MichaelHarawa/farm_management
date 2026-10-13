"""Internal original-payable proof, not a financial API or historical adoption.

New atomic posting receipts bind original sources, allocations and whole GL
evidence. Legitimate derived payment/stock balances and period-lock metadata are
not original economic evidence. Privileged SQL is outside writer guarantees;
damaged/missing proof is refused, never repaired or stamped on an old receipt.
"""
from collections import Counter
from decimal import Decimal
import re
import uuid

from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import (AccountingNature, Expenditure, ExpenditureOrigin,
    ExpenditureStatus, FinancialCommandReceipt, InventoryLotBinding,
    JournalEntry, JournalStatus, StockMovement, StockMovementType)


POSTING_COMMANDS = frozenset({"finance.expenditure.create", "finance.expenditure.post", "inventory.receipt.record"})
ZERO = Decimal("0.00")
MESSAGE = "Original versioned expense/stock/payable evidence does not match; preserve it for controlled review."


def _refuse():
    raise ValidationError({"expenditure": MESSAGE})


def _row(instance, exclude=()):
    from .financial_capture import _canonical
    return _canonical({field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields if field.attname not in exclude})


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _provenance(expenditure, *, submission_id, command, actor_id, result):
    stock = expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE
    prefix = "inventory-purchase:" if stock else "financial-expense:"
    key = expenditure.idempotency_key or ""
    if not key.startswith(prefix):
        _refuse()
    try:
        creation_id = uuid.UUID(key[len(prefix):])
    except (ValueError, TypeError, AttributeError):
        _refuse()
    creation_command = "inventory.receipt.record" if stock else "finance.expenditure.create"
    if command == creation_command:
        if creation_id != submission_id or expenditure.created_by_id != actor_id:
            _refuse()
        return None, None
    if command != "finance.expenditure.post" or stock:
        _refuse()
    creation = FinancialCommandReceipt.objects.filter(pk=creation_id, command=creation_command,
        actor_id=expenditure.created_by_id, completed_at__isnull=False,
        result__expenditure_id=str(expenditure.pk), result__journal_id=None).first()
    version = result.get("posted_draft_version")
    if creation is None or not _digest(version) or not _digest(creation.result.get("draft_version")):
        _refuse()
    lineage = list(FinancialCommandReceipt.objects.filter(
        command__in=["finance.expenditure.create", "finance.expenditure.update"],
        completed_at__isnull=False, result__expenditure_id=str(expenditure.pk),
        result__journal_id=None, result__draft_version=version).order_by("pk")[:2])
    if len(lineage) != 1 or not _digest(creation.request_hash) or not _digest(lineage[0].request_hash):
        _refuse()
    return _row(creation), _row(lineage[0])


def _version(expenditure, journal, *, submission_id, command, actor_id, result):
    from .financial_capture import _cost_rows
    if (expenditure.status != ExpenditureStatus.POSTED or expenditure.origin != ExpenditureOrigin.FINANCE
            or expenditure.amount <= ZERO or expenditure.posted_by_id != actor_id or not expenditure.posted_at
            or expenditure.reversed_expenditure_id or expenditure.reversed_by_id or expenditure.reversed_at
            or expenditure.reversal_reason or Expenditure.objects.filter(reversed_expenditure=expenditure).exists()):
        _refuse()
    creation, lineage = _provenance(expenditure, submission_id=submission_id,
        command=command, actor_id=actor_id, result=result)
    stock = expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE
    journal_key = f"inventory-purchase:{expenditure.pk}" if stock else f"financial-expenditure:{expenditure.pk}"
    if (journal.status != JournalStatus.POSTED or journal.idempotency_key != journal_key
            or journal.source_model != "finance.Expenditure" or journal.source_identifier != str(expenditure.pk)
            or journal.posting_date != expenditure.expenditure_date
            or journal.accounting_period_id != expenditure.accounting_period_id
            or journal.created_by_id != actor_id or journal.posted_by_id != actor_id or not journal.posted_at
            or journal.reversal_of_id or journal.reversed_by_id or journal.reversed_at or journal.reversal_reason
            or JournalEntry.objects.filter(reversal_of=journal).exists()):
        _refuse()
    period = expenditure.accounting_period
    if period is None or not period.period_start <= expenditure.expenditure_date <= period.period_end:
        _refuse()
    costs = list(expenditure.cost_allocations.order_by("pk"))
    expected = [("2000", ZERO, expenditure.amount, None, None)]
    if expenditure.accounting_nature == AccountingNature.DIRECT_COST:
        plan = _cost_rows(expenditure.cost_allocation_plan)
        if (not plan or len({row["batch"] for row in plan}) != len(plan)
                or sum((row["amount"] for row in plan), ZERO) != expenditure.amount
                or Counter((row.batch_id, row.allocated_amount) for row in costs)
                != Counter((row["batch"], row["amount"]) for row in plan)
                or any(row.source_type != "expenditure" or row.allocation_method != "direct"
                    or row.accounting_period_id != period.pk or row.generated_by_id != actor_id for row in costs)):
            _refuse()
        expected += [("5000", row["amount"], ZERO, row["batch"], None) for row in plan]
    elif expenditure.accounting_nature in {AccountingNature.INDIRECT_OPERATING_EXPENSE, AccountingNature.INVENTORY_PURCHASE}:
        if costs or expenditure.cost_allocation_plan:
            _refuse()
        expected += [("1200" if stock else "6100", expenditure.amount, ZERO, None, None)]
    else:
        _refuse()
    lines = list(journal.lines.select_related("account").order_by("pk"))
    if Counter((line.account.code, line.debit, line.credit, line.batch_id,
                line.funding_source_id) for line in lines) != Counter(expected):
        _refuse()
    inventory = None
    if stock:
        binding = InventoryLotBinding.objects.select_related("lot", "item").filter(expenditure=expenditure).first()
        if binding is None or result.get("lot_id") != str(binding.lot_id):
            _refuse()
        lot = binding.lot
        from .inventory_units import require_quantity_definition
        require_quantity_definition(result.get("stock_quantity_evidence"), binding.item, lot.quantity_purchased)
        receipts = list(StockMovement.objects.filter(lot=lot, movement_type=StockMovementType.RECEIPT).order_by("pk")[:2])
        if len(receipts) != 1:
            _refuse()
        movement = receipts[0]
        if (result.get("movement_id") != str(movement.pk)
                or movement.idempotency_key != "inventory-receipt:" + expenditure.idempotency_key[len("inventory-purchase:"):]
                or movement.item_id != binding.item_id or movement.movement_date != expenditure.expenditure_date
                or movement.quantity != lot.quantity_purchased or movement.total_cost != expenditure.amount
                or lot.total_purchase_cost != expenditure.amount or lot.purchase_date != expenditure.expenditure_date
                or lot.created_by_id != actor_id or movement.created_by_id != actor_id
                or movement.from_location_id or not movement.to_location_id or movement.batch_id or movement.usage_id):
            _refuse()
        inventory = {"binding": _row(binding, {"updated_at"}),
            "lot": _row(lot, {"quantity_available", "payment_status", "payment_date", "updated_at", "usd_equivalent"}),
            "receipt_movement": _row(movement, {"updated_at"})}
    return checksum({"basis": "phase6-original-payable-v1",
        "expenditure": _row(expenditure, {"payment_status", "updated_at", "usd_equivalent"}),
        "costs": [_row(row, {"locked", "updated_at"}) for row in costs],
        "journal": _row(journal, {"updated_at"}),
        "lines": [{**_row(line, {"updated_at"}), "account_code": line.account.code} for line in lines],
        "creation_receipt": creation, "posted_draft_lineage": lineage, "inventory": inventory})


def _anchor(result, *, submission_id, command, actor_id, request_hash):
    return checksum({"basis": "phase6-payable-receipt-v1", "submission_id": str(submission_id),
        "command": command, "actor_id": str(actor_id), "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "payable_anchor"}})


def seal_payable_result(result, *, submission_id, command, actor_id, request_hash):
    """Only called before a NEW permanent receipt is created in _submission."""
    if command not in POSTING_COMMANDS or not result.get("journal_id"):
        return result
    expenditure = Expenditure.objects.get(pk=result["expenditure_id"])
    journal = JournalEntry.objects.get(pk=result["journal_id"])
    sealed = {**result, "payable_version": _version(expenditure, journal,
        submission_id=submission_id, command=command, actor_id=actor_id, result=result)}
    sealed["payable_anchor"] = _anchor(sealed, submission_id=submission_id,
        command=command, actor_id=actor_id, request_hash=request_hash)
    return sealed


def verified_payable(expenditure, *, _invoice_group=True):
    """One intact accepted posting plus exact current original evidence."""
    key = f"inventory-purchase:{expenditure.pk}" if expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE else f"financial-expenditure:{expenditure.pk}"
    journal = JournalEntry.objects.filter(idempotency_key=key).first()
    if journal is None:
        return False
    candidates = list(FinancialCommandReceipt.objects.filter(command__in=POSTING_COMMANDS,
        completed_at__isnull=False, result__expenditure_id=str(expenditure.pk),
        result__journal_id=str(journal.pk)).order_by("pk")[:2])
    if len(candidates) != 1:
        return False
    receipt = candidates[0]
    result = receipt.result
    if (not _digest(receipt.request_hash) or not _digest(result.get("payable_version"))
            or result.get("payable_anchor") != _anchor(result, submission_id=receipt.pk,
                command=receipt.command, actor_id=receipt.actor_id, request_hash=receipt.request_hash)):
        return False
    try:
        if _invoice_group:
            from .inventory_invoices import require_invoice_membership
            require_invoice_membership(receipt)
        return result["payable_version"] == _version(expenditure, journal, submission_id=receipt.pk,
            command=receipt.command, actor_id=receipt.actor_id, result=result)
    except ValidationError:
        return False
