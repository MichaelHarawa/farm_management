"""Phase6 posting foundations, deliberately NOT registered as mobile commands.

These explicit services wrap existing domain services. New source effects and
permanent financial replay evidence commit together; legacy rows are never
backfilled on read/retry. Currency is the existing farm ledger's MWK only.
Publication, positive financial projections, native review and all-writer gates
must pass before an endpoint advertises any of these capabilities.
"""
from datetime import date, datetime, timezone as datetime_timezone
from datetime import timedelta
from decimal import Decimal
import uuid
import hashlib

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.mobile_sync.policy import permits
from apps.mobile_sync.projections import checksum
from apps.mobile_sync.writers import sync_atomic
from apps.poultry.models import PaymentMethod, PaymentStatus, Sales, SaleSellingCostCategory
from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle
from ..models import (AccountingNature, Expenditure, ExpenditureCategory, ExpenditureStatus,
                      FinancialCommandReceipt, FundingClassification, FundingReceipt, JournalEntry, JournalStatus, SalePayment)
from ..permissions import FINANCE_WRITE_ROLES, OWNER_CAPITAL_ROLES
from .collections import record_sale_payment
from .expenditures import post_expenditure, record_expenditure_payment, validate_cost_allocations
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .ledger import post_journal
from .owner_capital import record_owner_contribution


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            raise ValidationError({"date": "An instant requires an explicit timezone."})
        return value.astimezone(datetime_timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    return value


def _currency(currency):
    if currency != "MWK":
        raise ValidationError({"currency": "Only the current MWK ledger is supported; no implicit conversion."})


def _fields(row, allowed, field):
    if not isinstance(row, dict) or set(row) - allowed:
        raise ValidationError({field: "Unexpected fields are not allowed."})


def _text(value, field, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError({field: f"Text must not exceed {limit} characters."})
    return value.strip()


def _rows(value, field):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 50:
        raise ValidationError({field: "Provide a list of at most 50 rows."})
    return value


def _identifier(value, field):
    # Never truncate fractional IDs or accept booleans as an existing source.
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValidationError({field: "Select an existing positive identifier."})
    try:
        identifier = int(value)
    except (ValueError, TypeError):
        raise ValidationError({field: "Select an existing positive identifier."})
    if not 0 < identifier <= 9223372036854775807 or (isinstance(value, str) and not value.isdecimal()):
        raise ValidationError({field: "Select an existing positive identifier."})
    return identifier


def _funding_rows(value):
    normalized = []
    for row in _rows(value, "funding_allocations"):
        _fields(row, {"funding_source", "amount", "classification"}, "funding_allocations")
        # Preserve historical omitted/null/blank defaults and their original
        # receipt hashes; reject arbitrary JSON before the older set checks.
        if "classification" in row and row["classification"] not in (None, "", *FundingClassification.values):
            raise ValidationError({"funding_allocations": "Select a supported explicit funding classification."})
        normalized.append({**row, "funding_source": _identifier(row.get("funding_source"), "funding_source"),
                           "amount": exact_decimal(row.get("amount"), positive=True)})
    return normalized


def _cost_rows(value):
    costs = []
    for row in _rows(value, "cost_allocations"):
        _fields(row, {"batch", "amount"}, "cost_allocations")
        costs.append({"batch": _identifier(row.get("batch"), "batch"),
                      "amount": exact_decimal(row.get("amount"), positive=True)})
    return costs


@sync_atomic
@transaction.atomic
def _submission(*, submission_id, command, user, payload, roles, effect):
    try:
        submission_id = uuid.UUID(str(submission_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError({"submission_id": "A stable UUID submission ID is required."})
    actor = get_user_model().objects.get(pk=user.pk)
    if not permits(actor, roles):
        raise PermissionDenied("Current role cannot record this financial event.")
    fingerprint = checksum({"actor": str(actor.pk), "command": command, "payload": _canonical(payload)})
    if connection.vendor != "postgresql":
        raise ValidationError({"database": "Financial posting foundations require the verified PostgreSQL backend."})
    # An intent mutex is NOT a source/mapping/receipt row lock. Order is stream,
    # intent mutex, periods, batches/sources, then append the permanent receipt.
    # No committed placeholder exists, and a rollback releases the mutex. Hash
    # collisions can only serialize unrelated intents, never authorize a replay.
    lock_id = int.from_bytes(hashlib.sha256(b"farm-financial-intent-v1:" + submission_id.bytes).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])
    actor = get_user_model().objects.get(pk=user.pk)
    if not permits(actor, roles):
        raise PermissionDenied("Current role cannot record this financial event.")
    receipt = FinancialCommandReceipt.objects.filter(pk=submission_id).first()
    if receipt:
        if receipt.request_hash != fingerprint or receipt.actor_id != actor.pk or receipt.command != command:
            raise ValidationError({"idempotency_key": "Submission ID is bound to different financial content."})
        if receipt.completed_at is None:
            raise ValidationError({"submission_id": "Incomplete financial receipt requires investigation."})
        return receipt.result, False
    receipt = FinancialCommandReceipt.objects.create(submission_id=submission_id, command=command,
        actor=actor, request_hash=fingerprint, result=effect(actor), completed_at=timezone.now())
    return receipt.result, True


def _receipt_payload(row):
    _fields(row, {"amount", "payment_date", "payment_method", "external_reference", "received_by_name", "notes"}, "receipt")
    if "payment_date" not in row or "payment_method" not in row:
        raise ValidationError({"receipt": "Record the actual receipt instant and payment method."})
    business_date(row["payment_date"], field="payment_date")
    if not isinstance(row["payment_date"], datetime) or row["payment_date"] > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"payment_date": "Record an actual timezone-aware receipt instant, not a future date."})
    if row["payment_method"] not in PaymentMethod.values:
        raise ValidationError({"payment_method": "Select a supported payment method."})
    return {**row, "amount": exact_decimal(row.get("amount"), positive=True),
            "external_reference": _text(row.get("external_reference", ""), "external_reference", 120),
            "received_by_name": _text(row.get("received_by_name", ""), "received_by_name", 200),
            "notes": _text(row.get("notes", ""), "notes", 4000)}


def _post_receipt(payment, actor):
    return post_journal(posting_date=business_date(payment.payment_date),
        description=f"Collection of {payment.sale.sale_id}", source_model="finance.SalePayment",
        source_identifier=payment.pk, idempotency_key=f"sale-receipt:{payment.pk}", user=actor,
        lines=[{"account": "1000", "debit": payment.amount, "batch_id": payment.sale.batch_id},
               {"account": "1100", "credit": payment.amount, "batch_id": payment.sale.batch_id}])


def record_financial_sale(*, submission_id, user, currency, batch_id, sale_date, product_type,
                          quantity_sold, unit_price, buyer_name, buyer_type, sold_by_name,
                          buyer_type_other="", receivable_follow_up_name="", due_date=None,
                          notes="", selling_costs=None, initial_receipt=None):
    _currency(currency)
    unit_price = exact_decimal(unit_price, field="unit_price", positive=True)
    if isinstance(quantity_sold, bool) or not isinstance(quantity_sold, int) or not 0 < quantity_sold <= 2147483647:
        raise ValidationError({"quantity_sold": "Enter a positive whole-bird/product-unit quantity."})
    exact_decimal(unit_price * quantity_sold, field="sale_total", positive=True)
    rows = []
    for row in _rows(selling_costs, "selling_costs"):
        _fields(row, {"category", "amount", "notes"}, "selling_costs")
        if row.get("category") not in SaleSellingCostCategory.values:
            raise ValidationError({"selling_costs": "Select a supported selling-cost category."})
        rows.append({"category": row["category"], "amount": exact_decimal(row.get("amount"), positive=True),
                     "notes": _text(row.get("notes", ""), "selling_costs.notes", 4000)})
    receipt = _receipt_payload(initial_receipt) if initial_receipt is not None else None
    if not isinstance(sale_date, datetime) or timezone.is_naive(sale_date) or sale_date > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"sale_date": "Record an actual timezone-aware sale instant, not a future date."})
    if receipt and receipt["payment_date"] < sale_date:
        raise ValidationError({"payment_date": "Pre-sale deposits require a separate verified workflow."})
    sale_data = dict(batch_id=_identifier(batch_id, "batch_id"), sale_date=sale_date, product_type=product_type,
        quantity_sold=quantity_sold, unit_price=unit_price, buyer_name=buyer_name, buyer_type=buyer_type,
        buyer_type_other=buyer_type_other, sold_by_name=sold_by_name, notes=notes,
        receivable_follow_up_name=receivable_follow_up_name, due_date=due_date, selling_costs=rows)
    def effect(actor):
        lock_financial_periods(sale_date, *([receipt["payment_date"]] if receipt else []))
        sale = create_sale_with_lifecycle(**sale_data, created_by=actor, amount_paid=Decimal("0.00"),
            payment_status=PaymentStatus.UNPAID, payment_method=receipt["payment_method"] if receipt else PaymentMethod.CASH)
        if sale.sale_date < sale.batch.entry_date:
            raise ValidationError({"sale_date": "A production sale cannot precede the actual batch arrival."})
        journals = [post_journal(posting_date=business_date(sale.sale_date),
            description=f"Sale {sale.sale_id}", source_model="poultry.Sales", source_identifier=sale.pk,
            idempotency_key=f"financial-sale:{sale.pk}", user=actor,
            lines=[{"account": "1100", "debit": sale.sale_total, "batch_id": sale.batch_id},
                   {"account": "4000", "credit": sale.sale_total, "batch_id": sale.batch_id}])]
        for cost in sale.selling_costs.order_by("pk"):
            journals.append(post_journal(posting_date=business_date(sale.sale_date),
                description=f"Selling cost of {sale.sale_id}", source_model="poultry.SaleSellingCost",
                source_identifier=cost.pk, idempotency_key=f"sale-selling-cost:{cost.pk}", user=actor,
                lines=[{"account": "6000", "debit": cost.amount, "batch_id": sale.batch_id},
                       {"account": "2000", "credit": cost.amount, "batch_id": sale.batch_id}]))
        payment = None
        if receipt:
            payment, _ = record_sale_payment(sale_id=sale.pk, **receipt, created_by=actor,
                idempotency_key=f"sale-initial:{submission_id}")
            journals.append(_post_receipt(payment, actor))
        return {"sale_id": str(sale.pk), "payment_id": str(payment.pk) if payment else None,
                "journal_ids": [str(entry.pk) for entry in journals]}
    result, created = _submission(submission_id=submission_id, command="poultry.sale.record", user=user,
        payload={"currency": currency, **sale_data, "initial_receipt": receipt}, roles=FINANCE_WRITE_ROLES, effect=effect)
    return Sales.objects.get(pk=result["sale_id"]), created


def record_financial_receipt(*, submission_id, user, currency, sale_id, **receipt):
    _currency(currency)
    sale_id = _identifier(sale_id, "sale_id")
    receipt = _receipt_payload(receipt)
    def effect(actor):
        lock_financial_periods(receipt["payment_date"], field="payment_date")
        payment, _ = record_sale_payment(sale_id=sale_id, **receipt, created_by=actor,
            idempotency_key=f"financial-receipt:{submission_id}")
        if payment.payment_date < payment.sale.sale_date:
            raise ValidationError({"payment_date": "Pre-sale deposits require a separate verified workflow."})
        journal = _post_receipt(payment, actor)
        return {"payment_id": str(payment.pk), "journal_id": str(journal.pk)}
    result, created = _submission(submission_id=submission_id, command="finance.sale_receipt.record", user=user,
        payload={"currency": currency, "sale_id": str(sale_id), **receipt}, roles=FINANCE_WRITE_ROLES, effect=effect)
    return SalePayment.objects.get(pk=result["payment_id"]), created


def record_financial_expenditure(*, submission_id, user, currency, expenditure_date, amount,
                                 category_id, accounting_nature, description, payee,
                                 external_reference="", notes="", cost_allocations=None,
                                 funding_allocations=None, payment_date=None, post=False):
    _currency(currency)
    amount = exact_decimal(amount, positive=True)
    if accounting_nature not in {AccountingNature.DIRECT_COST, AccountingNature.INDIRECT_OPERATING_EXPENSE}:
        raise ValidationError({"accounting_nature": "Capital, loan repayment, owner outflow and transfer need their own verified templates."})
    costs = _cost_rows(cost_allocations)
    funding_allocations = _funding_rows(funding_allocations)
    category_id = _identifier(category_id, "category_id")
    if accounting_nature == AccountingNature.DIRECT_COST and not costs:
        raise ValidationError({"cost_allocations": "Direct cost requires explicit beneficiary batches."})
    if accounting_nature == AccountingNature.INDIRECT_OPERATING_EXPENSE and costs:
        raise ValidationError({"cost_allocations": "Administration is not a direct batch cost."})
    if funding_allocations and payment_date is None:
        raise ValidationError({"payment_date": "Paid status requires dated payment evidence."})
    if not isinstance(post, bool):
        raise ValidationError({"post": "Explicit boolean posting intent is required."})
    if funding_allocations and not post:
        raise ValidationError({"funding_allocations": "An unposted draft cannot consume confirmed cash."})
    def effect(actor):
        day = business_date(expenditure_date, field="expenditure_date")
        periods = lock_financial_periods(day, *([payment_date] if funding_allocations else []))
        category = ExpenditureCategory.objects.filter(pk=category_id, is_active=True).first()
        if category is None:
            raise ValidationError({"category": "Select an active expenditure category."})
        if category.requires_item_details:
            raise ValidationError({"category": "Itemized/stock purchases require the inventory purchase template."})
        if category.requires_batch_beneficiary and not costs:
            raise ValidationError({"cost_allocations": "This category requires an explicit beneficiary batch."})
        expenditure = Expenditure(expenditure_date=day, amount=amount, category=category,
            accounting_period=periods[day], accounting_nature=accounting_nature,
            description=description, payee=payee, external_reference=external_reference, notes=notes,
            beneficiary_type="multiple_poultry_batches" if len(costs) > 1 else "one_poultry_batch" if costs else "general_admin",
            cost_allocation_plan=_canonical(costs), idempotency_key=f"financial-expense:{submission_id}", created_by=actor)
        expenditure.full_clean()
        if costs:
            validate_cost_allocations(expenditure, costs)
        expenditure.save()
        if not post:
            from .expenditure_drafts import expenditure_draft_version
            return {"expenditure_id": str(expenditure.pk), "journal_id": None,
                    "draft_version": expenditure_draft_version(expenditure)}
        journal = _post_expenditure_effect(expenditure=expenditure, actor=actor, costs=costs,
            funding_allocations=funding_allocations, payment_date=payment_date, submission_id=submission_id)
        return {"expenditure_id": str(expenditure.pk), "journal_id": str(journal.pk)}
    result, created = _submission(submission_id=submission_id, command="finance.expenditure.create", user=user,
        payload=dict(currency=currency, expenditure_date=expenditure_date, amount=amount, category_id=str(category_id),
            accounting_nature=accounting_nature, description=description, payee=payee, external_reference=external_reference,
            notes=notes, cost_allocations=costs, funding_allocations=funding_allocations or [], payment_date=payment_date, post=post),
        roles=FINANCE_WRITE_ROLES, effect=effect)
    return Expenditure.objects.get(pk=result["expenditure_id"]), created


def _post_expenditure_effect(*, expenditure, actor, costs, funding_allocations, payment_date, submission_id):
    """Shared source/payable/payment effect; caller holds dated/domain locks.

    Draft posting reuses the original expenditure and its one journal identity,
    not another create command or a duplicate batch-cost mirror.
    """
    if expenditure.expenditure_date > timezone.localdate():
        raise ValidationError({"expenditure_date": "Record the actual expense date, not a future event."})
    if funding_allocations:
        payment_date = business_date(payment_date, field="payment_date")
        if payment_date > timezone.localdate() or payment_date < expenditure.expenditure_date:
            raise ValidationError({"payment_date": "Record an actual payment date; pre-expense deposits require a separate verified workflow."})
    # Existing post_expenditure saves posted state without full_clean. Validate
    # the intended posted state before it creates allocation/payment sources.
    expenditure.status = ExpenditureStatus.POSTED
    expenditure.full_clean()
    expenditure.status = ExpenditureStatus.DRAFT
    expenditure = post_expenditure(expenditure_id=expenditure.pk, user=actor, cost_rows=costs, funding_rows=[], allow_unpaid=True)
    debit = ([{"account": "5000", "debit": row["amount"], "batch_id": row["batch"]} for row in costs]
             if costs else [{"account": "6100", "debit": expenditure.amount}])
    journal = post_journal(posting_date=expenditure.expenditure_date,
        description=f"Expenditure {expenditure.expenditure_reference}",
        source_model="finance.Expenditure", source_identifier=expenditure.pk,
        idempotency_key=f"financial-expenditure:{expenditure.pk}", user=actor,
        lines=debit + [{"account": "2000", "credit": expenditure.amount}])
    if funding_allocations:
        record_expenditure_payment(expenditure_id=expenditure.pk, funding_rows=funding_allocations,
            payment_group_key=f"financial-initial:{submission_id}", payment_date=payment_date, user=actor)
    return journal


def _verified_payable(expenditure):
    """An accepted draft-create alone does not prove a posted liability.

    Match permanent posting evidence to the actual unreversed control-account
    journal. Never backfill or manufacture a missing historical payable.
    """
    key = (f"inventory-purchase:{expenditure.pk}" if expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE
           else f"financial-expenditure:{expenditure.pk}")
    results = FinancialCommandReceipt.objects.filter(
        command__in=["finance.expenditure.create", "finance.expenditure.post", "inventory.receipt.record"],
        completed_at__isnull=False, result__expenditure_id=str(expenditure.pk)).values_list("result", flat=True)
    for result in results:
        journal_id = result.get("journal_id")
        if journal_id and JournalEntry.objects.filter(pk=journal_id, status=JournalStatus.POSTED,
                source_model="finance.Expenditure", source_identifier=str(expenditure.pk),
                idempotency_key=key, posting_date=expenditure.expenditure_date,
                lines__account__code="2000", lines__credit=expenditure.amount, lines__debit=Decimal("0.00")).exists():
            return True
    return False


def record_financial_supplier_payment(*, submission_id, user, currency, expenditure_id, payment_date, funding_allocations):
    _currency(currency)
    expenditure_id = _identifier(expenditure_id, "expenditure_id")
    payment_date = business_date(payment_date, field="payment_date")
    if payment_date > timezone.localdate():
        raise ValidationError({"payment_date": "Record the actual payment date, not a future event."})
    funding_allocations = _funding_rows(funding_allocations)
    def effect(actor):
        lock_financial_periods(payment_date, field="payment_date")
        expenditure = Expenditure.objects.select_for_update().get(pk=expenditure_id)
        # Never create an orphan settlement for an unreconciled historical
        # payable. Other verified (labour/payroll) template settlement is Phase7.
        if expenditure.status != ExpenditureStatus.POSTED or not _verified_payable(expenditure):
            raise ValidationError({"expenditure": "Only verified Phase6 payables can use this settlement template; legacy reconciliation is required."})
        if payment_date < expenditure.expenditure_date:
            raise ValidationError({"payment_date": "Pre-expense deposits require a separate verified workflow."})
        expenditure = record_expenditure_payment(expenditure_id=expenditure_id, payment_date=payment_date,
            funding_rows=funding_allocations, payment_group_key=f"financial-payment:{submission_id}", user=actor,
            _inventory_purchase=expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE)
        if expenditure.accounting_nature == AccountingNature.INVENTORY_PURCHASE:
            from .inventory_capture import _sync_lot_payment
            from ..models import InventoryLotBinding, SharedConsumableLot
            binding = InventoryLotBinding.objects.get(expenditure=expenditure)
            lot = SharedConsumableLot.objects.select_for_update().get(pk=binding.lot_id)
            _sync_lot_payment(lot, expenditure)
        return {"expenditure_id": str(expenditure_id)}
    result, created = _submission(submission_id=submission_id, command="finance.expenditure.pay", user=user,
        payload=dict(currency=currency, expenditure_id=str(expenditure_id), payment_date=payment_date,
                     funding_allocations=funding_allocations), roles=FINANCE_WRITE_ROLES, effect=effect)
    return Expenditure.objects.get(pk=result["expenditure_id"]), created


def record_financial_owner_contribution(*, submission_id, user, currency, owner_id, amount, receipt_date,
                                        reference="", notes="", designations=None, designation_date=None,
                                        funding_source_id=None, source_description=""):
    _currency(currency)
    amount = exact_decimal(amount, positive=True)
    owner_id = _identifier(owner_id, "owner_id")
    funding_source_id = _identifier(funding_source_id, "funding_source_id") if funding_source_id is not None else None
    if not isinstance(receipt_date, datetime) or timezone.is_naive(receipt_date) or receipt_date > timezone.now() + timedelta(minutes=5):
        raise ValidationError({"receipt_date": "Record an actual timezone-aware receipt instant, not a future date."})
    # The reused service checks .date() directly; normalize before calling it so
    # its lock and reporting calendar agree even at midnight across offsets.
    receipt_date = receipt_date.astimezone(timezone.get_default_timezone())
    designation_date = business_date(designation_date, field="designation_date") if designation_date is not None else None
    normalized = []
    for row in _rows(designations, "designations"):
        _fields(row, {"batch", "amount", "notes"}, "designations")
        normalized.append({"batch": _identifier(row.get("batch"), "batch"),
                           "amount": exact_decimal(row.get("amount"), positive=True),
                           "notes": _text(row.get("notes", ""), "designations.notes", 4000)})
    designations = normalized
    reference = _text(reference, "reference", 120)
    notes = _text(notes, "notes", 4000)
    source_description = _text(source_description, "source_description", 255)
    def effect(actor):
        lock_financial_periods(receipt_date, *([designation_date] if designations and designation_date else []))
        receipt, _ = record_owner_contribution(owner_id=owner_id, amount=amount, receipt_date=receipt_date,
            reference=reference, notes=notes, designations=designations or [], designation_date=designation_date,
            funding_source_id=funding_source_id, source_description=source_description,
            idempotency_key=f"financial-owner:{submission_id}", user=actor)
        journal = post_journal(posting_date=business_date(receipt.receipt_date), description="Owner capital received",
            source_model="finance.FundingReceipt", source_identifier=receipt.pk,
            idempotency_key=f"financial-owner-receipt:{receipt.pk}", user=actor,
            lines=[{"account": "1000", "debit": amount, "funding_source_id": receipt.funding_source_id},
                   {"account": "3000", "credit": amount, "funding_source_id": receipt.funding_source_id}])
        return {"receipt_id": str(receipt.pk), "journal_id": str(journal.pk)}
    result, created = _submission(submission_id=submission_id, command="finance.owner_contribution.record", user=user,
        payload=dict(currency=currency, owner_id=str(owner_id), amount=amount, receipt_date=receipt_date,
            reference=reference, notes=notes, designations=designations or [], designation_date=designation_date,
            funding_source_id=str(funding_source_id) if funding_source_id else None, source_description=source_description),
        roles=OWNER_CAPITAL_ROLES, effect=effect)
    return FundingReceipt.objects.get(pk=result["receipt_id"]), created
