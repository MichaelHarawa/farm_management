from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AccountingPeriodViewSet,
    AdHocLabourPaymentViewSet,
    AssetCategoryViewSet,
    AssetDepreciationEntryViewSet,
    AssetUsageRecordViewSet,
    AssetViewSet,
    BatchPortfolioView,
    BatchProfitabilityView,
    BirdDaySnapshotViewSet,
    ConsumableUsageViewSet,
    CostAllocationViewSet,
    DashboardView,
    EmployeeBatchWorkLogViewSet,
    EmployeeProfileViewSet,
    ExpenseRecognitionScheduleViewSet,
    ExpenditureViewSet,
    ExpenditureCategoryViewSet,
    FundingSourceViewSet,
    FundingReceiptViewSet,
    MonthlyReportView,
    BatchRevenueUtilizationView,
    CrossBatchFinancingReportView,
    PayrollEntryViewSet,
    ReceivablesView,
    SalePaymentsView,
    SalePaymentReverseView,
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
router.register("expenditures", ExpenditureViewSet, basename="finance-expenditure")
router.register("funding-sources", FundingSourceViewSet, basename="finance-funding-source")
router.register("funding-receipts", FundingReceiptViewSet, basename="finance-funding-receipt")
router.register("expenditure-categories", ExpenditureCategoryViewSet, basename="finance-expenditure-category")

app_name = "finance"

urlpatterns = [
    path("", include(router.urls)),
    path("reports/monthly", MonthlyReportView.as_view(), name="monthly-report"),
    path(
        "reports/batches",
        BatchPortfolioView.as_view(),
        name="batch-portfolio",
    ),
    path(
        "reports/batches/<int:batch_id>",
        BatchProfitabilityView.as_view(),
        name="batch-profitability",
    ),
    path("dashboard", DashboardView.as_view(), name="dashboard"),
    path("receivables", ReceivablesView.as_view(), name="receivables"),
    path(
        "receivables/<int:sale_id>/payments",
        SalePaymentsView.as_view(),
        name="sale-payments",
    ),
    path(
        "payments/<int:payment_id>/reverse",
        SalePaymentReverseView.as_view(),
        name="sale-payment-reverse",
    ),
    path(
        "reports/batches/<int:batch_id>/revenue-utilization",
        BatchRevenueUtilizationView.as_view(),
        name="batch-revenue-utilization",
    ),
    path(
        "reports/cross-batch-financing",
        CrossBatchFinancingReportView.as_view(),
        name="cross-batch-financing",
    ),
]
