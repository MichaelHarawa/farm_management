from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.poultry.models import Batch, BatchStatus, ProductType, Sales

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
    ConsumableItem,
    CostAllocation,
    Customer,
    CustomerCostAttribution,
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
    FundingClassification,
    FundingSourceType,
    FinanceActionEvent,
    OwnerContributor,
    OwnerReceiptDesignation,
    SalePayment,
    PayrollEntry,
    PayrollPayment,
    PeriodStatus,
    ReplacementReserveTransaction,
    SharedExpense,
    SharedConsumableLot,
    StockMovement,
    InventoryLocation,
    AssetLifecycleEvent,
)
from .permissions import (
    FinancePermission,
    OwnerCapitalPermission,
    has_owner_capital_access,
)
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
    ConsumableItemSerializer,
    CostAllocationSerializer,
    CustomerCostAttributionCommandSerializer,
    CustomerCostAttributionReverseSerializer,
    CustomerCostAttributionSerializer,
    CustomerReviewSerializer,
    CustomerSaleLinkSerializer,
    CustomerSerializer,
    EmployeeBatchWorkLogSerializer,
    EmployeeProfileSerializer,
    ExpenseRecognitionScheduleSerializer,
    PayrollEntrySerializer,
    PayrollPaymentSerializer,
    ReplacementReserveTransactionSerializer,
    SharedExpenseSerializer,
    SharedConsumableLotSerializer,
    FundingReceiptSerializer,
    FinanceActionEventSerializer,
    OwnerContributionCommandSerializer,
    OwnerContributorSerializer,
    OwnerDesignationCommandSerializer,
    OwnerReceiptDesignationSerializer,
    RecordSalePaymentSerializer,
    SalePaymentSerializer,
    StockMovementSerializer,
    InventoryLocationSerializer,
    AssetLifecycleEventSerializer,
)
from .services.allocations import regenerate_allocations_for_period
from .services.assets import dispose_asset, impair_asset, link_capital_expense_to_asset, transfer_asset
from .services.consumables import record_consumable_receipt, record_consumable_usage
from .services.labour import approve_labour, pay_labour, post_labour, reverse_labour
from .services.depreciation import (
    asset_recovery_summary,
    generate_depreciation_for_period,
)
from .services.payroll import generate_payroll_for_period
from .services.salary_payments import (
    create_deduction_liability,
    ensure_salary_expense,
    record_salary_payment,
    reverse_salary_payment,
    set_salary_cost_allocations,
)
from .services.profitability import (
    batch_portfolio_report,
    batch_profitability,
    create_final_snapshot,
)
from .services.reporting import (
    create_period_report_snapshot,
    dashboard_indicators,
    monthly_profitability_report,
    receivables_report,
)
from .services.collections import record_sale_payment, reverse_sale_payment
from .services.expenditures import (
    post_expenditure,
    record_expenditure_payment,
    reconciliation_summary,
    project_shared_expense,
    reverse_expenditure,
)
from .services.action_audit import record_finance_action
from .services.funding_attribution import expenditure_payment_beneficiary_shares
from .services.owner_capital import (
    add_owner_designations,
    owner_contribution_report,
    record_owner_contribution,
    reverse_funding_receipt,
    reverse_owner_designation,
)
from .services.customer_contribution import (
    customer_contribution_report,
    customer_cost_source_candidates,
    link_sale_customer,
    record_customer_cost_attribution,
    reverse_customer_cost_attribution,
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

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = True
        if employee.user_id:
            employee.user.is_active = True
            employee.user.save(update_fields=["is_active", "updated_at"])
        employee.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(employee).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request, pk=None):
        employee = self.get_object()
        employee.is_active = False
        if employee.user_id:
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
        create_period_report_snapshot(period, generated_by=request.user)
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
    ).prefetch_related(
        "payments__funding_allocations__funding_source",
        "payments__posted_by",
        "payments__reversed_by",
    )

    def perform_create(self, serializer):
        entry = serializer.save(created_by=self.request.user)
        create_deduction_liability(entry)
        ensure_salary_expense(entry, user=self.request.user)

    def perform_update(self, serializer):
        entry = serializer.save()
        create_deduction_liability(entry)
        ensure_salary_expense(entry, user=self.request.user)

    @action(detail=True, methods=["post"], url_path="allocate-costs")
    def allocate_costs(self, request, pk=None):
        entry = set_salary_cost_allocations(
            payroll_entry_id=self.get_object().pk,
            rows=request.data.get("cost_allocations"),
            user=request.user,
        )
        return Response(self.get_serializer(entry).data)

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        payment = record_salary_payment(
            payroll_entry_id=self.get_object().pk,
            amount=request.data.get("amount"),
            payment_date=request.data.get("payment_date"),
            payment_method=str(request.data.get("payment_method", "")),
            funding_rows=request.data.get("funding_allocations"),
            idempotency_key=str(request.data.get("idempotency_key", "")),
            external_reference=str(request.data.get("external_reference", "")),
            user=request.user,
        )
        return Response(PayrollPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="reverse-payment")
    def reverse_payment(self, request, pk=None):
        payment = get_object_or_404(
            PayrollPayment,
            pk=request.data.get("payment_id"),
            payroll_entry=self.get_object(),
        )
        payment = reverse_salary_payment(
            payment_id=payment.pk,
            reason=str(request.data.get("reason", "")),
            user=request.user,
        )
        return Response(PayrollPaymentSerializer(payment).data)


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

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(self.get_serializer(approve_labour(labour_id=self.get_object().pk, user=request.user)).data)

    @action(detail=True, methods=["post"])
    def post(self, request, pk=None):
        return Response(self.get_serializer(post_labour(labour_id=self.get_object().pk, user=request.user)).data)

    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        labour = pay_labour(
            labour_id=self.get_object().pk,
            funding_rows=request.data.get("funding_allocations", []),
            payment_group_key=str(request.data.get("idempotency_key", "")),
            payment_date=request.data.get("payment_date"),
            user=request.user,
        )
        return Response(self.get_serializer(labour).data)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        labour = reverse_labour(
            labour_id=self.get_object().pk,
            reason=str(request.data.get("reason", "")),
            user=request.user,
        )
        return Response(self.get_serializer(labour).data)


class SharedExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = SharedExpenseSerializer
    permission_classes = (FinancePermission,)
    queryset = SharedExpense.objects.select_related(
        "accounting_period",
        "directly_assigned_batch",
        "created_by",
    )

    def perform_create(self, serializer):
        expense = serializer.save(created_by=self.request.user)
        project_shared_expense(expense, user=self.request.user)

    def perform_update(self, serializer):
        expense = serializer.save()
        project_shared_expense(expense, user=self.request.user)


class SharedConsumableLotViewSet(viewsets.ModelViewSet):
    serializer_class = SharedConsumableLotSerializer
    permission_classes = (FinancePermission,)
    queryset = SharedConsumableLot.objects.select_related(
        "linked_expense",
        "created_by",
    )

    def perform_create(self, serializer):
        try:
            serializer.instance = record_consumable_receipt(
                created_by=self.request.user, **serializer.validated_data
            )
        except (ValueError, ValidationError) as error:
            raise ValidationError({"detail": str(error)}) from error


class ConsumableItemViewSet(viewsets.ModelViewSet):
    serializer_class = ConsumableItemSerializer
    permission_classes = (FinancePermission,)
    queryset = ConsumableItem.objects.all()


class InventoryLocationViewSet(viewsets.ModelViewSet):
    serializer_class = InventoryLocationSerializer
    permission_classes = (FinancePermission,)
    queryset = InventoryLocation.objects.all()


class StockMovementViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = StockMovementSerializer
    permission_classes = (FinancePermission,)
    queryset = StockMovement.objects.select_related("item", "lot", "usage", "batch", "from_location", "to_location")
    filterset_fields = ("movement_type", "item", "batch")


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
        asset = serializer.save(created_by=self.request.user)
        AssetLifecycleEvent.objects.create(
            asset=asset,
            event_type="acquisition",
            event_date=asset.purchase_date,
            details={"capitalized_cost": str(asset.total_capitalized_cost)},
            created_by=self.request.user,
        )

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
            event_date = request.data.get("event_date")
            parsed_event_date = (
                datetime.strptime(event_date, "%Y-%m-%d").date()
                if event_date else timezone.localdate()
            )
            updated = impair_asset(
                asset=asset,
                amount=Decimal(str(request.data.get("amount", "0.00"))),
                event_date=parsed_event_date,
                reason=str(request.data.get("reason", "")),
                user=request.user,
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
                reason=str(request.data.get("reason", "")),
                user=request.user,
            )
        except (ValueError, TypeError) as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        event_date = request.data.get("event_date")
        if not event_date or not request.data.get("reason"):
            raise ValidationError({"detail": "event_date and reason are required."})
        updated = transfer_asset(
            asset=self.get_object(),
            event_date=datetime.strptime(event_date, "%Y-%m-%d").date(),
            location=str(request.data.get("location", "")),
            custodian=str(request.data.get("custodian", "")),
            reason=str(request.data.get("reason")),
            user=request.user,
        )
        return Response(self.get_serializer(updated).data)

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        rows = self.get_object().lifecycle_events.select_related("created_by")
        return Response(AssetLifecycleEventSerializer(rows, many=True).data)

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
        return Response(json_safe(dashboard_indicators(request.query_params)))


class ReceivablesView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        return Response(json_safe(receivables_report(request.query_params)))


class SalePaymentsView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request, sale_id: int):
        payments = SalePayment.objects.filter(sale_id=sale_id).select_related(
            "sale__batch", "created_by", "reversed_by"
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
        payment = SalePayment.objects.select_related(
            "sale__batch", "created_by", "reversed_by"
        ).get(pk=payment.pk)
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
        payment = SalePayment.objects.select_related(
            "sale__batch", "created_by", "reversed_by"
        ).get(pk=payment.pk)
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
    batch_expenditure_funding_mix,
    batch_revenue_utilization,
    validate_funding_allocations,
    available_batch_cash,
)


class ExpenditurePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class FinanceRegisterPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CustomerViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CustomerSerializer
    permission_classes = (FinancePermission,)
    pagination_class = FinanceRegisterPagination

    def get_queryset(self):
        queryset = Customer.objects.select_related("created_by", "reviewed_by").all()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(display_name__icontains=search)
                | Q(contact_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
            )
        active = self.request.query_params.get("is_active")
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset

    def perform_create(self, serializer):
        customer = serializer.save(created_by=self.request.user)
        record_finance_action(
            actor=self.request.user,
            action="customer_created",
            entity_type="finance.Customer",
            entity_id=customer.pk,
            after_data={
                "public_id": customer.public_id,
                "display_name": customer.display_name,
                "customer_type": customer.customer_type,
                "is_active": customer.is_active,
            },
        )

    def perform_update(self, serializer):
        current = self.get_object()
        before = {
            "display_name": current.display_name,
            "customer_type": current.customer_type,
            "contact_name": current.contact_name,
            "phone": current.phone,
            "email": current.email,
            "notes": current.notes,
            "is_active": current.is_active,
        }
        customer = serializer.save()
        record_finance_action(
            actor=self.request.user,
            action="customer_updated",
            entity_type="finance.Customer",
            entity_id=customer.pk,
            before_data=before,
            after_data={key: getattr(customer, key) for key in before},
        )

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        customer = self.get_object()
        serializer = CustomerReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        before = {
            "contribution_label": customer.contribution_label,
            "review_notes": customer.review_notes,
        }
        customer.contribution_label = serializer.validated_data["contribution_label"]
        customer.review_notes = serializer.validated_data["review_notes"]
        customer.reviewed_at = timezone.now()
        customer.reviewed_by = request.user
        customer.full_clean()
        customer.save(
            update_fields=[
                "contribution_label", "review_notes", "reviewed_at",
                "reviewed_by", "updated_at",
            ]
        )
        record_finance_action(
            actor=request.user,
            action="customer_contribution_reviewed",
            entity_type="finance.Customer",
            entity_id=customer.pk,
            before_data=before,
            after_data={
                "contribution_label": customer.contribution_label,
                "review_notes": customer.review_notes,
            },
            reason=customer.review_notes,
        )
        return Response(self.get_serializer(customer).data)


class CustomerCostAttributionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (FinancePermission,)
    pagination_class = FinanceRegisterPagination
    queryset = CustomerCostAttribution.objects.select_related(
        "customer", "sale", "batch", "accounting_period", "created_by", "reversed_by"
    ).all()

    def get_serializer_class(self):
        return (
            CustomerCostAttributionCommandSerializer
            if self.action == "create"
            else CustomerCostAttributionSerializer
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        for key in ("customer", "sale", "batch", "category", "status", "evidence_status"):
            value = self.request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{key: value})
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        row, created = record_customer_cost_attribution(
            customer_id=data["customer"].pk,
            sale_id=data.get("sale_id"),
            batch_id=data.get("batch_id"),
            attribution_date=data["attribution_date"],
            category=data["category"],
            amount=data["amount"],
            source_type=data["source_type"],
            source_id=data.get("source_id"),
            evidence_status=data["evidence_status"],
            attribution_basis=data["attribution_basis"],
            reason=data["reason"],
            idempotency_key=data["idempotency_key"],
            user=request.user,
        )
        row = self.get_queryset().get(pk=row.pk)
        return Response(
            CustomerCostAttributionSerializer(row).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        serializer = CustomerCostAttributionReverseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            row = reverse_customer_cost_attribution(
                attribution_id=int(pk),
                reason=serializer.validated_data["reason"],
                user=request.user,
            )
        except CustomerCostAttribution.DoesNotExist:
            raise ValidationError({"id": "Customer cost attribution not found."})
        row = self.get_queryset().get(pk=row.pk)
        return Response(CustomerCostAttributionSerializer(row).data)


class CustomerSaleLinkView(APIView):
    permission_classes = (FinancePermission,)

    def post(self, request, sale_id: int):
        serializer = CustomerSaleLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            sale = link_sale_customer(
                sale_id=sale_id,
                customer_id=serializer.validated_data.get("customer_id"),
                reason=serializer.validated_data.get("reason", ""),
                user=request.user,
            )
        except Sales.DoesNotExist:
            raise ValidationError({"sale": "Sale not found."})
        return Response(
            {
                "sale_id": sale.pk,
                "sale_reference": sale.sale_id,
                "customer_id": sale.customer_id,
                "buyer_name": sale.buyer_name,
            }
        )


class CustomerCostSourceView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        return Response(json_safe(customer_cost_source_candidates(search=search)))


class CustomerUnlinkedSalesView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        queryset = (
            Sales.objects.select_related("batch")
            .filter(customer__isnull=True)
            .exclude(payment_status="cancelled")
            .order_by("-sale_date", "-pk")
        )
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(sale_id__icontains=search)
                | Q(buyer_name__icontains=search)
                | Q(batch__batch_id__icontains=search)
            )
        return Response(
            [
                {
                    "id": sale.pk,
                    "sale_id": sale.sale_id,
                    "sale_date": sale.sale_date,
                    "buyer_name": sale.buyer_name,
                    "buyer_type": sale.buyer_type,
                    "batch_id": sale.batch_id,
                    "batch_code": sale.batch.batch_id,
                    "product_type": sale.product_type,
                    "revenue": sale.sale_total,
                }
                for sale in queryset[:100]
            ]
        )


class CustomerContributionReportView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        customer_values = [
            value.strip()
            for raw in request.query_params.getlist("customer")
            for value in raw.split(",")
            if value.strip()
        ]
        try:
            customer_ids = {int(value) for value in customer_values}
        except ValueError:
            raise ValidationError({"customer": "Select valid customers."})
        if len(customer_ids) > 100:
            raise ValidationError({"customer": "Select no more than 100 customers."})
        product_type = request.query_params.get("product_type", "").strip()
        if product_type and product_type not in ProductType.values:
            raise ValidationError({"product_type": "Select a valid poultry product."})
        filters = {
            "date_from": _parse_report_date(request.query_params.get("date_from"), "date_from"),
            "date_to": _parse_report_date(request.query_params.get("date_to"), "date_to"),
            "customer_ids": customer_ids,
            "product_type": product_type,
            "search": request.query_params.get("search", "").strip(),
        }
        if filters["date_from"] and filters["date_to"] and filters["date_from"] > filters["date_to"]:
            raise ValidationError({"date_to": "The end date must not be before the start date."})
        report = customer_contribution_report(**filters)
        is_export = request.query_params.get("export") == "1"
        if not is_export:
            report["customers"], report["page"] = _nested_page(
                report["customers"], request, prefix="customer"
            )
        record_finance_action(
            actor=request.user,
            action="customer_contribution_report_viewed",
            entity_type="finance.CustomerContributionReport",
            after_data={
                "date_from": filters["date_from"],
                "date_to": filters["date_to"],
                "customer_ids": sorted(customer_ids),
                "product_type": product_type,
                "full_filtered_export": is_export,
            },
        )
        return Response(json_safe(report))


class OwnerContributorViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = OwnerContributorSerializer
    permission_classes = (OwnerCapitalPermission,)
    pagination_class = FinanceRegisterPagination
    queryset = OwnerContributor.objects.select_related("created_by").all()
    search_fields = ["display_name", "notes"]
    filterset_fields = ["is_active"]

    def perform_create(self, serializer):
        owner = serializer.save(created_by=self.request.user)
        record_finance_action(
            actor=self.request.user,
            action="owner_contributor_created",
            entity_type="finance.OwnerContributor",
            entity_id=owner.pk,
            after_data={
                "public_id": owner.public_id,
                "display_name": owner.display_name,
                "is_active": owner.is_active,
            },
        )

    def perform_update(self, serializer):
        current = self.get_object()
        before = {
            "display_name": current.display_name,
            "notes": current.notes,
            "is_active": current.is_active,
        }
        owner = serializer.save()
        record_finance_action(
            actor=self.request.user,
            action="owner_contributor_updated",
            entity_type="finance.OwnerContributor",
            entity_id=owner.pk,
            before_data=before,
            after_data={
                "display_name": owner.display_name,
                "notes": owner.notes,
                "is_active": owner.is_active,
            },
        )


class OwnerReceiptDesignationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OwnerReceiptDesignationSerializer
    permission_classes = (OwnerCapitalPermission,)
    pagination_class = FinanceRegisterPagination
    queryset = OwnerReceiptDesignation.objects.select_related(
        "receipt__funding_source__owner", "batch", "created_by", "reversed_by"
    ).all()
    filterset_fields = ["receipt", "batch", "status", "designation_date"]

    @action(detail=False, methods=["post"], url_path="for-receipt/(?P<receipt_id>[^/.]+)")
    def for_receipt(self, request, receipt_id=None):
        get_object_or_404(FundingReceipt, pk=receipt_id)
        serializer = OwnerDesignationCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = add_owner_designations(
            receipt_id=int(receipt_id),
            designation_date=serializer.validated_data["designation_date"],
            designations=serializer.validated_data["designations"],
            user=request.user,
        )
        return Response(
            self.get_serializer(rows, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        self.get_object()
        row = reverse_owner_designation(
            designation_id=int(pk),
            reason=request.data.get("reason", ""),
            user=request.user,
        )
        return Response(self.get_serializer(row).data)


class FinanceActionEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FinanceActionEventSerializer
    permission_classes = (OwnerCapitalPermission,)
    pagination_class = FinanceRegisterPagination
    queryset = FinanceActionEvent.objects.select_related("actor").all()
    filterset_fields = ["action", "entity_type", "entity_id", "actor"]


class OwnerContributionView(APIView):
    permission_classes = (OwnerCapitalPermission,)

    def post(self, request):
        serializer = OwnerContributionCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        receipt, created = record_owner_contribution(
            owner_id=data["owner"].pk,
            funding_source_id=(data.get("funding_source").pk if data.get("funding_source") else None),
            source_description=data.get("source_description", ""),
            amount=data["amount"],
            receipt_date=data["receipt_date"],
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            designation_date=data.get("designation_date"),
            designations=data.get("designations", []),
            idempotency_key=data["idempotency_key"],
            user=request.user,
        )
        receipt = FundingReceipt.objects.select_related(
            "funding_source__owner", "created_by", "reversed_by"
        ).get(pk=receipt.pk)
        return Response(
            FundingReceiptSerializer(receipt, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


def _parse_report_date(value, field_name):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({field_name: "Use YYYY-MM-DD."})


def _nested_page(rows, request, *, prefix: str, default_size=20):
    try:
        page = max(int(request.query_params.get(f"{prefix}_page", 1)), 1)
        size = min(
            max(int(request.query_params.get(f"{prefix}_page_size", default_size)), 1),
            100,
        )
    except (TypeError, ValueError):
        raise ValidationError({f"{prefix}_page": "Page values must be positive integers."})
    count = len(rows)
    pages = max((count + size - 1) // size, 1)
    page = min(page, pages)
    start = (page - 1) * size
    return rows[start:start + size], {
        "count": count,
        "page": page,
        "page_size": size,
        "pages": pages,
        "next": page + 1 if page < pages else None,
        "previous": page - 1 if page > 1 else None,
    }


class OwnerContributionReportView(APIView):
    permission_classes = (OwnerCapitalPermission,)

    def get(self, request):
        owner_value = request.query_params.get("owner", "").strip()
        unknown_owner = owner_value == "unknown"
        owner_id = None
        if owner_value and not unknown_owner:
            try:
                owner_id = int(owner_value)
            except ValueError:
                raise ValidationError({"owner": "Select a valid owner."})
        batch_values = [
            value.strip()
            for raw in request.query_params.getlist("batch")
            for value in raw.split(",")
            if value.strip()
        ]
        try:
            batch_ids = {int(value) for value in batch_values}
        except ValueError:
            raise ValidationError({"batch": "Select valid poultry batches."})
        filters = {
            "date_from": _parse_report_date(request.query_params.get("date_from"), "date_from"),
            "date_to": _parse_report_date(request.query_params.get("date_to"), "date_to"),
            "owner_id": owner_id,
            "unknown_owner": unknown_owner,
            "batch_ids": batch_ids,
        }
        report = owner_contribution_report(**filters)
        is_export = request.query_params.get("export") == "1"
        if not is_export:
            for key, prefix in (("batches", "batch"), ("receipts", "receipt"), ("timeline", "timeline")):
                report[key], report[f"{prefix}_page"] = _nested_page(
                    report[key], request, prefix=prefix
                )
        record_finance_action(
            actor=request.user,
            action="owner_contribution_report_viewed",
            entity_type="finance.OwnerContributionReport",
            after_data={
                "date_from": filters["date_from"],
                "date_to": filters["date_to"],
                "owner_id": owner_id,
                "unknown_owner": unknown_owner,
                "batch_ids": sorted(batch_ids),
                "full_filtered_export": is_export,
            },
        )
        return Response(json_safe(report))


class ExpenditureViewSet(viewsets.ModelViewSet):
    """
    CRUD + Post action for expenditures.
    Supports the full funding + cost allocation workflow.
    """
    queryset = Expenditure.objects.all().select_related(
        "category", "created_by", "posted_by", "reversed_by"
    ).prefetch_related(
        "funding_allocations__funding_source",
        "funding_allocations__created_by",
        "cost_allocations__batch",
    )
    serializer_class = ExpenditureSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = [
        "status", "payment_status", "origin", "accounting_nature", "category",
        "expenditure_date",
    ]
    search_fields = ["description", "payee", "expenditure_reference", "external_reference"]
    pagination_class = ExpenditurePagination

    def _enforce_owner_payment_access(self, rows):
        rows = rows or []
        owner_only = {
            FundingClassification.OWNER_CAPITAL_RETURN,
            FundingClassification.OWNER_DRAWING,
            FundingClassification.OWNER_COMPENSATION,
            FundingClassification.OWNER_DISTRIBUTION,
        }
        sensitive = [row for row in rows if row.get("classification") in owner_only]
        all_source_ids = [row.get("funding_source") for row in rows]
        uses_owner_cash = FundingSource.objects.filter(
            pk__in=all_source_ids,
            source_type=FundingSourceType.OWNER_CAPITAL,
        ).exists()
        if uses_owner_cash and not has_owner_capital_access(self.request.user):
            raise PermissionDenied(
                "Only administrators and directors can assign owner-capital cash."
            )
        if not sensitive:
            return
        if not has_owner_capital_access(self.request.user):
            raise PermissionDenied(
                "Only administrators and directors can classify owner payments."
            )
        source_ids = [row.get("funding_source") for row in sensitive]
        if FundingSource.objects.filter(pk__in=source_ids).exclude(
            source_type=FundingSourceType.OWNER_CAPITAL
        ).exists():
            raise ValidationError(
                {"funding_allocations": "Owner payment classifications require an owner-capital source."}
            )

    def _audit_owner_payment(self, expenditure, action_name):
        owner_only = {
            FundingClassification.OWNER_CAPITAL_RETURN,
            FundingClassification.OWNER_DRAWING,
            FundingClassification.OWNER_COMPENSATION,
            FundingClassification.OWNER_DISTRIBUTION,
        }
        rows = list(
            expenditure.funding_allocations.filter(
                classification__in=owner_only
            ).values("id", "funding_source_id", "amount", "classification", "allocation_date")
        )
        if rows:
            record_finance_action(
                actor=self.request.user,
                action=action_name,
                entity_type="finance.Expenditure",
                entity_id=expenditure.pk,
                after_data={
                    "expenditure_reference": expenditure.expenditure_reference,
                    "owner_payment_rows": rows,
                },
            )

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search", "").strip()
        expenditure_status = self.request.query_params.get("status", "").strip()
        payment_status = self.request.query_params.get("payment_status", "").strip()

        if search:
            queryset = queryset.filter(
                Q(description__icontains=search)
                | Q(payee__icontains=search)
                | Q(expenditure_reference__icontains=search)
                | Q(external_reference__icontains=search)
            )
        if expenditure_status:
            queryset = queryset.filter(status=expenditure_status)
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)
        return queryset

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
        rows_to_check = funding_data
        if rows_to_check is None:
            rows_to_check = list(
                self.get_object().funding_allocations.values(
                    "funding_source", "classification"
                )
            )
        self._enforce_owner_payment_access(rows_to_check)
        cost_data = request.data.get("cost_allocations")
        allow_unpaid = request.data.get("payment_status") in {"credit", "unpaid", "partial"}
        expenditure = post_expenditure(
            expenditure_id=pk,
            user=request.user,
            funding_rows=funding_data,
            cost_rows=cost_data,
            allow_unpaid=allow_unpaid,
        )
        self._audit_owner_payment(expenditure, "owner_payment_posted")
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        current = self.get_object()
        current_rows = list(
            current.funding_allocations.values("funding_source", "classification")
        )
        self._enforce_owner_payment_access(current_rows)
        expenditure = reverse_expenditure(
            expenditure_id=pk,
            reason=request.data.get("reason"),
            user=request.user,
        )
        self._audit_owner_payment(current, "owner_payment_reversed")
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"], url_path="assign-funding")
    def assign_funding(self, request, pk=None):
        """Controlled reconciliation for historical posted, wholly unfunded rows."""
        self._enforce_owner_payment_access(request.data.get("funding_allocations", []))
        expenditure = record_expenditure_payment(
            expenditure_id=pk,
            funding_rows=request.data.get("funding_allocations", []) or [],
            payment_group_key=request.data.get("idempotency_key") or f"historical-{pk}",
            payment_date=request.data.get("payment_date"),
            user=request.user,
        )
        self._audit_owner_payment(expenditure, "owner_payment_recorded")
        return Response(ExpenditureSerializer(expenditure).data)

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        self._enforce_owner_payment_access(request.data.get("funding_allocations", []))
        expenditure = record_expenditure_payment(
            expenditure_id=pk,
            funding_rows=request.data.get("funding_allocations", []) or [],
            payment_group_key=request.data.get("idempotency_key"),
            payment_date=request.data.get("payment_date"),
            user=request.user,
        )
        self._audit_owner_payment(expenditure, "owner_payment_recorded")
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
    queryset = FundingSource.objects.select_related("batch", "owner").all()
    serializer_class = FundingSourceSerializer
    permission_classes = (FinancePermission,)

    def get_queryset(self):
        queryset = super().get_queryset()
        if not has_owner_capital_access(self.request.user):
            queryset = queryset.exclude(source_type=FundingSourceType.OWNER_CAPITAL)
        return queryset

    def _protect_owner_write(self, source_type):
        if (
            source_type == FundingSourceType.OWNER_CAPITAL
            and not has_owner_capital_access(self.request.user)
        ):
            raise PermissionDenied("Only administrators and directors can manage owner capital.")

    def perform_create(self, serializer):
        source_type = serializer.validated_data.get("source_type")
        self._protect_owner_write(source_type)
        source = serializer.save()
        if source_type == FundingSourceType.OWNER_CAPITAL:
            record_finance_action(
                actor=self.request.user,
                action="owner_funding_source_created",
                entity_type="finance.FundingSource",
                entity_id=source.pk,
                after_data={"owner_id": source.owner_id, "description": source.description},
            )

    def perform_update(self, serializer):
        current = self.get_object()
        requested_type = serializer.validated_data.get("source_type", current.source_type)
        self._protect_owner_write(current.source_type)
        self._protect_owner_write(requested_type)
        before = {
            "owner_id": current.owner_id,
            "description": current.description,
            "is_active": current.is_active,
        }
        source = serializer.save()
        if current.source_type == FundingSourceType.OWNER_CAPITAL or requested_type == FundingSourceType.OWNER_CAPITAL:
            record_finance_action(
                actor=self.request.user,
                action="owner_funding_source_updated",
                entity_type="finance.FundingSource",
                entity_id=source.pk,
                before_data=before,
                after_data={
                    "owner_id": source.owner_id,
                    "description": source.description,
                    "is_active": source.is_active,
                },
            )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().filter(is_active=True)
        search = request.query_params.get("search", "").strip()
        if search:
            search_filter = (
                Q(description__icontains=search)
                | Q(batch__batch_id__icontains=search)
                | Q(source_type__icontains=search.replace(" ", "_"))
            )
            normalized_search = search.lower()
            if normalized_search in {"batch", "batch sales", "sales", "revenue"}:
                search_filter |= Q(source_type=FundingSourceType.BATCH_COLLECTION)
            if normalized_search in {"owner", "owner equity", "equity", "capital"}:
                search_filter |= Q(source_type=FundingSourceType.OWNER_CAPITAL)
            if normalized_search in {"farm", "farm cash", "cash"}:
                search_filter |= Q(source_type=FundingSourceType.GENERAL_FARM_CASH)
            queryset = queryset.filter(search_filter)

        requested_types = [
            value.strip()
            for raw_value in request.query_params.getlist("source_type")
            for value in raw_value.split(",")
            if value.strip()
        ]
        if requested_types:
            valid_types = {choice for choice, _ in FundingSourceType.choices}
            invalid_types = sorted(set(requested_types) - valid_types)
            if invalid_types:
                raise ValidationError(
                    {"source_type": "Unknown source type(s): " + ", ".join(invalid_types)}
                )
            queryset = queryset.filter(source_type__in=requested_types)

        batch_id = request.query_params.get("batch")
        if batch_id:
            queryset = queryset.filter(batch_id=batch_id)

        sources = list(queryset.order_by("source_type", "batch__batch_id", "description", "pk"))
        from .services.profitability import funding_source_available_balances

        available_balances = funding_source_available_balances(sources)
        if request.query_params.get("include_empty") != "1":
            sources = [
                source for source in sources if available_balances[source.pk] > 0
            ]
        paginator = FinanceRegisterPagination()
        page = paginator.paginate_queryset(sources, request, view=self)
        serializer = self.get_serializer(
            page,
            many=True,
            context={
                **self.get_serializer_context(),
                "available_balances": available_balances,
            },
        )
        return paginator.get_paginated_response(serializer.data)


class FundingReceiptViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = FundingReceipt.objects.all().select_related(
        "funding_source__owner", "created_by", "reversed_by"
    )
    serializer_class = FundingReceiptSerializer
    permission_classes = (FinancePermission,)
    filterset_fields = ["funding_source", "status"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not has_owner_capital_access(self.request.user):
            queryset = queryset.exclude(
                funding_source__source_type=FundingSourceType.OWNER_CAPITAL
            )
        return queryset

    def perform_create(self, serializer):
        source = serializer.validated_data["funding_source"]
        if source.source_type == FundingSourceType.BATCH_COLLECTION:
            raise ValidationError(
                {"funding_source": "Batch collection balances come from sale payments."}
            )
        if source.source_type == FundingSourceType.OWNER_CAPITAL:
            if not has_owner_capital_access(self.request.user):
                raise PermissionDenied("Only administrators and directors can record owner capital.")
            if source.owner_id is None:
                raise ValidationError(
                    {"funding_source": "New owner-capital receipts require a named owner."}
                )
            raise ValidationError(
                {
                    "funding_source": (
                        "Record owner capital through the owner-contributions workflow "
                        "so identity, idempotency, designations, and audit history remain complete."
                    )
                }
            )
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        receipt = get_object_or_404(
            FundingReceipt.objects.select_related("funding_source"), pk=pk
        )
        if (
            receipt.funding_source.source_type == FundingSourceType.OWNER_CAPITAL
            and not has_owner_capital_access(request.user)
        ):
            raise PermissionDenied("Only administrators and directors can reverse owner capital.")
        receipt = reverse_funding_receipt(
            receipt_id=int(pk),
            reason=request.data.get("reason", ""),
            user=request.user,
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
        transactions = data.get("transactions", [])
        try:
            page_number = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
        except (TypeError, ValueError):
            raise ValidationError({"page": "Page and page_size must be positive integers."})
        transaction_count = len(transactions)
        page_count = max((transaction_count + page_size - 1) // page_size, 1)
        page_number = min(page_number, page_count)
        start = (page_number - 1) * page_size
        data["transactions"] = transactions[start:start + page_size]
        data["transaction_page"] = {
            "count": transaction_count,
            "page": page_number,
            "page_size": page_size,
            "pages": page_count,
            "next": page_number + 1 if page_number < page_count else None,
            "previous": page_number - 1 if page_number > 1 else None,
        }
        return Response(json_safe(data))


class BatchRevenueUtilizationListView(APIView):
    """One paginated request for batch cash-utilization summaries."""
    permission_classes = (FinancePermission,)

    def get(self, request):
        ordering = request.query_params.get("ordering", "-entry_date")
        allowed_ordering = {"entry_date", "-entry_date", "batch_id", "-batch_id"}
        if ordering not in allowed_ordering:
            ordering = "-entry_date"
        queryset = Batch.objects.all().order_by(ordering, "-pk")
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(batch_id__icontains=search)
        paginator = FinanceRegisterPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        batch_ids = [batch.pk for batch in page]
        posted_receipts = {
            row["sale__batch_id"]: Decimal(row["total"] or 0)
            for row in SalePayment.objects.filter(
                sale__batch_id__in=batch_ids, status="posted"
            ).values("sale__batch_id").annotate(total=Sum("amount"))
        }
        reversed_receipts = {
            row["sale__batch_id"]: Decimal(row["total"] or 0)
            for row in SalePayment.objects.filter(
                sale__batch_id__in=batch_ids, status="reversed"
            ).values("sale__batch_id").annotate(total=Sum("amount"))
        }
        spent = {
            row["funding_source__batch_id"]: Decimal(row["total"] or 0)
            for row in FundingAllocation.objects.filter(
                funding_source__batch_id__in=batch_ids,
                funding_source__source_type=FundingSourceType.BATCH_COLLECTION,
                expenditure__status=ExpenditureStatus.POSTED,
            ).values("funding_source__batch_id").annotate(total=Sum("amount"))
        }
        results = []
        for batch in page:
            collected = posted_receipts.get(batch.pk, Decimal("0.00"))
            refunds = reversed_receipts.get(batch.pk, Decimal("0.00"))
            used = spent.get(batch.pk, Decimal("0.00"))
            results.append({
                "batch_id": batch.pk,
                "batch_code": batch.batch_id,
                "cash_collected": collected,
                "gross_collections": collected + refunds,
                "refunds": refunds,
                "cash_used": used,
                "available_cash": collected - used,
                "utilization_percent": (used * Decimal("100") / collected).quantize(Decimal("0.01")) if collected else None,
                "beneficiary_modules": [],
            })
        return paginator.get_paginated_response(json_safe(results))


class BatchFundingMixView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request, batch_id: int):
        batch = get_object_or_404(Batch, pk=batch_id)
        data = batch_expenditure_funding_mix(batch)
        transactions = data["transactions"]
        try:
            page_number = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("page_size", 20)), 1), 100)
        except (TypeError, ValueError):
            raise ValidationError({"page": "Page and page_size must be positive integers."})
        transaction_count = len(transactions)
        page_count = max((transaction_count + page_size - 1) // page_size, 1)
        page_number = min(page_number, page_count)
        start = (page_number - 1) * page_size
        data["transactions"] = transactions[start:start + page_size]
        data["transaction_page"] = {
            "count": transaction_count,
            "page": page_number,
            "page_size": page_size,
            "pages": page_count,
            "next": page_number + 1 if page_number < page_count else None,
            "previous": page_number - 1 if page_number > 1 else None,
        }
        return Response(json_safe(data))


class BatchFundingMixListView(APIView):
    permission_classes = (FinancePermission,)

    def get(self, request):
        queryset = Batch.objects.all().order_by("-entry_date", "-pk")
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(batch_id__icontains=search)
        paginator = FinanceRegisterPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        results = [
            batch_expenditure_funding_mix(batch, include_transactions=False)
            for batch in page
        ]
        return paginator.get_paginated_response(json_safe(results))


class CrossBatchFinancingReportView(APIView):
    """Batch sales used for costs carried by another batch."""
    permission_classes = (FinancePermission,)

    def get(self, request):
        batch_id = request.query_params.get("batch")
        cost_allocations = (
            CostAllocation.objects.filter(
                expenditure__status=ExpenditureStatus.POSTED,
                expenditure__funding_allocations__funding_source__source_type=(
                    FundingSourceType.BATCH_COLLECTION
                ),
            )
            .select_related("batch", "expenditure")
            .prefetch_related(
                "expenditure__cost_allocations",
                "expenditure__funding_allocations__funding_source__batch",
            )
            .distinct()
        )
        flows = []
        for cost_allocation in cost_allocations:
            expenditure = cost_allocation.expenditure
            for funding in expenditure.funding_allocations.all():
                source = funding.funding_source
                if (
                    source.source_type != FundingSourceType.BATCH_COLLECTION
                    or not source.batch_id
                    or source.batch_id == cost_allocation.batch_id
                ):
                    continue
                if batch_id and str(source.batch_id) != batch_id and str(
                    cost_allocation.batch_id
                ) != batch_id:
                    continue
                attribution = expenditure_payment_beneficiary_shares(
                    expenditure, funding.amount
                )
                attributed_amount = attribution["allocation_shares"].get(
                    cost_allocation.pk, Decimal("0.00")
                )
                if attributed_amount <= Decimal("0.00"):
                    continue
                flows.append(
                    {
                        "funding_batch_id": source.batch_id,
                        "funding_batch_code": source.batch.batch_id,
                        "expenditure_id": expenditure.pk,
                        "expenditure_desc": expenditure.description,
                        "amount_funded": attributed_amount,
                        "allocated_to_batch_id": cost_allocation.batch_id,
                        "allocated_to_batch_code": cost_allocation.batch.batch_id,
                        "allocated_amount": cost_allocation.allocated_amount,
                        "date": funding.allocation_date,
                    }
                )
        ordering = request.query_params.get("ordering", "-allocation_date")
        allowed_ordering = {"allocation_date", "-allocation_date", "amount", "-amount"}
        if ordering not in allowed_ordering:
            ordering = "-allocation_date"
        reverse = ordering.startswith("-")
        ordering_key = "date" if "allocation_date" in ordering else "amount_funded"
        flows.sort(key=lambda row: row[ordering_key], reverse=reverse)
        paginator = FinanceRegisterPagination()
        page = paginator.paginate_queryset(flows, request, view=self)
        return paginator.get_paginated_response(json_safe(page))
