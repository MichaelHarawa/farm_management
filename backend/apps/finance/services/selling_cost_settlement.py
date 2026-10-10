"""Unregistered Phase6 sale-cost settlement; never adopt historical liabilities."""
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from apps.poultry.models import Batch, PaymentStatus, Sales, SaleSellingCost
from ..models import (ExpenditureStatus, FinancialCommandReceipt, FundingAllocation,
    FundingClassification, FundingReceipt, FundingReceiptStatus, FundingSource,
    FundingSourceType, JournalEntry, JournalStatus, PayrollPaymentFunding,
    PayrollPaymentStatus, SaleCostPayment, SalePayment, SalePaymentStatus)
from ..permissions import FINANCE_WRITE_ROLES
from .action_audit import record_finance_action
from .expenditures import _validate_payment_rows
from .financial_capture import _canonical, _currency, _funding_rows, _identifier, _submission, _text
from .financial_values import business_date, exact_decimal, lock_financial_periods
from .ledger import post_journal

ZERO = Decimal("0.00")


def sale_cost_reads_enabled():
    return (getattr(settings, "FINANCE_SALE_COST_SETTLEMENT", False)
            or getattr(settings, "FINANCE_SALE_COST_REVERSALS", False))


def sale_cost_payment_version(payment):
    from .funding_capture import funding_source_version
    return checksum(_canonical({"basis": "phase6-sale-cost-payment-v1",
        "payment": {field.attname: getattr(payment, field.attname) for field in payment._meta.concrete_fields},
        "source_binding": funding_source_version(payment.funding_source)}))


def sale_cost_cash_total(filters, *, cutoff=None):
    rows = SaleCostPayment.objects.filter(**filters)
    if cutoff is not None:
        rows = rows.filter(payment_date__lte=cutoff)
    total = rows.aggregate(total=Sum("amount"))["total"] or ZERO
    if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
        from ..models import SaleCostPaymentReversal
        refunds = SaleCostPaymentReversal.objects.filter(**{"payment__" + key: value for key, value in filters.items()})
        if cutoff is not None:
            refunds = refunds.filter(refund_date__lte=cutoff)
        total -= refunds.aggregate(total=Sum("amount"))["total"] or ZERO
    return total


def net_sale_cost_payment_rows(rows):
    rows = list(rows)
    refunds = {}
    if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
        from ..models import SaleCostPaymentReversal
        refunds = dict(SaleCostPaymentReversal.objects.filter(payment_id__in=[row.pk for row in rows]).values_list("payment_id", "amount"))
    return [(row, row.amount - refunds.get(row.pk, ZERO)) for row in rows]


def selling_cost_version(cost):
    """Whole original cost + sale economics, excluding derived collection state."""
    sale = cost.sale
    return checksum(_canonical({"kind": "phase6-sale-cost-v1",
        "cost": {field.attname: getattr(cost, field.attname) for field in cost._meta.concrete_fields},
        "sale": {field: getattr(sale, field) for field in (
            "id", "sale_id", "batch_id", "sale_date", "product_type", "quantity_sold", "unit_price",
            "created_by_id", "created_at")}}))


def sale_cost_payment_total(cost, *, cutoff=None):
    return sale_cost_cash_total({"selling_cost": cost}, cutoff=cutoff)


def sale_cost_payable_summary(cutoff):
    """Original accepted control entries minus dated settlements, not backfill.

    Mutable cost edits cannot silently remove the already recognized liability.
    This reports original journal amounts; missing/changed sources require review.
    """
    anchors = {}
    for result in FinancialCommandReceipt.objects.filter(command="poultry.sale.record").values_list("result", flat=True):
        for row in result.get("selling_cost_versions", []):
            anchors[row["journal_id"]] = row
    total = ZERO
    ageing = {"current": ZERO, "31_60": ZERO, "61_90": ZERO, "over_90": ZERO}
    review_required = 0
    journals = JournalEntry.objects.filter(pk__in=anchors, status=JournalStatus.POSTED,
        source_model="poultry.SaleSellingCost", posting_date__lte=cutoff).prefetch_related("lines__account")
    payments = {row["selling_cost_id"]: row["total"] for row in SaleCostPayment.objects.filter(
        payment_date__lte=cutoff).values("selling_cost_id").annotate(total=Sum("amount"))}
    if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
        from ..models import SaleCostPaymentReversal
        for row in SaleCostPaymentReversal.objects.filter(refund_date__lte=cutoff).values(
                "payment__selling_cost_id").annotate(total=Sum("amount")):
            pk = row["payment__selling_cost_id"]
            payments[pk] = payments.get(pk, ZERO) - row["total"]
    costs = {str(cost.pk): cost for cost in SaleSellingCost.objects.filter(
        pk__in=[row["selling_cost_id"] for row in anchors.values()]).select_related("sale")}
    for journal in journals:
        anchor = anchors[str(journal.pk)]
        cost = costs.get(anchor["selling_cost_id"])
        control = sum((line.credit - line.debit for line in journal.lines.all() if line.account.code == "2000"), ZERO)
        outstanding = control - payments.get(int(anchor["selling_cost_id"]), ZERO)
        if cost is None or selling_cost_version(cost) != anchor["source_version"] or cost.sale.payment_status == PaymentStatus.CANCELLED:
            review_required += 1
        total += outstanding
        age = (cutoff - journal.posting_date).days
        bucket = "current" if age <= 30 else "31_60" if age <= 60 else "61_90" if age <= 90 else "over_90"
        ageing[bucket] += outstanding
    return {"total": total, "ageing": ageing, "review_required": review_required}


def _verified_liability(cost):
    """Accepted source version and full original unreversed journal must agree."""
    version = selling_cost_version(cost)
    results = FinancialCommandReceipt.objects.filter(command="poultry.sale.record",
        result__sale_id=str(cost.sale_id), completed_at__isnull=False).values_list("result", flat=True)
    for result in results:
        anchor = next((row for row in result.get("selling_cost_versions", [])
                       if row["selling_cost_id"] == str(cost.pk)), None)
        if not anchor or anchor["source_version"] != version:
            continue
        journal = JournalEntry.objects.filter(pk=anchor["journal_id"], status=JournalStatus.POSTED,
            idempotency_key=f"sale-selling-cost:{cost.pk}", source_model="poultry.SaleSellingCost",
            source_identifier=str(cost.pk), posting_date=business_date(cost.sale.sale_date)).first()
        if journal is None:
            continue
        actual = [(line.account.code, line.debit, line.credit, line.batch_id,
                   line.funding_source_id) for line in journal.lines.select_related("account")]
        expected = [("2000", ZERO, cost.amount, cost.sale.batch_id, None),
                    ("6000", cost.amount, ZERO, cost.sale.batch_id, None)]
        if len(actual) == 2 and set(actual) == set(expected):
            return journal, version
    raise ValidationError({"selling_cost": "Original versioned sale-cost/payable evidence does not match; controlled review is required."})


def _dated_source_cash(source, day):
    """Conservative dated funding: incoming to this day minus ALL committed uses.

    Later cash is not available to a backdated payment. Subtracting future uses
    also reserves their confirmed cash; this never reorders historical payments.
    """
    if source.source_type == FundingSourceType.BATCH_COLLECTION:
        scope = {"funding_source__source_type": FundingSourceType.BATCH_COLLECTION,
                 "funding_source__batch_id": source.batch_id}
        received = SalePayment.objects.filter(sale__batch_id=source.batch_id,
            sale__payment_status__in=[PaymentStatus.PAID, PaymentStatus.PARTIAL, PaymentStatus.UNPAID],
            status=SalePaymentStatus.POSTED, payment_date__date__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
    else:
        scope = {"funding_source_id": source.pk}
        received = FundingReceipt.objects.filter(funding_source=source, status=FundingReceiptStatus.POSTED,
            receipt_date__date__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
    expense = FundingAllocation.objects.filter(**scope, expenditure__status=ExpenditureStatus.POSTED).aggregate(total=Sum("amount"))["total"] or ZERO
    payroll = PayrollPaymentFunding.objects.filter(**scope, payment__status=PayrollPaymentStatus.POSTED).aggregate(total=Sum("amount"))["total"] or ZERO
    costs = SaleCostPayment.objects.filter(**scope).aggregate(total=Sum("amount"))["total"] or ZERO
    if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
        from ..models import SaleCostPaymentReversal
        costs -= SaleCostPaymentReversal.objects.filter(**scope, refund_date__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
    reversed_funding = ZERO
    if getattr(settings, "FINANCE_FUNDING_REVERSALS", False):
        from ..models import FundingReceiptReversal
        reversed_funding = FundingReceiptReversal.objects.filter(funding_source=source).aggregate(total=Sum("amount"))["total"] or ZERO
    return received - expense - payroll - costs - reversed_funding


def record_sale_cost_payment(*, submission_id, user, currency, selling_cost_id,
                             payment_date, funding_allocations, payee, payment_method,
                             external_reference="", notes=""):
    if not getattr(settings, "FINANCE_SALE_COST_SETTLEMENT", False):
        raise ValidationError({"command_unavailable": "Sale-cost settlement requires its migrated isolated deployment gate."})
    _currency(currency)
    selling_cost_id = _identifier(selling_cost_id, "selling_cost_id")
    day = business_date(payment_date, field="payment_date")
    if day > timezone.localdate():
        raise ValidationError({"payment_date": "Record an actual payment date, not a future event."})
    if payment_method not in ("cash", "mobile_money", "bank_transfer"):
        raise ValidationError({"payment_method": "Select an actual cash payment method; credit is not payment."})
    payee = _text(payee, "payee", 200)
    if not payee:
        raise ValidationError({"payee": "Record the actual selling-cost payee."})
    external_reference = _text(external_reference, "external_reference", 120)
    notes = _text(notes, "notes", 4000)
    funding = _funding_rows(funding_allocations)
    if not funding:
        raise ValidationError({"funding_allocations": "Select at least one confirmed cash source."})
    for row in funding:
        if (row.get("classification") or FundingClassification.REINVESTMENT) not in (
                FundingClassification.REINVESTMENT, FundingClassification.WORKING_CAPITAL,
                FundingClassification.COST_RECOVERY):
            raise ValidationError({"funding_allocations": "Selling-cost settlement is operating cash use, not owner distribution or debt service."})
    exact_decimal(sum((row["amount"] for row in funding), ZERO), positive=True)
    payload = dict(currency=currency, selling_cost_id=str(selling_cost_id), payment_date=day,
        funding_allocations=funding, payee=payee, payment_method=payment_method,
        external_reference=external_reference, notes=notes)

    def effect(actor):
        lock_financial_periods(day, field="payment_date")
        candidate = SaleSellingCost.objects.filter(pk=selling_cost_id).first()
        if candidate is None:
            raise ValidationError({"selling_cost_id": "Select an existing sale-specific cost."})
        funding_ids = [row["funding_source"] for row in funding]
        sources = list(FundingSource.objects.filter(pk__in=funding_ids))
        source_bindings = {source.pk: (source.source_type, source.batch_id, source.owner_id) for source in sources}
        batches = {candidate.sale.batch_id} | {source.batch_id for source in sources if source.batch_id}
        list(Batch.objects.select_for_update().filter(pk__in=batches).order_by("pk"))
        sale = Sales.objects.select_for_update().get(pk=candidate.sale_id)
        cost = SaleSellingCost.objects.select_for_update().get(pk=selling_cost_id)
        if (cost.sale_id != candidate.sale_id or sale.batch_id != candidate.sale.batch_id
                or sale.payment_status == PaymentStatus.CANCELLED):
            raise ValidationError({"selling_cost": "The original sale changed or was cancelled; review is required."})
        cost.sale = sale
        if day < business_date(sale.sale_date):
            raise ValidationError({"payment_date": "Pre-sale deposits require a separate verified workflow."})
        journal, version = _verified_liability(cost)
        # Owner funding needs the separate owner settlement/report/reversal gate.
        # Do not expose it merely because this actor is an administrator.
        aliases = FundingSource.objects.filter(source_type=FundingSourceType.BATCH_COLLECTION,
                                               batch_id__in=batches).values_list("pk", flat=True)
        locked_sources = list(FundingSource.objects.select_for_update().filter(
            pk__in=set(funding_ids) | set(aliases)).order_by("pk"))
        for source in locked_sources:
            if source.pk not in funding_ids:
                continue
            if source_bindings.get(source.pk) != (source.source_type, source.batch_id, source.owner_id):
                raise ValidationError({"funding_allocations": "Cash-source binding changed; review is required."})
            if source.source_type == FundingSourceType.OWNER_CAPITAL:
                raise ValidationError({"funding_allocations": "Owner-cash selling-cost settlement is not enabled; use controlled owner review."})
        # Reserve every committed payment, but reopen this dated payable only
        # for refunds actually received by this payment date. A future refund
        # must not allow a backdated overpayment even when source cash is ample.
        reserved_paid = SaleCostPayment.objects.filter(selling_cost=cost).aggregate(total=Sum("amount"))["total"] or ZERO
        if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
            from ..models import SaleCostPaymentReversal
            reserved_paid -= SaleCostPaymentReversal.objects.filter(payment__selling_cost=cost,
                refund_date__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
        outstanding = cost.amount - reserved_paid
        normalized = _validate_payment_rows(funding, outstanding, allow_less=True, user=actor)
        totals = defaultdict(lambda: ZERO)
        for row in normalized:
            totals[row["funding_source"]] += row["amount"]
        sources = {source.pk: source for source in FundingSource.objects.filter(pk__in=totals)}
        # Aliased batch sources share one cash pool, not separate balances.
        pool_totals = defaultdict(lambda: ZERO)
        pool_sources = {}
        for pk, amount in totals.items():
            source = sources[pk]
            pool = ("batch", source.batch_id) if source.source_type == FundingSourceType.BATCH_COLLECTION else ("source", pk)
            pool_totals[pool] += amount
            pool_sources[pool] = source
        for pool, amount in pool_totals.items():
            if amount > _dated_source_cash(pool_sources[pool], day):
                raise ValidationError({"funding_allocations": "Confirmed dated cash is insufficient; later receipts cannot fund this event."})
        ids, journals, versions = [], [], []
        for index, row in enumerate(normalized):
            payment = SaleCostPayment(selling_cost=cost, funding_source_id=row["funding_source"],
                payable_journal=journal, source_version=version, submission_id=submission_id, split_index=index,
                amount=row["amount"], classification=row["classification"], payment_date=day,
                payee=payee, payment_method=payment_method, external_reference=external_reference,
                notes=notes, created_by=actor)
            payment.save(_financial_posting=True)
            entry = post_journal(posting_date=day, description=f"Payment of selling cost for {sale.sale_id}",
                source_model="finance.SaleCostPayment", source_identifier=payment.pk,
                idempotency_key=f"sale-cost-payment:{payment.pk}", user=actor,
                lines=[{"account": "2000", "debit": payment.amount, "batch_id": sale.batch_id,
                        "funding_source_id": payment.funding_source_id},
                       {"account": "1000", "credit": payment.amount, "funding_source_id": payment.funding_source_id}])
            ids.append(str(payment.pk))
            journals.append(str(entry.pk))
            versions.append(sale_cost_payment_version(payment))
        record_finance_action(actor=actor, action="sale_selling_cost_paid",
            entity_type="poultry.SaleSellingCost", entity_id=cost.pk,
            after_data={"submission_id": str(submission_id), "source_version": version,
                        "payment_ids": ids, "payment_date": day, "payee": payee})
        return {"selling_cost_id": str(cost.pk), "payment_ids": ids, "journal_ids": journals,
                "source_version": version, "original_request": _canonical(payload), "payment_versions": versions}

    result, created = _submission(submission_id=submission_id, command="finance.sale_cost.pay", user=user,
        payload=payload, roles=FINANCE_WRITE_ROLES, effect=effect)
    return list(SaleCostPayment.objects.filter(pk__in=result["payment_ids"]).order_by("split_index")), created
