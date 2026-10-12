"""One locked cash pool per batch, with explicit dated Phase6 funding checks.

Funding-source aliases are labels, not independent batch cash balances. Call
the locking/validation pair in the caller's atomic payment transaction, after
its period and liability locks. No historical payment dates are rewritten.
"""
from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.poultry.models import PaymentStatus
from ..models import (ExpenditureStatus, FundingAllocation, FundingReceipt,
    FundingReceiptStatus, FundingSource, FundingSourceType, PayrollPaymentFunding,
    PayrollPaymentStatus, SalePayment, SalePaymentStatus)

ZERO = Decimal("0.00")
MAX_CASH_SOURCES = 10000


def lock_cash_sources(source_ids):
    """Lock selected sources AND all their batch aliases in one PK order.

    Do not acquire a Batch lock here: suppliers already hold their payable,
    whereas selling-cost settlement locks batches before its payable. Taking
    another batch lock here would introduce an inverted lock order. All cash
    consumers instead share the same existing source-family rows.
    """
    if not transaction.get_connection().in_atomic_block:
        raise ValidationError({"funding_allocations": "Cash validation requires an atomic payment transaction."})
    ids = set(source_ids)
    if len(ids) > MAX_CASH_SOURCES:
        raise ValidationError({"funding_allocations": "Cash-source family exceeds the safe review limit."})
    observed = {
        row[0]: row[1:] for row in FundingSource.objects.filter(pk__in=ids).values_list(
            "pk", "source_type", "batch_id", "owner_id")}
    if set(observed) != ids:
        raise ValidationError({"funding_allocations": "A selected funding source does not exist."})
    batches = {binding[1] for binding in observed.values()
               if binding[0] == FundingSourceType.BATCH_COLLECTION and binding[1] is not None}
    family = FundingSource.objects.filter(Q(pk__in=ids) | Q(
        source_type=FundingSourceType.BATCH_COLLECTION, batch_id__in=batches))
    family_ids = list(family.order_by("pk").values_list("pk", flat=True)[:MAX_CASH_SOURCES + 1])
    if len(family_ids) > MAX_CASH_SOURCES:
        raise ValidationError({"funding_allocations": "Cash-source family exceeds the safe review limit."})
    # Do not join nullable batch/owner tables under PostgreSQL FOR UPDATE.
    locked = list(FundingSource.objects.select_for_update().filter(pk__in=family_ids).order_by("pk"))
    sources = {source.pk: source for source in locked if source.pk in ids}
    if set(sources) != ids or any(observed[pk] != (
            source.source_type, source.batch_id, source.owner_id) for pk, source in sources.items()):
        raise ValidationError({"funding_allocations": "Cash-source binding changed; review is required."})
    return sources


def dated_source_cash(source, day):
    """Receipts through this accounting day, less ALL currently committed uses.

    Future confirmed uses remain reserved. Only actual sale-cost refunds
    received by this day reopen cash. This is not a legacy correction/backfill
    policy: the existing POSTED status semantics remain unchanged.
    """
    if source.source_type == FundingSourceType.BATCH_COLLECTION:
        if source.batch_id is None:
            return ZERO
        scope = {"funding_source__source_type": FundingSourceType.BATCH_COLLECTION,
                 "funding_source__batch_id": source.batch_id}
        receipts = SalePayment.objects.filter(sale__batch_id=source.batch_id,
            sale__payment_status__in=[PaymentStatus.PAID, PaymentStatus.PARTIAL, PaymentStatus.UNPAID],
            status=SalePaymentStatus.POSTED)
        date_field = "payment_date"
    else:
        scope = {"funding_source_id": source.pk}
        receipts = FundingReceipt.objects.filter(funding_source=source, status=FundingReceiptStatus.POSTED)
        date_field = "receipt_date"
    # Use the established accounting calendar, not a request's active timezone
    # or the mobile Africa/Blantyre display calendar (see business_date).
    received = receipts.annotate(cash_day=TruncDate(date_field,
        tzinfo=timezone.get_default_timezone())).filter(cash_day__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
    expense = FundingAllocation.objects.filter(**scope,
        expenditure__status=ExpenditureStatus.POSTED).aggregate(total=Sum("amount"))["total"] or ZERO
    payroll = PayrollPaymentFunding.objects.filter(**scope,
        payment__status=PayrollPaymentStatus.POSTED).aggregate(total=Sum("amount"))["total"] or ZERO
    costs = ZERO
    if (getattr(settings, "FINANCE_SALE_COST_SETTLEMENT", False)
            or getattr(settings, "FINANCE_SALE_COST_REVERSALS", False)):
        from ..models import SaleCostPayment
        costs = SaleCostPayment.objects.filter(**scope).aggregate(total=Sum("amount"))["total"] or ZERO
        if getattr(settings, "FINANCE_SALE_COST_REVERSALS", False):
            from ..models import SaleCostPaymentReversal
            costs -= SaleCostPaymentReversal.objects.filter(**scope,
                refund_date__lte=day).aggregate(total=Sum("amount"))["total"] or ZERO
    reversed_funding = ZERO
    if getattr(settings, "FINANCE_FUNDING_REVERSALS", False):
        from ..models import FundingReceiptReversal
        reversed_funding = FundingReceiptReversal.objects.filter(
            funding_source=source).aggregate(total=Sum("amount"))["total"] or ZERO
    return received - expense - payroll - costs - reversed_funding


def validate_cash_totals(totals, sources, *, day=None):
    """Combined splits must fit each shared pool, never each alias separately."""
    from .profitability import available_funding_source_cash
    pools = defaultdict(lambda: ZERO)
    representatives = {}
    for pk, amount in totals.items():
        source = sources[pk]
        pool = ("batch", source.batch_id) if source.source_type == FundingSourceType.BATCH_COLLECTION else ("source", pk)
        pools[pool] += amount
        representatives[pool] = source
    for pool, required in pools.items():
        source = representatives[pool]
        available = dated_source_cash(source, day) if day is not None else available_funding_source_cash(source)
        if required > available:
            message = ("Confirmed dated cash is insufficient; later receipts cannot fund this event."
                       if day is not None else "Combined funding splits exceed the shared cash pool's available balance.")
            raise ValidationError({"funding_allocations": message})
