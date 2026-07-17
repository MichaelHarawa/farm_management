from django.contrib import admin

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    BatchProfitabilitySnapshot,
    BirdDaySnapshot,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    PayrollEntry,
    SharedExpense,
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
