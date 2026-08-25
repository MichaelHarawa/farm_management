from django.core.management.base import BaseCommand
from django.db.models import Sum

from apps.poultry.models import PaymentStatus, Sales

from apps.finance.models import Expenditure, ExpenditureStatus, FundingSource, FundingSourceType, SalePayment, SalePaymentStatus
from apps.finance.services.profitability import ensure_batch_funding_source


class Command(BaseCommand):
    help = "Report historical sales or posted expenditures that are incomplete in the finance ledgers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-batch-sources",
            action="store_true",
            help="Create the derived batch collection source identities when payments exist.",
        )

    def handle(self, *args, **options):
        problems = 0
        sales = Sales.objects.exclude(payment_status=PaymentStatus.CANCELLED)
        for sale in sales.iterator():
            ledger_total = sale.payments.filter(status=SalePaymentStatus.POSTED).aggregate(
                total=Sum("amount")
            )["total"] or 0
            if ledger_total != sale.amount_paid:
                problems += 1
                self.stdout.write(
                    f"SALE {sale.sale_id}: summary={sale.amount_paid} ledger={ledger_total}"
                )

        for expenditure in Expenditure.objects.filter(status=ExpenditureStatus.POSTED).iterator():
            funded = expenditure.funding_allocations.aggregate(total=Sum("amount"))["total"] or 0
            if funded != expenditure.amount:
                problems += 1
                self.stdout.write(
                    f"EXPENDITURE {expenditure.expenditure_reference or expenditure.pk}: "
                    f"amount={expenditure.amount} funded={funded} [UNFUNDED]"
                )

        payment_batch_ids = SalePayment.objects.filter(
            status=SalePaymentStatus.POSTED
        ).values_list("sale__batch_id", flat=True).distinct()
        for batch_id in payment_batch_ids:
            if not FundingSource.objects.filter(
                source_type=FundingSourceType.BATCH_COLLECTION,
                batch_id=batch_id,
            ).exists():
                problems += 1
                self.stdout.write(f"BATCH {batch_id}: collection source missing")
                if options["create_batch_sources"]:
                    sale = Sales.objects.filter(batch_id=batch_id).select_related("batch").first()
                    if sale:
                        ensure_batch_funding_source(sale.batch)
                        self.stdout.write(self.style.SUCCESS("  source created"))

        if problems:
            self.stdout.write(self.style.WARNING(f"Found {problems} reconciliation issue(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("Finance ledgers reconcile."))
