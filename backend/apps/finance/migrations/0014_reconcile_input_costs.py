from decimal import Decimal
import re

from django.db import migrations
from django.db.models import Sum
from django.utils import timezone


CATEGORY_DEFINITIONS = [
    ("Feed", "feed", "direct_cost", True, True, 20),
    ("Chicks or livestock", "chicks_livestock", "direct_cost", True, True, 30),
    ("Veterinary and medication", "veterinary_medication", "direct_cost", True, True, 40),
    ("Batch transport", "batch_transport", "direct_cost", True, True, 45),
    ("Batch utilities", "batch_utilities", "direct_cost", True, True, 55),
    ("Biosecurity", "biosecurity", "direct_cost", True, True, 56),
    ("Batch supplies", "batch_supplies", "direct_cost", True, True, 57),
]


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def category_code_for(input_cost):
    text = normalize(f"{input_cost.category} {input_cost.item}")
    if "feed" in text or "maize" in text or "soya" in text or "kbc" in text:
        return "feed"
    if "chick" in text:
        return "chicks_livestock"
    if any(word in text for word in ("drug", "vacc", "vitamin", "hitchner", "gumbolo", "lasota", "otc", "stress", "utuchi")):
        return "veterinary_medication"
    if "transport" in text:
        return "batch_transport"
    if any(word in text for word in ("water", "charcoal", "temperature")):
        return "batch_utilities"
    if any(word in text for word in ("biosecurity", "disinfect", "cleanser")):
        return "biosecurity"
    return "batch_supplies"


def next_reference(Expenditure, transaction_date):
    prefix = f"EXP-{transaction_date:%Y%m%d}-"
    suffixes = []
    for reference in Expenditure.objects.filter(
        expenditure_reference__startswith=prefix
    ).values_list("expenditure_reference", flat=True):
        try:
            suffixes.append(int(reference.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{max(suffixes, default=0) + 1:04d}"


def reconcile_input_costs(apps, schema_editor):
    AccountingPeriod = apps.get_model("finance", "AccountingPeriod")
    CostAllocation = apps.get_model("finance", "CostAllocation")
    Expenditure = apps.get_model("finance", "Expenditure")
    ExpenditureCategory = apps.get_model("finance", "ExpenditureCategory")
    FundingAllocation = apps.get_model("finance", "FundingAllocation")
    InputCost = apps.get_model("poultry", "InputCosts")
    Reconciliation = apps.get_model("finance", "InputCostReconciliation")

    categories = {}
    for name, code, nature, item_details, batch_required, order in CATEGORY_DEFINITIONS:
        category, _ = ExpenditureCategory.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "default_accounting_nature": nature,
                "requires_item_details": item_details,
                "requires_batch_beneficiary": batch_required,
                "is_active": True,
                "display_order": order,
            },
        )
        categories[code] = category

    # Bring existing central transactions onto the derived payment-state model.
    for expenditure in Expenditure.objects.all():
        funded = FundingAllocation.objects.filter(expenditure_id=expenditure.pk).aggregate(
            total=Sum("amount")
        )["total"] or Decimal("0.00")
        if funded >= expenditure.amount:
            payment_status = "paid"
        elif funded > Decimal("0.00"):
            payment_status = "partial"
        else:
            payment_status = "unpaid"
        Expenditure.objects.filter(pk=expenditure.pk).update(payment_status=payment_status)

    for input_cost in InputCost.objects.select_related("batch").order_by("pk"):
        if input_cost.expenditure_id:
            Reconciliation.objects.get_or_create(
                input_cost_id=input_cost.pk,
                defaults={
                    "expenditure_id": input_cost.expenditure_id,
                    "status": "matched",
                    "match_basis": "Pre-existing explicit relationship.",
                },
            )
            continue

        transaction_date = input_cost.purchase_date.date()
        amount = (
            Decimal(input_cost.quantity)
            * Decimal(input_cost.unit)
            * input_cost.unit_cost
        ).quantize(Decimal("0.01"))
        category = categories[category_code_for(input_cost)]
        candidates = list(
            Expenditure.objects.filter(
                expenditure_date=transaction_date,
                amount=amount,
                cost_allocations__batch_id=input_cost.batch_id,
                status="posted",
            ).distinct()
        )
        confirmed = [
            candidate
            for candidate in candidates
            if normalize(candidate.description) == normalize(input_cost.item)
            or candidate.category_id == category.pk
        ]

        if len(confirmed) == 1:
            expenditure = confirmed[0]
            InputCost.objects.filter(pk=input_cost.pk).update(expenditure_id=expenditure.pk)
            Reconciliation.objects.create(
                input_cost_id=input_cost.pk,
                expenditure_id=expenditure.pk,
                status="matched",
                match_basis="Exact batch, date, amount, and description/category match.",
            )
            continue

        if candidates:
            Reconciliation.objects.create(
                input_cost_id=input_cost.pk,
                status="uncertain",
                match_basis=(
                    "Possible expenditure match on batch, date, and amount; description/category "
                    "was not conclusive. Existing records were left unchanged."
                ),
                requires_manual_review=True,
            )
            continue

        period = AccountingPeriod.objects.filter(
            period_start__lte=transaction_date,
            period_end__gte=transaction_date,
        ).order_by("-period_start").first()
        if period is None:
            Reconciliation.objects.create(
                input_cost_id=input_cost.pk,
                status="unresolved",
                match_basis="No accounting period covers the historical purchase date.",
                requires_manual_review=True,
            )
            continue

        expenditure = Expenditure.objects.create(
            expenditure_date=transaction_date,
            accounting_period_id=period.pk,
            amount=amount,
            category_id=category.pk,
            accounting_nature="direct_cost",
            description=input_cost.item,
            expenditure_reference=next_reference(Expenditure, transaction_date),
            status="posted",
            payment_status="historical_unassigned",
            origin="historical_input_cost",
            beneficiary_type="one_poultry_batch",
            beneficiary_detail=input_cost.batch.batch_id,
            cost_allocation_plan=[{"batch": input_cost.batch_id, "amount": str(amount)}],
            notes=input_cost.notes,
            created_by_id=input_cost.created_by_id,
            posted_by_id=input_cost.created_by_id,
            posted_at=input_cost.created_at or timezone.now(),
        )
        CostAllocation.objects.create(
            accounting_period_id=period.pk,
            batch_id=input_cost.batch_id,
            source_type="expenditure",
            expenditure_id=expenditure.pk,
            allocation_method="direct",
            driver_quantity=amount,
            total_driver_quantity=amount,
            allocation_percentage=Decimal("100.0000"),
            allocated_amount=amount,
            generated_at=input_cost.created_at or timezone.now(),
            generated_by_id=input_cost.created_by_id,
            manual_reason="Migrated from historical poultry InputCosts record.",
        )
        InputCost.objects.filter(pk=input_cost.pk).update(expenditure_id=expenditure.pk)
        Reconciliation.objects.create(
            input_cost_id=input_cost.pk,
            expenditure_id=expenditure.pk,
            status="migrated",
            match_basis="No candidate expenditure found; authoritative expenditure created.",
        )


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0013_expenditure_idempotency_key_expenditure_origin_and_more"),
        ("poultry", "0029_inputcosts_expenditure"),
    ]

    operations = [
        migrations.RunPython(reconcile_input_costs, migrations.RunPython.noop),
    ]
