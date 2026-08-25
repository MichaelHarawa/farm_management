from django.db import migrations


def backfill_sale_payments(apps, schema_editor):
    Sales = apps.get_model("poultry", "Sales")
    FundingSource = apps.get_model("finance", "FundingSource")
    SalePayment = apps.get_model("finance", "SalePayment")

    sales = Sales.objects.exclude(payment_status="cancelled").filter(amount_paid__gt=0)
    for sale in sales.iterator():
        FundingSource.objects.get_or_create(
            source_type="batch_collection",
            batch_id=sale.batch_id,
            defaults={"description": f"Batch sales collections ({sale.batch_id})"},
        )
        SalePayment.objects.get_or_create(
            idempotency_key=f"legacy-sale:{sale.sale_id}",
            defaults={
                "sale_id": sale.pk,
                "payment_reference": f"PAY-LEGACY-{sale.pk:010d}",
                "amount": sale.amount_paid,
                "payment_date": sale.sale_date,
                "payment_method": sale.payment_method,
                "received_by_name": sale.sold_by_name,
                "notes": "Backfilled from the historical sale amount paid.",
                "status": "posted",
                "created_by_id": sale.created_by_id,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0009_expenditure_cost_allocation_plan_fundingreceipt_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_sale_payments, migrations.RunPython.noop),
    ]
