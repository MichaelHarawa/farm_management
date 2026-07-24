from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountingPeriodViewSet,
    AdHocLabourPaymentViewSet,
    AssetCategoryViewSet,
    AssetDepreciationEntryViewSet,
    AssetUsageRecordViewSet,
    AssetViewSet,
    BatchProfitabilityView,
    BirdDaySnapshotViewSet,
    ConsumableUsageViewSet,
    CostAllocationViewSet,
    DashboardView,
    EmployeeBatchWorkLogViewSet,
    EmployeeProfileViewSet,
    ExpenseRecognitionScheduleViewSet,
    MonthlyReportView,
    PayrollEntryViewSet,
    ReceivablesView,
    ReplacementReserveTransactionViewSet,
    SharedExpenseViewSet,
    SharedConsumableLotViewSet,
)


router = DefaultRouter(trailing_slash=False)
router.register("employees", EmployeeProfileViewSet, basename="finance-employee")
router.register(
    "accounting-periods",
    AccountingPeriodViewSet,
    basename="finance-accounting-period",
)
router.register("payroll-entries", PayrollEntryViewSet, basename="finance-payroll-entry")
router.register("ad-hoc-labour", AdHocLabourPaymentViewSet, basename="finance-labour")
router.register("expenses", SharedExpenseViewSet, basename="finance-expense")
router.register(
    "consumable-lots",
    SharedConsumableLotViewSet,
    basename="finance-consumable-lot",
)
router.register(
    "consumable-usages",
    ConsumableUsageViewSet,
    basename="finance-consumable-usage",
)
router.register(
    "prepaid-recognition",
    ExpenseRecognitionScheduleViewSet,
    basename="finance-prepaid-recognition",
)
router.register("asset-categories", AssetCategoryViewSet, basename="finance-asset-category")
router.register("assets", AssetViewSet, basename="finance-asset")
router.register("asset-usage", AssetUsageRecordViewSet, basename="finance-asset-usage")
router.register(
    "asset-depreciation",
    AssetDepreciationEntryViewSet,
    basename="finance-asset-depreciation",
)
router.register(
    "reserve-transactions",
    ReplacementReserveTransactionViewSet,
    basename="finance-reserve-transaction",
)
router.register("work-logs", EmployeeBatchWorkLogViewSet, basename="finance-work-log")
router.register("bird-day-snapshots", BirdDaySnapshotViewSet, basename="finance-bird-days")
router.register("allocations", CostAllocationViewSet, basename="finance-allocation")

app_name = "finance"

urlpatterns = [
    path("", include(router.urls)),
    path("reports/monthly", MonthlyReportView.as_view(), name="monthly-report"),
    path(
        "reports/batches/<int:batch_id>",
        BatchProfitabilityView.as_view(),
        name="batch-profitability",
    ),
    path("dashboard", DashboardView.as_view(), name="dashboard"),
    path("receivables", ReceivablesView.as_view(), name="receivables"),
]
