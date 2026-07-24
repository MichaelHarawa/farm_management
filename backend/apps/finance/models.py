from __future__ import annotations

import uuid
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
POSITIVE_DECIMAL_VALIDATOR = MinValueValidator(Decimal("0.000001"))


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DollarReferenceMixin(models.Model):
    usd_exchange_rate = models.DecimalField(
        max_digits=16,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[POSITIVE_DECIMAL_VALIDATOR],
        help_text="MWK per USD at entry time.",
    )
    usd_equivalent = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
        help_text="USD equivalent captured for future inflation reference.",
    )

    class Meta:
        abstract = True

    def set_usd_equivalent(self, mwk_amount: Decimal | int | None) -> None:
        if self.usd_exchange_rate and mwk_amount is not None:
            self.usd_equivalent = (
                Decimal(mwk_amount) / self.usd_exchange_rate
            ).quantize(Decimal("0.01"))


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


class ExpenseRecognitionType(models.TextChoices):
    OPERATING_EXPENSE = "operating_expense", "Operating expense"
    CAPITAL_EXPENDITURE = "capital_expenditure", "Capital expenditure"
    PREPAID_EXPENSE = "prepaid_expense", "Prepaid expense"
    SHARED_CONSUMABLE = "shared_consumable", "Shared consumable"
    FINANCE_COST = "finance_cost", "Finance cost"
    TAX = "tax", "Tax"
    OTHER = "other", "Other"


class AllocationMethod(models.TextChoices):
    DIRECT = "direct", "Direct"
    ACTUAL_HOURS = "actual_hours", "Actual hours"
    BIRD_DAYS = "bird_days", "Bird-days"
    BATCH_DAYS = "batch_days", "Batch-days"
    HOUSE_OCCUPANCY_DAYS = "house_occupancy_days", "House occupancy days"
    FLOOR_AREA_DAYS = "floor_area_days", "Floor-area days"
    EQUAL_SHARE = "equal_share", "Equal share"
    REVENUE_SHARE = "revenue_share", "Revenue share"
    SALES_QUANTITY = "sales_quantity", "Sales quantity"
    ACTUAL_QUANTITY = "actual_quantity", "Actual quantity"
    MANUAL_WITH_REASON = "manual_with_reason", "Manual with reason"
    MANUAL = "manual", "Manual"
    NONE = "none", "None"


class AllocationSourceType(models.TextChoices):
    PAYROLL = "payroll", "Payroll"
    AD_HOC_LABOUR = "ad_hoc_labour", "Ad-hoc labour"
    SHARED_EXPENSE = "shared_expense", "Shared expense"
    CONSUMABLE_USAGE = "consumable_usage", "Consumable usage"
    DEPRECIATION = "depreciation", "Depreciation"


class ConsumableUsageScope(models.TextChoices):
    BATCH_DIRECT = "batch_direct", "Batch direct"
    SHARED_PRODUCTION = "shared_production", "Shared production"
    ADMINISTRATION = "administration", "Administration"
    SELLING_AND_DISTRIBUTION = (
        "selling_and_distribution",
        "Selling and distribution",
    )


class RecognitionMethod(models.TextChoices):
    STRAIGHT_LINE = "straight_line", "Straight line"
    USAGE_BASED = "usage_based", "Usage based"
    MANUAL_SCHEDULE = "manual_schedule", "Manual schedule"


class AssetCategoryCode(models.TextChoices):
    POULTRY_HOUSE = "poultry_house", "Poultry house"
    FEEDING_EQUIPMENT = "feeding_equipment", "Feeding equipment"
    WATERING_EQUIPMENT = "watering_equipment", "Watering equipment"
    BROODING_EQUIPMENT = "brooding_equipment", "Brooding equipment"
    WATER_INFRASTRUCTURE = "water_infrastructure", "Water infrastructure"
    PROCESSING_EQUIPMENT = "processing_equipment", "Processing equipment"
    COLD_STORAGE = "cold_storage", "Cold storage"
    SOLAR_EQUIPMENT = "solar_equipment", "Solar equipment"
    VEHICLE = "vehicle", "Vehicle"
    OFFICE_EQUIPMENT = "office_equipment", "Office equipment"
    OTHER = "other", "Other"


class AssetStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    AVAILABLE_FOR_USE = "available_for_use", "Available for use"
    IDLE = "idle", "Idle"
    UNDER_MAINTENANCE = "under_maintenance", "Under maintenance"
    IMPAIRED = "impaired", "Impaired"
    DISPOSED = "disposed", "Disposed"
    RETIRED = "retired", "Retired"


class AssetProductionScope(models.TextChoices):
    POULTRY_PRODUCTION = "poultry_production", "Poultry production"
    SELLING_AND_DISTRIBUTION = (
        "selling_and_distribution",
        "Selling and distribution",
    )
    FARM_ADMINISTRATION = "farm_administration", "Farm administration"
    MIXED_USE = "mixed_use", "Mixed use"


class DepreciationMethod(models.TextChoices):
    STRAIGHT_LINE = "straight_line", "Straight line"
    UNITS_OF_PRODUCTION = "units_of_production", "Units of production"
    DECLINING_BALANCE = "declining_balance", "Declining balance"


class ReserveTransactionType(models.TextChoices):
    CONTRIBUTION = "contribution", "Contribution"
    WITHDRAWAL = "withdrawal", "Withdrawal"
    RETURN = "return", "Investment return"


class AccountingPeriod(TimestampedModel):
    period_start = models.DateField()
    period_end = models.DateField()
    year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    month = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
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
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reopened_accounting_periods",
    )
    reopening_reason = models.TextField(blank=True, default="")
    recalculation_version = models.PositiveIntegerField(default=1)
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
            models.CheckConstraint(
                condition=Q(month__isnull=True) | (Q(month__gte=1) & Q(month__lte=12)),
                name="accounting_period_valid_month",
            ),
        ]
        indexes = [
            models.Index(fields=["period_start", "period_end"]),
            models.Index(fields=["status", "period_start"]),
        ]

    def __str__(self) -> str:
        return f"{self.period_start:%Y-%m-%d} to {self.period_end:%Y-%m-%d}"

    def save(self, *args, **kwargs):
        if self.period_start:
            self.year = self.period_start.year
            self.month = self.period_start.month
        super().save(*args, **kwargs)


class EmployeeProfile(DollarReferenceMixin, TimestampedModel):
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

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.base_monthly_salary)
        super().save(*args, **kwargs)


class PayrollEntry(DollarReferenceMixin, TimestampedModel):
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
        self.set_usd_equivalent(self.total_employer_cost)
        super().save(*args, **kwargs)


class AdHocLabourPayment(DollarReferenceMixin, TimestampedModel):
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

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.payment_amount)
        super().save(*args, **kwargs)


class SharedExpense(DollarReferenceMixin, TimestampedModel):
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
    recognition_type = models.CharField(
        max_length=40,
        choices=ExpenseRecognitionType.choices,
        default=ExpenseRecognitionType.OPERATING_EXPENSE,
        db_index=True,
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
        return (
            self.scope == SharedExpenseScope.CAPITAL_EXPENDITURE
            or self.recognition_type == ExpenseRecognitionType.CAPITAL_EXPENDITURE
        )

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

        if self.scope == SharedExpenseScope.CAPITAL_EXPENDITURE:
            self.recognition_type = ExpenseRecognitionType.CAPITAL_EXPENDITURE
        elif self.scope == SharedExpenseScope.FINANCE_COST:
            self.recognition_type = ExpenseRecognitionType.FINANCE_COST
        elif self.scope == SharedExpenseScope.TAX:
            self.recognition_type = ExpenseRecognitionType.TAX

    def save(self, *args, **kwargs):
        if self.scope == SharedExpenseScope.CAPITAL_EXPENDITURE:
            self.recognition_type = ExpenseRecognitionType.CAPITAL_EXPENDITURE
        elif self.scope == SharedExpenseScope.FINANCE_COST:
            self.recognition_type = ExpenseRecognitionType.FINANCE_COST
        elif self.scope == SharedExpenseScope.TAX:
            self.recognition_type = ExpenseRecognitionType.TAX
        self.set_usd_equivalent(self.amount)
        super().save(*args, **kwargs)


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


class SharedConsumableLot(DollarReferenceMixin, TimestampedModel):
    item = models.CharField(max_length=160)
    category = models.CharField(max_length=120)
    purchase_date = models.DateField(db_index=True)
    supplier = models.CharField(max_length=160, blank=True, default="")
    invoice_reference = models.CharField(max_length=120, blank=True, default="")
    quantity_purchased = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    unit_of_measurement = models.CharField(max_length=40)
    total_purchase_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    unit_cost = models.DecimalField(
        max_digits=16,
        decimal_places=6,
        validators=[MONEY_VALIDATOR],
    )
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    storage_location = models.CharField(max_length=160, blank=True, default="")
    quantity_available = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MONEY_VALIDATOR],
    )
    payment_status = models.CharField(
        max_length=20,
        choices=FinancePaymentStatus.choices,
        default=FinancePaymentStatus.UNPAID,
        db_index=True,
    )
    payment_date = models.DateField(null=True, blank=True, db_index=True)
    linked_expense = models.OneToOneField(
        SharedExpense,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consumable_lot",
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_consumable_lots",
    )

    class Meta:
        ordering = ["item", "purchase_date"]
        indexes = [
            models.Index(fields=["category", "purchase_date"]),
            models.Index(fields=["expiry_date"]),
            models.Index(fields=["payment_status", "payment_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_purchased__gt=0),
                name="consumable_quantity_purchased_positive",
            ),
            models.CheckConstraint(
                condition=Q(quantity_available__gte=0),
                name="consumable_quantity_available_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total_purchase_cost__gte=0),
                name="consumable_purchase_cost_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.item} lot from {self.purchase_date:%Y-%m-%d}"

    @property
    def is_expired(self) -> bool:
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    def clean(self):
        super().clean()
        if self.quantity_available > self.quantity_purchased:
            raise ValidationError(
                {"quantity_available": "Available stock cannot exceed purchased stock."}
            )

    def save(self, *args, **kwargs):
        self.unit_cost = (
            self.total_purchase_cost / self.quantity_purchased
        ).quantize(Decimal("0.000001"))
        if self._state.adding and self.quantity_available == Decimal("0.0000"):
            self.quantity_available = self.quantity_purchased
        self.set_usd_equivalent(self.total_purchase_cost)
        super().save(*args, **kwargs)


class ConsumableUsage(TimestampedModel):
    consumable_lot = models.ForeignKey(
        SharedConsumableLot,
        on_delete=models.PROTECT,
        related_name="usages",
    )
    usage_date = models.DateField(db_index=True)
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="consumable_usages",
    )
    quantity_used = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consumable_usages",
    )
    poultry_house = models.CharField(max_length=120, blank=True, default="")
    usage_scope = models.CharField(
        max_length=40,
        choices=ConsumableUsageScope.choices,
        db_index=True,
    )
    allocation_driver = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
        default=AllocationMethod.NONE,
    )
    task_or_purpose = models.CharField(max_length=255)
    recognized_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_consumable_usages",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_consumable_usages",
    )
    notes = models.TextField(blank=True, default="")
    locked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-usage_date", "-created_at"]
        indexes = [
            models.Index(fields=["accounting_period", "usage_scope"]),
            models.Index(fields=["batch", "usage_scope"]),
            models.Index(fields=["locked"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_used__gt=0),
                name="consumable_usage_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(recognized_cost__gte=0),
                name="consumable_usage_cost_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity_used} {self.consumable_lot.unit_of_measurement} {self.consumable_lot.item}"

    def clean(self):
        super().clean()
        errors = {}
        if self.accounting_period.status == PeriodStatus.CLOSED:
            errors["accounting_period"] = "Closed accounting periods cannot be changed."
        if self.usage_scope == ConsumableUsageScope.BATCH_DIRECT and not self.batch_id:
            errors["batch"] = "Batch is required for direct consumable usage."
        if (
            self.usage_scope == ConsumableUsageScope.SHARED_PRODUCTION
            and self.batch_id
            and self.allocation_driver != AllocationMethod.DIRECT
        ):
            errors["batch"] = "Shared production usage should be allocated, not pinned to one batch."
        if self.quantity_used > self.consumable_lot.quantity_available and self._state.adding:
            errors["quantity_used"] = "Usage cannot exceed available stock."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.recognized_cost = (
            self.quantity_used * self.consumable_lot.unit_cost
        ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class ExpenseRecognitionSchedule(DollarReferenceMixin, TimestampedModel):
    source_expense = models.ForeignKey(
        SharedExpense,
        on_delete=models.PROTECT,
        related_name="recognition_schedules",
    )
    benefit_start_date = models.DateField()
    benefit_end_date = models.DateField()
    total_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    recognition_method = models.CharField(
        max_length=40,
        choices=RecognitionMethod.choices,
        default=RecognitionMethod.STRAIGHT_LINE,
    )
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="expense_recognition_schedules",
    )
    amount_recognized = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    remaining_deferred_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    generated_at = models.DateTimeField(default=timezone.now)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_expense_recognition_schedules",
    )
    locked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["accounting_period", "source_expense"]
        indexes = [
            models.Index(fields=["accounting_period", "locked"]),
            models.Index(fields=["source_expense", "accounting_period"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_expense", "accounting_period"],
                name="unique_expense_recognition_per_period",
            ),
            models.CheckConstraint(
                condition=Q(benefit_end_date__gte=models.F("benefit_start_date")),
                name="expense_recognition_benefit_end_after_start",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_expense} recognition for {self.accounting_period}"

    def clean(self):
        super().clean()
        if self.accounting_period.status == PeriodStatus.CLOSED and not self.locked:
            raise ValidationError(
                {"accounting_period": "Closed-period recognition entries must be locked."}
            )

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.amount_recognized)
        super().save(*args, **kwargs)


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
    consumable_usage = models.ForeignKey(
        ConsumableUsage,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_allocations",
    )
    depreciation_entry = models.ForeignKey(
        "AssetDepreciationEntry",
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
                        & Q(consumable_usage__isnull=True)
                        & Q(depreciation_entry__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=False)
                        & Q(shared_expense__isnull=True)
                        & Q(consumable_usage__isnull=True)
                        & Q(depreciation_entry__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=True)
                        & Q(shared_expense__isnull=False)
                        & Q(consumable_usage__isnull=True)
                        & Q(depreciation_entry__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=True)
                        & Q(shared_expense__isnull=True)
                        & Q(consumable_usage__isnull=False)
                        & Q(depreciation_entry__isnull=True)
                    )
                    | (
                        Q(payroll_entry__isnull=True)
                        & Q(ad_hoc_labour_payment__isnull=True)
                        & Q(shared_expense__isnull=True)
                        & Q(consumable_usage__isnull=True)
                        & Q(depreciation_entry__isnull=False)
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
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "consumable_usage"],
                condition=Q(consumable_usage__isnull=False),
                name="unique_consumable_allocation_period_batch",
            ),
            models.UniqueConstraint(
                fields=["accounting_period", "batch", "depreciation_entry"],
                condition=Q(depreciation_entry__isnull=False),
                name="unique_depreciation_allocation_period_batch",
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
                self.consumable_usage_id,
                self.depreciation_entry_id,
            )
        )
        if source_count != 1:
            raise ValidationError("Exactly one allocation source is required.")
        if (
            self.allocation_method
            in {AllocationMethod.MANUAL, AllocationMethod.MANUAL_WITH_REASON}
            and not self.manual_reason
        ):
            raise ValidationError(
                {"manual_reason": "Manual allocations require an audit reason."}
            )


class AssetCategory(TimestampedModel):
    name = models.CharField(max_length=120)
    code = models.CharField(
        max_length=40,
        choices=AssetCategoryCode.choices,
        unique=True,
    )
    default_useful_life_months = models.PositiveIntegerField()
    default_residual_value_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[PERCENT_VALIDATOR],
    )
    default_depreciation_method = models.CharField(
        max_length=40,
        choices=DepreciationMethod.choices,
        default=DepreciationMethod.STRAIGHT_LINE,
    )
    default_production_scope = models.CharField(
        max_length=40,
        choices=AssetProductionScope.choices,
        default=AssetProductionScope.POULTRY_PRODUCTION,
    )
    default_allocation_driver = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
        default=AllocationMethod.BIRD_DAYS,
    )
    capitalization_threshold = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    requires_serial_number = models.BooleanField(default=False)
    maintenance_interval_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(default_residual_value_percentage__gte=0)
                & Q(default_residual_value_percentage__lte=100),
                name="asset_category_residual_percentage_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Asset(DollarReferenceMixin, TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    asset_code = models.CharField(max_length=40, unique=True, db_index=True, blank=True)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    asset_category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        related_name="assets",
    )
    category_other = models.CharField(max_length=120, blank=True, default="")
    serial_number = models.CharField(max_length=120, blank=True, default="")
    manufacturer = models.CharField(max_length=120, blank=True, default="")
    model_number = models.CharField(max_length=120, blank=True, default="")
    supplier = models.CharField(max_length=160, blank=True, default="")
    invoice_reference = models.CharField(max_length=120, blank=True, default="")
    purchase_date = models.DateField(db_index=True)
    available_for_use_date = models.DateField(null=True, blank=True, db_index=True)
    purchase_price = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    delivery_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    installation_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    non_refundable_tax_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    other_capitalized_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    total_capitalized_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    residual_value = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    recognized_impairment_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    useful_life_months = models.PositiveIntegerField()
    depreciation_method = models.CharField(
        max_length=40,
        choices=DepreciationMethod.choices,
        default=DepreciationMethod.STRAIGHT_LINE,
    )
    depreciation_unit = models.CharField(max_length=40, blank=True, default="")
    estimated_total_lifetime_units = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
    )
    production_scope = models.CharField(
        max_length=40,
        choices=AssetProductionScope.choices,
        default=AssetProductionScope.POULTRY_PRODUCTION,
        db_index=True,
    )
    production_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[PERCENT_VALIDATOR],
    )
    administration_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[PERCENT_VALIDATOR],
    )
    selling_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[PERCENT_VALIDATOR],
    )
    default_allocation_driver = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
        default=AllocationMethod.BIRD_DAYS,
    )
    fallback_allocation_driver = models.CharField(
        max_length=40,
        choices=AllocationMethod.choices,
        default=AllocationMethod.EQUAL_SHARE,
    )
    location = models.CharField(max_length=160, blank=True, default="")
    custodian = models.CharField(max_length=160, blank=True, default="")
    condition = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(
        max_length=40,
        choices=AssetStatus.choices,
        default=AssetStatus.DRAFT,
        db_index=True,
    )
    warranty_expiry_date = models.DateField(null=True, blank=True)
    financing_type = models.CharField(max_length=80, blank=True, default="")
    disposal_date = models.DateField(null=True, blank=True)
    disposal_proceeds = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    disposal_gain_loss = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_assets",
    )

    class Meta:
        ordering = ["asset_code", "name"]
        indexes = [
            models.Index(fields=["status", "production_scope"]),
            models.Index(fields=["purchase_date", "available_for_use_date"]),
            models.Index(fields=["asset_category", "status"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_capitalized_cost__gt=0),
                name="asset_total_capitalized_cost_positive",
            ),
            models.CheckConstraint(
                condition=Q(residual_value__gte=0),
                name="asset_residual_value_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(residual_value__lte=models.F("total_capitalized_cost")),
                name="asset_residual_not_above_cost",
            ),
            models.CheckConstraint(
                condition=Q(production_percentage__gte=0)
                & Q(production_percentage__lte=100)
                & Q(administration_percentage__gte=0)
                & Q(administration_percentage__lte=100)
                & Q(selling_percentage__gte=0)
                & Q(selling_percentage__lte=100),
                name="asset_percentages_between_zero_and_hundred",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} - {self.name}"

    @property
    def depreciable_amount(self) -> Decimal:
        amount = (
            self.total_capitalized_cost
            - self.residual_value
            - self.recognized_impairment_amount
        )
        return max(amount, Decimal("0.00")).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        errors = {}
        if self.available_for_use_date and self.available_for_use_date < self.purchase_date:
            errors["available_for_use_date"] = (
                "Available-for-use date cannot be before purchase date."
            )
        if self.asset_category.requires_serial_number and not self.serial_number:
            errors["serial_number"] = "This asset category requires a serial number."
        if self.asset_category.code == AssetCategoryCode.OTHER and not self.category_other:
            errors["category_other"] = "Enter the manual category for Other assets."
        if (
            self.production_percentage
            + self.administration_percentage
            + self.selling_percentage
            != Decimal("100.00")
        ):
            errors["production_percentage"] = (
                "Production, administration, and selling percentages must total 100."
            )
        if (
            self.depreciation_method == DepreciationMethod.UNITS_OF_PRODUCTION
            and not self.estimated_total_lifetime_units
        ):
            errors["estimated_total_lifetime_units"] = (
                "Units-of-production depreciation requires estimated lifetime units."
            )
        if self.status == AssetStatus.DISPOSED and not self.disposal_date:
            errors["disposal_date"] = "Disposed assets require a disposal date."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.asset_code:
            self.asset_code = f"AST-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        self.total_capitalized_cost = (
            self.purchase_price
            + self.delivery_cost
            + self.installation_cost
            + self.non_refundable_tax_cost
            + self.other_capitalized_cost
        ).quantize(Decimal("0.01"))
        self.set_usd_equivalent(self.total_capitalized_cost)
        super().save(*args, **kwargs)


class AssetCapitalizedCost(DollarReferenceMixin, TimestampedModel):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="capitalized_cost_links",
    )
    expense = models.ForeignKey(
        SharedExpense,
        on_delete=models.PROTECT,
        related_name="capitalized_asset_links",
    )
    capitalized_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_asset_capitalized_costs",
    )

    class Meta:
        ordering = ["asset", "expense"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "expense"],
                name="unique_asset_capitalized_expense_link",
            ),
            models.CheckConstraint(
                condition=Q(capitalized_amount__gte=0),
                name="asset_capitalized_amount_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.expense} capitalized into {self.asset}"

    def clean(self):
        super().clean()
        if not self.expense.is_capital_expenditure:
            raise ValidationError(
                {"expense": "Only capital-expenditure expenses can be capitalized."}
            )

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.capitalized_amount)
        super().save(*args, **kwargs)


class AssetUsageRecord(TimestampedModel):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="usage_records",
    )
    usage_date = models.DateField(db_index=True)
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="asset_usage_records",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_usage_records",
    )
    usage_unit = models.CharField(max_length=40)
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    meter_opening = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
    )
    meter_closing = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
    )
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_asset_usage",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_asset_usage",
    )
    locked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-usage_date", "-created_at"]
        indexes = [
            models.Index(fields=["asset", "accounting_period"]),
            models.Index(fields=["batch", "usage_date"]),
            models.Index(fields=["locked"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="asset_usage_quantity_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset} {self.quantity} {self.usage_unit}"

    def clean(self):
        super().clean()
        errors = {}
        if self.accounting_period.status == PeriodStatus.CLOSED and not self.locked:
            errors["accounting_period"] = "Closed-period asset usage must be locked."
        if self.asset.status == AssetStatus.DISPOSED:
            errors["asset"] = "Disposed assets cannot receive usage records."
        if (
            self.meter_opening is not None
            and self.meter_closing is not None
            and self.meter_closing < self.meter_opening
        ):
            errors["meter_closing"] = "Meter closing cannot be below opening."
        if self.asset.disposal_date and self.usage_date > self.asset.disposal_date:
            errors["usage_date"] = "Usage cannot be recorded after disposal."
        if errors:
            raise ValidationError(errors)


class AssetDepreciationEntry(DollarReferenceMixin, TimestampedModel):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="depreciation_entries",
    )
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        related_name="asset_depreciation_entries",
    )
    opening_carrying_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    depreciation_method_snapshot = models.CharField(max_length=40)
    useful_life_snapshot = models.PositiveIntegerField()
    residual_value_snapshot = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    period_depreciation = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    impairment_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    closing_carrying_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    calculation_version = models.CharField(max_length=40, default="depreciation-v1")
    generated_at = models.DateTimeField(default=timezone.now)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_asset_depreciation_entries",
    )
    locked = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["accounting_period", "asset"]
        indexes = [
            models.Index(fields=["accounting_period", "locked"]),
            models.Index(fields=["asset", "accounting_period"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "accounting_period"],
                name="unique_asset_depreciation_entry_per_period",
            ),
            models.CheckConstraint(
                condition=Q(period_depreciation__gte=0),
                name="asset_period_depreciation_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset} depreciation for {self.accounting_period}"

    def clean(self):
        super().clean()
        if self.accounting_period.status == PeriodStatus.CLOSED and not self.locked:
            raise ValidationError(
                {"accounting_period": "Closed-period depreciation must be locked."}
            )

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.period_depreciation)
        super().save(*args, **kwargs)


class AssetMaintenanceRecord(DollarReferenceMixin, TimestampedModel):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    maintenance_date = models.DateField(db_index=True)
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_maintenance_records",
    )
    description = models.CharField(max_length=255)
    cost_amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    linked_expense = models.ForeignKey(
        SharedExpense,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_maintenance_records",
    )
    next_due_date = models.DateField(null=True, blank=True, db_index=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_asset_maintenance",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-maintenance_date", "-created_at"]
        indexes = [
            models.Index(fields=["asset", "maintenance_date"]),
            models.Index(fields=["next_due_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.asset} maintenance on {self.maintenance_date}"

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.cost_amount)
        super().save(*args, **kwargs)


class AssetReplacementPlan(DollarReferenceMixin, TimestampedModel):
    asset = models.OneToOneField(
        Asset,
        on_delete=models.PROTECT,
        related_name="replacement_plan",
    )
    current_replacement_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    annual_inflation_rate_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[PERCENT_VALIDATOR],
    )
    target_replacement_date = models.DateField()
    projected_future_replacement_cost = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    target_reserve_balance = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MONEY_VALIDATOR],
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_asset_replacement_plans",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["asset"]

    def __str__(self) -> str:
        return f"{self.asset} replacement plan"

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.projected_future_replacement_cost)
        super().save(*args, **kwargs)


class ReplacementReserveTransaction(DollarReferenceMixin, TimestampedModel):
    asset = models.ForeignKey(
        Asset,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reserve_transactions",
    )
    accounting_period = models.ForeignKey(
        AccountingPeriod,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replacement_reserve_transactions",
    )
    transaction_date = models.DateField(db_index=True)
    transaction_type = models.CharField(
        max_length=40,
        choices=ReserveTransactionType.choices,
        db_index=True,
    )
    amount = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorized_replacement_reserve_transactions",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-transaction_date", "-created_at"]
        indexes = [
            models.Index(fields=["asset", "transaction_date"]),
            models.Index(fields=["transaction_type", "transaction_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="replacement_reserve_amount_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_type} {self.amount}"

    def save(self, *args, **kwargs):
        self.set_usd_equivalent(self.amount)
        super().save(*args, **kwargs)


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
