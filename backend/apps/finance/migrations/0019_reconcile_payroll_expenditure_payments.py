from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def reconcile_payroll_payment_status(apps, schema_editor):
    PayrollEntry = apps.get_model("finance", "PayrollEntry")
    FundingAllocation = apps.get_model("finance", "FundingAllocation")
    PayrollPayment = apps.get_model("finance", "PayrollPayment")

    for entry in PayrollEntry.objects.exclude(expenditure_id__isnull=True):
        expenditure_paid = FundingAllocation.objects.filter(
            expenditure_id=entry.expenditure_id
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        payroll_paid = PayrollPayment.objects.filter(
            payroll_entry_id=entry.pk,
            status="posted",
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        paid = expenditure_paid if expenditure_paid > 0 else payroll_paid
        payable = max(entry.gross_salary - entry.deductions, Decimal("0.00"))

        if paid >= payable and payable > 0:
            status = "paid"
        elif paid > 0:
            status = "partial"
        else:
            status = "unpaid"

        expenditure_date = FundingAllocation.objects.filter(
            expenditure_id=entry.expenditure_id
        ).order_by("-allocation_date", "-pk").values_list(
            "allocation_date", flat=True
        ).first()
        payroll_date = PayrollPayment.objects.filter(
            payroll_entry_id=entry.pk,
            status="posted",
        ).order_by("-payment_date", "-pk").values_list(
            "payment_date", flat=True
        ).first()
        dates = [value for value in [expenditure_date, payroll_date] if value]
        entry.payment_status = status
        entry.payment_date = max(dates) if dates else None
        entry.save(update_fields=["payment_status", "payment_date", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0018_batchprofitabilitysnapshot_management_costs"),
    ]

    operations = [
        migrations.RunPython(
            reconcile_payroll_payment_status,
            migrations.RunPython.noop,
        ),
    ]
