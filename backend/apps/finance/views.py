from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.poultry.models import Batch

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    BirdDaySnapshot,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    PayrollEntry,
    PeriodStatus,
    SharedExpense,
)
from .permissions import FinancePermission
from .serializers import (
    AccountingPeriodSerializer,
    AdHocLabourPaymentSerializer,
    BirdDaySnapshotSerializer,
    CostAllocationSerializer,
    EmployeeBatchWorkLogSerializer,
    EmployeeProfileSerializer,
    PayrollEntrySerializer,
    SharedExpenseSerializer,
)
from .services.allocations import regenerate_allocations_for_period
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
        return Response(self.get_serializer(period).data)


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
