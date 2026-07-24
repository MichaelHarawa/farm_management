from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.poultry.models import Batch

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    Asset,
    AssetDepreciationEntry,
    AssetMaintenanceRecord,
    AssetReplacementPlan,
    AssetUsageRecord,
    AssetCategory,
    AssetStatus,
    BirdDaySnapshot,
    ConsumableUsage,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    ExpenseRecognitionSchedule,
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
)
from .services.allocations import regenerate_allocations_for_period
from .services.assets import dispose_asset, impair_asset, link_capital_expense_to_asset
from .services.consumables import record_consumable_usage
from .services.depreciation import (
    asset_recovery_summary,
    generate_depreciation_for_period,
)
from .services.payroll import generate_payroll_for_period
from .services.profitability import batch_profitability
from .services.reporting import (
    dashboard_indicators,
    monthly_profitability_report,
    receivables_report,
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
    def close(self, request, pk=None):
        period = self.get_object()
        if period.status == PeriodStatus.CLOSED:
            return Response(self.get_serializer(period).data)

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
        return Response(self.get_serializer(period).data)

    @action(detail=True, methods=["post"], url_path="reopen")
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


class DashboardView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        return Response(json_safe(dashboard_indicators()))


class ReceivablesView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        return Response(json_safe(receivables_report()))


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
