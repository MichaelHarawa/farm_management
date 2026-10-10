"""Private source-linked sale-cost journal boundary; no API authorization grant."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models import Q

_journal = ContextVar("sale_cost_reversal_journal", default=None)


@contextmanager
def sale_cost_reversal_boundary(journal_id):
    token = _journal.set(journal_id)
    try:
        yield
    finally:
        _journal.reset(token)


def sale_cost_reversal_allowed(journal_id):
    return journal_id is not None and _journal.get() == journal_id


def is_managed_sale_cost_journal(journal_id):
    from ..models import JournalEntry
    original = Q(source_model="finance.SaleCostPayment", idempotency_key__startswith="sale-cost-payment:")
    original |= Q(source_model="poultry.SaleSellingCost", idempotency_key__startswith="sale-selling-cost:")
    opposite = Q(reversal_of__source_model="finance.SaleCostPayment",
                 reversal_of__idempotency_key__startswith="sale-cost-payment:")
    opposite |= Q(reversal_of__source_model="poultry.SaleSellingCost",
                  reversal_of__idempotency_key__startswith="sale-selling-cost:")
    # Existing journal tables only, including when the migrated feature is off.
    return JournalEntry.objects.filter(pk=journal_id).filter(original | opposite).exists()
