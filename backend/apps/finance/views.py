from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.poultry.models import Batch, BatchStatus

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationSourceType,
    Asset,
    AssetDepreciationEntry,
    AssetMaintenanceRecord,
    AssetReplacementPlan,
    AssetUsageRecord,
    AssetCategory,
    AssetStatus,
    BatchProfitabilitySnapshot,
    BirdDaySnapshot,
    ConsumableUsage,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    ExpenseRecognitionSchedule,
    Expenditure,
    ExpenditureCategory,
    ExpenditureStatus,
    FundingSource,
    FundingAllocation,
    FundingReceipt,
    FundingReceiptStatus,
    FundingSourceType,
    SalePayment,
    PayrollEntry,
    PeriodStatus,
    ReplacementReserveTransaction,
    SharedExpense,
    SharedConsumableLot,
)
from .permissions import FinancePermission
from .serializers import (
    AccountingPeriodSerializer,
    AdHocLabourPaymentSerializer,
    AssetCapitalizedCostSerializer,
    AssetCategorySerializer,
    AssetDepreciationEntrySerializer,
    AssetMaintenanceRecordSerializer,
    AssetReplacementPlanSerializer,
    AssetSerializer,
    AssetUsageRecordSerializer,
    BirdDaySnapshotSerializer,
    ConsumableUsageSerializer,
    CostAllocationSerializer,
    EmployeeBatchWorkLogSerializer,
    EmployeeProfileSerializer,
    ExpenseRecognitionScheduleSerializer,
    PayrollEntrySerializer,
    ReplacementReserveTransactionSerializer,
    SharedExpenseSerializer,
    SharedConsumableLotSerializer,
    FundingReceiptSerializer,
    RecordSalePaymentSerializer,
    SalePaymentSerializer,
)
from .services.allocations import regenerate_allocations_for_period
from .services.assets import dispose_asset, impair_asset, link_capital_expense_to_asset
from .services.consumables import record_consumable_usage
from .services.depreciation import (
    asset_recovery_summary,
    generate_depreciation_for_period,
)
from .services.payroll import generate_payroll_for_period
from .services.profitability import (
    batch_portfolio_report,
    batch_profitability,
    create_final_snapshot,
)
from .services.reporting import (
    dashboard_indicators,
    monthly_profitability_report,
    receivables_report,
)
from .services.collections import record_sale_payment, reverse_sale_payment
from .services.expenditures import (
    post_expenditure,
    record_expenditure_payment,
    reconciliation_summary,
    reverse_expenditure,
)


def json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


class EmployeeProfileViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EmployeeProfileSerializer
    permission_classes = (FinancePermission,)
    queryset = EmployeeProfile.objects.select_related("user", "created_by").prefetch_related(
        "user__roles"
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = True
        employee.user.is_active = True
        employee.user.save(update_fields=["is_active", "updated_at"])
        employee.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(employee).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = False
        employee.user.is_active = False
        employee.user.save(update_fields=["is_active", "updated_at"])
        employee.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(employee).data)


class AccountingPeriodViewSet(viewsets.ModelViewSet):
    serializer_class = AccountingPeriodSerializer
    permission_classes = (FinancePermission,)
    queryset = AccountingPeriod.objects.select_related("closed_by")

    @action(detail=True, methods=["post"], url_path="generate-payroll")
    def generate_payroll(self, request, pk=None):
        period = self.get_object()
        try:
            entries = generate_payroll_for_period(
                period,
                created_by=request.user,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PayrollEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="recalculate")
    def recalculate(self, request, pk=None):
        period = self.get_object()
        try:
            allocations = regenerate_allocations_for_period(
                period,
                generated_by=request.user,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "period": period.pk,
                "allocations_created": len(allocations),
                "bird_day_snapshots": BirdDaySnapshot.objects.filter(
                    accounting_period=period
                ).count(),
            }
        )

    @action(detail=True, methods=["post"], url_path="close")
    @transaction.atomic
    def close(self, request, pk=None):
        period = self.get_object()
        if period.status == PeriodStatus.CLOSED:
            return Response(self.get_serializer(period).data)

        try:
            regenerate_allocations_for_period(
                period,
                generated_by=request.user,
            )
        except ValueError as error:
            return Response(
                {"detail": str(error)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        period.status = PeriodStatus.CLOSED
        period.closed_at = timezone.now()
        period.closed_by = request.user
        period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
        CostAllocation.objects.filter(accounting_period=period).update(locked=True)
        ConsumableUsage.objects.filter(accounting_period=period).update(locked=True)
        ExpenseRecognitionSchedule.objects.filter(accounting_period=period).update(
            locked=True
        )
        AssetUsageRecord.objects.filter(accounting_period=period).update(locked=True)
        AssetDepreciationEntry.objects.filter(accounting_period=period).update(
            locked=True
        )
        batches_to_finalize = list(
            Batch.objects.filter(
                status=BatchStatus.CLOSED,
                closed_at__date__gte=period.period_start,
                closed_at__date__lte=period.period_end,
            )
        )
        finalizing_batch_ids = [batch.pk for batch in batches_to_finalize]
        retired_legacy_snapshots = BatchProfitabilitySnapshot.objects.filter(
            batch_id__in=finalizing_batch_ids,
            final=True,
        ).exclude(accounting_period=period)
        retired_batch_ids = list(
            retired_legacy_snapshots.values_list("batch_id", flat=True)
        )
        retired_legacy_snapshots.update(final=False)
        Batch.objects.filter(pk__in=retired_batch_ids).update(
            profitability_finalized_at=None
        )
        for batch in batches_to_finalize:
            if batch.pk in retired_batch_ids:
                batch.profitability_finalized_at = None
            create_final_snapshot(
                batch,
                accounting_period=period,
                generated_by=request.user,
            )
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"], url_path="reopen")
    @transaction.atomic
    def reopen(self, request, pk=None):
        period = self.get_object()
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            return Response(
                {"detail": "A reopening reason is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        period.status = PeriodStatus.OPEN
        period.reopened_at = timezone.now()
        period.reopened_by = request.user
        period.reopening_reason = reason
        period.recalculation_version += 1
        period.save(
            update_fields=[
                "status",
                "reopened_at",
                "reopened_by",
                "reopening_reason",
                "recalculation_version",
                "updated_at",
            ]
        )
        CostAllocation.objects.filter(accounting_period=period).update(locked=False)
        ConsumableUsage.objects.filter(accounting_period=period).update(locked=False)
        ExpenseRecognitionSchedule.objects.filter(accounting_period=period).update(
            locked=False
        )
        AssetUsageRecord.objects.filter(accounting_period=period).update(locked=False)
        AssetDepreciationEntry.objects.filter(accounting_period=period).update(
            locked=False
        )
        finalized_snapshots = BatchProfitabilitySnapshot.objects.filter(
            Q(accounting_period=period)
            | Q(
                accounting_period__isnull=True,
                batch__closed_at__date__gte=period.period_start,
                batch__closed_at__date__lte=period.period_end,
            ),
            final=True,
        )
        finalized_batch_ids = list(
            finalized_snapshots.values_list("batch_id", flat=True)
        )
        finalized_snapshots.update(final=False)
        Batch.objects.filter(pk__in=finalized_batch_ids).update(
            profitability_finalized_at=None
        )
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"], url_path="generate-depreciation")
    def generate_depreciation(self, request, pk=None):
        period = self.get_object()
        try:
            entries = generate_depreciation_for_period(
                period,
                generated_by=request.user,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(AssetDepreciationEntrySerializer(entries, many=True).data)

    @action(detail=True, methods=["post"], url_path="allocate-depreciation")
    def allocate_depreciation(self, request, pk=None):
        period = self.get_object()
        try:
            generate_depreciation_for_period(period, generated_by=request.user)
            allocations = regenerate_allocations_for_period(
                period,
                generated_by=request.user,
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "period": period.pk,
                "allocations_created": len(allocations),
            }
        )


class PayrollEntryViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollEntrySerializer
    permission_classes = (FinancePermission,)
    queryset = PayrollEntry.objects.select_related(
        "accounting_period",
        "employee",
        "employee__user",
        "created_by",
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AdHocLabourPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = AdHocLabourPaymentSerializer
    permission_classes = (FinancePermission,)
    queryset = AdHocLabourPayment.objects.select_related(
        "linked_employee",
        "batch",
        "accounting_period",
        "created_by",
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SharedExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = SharedExpenseSerializer
    permission_classes = (FinancePermission,)
    queryset = SharedExpense.objects.select_related(
        "accounting_period",
        "directly_assigned_batch",
        "created_by",
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SharedConsumableLotViewSet(viewsets.ModelViewSet):
    serializer_class = SharedConsumableLotSerializer
    permission_classes = (FinancePermission,)
    queryset = SharedConsumableLot.objects.select_related(
        "linked_expense",
        "created_by",
    )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ConsumableUsageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ConsumableUsageSerializer
    permission_classes = (FinancePermission,)
    queryset = ConsumableUsage.objects.select_related(
        "consumable_lot",
        "accounting_period",
        "batch",
        "recorded_by",
        "approved_by",
    )

    def perform_create(self, serializer):
        try:
            usage = record_consumable_usage(
                recorded_by=self.request.user,
                **serializer.validated_data,
            )
        except ValueError as error:
            raise ValidationError({"detail": str(error)}) from error
        serializer.instance = usage


class ExpenseRecognitionScheduleViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseRecognitionScheduleSerializer
    permission_classes = (FinancePermission,)
    queryset = ExpenseRecognitionSchedule.objects.select_related(
        "source_expense",
        "accounting_period",
        "generated_by",
    )

    def perform_create(self, serializer):
        serializer.save(generated_by=self.request.user)


class AssetCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = AssetCategorySerializer
    permission_classes = (FinancePermission,)
    queryset = AssetCategory.objects.all()


class AssetViewSet(viewsets.ModelViewSet):
    serializer_class = AssetSerializer
    permission_classes = (FinancePermission,)
    queryset = Asset.objects.select_related("asset_category", "created_by")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="from-expense")
    def from_expense(self, request):
        expense = get_object_or_404(SharedExpense, pk=request.data.get("expense"))
        asset_payload = request.data.copy()
        asset_payload.pop("expense", None)
        serializer = self.get_serializer(data=asset_payload)
        serializer.is_valid(raise_exception=True)
        asset = serializer.save(created_by=request.user)
        link = link_capital_expense_to_asset(
            asset=asset,
            expense=expense,
            amount=expense.amount,
            created_by=request.user,
            notes="Created from capital expenditure.",
        )
        return Response(
            {
                "asset": self.get_serializer(asset).data,
                "capitalized_cost": AssetCapitalizedCostSerializer(link).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get", "post"], url_path="usage")
    def usage(self, request, pk=None):
        asset = self.get_object()
        if request.method == "GET":
            records = asset.usage_records.select_related(
                "accounting_period",
                "batch",
                "recorded_by",
                "approved_by",
            )
            return Response(AssetUsageRecordSerializer(records, many=True).data)

        serializer = AssetUsageRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(asset=asset, recorded_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="maintenance")
    def maintenance(self, request, pk=None):
        asset = self.get_object()
        if request.method == "GET":
            records = asset.maintenance_records.select_related(
                "accounting_period",
                "linked_expense",
                "recorded_by",
            )
            return Response(AssetMaintenanceRecordSerializer(records, many=True).data)

        serializer = AssetMaintenanceRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(asset=asset, recorded_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="replacement-plan")
    def replacement_plan(self, request, pk=None):
        asset = self.get_object()
        if request.method == "GET":
            plan = getattr(asset, "replacement_plan", None)
            if not plan:
                return Response(
                    {"detail": "No replacement plan exists."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(AssetReplacementPlanSerializer(plan).data)

        serializer = AssetReplacementPlanSerializer(
            getattr(asset, "replacement_plan", None),
            data={**request.data, "asset": asset.pk},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(asset=asset, updated_by=request.user)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="reserve-transactions")
    def reserve_transactions(self, request, pk=None):
        asset = self.get_object()
        if request.method == "GET":
            rows = asset.reserve_transactions.select_related(
                "accounting_period",
                "authorized_by",
            )
            return Response(ReplacementReserveTransactionSerializer(rows, many=True).data)

        serializer = ReplacementReserveTransactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(asset=asset, authorized_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="impair")
    def impair(self, request, pk=None):
        asset = self.get_object()
        try:
            updated = impair_asset(
                asset=asset,
                amount=Decimal(str(request.data.get("amount", "0.00"))),
            )
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["post"], url_path="dispose")
    def dispose(self, request, pk=None):
        asset = self.get_object()
        disposal_date = request.data.get("disposal_date")
        if not disposal_date:
            return Response(
                {"detail": "disposal_date is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parsed_date = datetime.strptime(disposal_date, "%Y-%m-%d").date()
            updated = dispose_asset(
                asset=asset,
                disposal_date=parsed_date,
                proceeds=Decimal(str(request.data.get("proceeds", "0.00"))),
            )
        except (ValueError, TypeError) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["get"], url_path="depreciation-schedule")
    def depreciation_schedule(self, request, pk=None):
        asset = self.get_object()
        rows = asset.depreciation_entries.select_related(
            "accounting_period",
            "generated_by",
        )
        return Response(AssetDepreciationEntrySerializer(rows, many=True).data)

    @action(detail=True, methods=["get"], url_path="recovery")
    def recovery(self, request, pk=None):
        return Response(json_safe(asset_recovery_summary(self.get_object())))


class AssetUsageRecordViewSet(viewsets.ModelViewSet):
    serializer_class = AssetUsageRecordSerializer
    permission_classes = (FinancePermission,)
    queryset = AssetUsageRecord.objects.select_related(
        "asset",
        "accounting_period",
        "batch",
        "recorded_by",
        "approved_by",
    )

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class AssetDepreciationEntryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AssetDepreciationEntrySerializer
    permission_classes = (FinancePermission,)
    queryset = AssetDepreciationEntry.objects.select_related(
        "asset",
        "accounting_period",
        "generated_by",
    )


class ReplacementReserveTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = ReplacementReserveTransactionSerializer
    permission_classes = (FinancePermission,)
    queryset = ReplacementReserveTransaction.objects.select_related(
        "asset",
        "accounting_period",
        "authorized_by",
    )

    def perform_create(self, serializer):
        serializer.save(authorized_by=self.request.user)


class EmployeeBatchWorkLogViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeBatchWorkLogSerializer
    permission_classes = (FinancePermission,)
    queryset = EmployeeBatchWorkLog.objects.select_related(
        "employee",
        "employee__user",
        "batch",
        "approved_by",
    )


class BirdDaySnapshotViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BirdDaySnapshotSerializer
    permission_classes = (FinancePermission,)
    queryset = BirdDaySnapshot.objects.select_related("accounting_period", "batch")


class CostAllocationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CostAllocationSerializer
    permission_classes = (FinancePermission,)
    queryset = CostAllocation.objects.select_related(
        "accounting_period",
        "batch",
        "payroll_entry",
        "ad_hoc_labour_payment",
        "shared_expense",
        "generated_by",
    )


class MonthlyReportView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        period = resolve_period(request)
        if period is None:
            return Response(
                {"detail": "No accounting period exists."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(json_safe(monthly_profitability_report(period)))


class BatchProfitabilityView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request, batch_id: int):
        batch = get_object_or_404(Batch, pk=batch_id)
        return Response(json_safe(batch_profitability(batch)))


class BatchPortfolioView(APIView):
    permission_classes = (FinancePermission,)
    max_batch_selection = 50

    def get(self, request):
        raw_values = [
            *request.query_params.getlist("batch"),
            *request.query_params.getlist("batch_ids"),
        ]
        raw_ids = [
            token.strip()
            for raw_value in raw_values
            for token in raw_value.split(",")
            if token.strip()
        ]

        if not raw_ids:
            raise ValidationError(
                {"batch": "Select at least one poultry batch to analyse."}
            )

        try:
            parsed_ids = [int(raw_id) for raw_id in raw_ids]
        except ValueError as error:
            raise ValidationError(
                {"batch": "Batch selections must be positive whole numbers."}
            ) from error

        if any(batch_id <= 0 for batch_id in parsed_ids):
            raise ValidationError(
                {"batch": "Batch selections must be positive whole numbers."}
            )

        selected_ids = list(dict.fromkeys(parsed_ids))
        if len(selected_ids) > self.max_batch_selection:
            raise ValidationError(
                {
                    "batch": (
                        f"Select no more than {self.max_batch_selection} batches "
                        "at one time."
                    )
                }
            )

        batches_by_id = Batch.objects.in_bulk(selected_ids)
        missing_ids = [
            batch_id for batch_id in selected_ids if batch_id not in batches_by_id
        ]
        if missing_ids:
            raise ValidationError(
                {
                    "batch": (
                        "Unknown poultry batch selection(s): "
                        + ", ".join(str(batch_id) for batch_id in missing_ids)
                        + "."
                    )
                }
            )

        batches = [batches_by_id[batch_id] for batch_id in selected_ids]
        return Response(json_safe(batch_portfolio_report(batches)))


class DashboardView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        return Response(json_safe(dashboard_indicators()))


class ReceivablesView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        return Response(json_safe(receivables_report(request.query_params)))


class SalePaymentsView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request, sale_id: int):
        payments = SalePayment.objects.filter(sale_id=sale_id).select_related(
            "sale__batch"
        )
        return Response(SalePaymentSerializer(payments, many=True).data)

    def post(self, request, sale_id: int):
        serializer = RecordSalePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment, created = record_sale_payment(
            sale_id=sale_id,
            created_by=request.user,
            **serializer.validated_data,
        )
        payment = SalePayment.objects.select_related("sale__batch").get(pk=payment.pk)
        return Response(
            SalePaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SalePaymentReverseView(APIView):
    permission_classes = (FinancePermission,)

    def post(self, request, payment_id: int):
        payment = reverse_sale_payment(
            payment_id=payment_id,
            reason=request.data.get("reason", ""),
            reversed_by=request.user,
        )
        payment = SalePayment.objects.select_related("sale__batch").get(pk=payment.pk)
        return Response(SalePaymentSerializer(payment).data)


def resolve_period(request) -> AccountingPeriod | None:
    period_id = request.query_params.get("period_id")
    if period_id:
        return get_object_or_404(AccountingPeriod, pk=period_id)

    period = request.query_params.get("period")
    if period:
        try:
            parsed = datetime.strptime(period, "%Y-%m")
        except ValueError:
            return None
        return AccountingPeriod.objects.filter(
            period_start__year=parsed.year,
            period_start__month=parsed.month,
        ).first()

    return AccountingPeriod.objects.order_by("-period_start").first()


# =============================================================================
# New API: Expenditures + Funding Allocations (batch cash tracking)
# =============================================================================

from .serializers import (
    ExpenditureSerializer,
    FundingSourceSerializer,
    FundingAllocationSerializer,
    BatchRevenueUtilizationSerializer,
)
from .services.profitability import (
    batch_revenue_utilization,
    validate_funding_allocations,
    available_batch_cash,
)


class ExpenditureViewSet(viewsets.ModelViewSet):
    """
    CRUD + Post action for expenditures.
    Supports the full funding + cost allocation workflow.
    """
    queryset = Expenditure.objects.all().select_related("category").prefetch_related(
        "funding_allocations__funding_source",
        "cost_allocations__batch",
    )
    serializer_class = ExpenditureSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = [
        "status", "payment_status", "origin", "accounting_nature", "category",
        "expenditure_date",
    ]
    search_fields = ["description", "payee", "expenditure_reference", "external_reference"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if serializer.instance.status != ExpenditureStatus.DRAFT:
            raise ValidationError(
                {"detail": "Posted expenditures are immutable; reverse and replace the transaction."}
            )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        if self.get_object().status != ExpenditureStatus.DRAFT:
            raise ValidationError(
                {"detail": "Posted expenditures cannot be deleted; use reversal."}
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        """
        Post a draft expenditure. This makes funding allocations count against
        batch available cash. Supports passing funding_allocations in the body.
        """
        funding_data = request.data.get("funding_allocations") if "funding_allocations" in request.data else None
        cost_data = request.data.get("cost_allocations")
        allow_unpaid = request.data.get("payment_status") in {"credit", "unpaid", "partial"}
        expenditure = post_expenditure(
            expenditure_id=pk,
            user=request.user,
            funding_rows=funding_data,
            cost_rows=cost_data,
            allow_unpaid=allow_unpaid,
        )
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        expenditure = reverse_expenditure(
            expenditure_id=pk,
            reason=request.data.get("reason"),
            user=request.user,
        )
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"], url_path="assign-funding")
    def assign_funding(self, request, pk=None):
        """Controlled reconciliation for historical posted, wholly unfunded rows."""
        expenditure = record_expenditure_payment(
            expenditure_id=pk,
            funding_rows=request.data.get("funding_allocations", []) or [],
            payment_group_key=request.data.get("idempotency_key") or f"historical-{pk}",
            payment_date=request.data.get("payment_date"),
            user=request.user,
        )
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        expenditure = record_expenditure_payment(
            expenditure_id=pk,
            funding_rows=request.data.get("funding_allocations", []) or [],
            payment_group_key=request.data.get("idempotency_key"),
            payment_date=request.data.get("payment_date"),
            user=request.user,
        )
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=False, methods=["get"], url_path="reconciliation-report")
    def reconciliation_report(self, request):
        return Response(reconciliation_summary())

    @action(detail=False, methods=["get"])
    def payables(self, request):
        queryset = self.get_queryset().filter(
            status=ExpenditureStatus.POSTED,
            payment_status__in=["unpaid", "partial", "historical_unassigned"],
        )
        return Response(self.get_serializer(queryset, many=True).data)


class FundingSourceViewSet(viewsets.ModelViewSet):
    queryset = FundingSource.objects.all()
    serializer_class = FundingSourceSerializer
    permission_classes = (FinancePermission,)

    def list(self, request, *args, **kwargs):
        sources = list(self.get_queryset().filter(is_active=True).select_related("batch"))
        if request.query_params.get("include_empty") != "1":
            from .services.profitability import available_funding_source_cash

            sources = [source for source in sources if available_funding_source_cash(source) > 0]
        return Response(self.get_serializer(sources, many=True).data)


class FundingReceiptViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = FundingReceipt.objects.all().select_related("funding_source")
    serializer_class = FundingReceiptSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ["funding_source", "status"]

    def perform_create(self, serializer):
        source = serializer.validated_data["funding_source"]
        if source.source_type == FundingSourceType.BATCH_COLLECTION:
            raise ValidationError(
                {"funding_source": "Batch collection balances come from sale payments."}
            )
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError({"reason": "A reversal reason is required."})
        with transaction.atomic():
            receipt = FundingReceipt.objects.select_for_update().select_related(
                "funding_source"
            ).get(pk=pk)
            if receipt.status != FundingReceiptStatus.POSTED:
                raise ValidationError({"detail": "Only posted receipts can be reversed."})
            source = FundingSource.objects.select_for_update().get(
                pk=receipt.funding_source_id
            )
            from .services.profitability import available_funding_source_cash

            if available_funding_source_cash(source) < receipt.amount:
                raise ValidationError(
                    {"detail": "This receipt funds posted expenditures and cannot be reversed."}
                )
            receipt.status = FundingReceiptStatus.REVERSED
            receipt.reversed_at = timezone.now()
            receipt.reversed_by = request.user
            receipt.reversal_reason = reason
            receipt.save(
                update_fields=[
                    "status", "reversed_at", "reversed_by", "reversal_reason", "updated_at"
                ]
            )
        return Response(self.get_serializer(receipt).data)


class ExpenditureCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only for frontend selectors."""
    queryset = ExpenditureCategory.objects.filter(is_active=True).order_by("display_order", "name")
    serializer_class = None  # use simple or add later
    permission_classes = (FinancePermission,)

    def get_serializer_class(self):
        from .serializers import ExpenditureCategorySerializer
        return ExpenditureCategorySerializer


class BatchRevenueUtilizationView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request, batch_id: int):
        batch = get_object_or_404(Batch, pk=batch_id)
        data = batch_revenue_utilization(batch)
        return Response(json_safe(data))


class CrossBatchFinancingReportView(APIView):
    """Simple cross-batch financing flows: which batch collections funded expenditures allocated to other batches."""
    permission_classes = (FinancePermission,)

    def get(self, request):
        posted_fundings = FundingAllocation.objects.filter(
            expenditure__status=ExpenditureStatus.POSTED,
            funding_source__source_type=FundingSourceType.BATCH_COLLECTION,
        ).select_related("funding_source__batch", "expenditure")

        flows = []
        for fa in posted_fundings:
            src_batch = fa.funding_source.batch
            if not src_batch:
                continue
            # find cost allocations linked to the expenditure
            cas = CostAllocation.objects.filter(expenditure=fa.expenditure).select_related("batch")
            for ca in cas:
                if ca.batch_id and ca.batch_id != src_batch.pk:
                    flows.append({
                        "funding_batch_id": src_batch.pk,
                        "funding_batch_code": src_batch.batch_id,
                        "expenditure_id": fa.expenditure_id,
                        "expenditure_desc": fa.expenditure.description,
                        "amount_funded": str(fa.amount),
                        "allocated_to_batch_id": ca.batch_id,
                        "allocated_amount": str(ca.allocated_amount),
                        "date": str(fa.allocation_date),
                    })

        return Response({"flows": flows[:100]})
