from __future__ import annotations

import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ..models import (
    AccountingPeriod,
    ChartOfAccount,
    JournalEntry,
    JournalLine,
    JournalStatus,
    PeriodStatus,
)
from .financial_values import business_date, exact_decimal, lock_financial_periods


ZERO = Decimal("0.00")


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _line_content(line):
    return (str(line["account"]), exact_decimal(line.get("debit", 0), max_digits=18, field="lines"),
            exact_decimal(line.get("credit", 0), max_digits=18, field="lines"),
            str(line["batch_id"]) if line.get("batch_id") is not None else "",
            str(line["funding_source_id"]) if line.get("funding_source_id") is not None else "",
            line.get("memo", ""))


def _assert_replay(entry, *, posting_date, description, source_model, source_identifier, content):
    actual = sorted((line.account.code, line.debit, line.credit,
                     str(line.batch_id) if line.batch_id is not None else "",
                     str(line.funding_source_id) if line.funding_source_id is not None else "", line.memo)
                    for line in entry.lines.select_related("account").all())
    if (entry.posting_date != posting_date or entry.description != description or
            entry.source_model != source_model or entry.source_identifier != str(source_identifier) or
            actual != sorted(content)):
        raise ValidationError({"idempotency_key": "This journal key is bound to different posting content."})
    return entry


def period_for(posting_date):
    return AccountingPeriod.objects.filter(
        period_start__lte=posting_date, period_end__gte=posting_date
    ).order_by("-period_start").first()


@transaction.atomic
def post_journal(
    *,
    posting_date,
    description: str,
    source_model: str,
    source_identifier: str,
    idempotency_key: str,
    lines: list[dict],
    user=None,
    allow_historical=False,
) -> JournalEntry:
    posting_date = business_date(posting_date)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 180:
        raise ValidationError({"idempotency_key": "A non-blank journal submission key of at most 180 characters is required."})
    if not isinstance(lines, list) or not lines:
        raise ValidationError({"lines": "Provide balanced journal lines."})
    content = [_line_content(line) for line in lines]
    if any(not ((debit > 0 and credit == 0) or (credit > 0 and debit == 0)) for _, debit, credit, *_ in content):
        raise ValidationError({"lines": "Each line requires exactly one positive debit or credit."})
    replay = dict(posting_date=posting_date, description=description, source_model=source_model,
                  source_identifier=source_identifier, content=content)
    existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return _assert_replay(existing, **replay)
    period = (period_for(posting_date) if allow_historical else
              lock_financial_periods(posting_date)[posting_date])
    if period is None:
        raise ValidationError({"posting_date": "Create an accounting period covering this date."})
    if period.status == PeriodStatus.CLOSED and not allow_historical:
        raise ValidationError({"accounting_period": "Closed periods reject new postings; formally reopen it first."})
    debit = sum((line[1] for line in content), ZERO)
    credit = sum((line[2] for line in content), ZERO)
    if debit <= ZERO or debit != credit:
        raise ValidationError({"lines": f"Journal must balance exactly; debits={debit}, credits={credit}."})
    # Recheck after waiting on the dated lock. A concurrent identical key may
    # have committed meanwhile, including a request using a different date.
    existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return _assert_replay(existing, **replay)
    try:
        with transaction.atomic():
            entry = JournalEntry.objects.create(
                reference=f"JRN-{posting_date:%Y%m%d}-{uuid.uuid4().hex[:10].upper()}",
                posting_date=posting_date, accounting_period=period, description=description,
                source_model=source_model, source_identifier=str(source_identifier),
                idempotency_key=idempotency_key, created_by=user)
    except IntegrityError:
        existing = JournalEntry.objects.filter(idempotency_key=idempotency_key).first()
        if existing is None:
            raise
        return _assert_replay(existing, **replay)
    account_map = {
        account.code: account
        for account in ChartOfAccount.objects.filter(
            code__in={line["account"] for line in lines}, is_active=True
        )
    }
    missing = {line["account"] for line in lines} - set(account_map)
    if missing:
        raise ValidationError({"account": "Missing chart account(s): " + ", ".join(sorted(missing))})
    JournalLine.objects.bulk_create(
        [
            JournalLine(
                journal_entry=entry,
                account=account_map[line["account"]],
                debit=money(line.get("debit")),
                credit=money(line.get("credit")),
                batch_id=line.get("batch_id"),
                funding_source_id=line.get("funding_source_id"),
                memo=line.get("memo", ""),
            )
            for line in lines
        ]
    )
    entry.status = JournalStatus.POSTED
    entry.posted_by = user
    entry.posted_at = timezone.now()
    entry.save(update_fields=["status", "posted_by", "posted_at", "updated_at"])
    return entry


@transaction.atomic
def reverse_journal(entry: JournalEntry, *, posting_date, reason: str, user=None):
    entry = JournalEntry.objects.select_for_update().prefetch_related("lines").get(pk=entry.pk)
    if entry.status != JournalStatus.POSTED:
        raise ValidationError("Only a posted journal can be reversed.")
    if not reason.strip():
        raise ValidationError("A reversal reason is required.")
    reversal = post_journal(
        posting_date=posting_date,
        description=f"Reversal of {entry.reference}: {reason}",
        source_model="finance.JournalEntry",
        source_identifier=entry.pk,
        idempotency_key=f"reversal:{entry.pk}",
        user=user,
        lines=[
            {
                "account": line.account.code,
                "debit": line.credit,
                "credit": line.debit,
                "batch_id": line.batch_id,
                "funding_source_id": line.funding_source_id,
                "memo": f"Reversal of line {line.pk}",
            }
            for line in entry.lines.all()
        ],
    )
    reversal.reversal_of = entry
    # This relationship is part of the reversal transaction and is set before the
    # original entry is marked reversed; financial line content remains immutable.
    JournalEntry.objects.filter(pk=reversal.pk).update(reversal_of=entry)
    entry.status = JournalStatus.REVERSED
    entry.reversed_by = user
    entry.reversed_at = timezone.now()
    entry.reversal_reason = reason
    entry.save(
        update_fields=["status", "reversed_by", "reversed_at", "reversal_reason", "updated_at"]
    )
    return reversal


def trial_balance(*, cutoff=None) -> dict:
    # A reversal is a new opposite posting, not deletion of the original effect.
    # Excluding REVERSED originals counted only the opposite side of history.
    lines = JournalLine.objects.filter(journal_entry__status__in=[JournalStatus.POSTED, JournalStatus.REVERSED])
    if cutoff:
        lines = lines.filter(journal_entry__posting_date__lte=cutoff)
    rows = lines.values("account__code", "account__name", "account__account_type").annotate(
        debit=Sum("debit"), credit=Sum("credit")
    )
    result = [
        {
            "code": row["account__code"],
            "name": row["account__name"],
            "account_type": row["account__account_type"],
            "debit": money(row["debit"]),
            "credit": money(row["credit"]),
            "balance": money(row["debit"] - row["credit"]),
        }
        for row in rows
    ]
    return {
        "debits": money(sum((row["debit"] for row in result), ZERO)),
        "credits": money(sum((row["credit"] for row in result), ZERO)),
        "accounts": result,
    }
