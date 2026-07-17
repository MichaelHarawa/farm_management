from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.poultry.models import Batch


MONEY_VALIDATOR = MinValueValidator(Decimal("0.00"))
PERCENT_VALIDATOR = MinValueValidator(Decimal("0.00"))


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class EmploymentType(models.TextChoices):
    PERMANENT = "permanent", "Permanent"
    CONTRACT = "contract", "Contract"
    TEMPORARY = "temporary", "Temporary"


class PeriodStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"


class FinancePaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    PARTIAL = "partial", "Partial"
    UNPAID = "unpaid", "Unpaid"
    CANCELLED = "cancelled", "Cancelled"


class CostScope(models.TextChoices):
    BATCH_DIRECT = "batch_direct", "Batch direct"
    SHARED_PRODUCTION = "shared_production", "Shared production"
    FARM_ADMINISTRATION = "farm_administration", "Farm administration"
    SELLING_AND_DISTRIBUTION = (
        "selling_and_distribution",
        "Selling and distribution",
    )


class SharedExpenseScope(models.TextChoices):
    SHARED_PRODUCTION = "shared_production", "Shared production"
    ADMIN_OVERHEAD = "admin_overhead", "Admin overhead"
    SELLING_EXPENSE = "selling_expense", "Selling expense"
    FINANCE_COST = "finance_cost", "Finance cost"
    CAPITAL_EXPENDITURE = "capital_expenditure", "Capital expenditure"
    TAX = "tax", "Tax"
    OTHER = "other", "Other"


class AllocationMethod(models.TextChoices):
    DIRECT = "direct", "Direct"
    ACTUAL_HOURS = "actual_hours", "Actual hours"
    BIRD_DAYS = "bird_days", "Bird-days"
    REVENUE_SHARE = "revenue_share", "Revenue share"
    SALES_QUANTITY = "sales_quantity", "Sales quantity"
    MANUAL = "manual", "Manual"
    NONE = "none", "None"


class AllocationSourceType(models.TextChoices):
    PAYROLL = "payroll", "Payroll"
    AD_HOC_LABOUR = "ad_hoc_labour", "Ad-hoc labour"
    SHARED_EXPENSE = "shared_expense", "Shared expense"


class AccountingPeriod(TimestampedModel):
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=PeriodStatus.choices,
        default=PeriodStatus.OPEN,
        db_index=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_accounting_periods",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["period_start", "period_end"],
                name="unique_accounting_period_dates",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=models.F("period_start")),
                name="accounting_period_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["period_start", "period_end"]),
            models.Index(fields=["status", "period_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d} to {self.period_end:%Y-%m-%d}"


class EmployeeProfile(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_profile",
    )
    employee_number = models.CharField(max_length=40, unique=True)
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.PERMANENT,
        db_index=True,
    )
    job_title = models.CharField(max_length=120)
    department = models.CharField(max_length=120, blank=True, default="")
    employment_start_date = models.DateField()
    employment_end_date = models.DateField(null=True, blank=True)
    base_monthly_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    standard_working_hours_per_day = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("8.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    standard_working_days_per_week = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("5.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    production_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("70.00"),
        validators=[PERCENT_VALIDATOR],
    )
    administration_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[PERCENT_VALIDATOR],
    )
    selling_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[PERCENT_VALIDATOR],
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employee_profiles",
    )

    class Meta:
        ordering = ["employee_number"]
        indexes = [
            models.Index(fields=["employment_type", "is_active"]),
            models.Index(fields=["employment_start_date", "employment_end_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee_number} - {self.user}"

    def clean(self):
        super().clean()
        allocation_total = (
            self.production_percentage
            + self.administration_percentage
            + self.selling_percentage
        )
        errors = {}
        if allocation_total != Decimal("100.00"):
            errors["production_percentage"] = (
                "Production, administration, and selling percentages must total 100."
            )
        if (
            self.employment_end_date
            and self.employment_end_date < self.employment_start_date
        ):
            errors["employment_end_date"] = (
                "Employment end date cannot be before the start date."
            )
        if errors:
            raise ValidationError(errors)


class PayrollEntry(TimestampedModel):
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="payroll_entries",
    )
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name="payroll_entries",
    )
    gross_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    employer_costs = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    deductions = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    total_employer_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    production_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    administration_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    selling_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    payment_status = models.CharField(
        max_length=20,
        choices=FinancePaymentStatus.choices,
        default=FinancePaymentStatus.UNPAID,
        db_index=True,
    )
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_entries",
    )

    class Meta:
        ordering = ["accounting_period", "employee__employee_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["accounting_period", "employee"],
                name="unique_payroll_entry_per_employee_period",
            )
        ]
        indexes = [
            models.Index(fields=["accounting_period", "employee"]),
            models.Index(fields=["payment_status", "payment_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee} payroll for {self.accounting_period}"

    @property
    def production_amount(self) -> Decimal:
        return (
            self.total_employer_cost * self.production_percentage / Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def administration_amount(self) -> Decimal:
        return (
            self.total_employer_cost
            * self.administration_percentage
            / Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def selling_amount(self) -> Decimal:
        return (
            self.total_employer_cost * self.selling_percentage / Decimal("100")
        ).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        if (
            self.production_percentage
            + self.administration_percentage
            + self.selling_percentage
            != Decimal("100.00")
        ):
            raise ValidationError(
                "Payroll allocation percentages must total 100."
            )

    def save(self, *args, **kwargs):
        self.total_employer_cost = (
            self.gross_salary + self.employer_costs
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class AdHocLabourPayment(TimestampedModel):
    worker_name = models.CharField(max_length=160)
    linked_employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ad_hoc_labour_payments",
    )
    task_description = models.CharField(max_length=255)
    work_date = models.DateField(db_index=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    hours_worked = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    payment_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    cost_scope = models.CharField(
        max_length=40,
        choices=CostScope.choices,
        db_index=True,
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ad_hoc_labour_payments",
    )
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ad_hoc_labour_payments",
    )
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    payment_method = models.CharField(max_length=80, blank=True, default="")
    payment_status = models.CharField(
        max_length=20,
        choices=FinancePaymentStatus.choices,
        default=FinancePaymentStatus.UNPAID,
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ad_hoc_labour_payments",
    )

    class Meta:
        ordering = ["-work_date", "-created_at"]
        indexes = [
            models.Index(fields=["accounting_period", "cost_scope"]),
            models.Index(fields=["batch", "cost_scope"]),
            models.Index(fields=["payment_status", "payment_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.worker_name} - {self.task_description}"

    def clean(self):
        super().clean()
        errors = {}
        if self.cost_scope == CostScope.BATCH_DIRECT and self.batch_id is None:
            errors["batch"] = "Batch is required for batch-direct labour."
        if (
            self.cost_scope == CostScope.SHARED_PRODUCTION
            and self.batch_id is not None
        ):
            errors["batch"] = (
                "Shared production labour should normally not be tied to one batch."
            )
        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "End date cannot be before start date."
        if errors:
            raise ValidationError(errors)


class SharedExpense(TimestampedModel):
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=120)
    expense_date = models.DateField(db_index=True)
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="shared_expenses",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    scope = models.CharField(
        max_length=40,
        choices=SharedExpenseScope.choices,
        db_index=True,
    )
    directly_assigned_batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="shared_expenses",
    )
    allocation_method = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
        default=AllocationMethod.NONE,
    )
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    payment_status = models.CharField(
        max_length=20,
        choices=FinancePaymentStatus.choices,
        default=FinancePaymentStatus.UNPAID,
        db_index=True,
    )
    supplier = models.CharField(max_length=160, blank=True, default="")
    reference_number = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_shared_expenses",
    )

    class Meta:
        ordering = ["-expense_date", "-created_at"]
        indexes = [
            models.Index(fields=["accounting_period", "scope"]),
            models.Index(fields=["directly_assigned_batch", "scope"]),
            models.Index(fields=["payment_status", "payment_date"]),
            models.Index(fields=["expense_date"]),
        ]

    def __str__(self) -> str:
        return self.description

    @property
    def is_capital_expenditure(self) -> bool:
        return self.scope == SharedExpenseScope.CAPITAL_EXPENDITURE

    def clean(self):
        super().clean()
        if (
            self.directly_assigned_batch_id
            and self.scope not in {
                SharedExpenseScope.SHARED_PRODUCTION,
                SharedExpenseScope.SELLING_EXPENSE,
            }
        ):
            raise ValidationError(
                {
                    "directly_assigned_batch": (
                        "Only production or selling expenses can be assigned to a batch."
                    )
                }
            )


class EmployeeBatchWorkLog(TimestampedModel):
    employee = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name="batch_work_logs",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="employee_work_logs",
    )
    work_date = models.DateField(db_index=True)
    hours_worked = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    task = models.CharField(max_length=255)
    notes = models.TextField(blank=True, default="")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_employee_batch_work_logs",
    )

    class Meta:
        ordering = ["-work_date", "employee"]
        indexes = [
            models.Index(fields=["employee", "work_date"]),
            models.Index(fields=["batch", "work_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.employee} worked {self.hours_worked}h on {self.batch}"


class BirdDaySnapshot(TimestampedModel):
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="bird_day_snapshots",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="bird_day_snapshots",
    )
    active_days = models.PositiveIntegerField(default=0)
    opening_live_birds = models.PositiveIntegerField(default=0)
    mortality = models.PositiveIntegerField(default=0)
    valid_bird_units_sold = models.PositiveIntegerField(default=0)
    closing_live_birds = models.PositiveIntegerField(default=0)
    bird_days = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MONEY_VALIDATOR],
    )
    calculation_version = models.CharField(max_length=40, default="bird-days-v1")
    calculated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["accounting_period", "batch"]
        constraints = [
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "calculation_version"],
                name="unique_bird_day_snapshot_period_batch_version",
            )
        ]
        indexes = [
            models.Index(fields=["accounting_period", "batch"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch} bird-days for {self.accounting_period}"


class CostAllocation(TimestampedModel):
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="cost_allocations",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="cost_allocations",
    )
    source_type = models.CharField(max_length=30, choices=AllocationSourceType.choices)
    payroll_entry = models.ForeignKey(
        PayrollEntry,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_allocations",
    )
    ad_hoc_labour_payment = models.ForeignKey(
        AdHocLabourPayment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_allocations",
    )
    shared_expense = models.ForeignKey(
        SharedExpense,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_allocations",
    )
    allocation_method = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
    )
    driver_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MONEY_VALIDATOR],
    )
    total_driver_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MONEY_VALIDATOR],
    )
    allocation_percentage = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[PERCENT_VALIDATOR],
    )
    allocated_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    calculation_version = models.CharField(max_length=40, default="allocation-v1")
    generated_at = models.DateTimeField(default=timezone.now)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_cost_allocations",
    )
    manual_reason = models.TextField(blank=True, default="")
    locked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["accounting_period", "batch", "source_type"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(payroll_entry__isnull=False)
                        & Q(ad_hoc_labour_payment__isnull=True)
                        & Q(shared_expense__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=False)
                        & Q(shared_expense__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=True)
                        & Q(shared_expense__isnull=False)
                    )
                ),
                name="cost_allocation_exactly_one_source",
            ),
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "payroll_entry"],
                condition=Q(payroll_entry__isnull=False),
                name="unique_payroll_allocation_period_batch",
            ),
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "ad_hoc_labour_payment"],
                condition=Q(ad_hoc_labour_payment__isnull=False),
                name="unique_labour_allocation_period_batch",
            ),
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "shared_expense"],
                condition=Q(shared_expense__isnull=False),
                name="unique_expense_allocation_period_batch",
            ),
        ]
        indexes = [
            models.Index(fields=["accounting_period", "batch"]),
            models.Index(fields=["source_type", "allocation_method"]),
            models.Index(fields=["locked"]),
        ]

    def __str__(self) -> str:
        return f"{self.allocated_amount} to {self.batch}"

    def clean(self):
        super().clean()
        source_count = sum(
            bool(value)
            for value in (
                self.payroll_entry_id,
                self.ad_hoc_labour_payment_id,
                self.shared_expense_id,
            )
        )
        if source_count != 1:
            raise ValidationError("Exactly one allocation source is required.")
        if self.allocation_method == AllocationMethod.MANUAL and not self.manual_reason:
            raise ValidationError(
                {"manual_reason": "Manual allocations require an audit reason."}
            )


class BatchProfitabilitySnapshot(TimestampedModel):
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="profitability_snapshots",
    )
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="batch_profitability_snapshots",
    )
    status = models.CharField(max_length=20)
    revenue = models.DecimalField(max_digits=14, decimal_places=2)
    cash_collected = models.DecimalField(max_digits=14, decimal_places=2)
    accounts_receivable = models.DecimalField(max_digits=14, decimal_places=2)
    direct_batch_cost = models.DecimalField(max_digits=14, decimal_places=2)
    allocated_production_cost = models.DecimalField(max_digits=14, decimal_places=2)
    total_production_cost = models.DecimalField(max_digits=14, decimal_places=2)
    batch_gross_profit = models.DecimalField(max_digits=14, decimal_places=2)
    fully_loaded_batch_profit = models.DecimalField(max_digits=14, decimal_places=2)
    valid_bird_units_sold = models.PositiveIntegerField(default=0)
    remaining_live_birds = models.PositiveIntegerField(default=0)
    final = models.BooleanField(default=False, db_index=True)
    calculation_version = models.CharField(max_length=40, default="profitability-v1")
    finalized_at = models.DateTimeField(null=True, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_profitability_snapshots",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch"],
                condition=Q(final=True),
                name="unique_final_profitability_snapshot_per_batch",
            )
        ]
        indexes = [
            models.Index(fields=["batch", "final"]),
            models.Index(fields=["accounting_period", "final"]),
        ]

    def __str__(self) -> str:
        label = "final" if self.final else "provisional"
        return f"{self.batch} {label} profitability"
