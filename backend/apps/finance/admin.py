from django.contrib import admin

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    Asset,
    AssetCapitalizedCost,
    AssetCategory,
    AssetDepreciationEntry,
    AssetMaintenanceRecord,
    AssetReplacementPlan,
    AssetUsageRecord,
    BatchProfitabilitySnapshot,
    BirdDaySnapshot,
    ConsumableUsage,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    ExpenseRecognitionSchedule,
    PayrollEntry,
    ReplacementReserveTransaction,
    SharedExpense,
    SharedConsumableLot,
)


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = (
        "employee_number",
        "user",
        "employment_type",
        "job_title",
        "is_active",
        "base_monthly_salary",
    )
    list_filter = ("employment_type", "is_active", "department")
    search_fields = ("employee_number", "user__username", "user__email", "job_title")
    autocomplete_fields = ("user", "created_by")


@admin.register(AccountingPeriod)
class AccountingPeriodAdmin(admin.ModelAdmin):
    list_display = ("period_start", "period_end", "status", "closed_at")
    list_filter = ("status",)
    search_fields = ("period_start", "period_end", "notes")
    date_hierarchy = "period_start"
    autocomplete_fields = ("closed_by",)


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    list_display = (
        "accounting_period",
        "employee",
        "gross_salary",
        "total_employer_cost",
        "payment_status",
    )
    list_filter = ("payment_status", "accounting_period")
    search_fields = ("employee__employee_number", "employee__user__username")
    autocomplete_fields = ("accounting_period", "employee", "created_by")


@admin.register(AdHocLabourPayment)
class AdHocLabourPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "worker_name",
        "work_date",
        "cost_scope",
        "batch",
        "payment_amount",
        "payment_status",
    )
    list_filter = ("cost_scope", "payment_status", "accounting_period")
    search_fields = ("worker_name", "task_description")
    autocomplete_fields = (
        "linked_employee",
        "batch",
        "accounting_period",
        "created_by",
    )


@admin.register(SharedExpense)
class SharedExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "expense_date",
        "scope",
        "amount",
        "payment_status",
    )
    list_filter = ("scope", "payment_status", "accounting_period")
    search_fields = ("description", "category", "supplier", "reference_number")
    autocomplete_fields = (
        "accounting_period",
        "directly_assigned_batch",
        "created_by",
    )


@admin.register(SharedConsumableLot)
class SharedConsumableLotAdmin(admin.ModelAdmin):
    list_display = (
        "item",
        "category",
        "purchase_date",
        "quantity_available",
        "unit_cost",
        "payment_status",
    )
    list_filter = ("category", "payment_status", "expiry_date")
    search_fields = ("item", "supplier", "invoice_reference")
    autocomplete_fields = ("linked_expense", "created_by")


@admin.register(ConsumableUsage)
class ConsumableUsageAdmin(admin.ModelAdmin):
    list_display = (
        "consumable_lot",
        "usage_date",
        "accounting_period",
        "usage_scope",
        "batch",
        "recognized_cost",
        "locked",
    )
    list_filter = ("usage_scope", "accounting_period", "locked")
    autocomplete_fields = (
        "consumable_lot",
        "accounting_period",
        "batch",
        "recorded_by",
        "approved_by",
    )


@admin.register(ExpenseRecognitionSchedule)
class ExpenseRecognitionScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "source_expense",
        "accounting_period",
        "recognition_method",
        "amount_recognized",
        "remaining_deferred_amount",
        "locked",
    )
    list_filter = ("recognition_method", "accounting_period", "locked")
    autocomplete_fields = ("source_expense", "accounting_period", "generated_by")


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "default_useful_life_months",
        "default_depreciation_method",
        "is_active",
    )
    list_filter = ("code", "default_depreciation_method", "is_active")
    search_fields = ("name", "code")


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = (
        "asset_code",
        "name",
        "asset_category",
        "status",
        "total_capitalized_cost",
        "available_for_use_date",
    )
    list_filter = ("status", "production_scope", "depreciation_method")
    search_fields = ("asset_code", "name", "serial_number", "supplier")
    autocomplete_fields = ("asset_category", "created_by")


@admin.register(AssetCapitalizedCost)
class AssetCapitalizedCostAdmin(admin.ModelAdmin):
    list_display = ("asset", "expense", "capitalized_amount")
    autocomplete_fields = ("asset", "expense", "created_by")


@admin.register(AssetUsageRecord)
class AssetUsageRecordAdmin(admin.ModelAdmin):
    list_display = ("asset", "usage_date", "usage_unit", "quantity", "batch")
    list_filter = ("usage_unit", "accounting_period", "locked")
    autocomplete_fields = ("asset", "accounting_period", "batch", "recorded_by", "approved_by")


@admin.register(AssetDepreciationEntry)
class AssetDepreciationEntryAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "accounting_period",
        "period_depreciation",
        "closing_carrying_amount",
        "locked",
    )
    list_filter = ("accounting_period", "depreciation_method_snapshot", "locked")
    autocomplete_fields = ("asset", "accounting_period", "generated_by")


@admin.register(AssetMaintenanceRecord)
class AssetMaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("asset", "maintenance_date", "cost_amount", "next_due_date")
    list_filter = ("maintenance_date", "next_due_date")
    autocomplete_fields = ("asset", "accounting_period", "linked_expense", "recorded_by")


@admin.register(AssetReplacementPlan)
class AssetReplacementPlanAdmin(admin.ModelAdmin):
    list_display = (
        "asset",
        "current_replacement_cost",
        "projected_future_replacement_cost",
        "target_reserve_balance",
    )
    autocomplete_fields = ("asset", "updated_by")


@admin.register(ReplacementReserveTransaction)
class ReplacementReserveTransactionAdmin(admin.ModelAdmin):
    list_display = ("asset", "transaction_date", "transaction_type", "amount")
    list_filter = ("transaction_type", "accounting_period")
    autocomplete_fields = ("asset", "accounting_period", "authorized_by")


@admin.register(EmployeeBatchWorkLog)
class EmployeeBatchWorkLogAdmin(admin.ModelAdmin):
    list_display = ("employee", "batch", "work_date", "hours_worked", "task")
    list_filter = ("work_date",)
    autocomplete_fields = ("employee", "batch", "approved_by")


@admin.register(BirdDaySnapshot)
class BirdDaySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "accounting_period",
        "batch",
        "active_days",
        "bird_days",
        "calculation_version",
    )
    list_filter = ("accounting_period", "calculation_version")
    autocomplete_fields = ("accounting_period", "batch")


@admin.register(CostAllocation)
class CostAllocationAdmin(admin.ModelAdmin):
    list_display = (
        "accounting_period",
        "batch",
        "source_type",
        "allocation_method",
        "allocated_amount",
        "locked",
    )
    list_filter = ("source_type", "allocation_method", "locked", "accounting_period")
    autocomplete_fields = (
        "accounting_period",
        "batch",
        "payroll_entry",
        "ad_hoc_labour_payment",
        "shared_expense",
        "generated_by",
    )


@admin.register(BatchProfitabilitySnapshot)
class BatchProfitabilitySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "batch",
        "status",
        "revenue",
        "batch_gross_profit",
        "fully_loaded_batch_profit",
        "final",
    )
    list_filter = ("final", "status", "accounting_period")
    autocomplete_fields = ("batch", "accounting_period", "generated_by")
