from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import Role, RoleChoices
from apps.accounts.serializers import RoleSummarySerializer
from apps.poultry.models import BatchStatus

from .models import (
    AccountingPeriod,
    AdHocLabourPayment,
    AllocationMethod,
    Asset,
    AssetCapitalizedCost,
    AssetCategory,
    AssetDepreciationEntry,
    AssetMaintenanceRecord,
    AssetReplacementPlan,
    AssetStatus,
    AssetUsageRecord,
    BatchProfitabilitySnapshot,
    BirdDaySnapshot,
    ConsumableUsage,
    ConsumableItem,
    ConsumableUsageScope,
    CostScope,
    CostAllocation,
    EmployeeBatchWorkLog,
    EmployeeProfile,
    EmployeeSalaryAdjustment,
    ExpenseRecognitionSchedule,
    ExpenditureStatus,
    FundingAllocation,
    PayrollEntry,
    PayrollPayment,
    PayrollPaymentFunding,
    PeriodStatus,
    ReplacementReserveTransaction,
    SharedExpense,
    SharedExpenseScope,
    SharedConsumableLot,
    StockMovement,
    InventoryLocation,
    AssetLifecycleEvent,
)



User = get_user_model()


class UserSummarySerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    roles = RoleSummarySerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_active",
            "roles",
        )

    def get_full_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class EmployeeProfileSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    display_name = serializers.SerializerMethodField()
    user_id = serializers.PrimaryKeyRelatedField(
        source="user",
        queryset=User.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    username = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(write_only=True, required=False)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    role_slugs = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = EmployeeProfile
        fields = (
            "id",
            "user",
            "user_id",
            "display_name",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "role_slugs",
            "employee_number",
            "employment_type",
            "job_title",
            "department",
            "employment_start_date",
            "employment_end_date",
            "base_monthly_salary",
            "usd_exchange_rate",
            "usd_equivalent",
            "standard_working_hours_per_day",
            "standard_working_days_per_week",
            "production_percentage",
            "administration_percentage",
            "selling_percentage",
            "is_active",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "display_name", "created_by", "created_at", "updated_at")

    def get_display_name(self, obj):
        name = f"{obj.first_name} {obj.last_name}".strip()
        if name:
            return name
        return obj.user.get_full_name() or obj.user.username if obj.user else obj.employee_number

    def validate(self, attrs):
        if self.instance and "password" in attrs:
            raise serializers.ValidationError(
                {"password": "Password can only be supplied during account creation."}
            )

        proposed_salary = attrs.get("base_monthly_salary")
        if (
            self.instance
            and proposed_salary is not None
            and proposed_salary != self.instance.base_monthly_salary
        ):
            raise serializers.ValidationError(
                {
                    "base_monthly_salary": (
                        "Use Adjust salary on the Payroll page so the change "
                        "is dated and retained in salary history."
                    )
                }
            )

        account_values = [attrs.get(field) for field in ("username", "email", "password")]
        if not self.instance and any(account_values) and not all(account_values):
            raise serializers.ValidationError(
                {"username": "Username, email, and password are all required when creating login access."}
            )
        if not self.instance and attrs.get("user") and any(account_values):
            raise serializers.ValidationError(
                {"user_id": "Choose an existing system user or enter new login details, not both."}
            )

        production = attrs.get(
            "production_percentage",
            getattr(self.instance, "production_percentage", Decimal("0.00")),
        )
        administration = attrs.get(
            "administration_percentage",
            getattr(self.instance, "administration_percentage", Decimal("0.00")),
        )
        selling = attrs.get(
            "selling_percentage",
            getattr(self.instance, "selling_percentage", Decimal("0.00")),
        )
        if production + administration + selling != Decimal("100.00"):
            raise serializers.ValidationError(
                {
                    "production_percentage": (
                        "Production, administration, and selling percentages "
                        "must total 100."
                    )
                }
            )

        role_slugs = attrs.get("role_slugs")
        if role_slugs:
            valid_role_slugs = {choice.value for choice in RoleChoices}
            invalid = sorted(set(role_slugs) - valid_role_slugs)
            if invalid:
                raise serializers.ValidationError(
                    {"role_slugs": f"Unknown role(s): {', '.join(invalid)}"}
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        role_slugs = validated_data.pop("role_slugs", [])
        user = validated_data.pop("user", None)
        username = validated_data.pop("username", "")
        email = validated_data.pop("email", "")
        password = validated_data.pop("password", "")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        if username:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
            )
            if role_slugs:
                user.roles.set(resolve_roles(role_slugs))

        profile = EmployeeProfile.objects.create(
            user=user, first_name=first_name, last_name=last_name, **validated_data
        )
        profile.full_clean()
        return profile

    @transaction.atomic
    def update(self, instance, validated_data):
        role_slugs = validated_data.pop("role_slugs", None)
        if "user" in validated_data:
            instance.user = validated_data.pop("user")
        identity_fields = {
            key: validated_data.pop(key)
            for key in ("username", "email", "first_name", "last_name")
            if key in validated_data
        }
        login_fields = {key: value for key, value in identity_fields.items() if key in {"username", "email"}}
        if login_fields and instance.user_id is None:
            raise serializers.ValidationError(
                {"user": "Link a system user from Administration before editing login details."}
            )
        for key in ("first_name", "last_name"):
            if key in identity_fields:
                setattr(instance, key, identity_fields[key])
        if instance.user_id:
            for key, value in identity_fields.items():
                setattr(instance.user, key, value)
            if identity_fields:
                instance.user.save(update_fields=[*identity_fields.keys(), "updated_at"])
        if role_slugs is not None and instance.user_id:
            instance.user.roles.set(resolve_roles(role_slugs))

        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.full_clean()
        instance.save()
        return instance


def resolve_roles(role_slugs: list[str]) -> list[Role]:
    role_labels = {choice.value: choice.label for choice in RoleChoices}
    roles = []
    for slug in role_slugs:
        role, _ = Role.objects.get_or_create(
            slug=slug,
            defaults={
                "name": role_labels.get(slug, slug.replace("_", " ").title()),
                "is_system": True,
            },
        )
        roles.append(role)
    return roles


class AccountingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingPeriod
        fields = "__all__"
        read_only_fields = ("closed_at", "closed_by", "created_at", "updated_at")


class EmployeeSalaryAdjustmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    effective_period_label = serializers.SerializerMethodField()
    change_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    change_type = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = EmployeeSalaryAdjustment
        fields = (
            "id",
            "employee",
            "employee_name",
            "effective_period",
            "effective_period_label",
            "previous_salary",
            "new_salary",
            "change_amount",
            "change_type",
            "reason",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "previous_salary",
            "created_by",
            "created_at",
            "updated_at",
        )

    def get_employee_name(self, obj):
        name = f"{obj.employee.first_name} {obj.employee.last_name}".strip()
        if name:
            return name
        if obj.employee.user_id:
            return obj.employee.user.get_full_name() or obj.employee.user.username
        return obj.employee.employee_number

    def get_effective_period_label(self, obj):
        period = obj.effective_period
        return f"{period.period_start:%d %b %Y} to {period.period_end:%d %b %Y}"

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Explain why the salary is changing.")
        return value

    def create(self, validated_data):
        from .services.payroll import record_salary_adjustment

        request = self.context.get("request")
        try:
            return record_salary_adjustment(
                **validated_data,
                created_by=request.user if request else None,
            )
        except ValueError as error:
            raise serializers.ValidationError({"detail": str(error)}) from error


class PayrollEntrySerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.user", read_only=True)
    production_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    administration_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    selling_amount = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    net_salary_payable = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    outstanding_salary = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    payments = serializers.SerializerMethodField()

    class Meta:
        model = PayrollEntry
        fields = "__all__"
        read_only_fields = (
            "total_employer_cost",
            "payment_status",
            "payment_date",
            "expenditure",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        gross = attrs.get("gross_salary", getattr(self.instance, "gross_salary", Decimal("0")))
        deductions = attrs.get("deductions", getattr(self.instance, "deductions", Decimal("0")))
        if deductions > gross:
            raise serializers.ValidationError({"deductions": "Deductions cannot exceed gross salary."})
        if self.instance and self.instance.payments.filter(status="posted").exists():
            protected = {"gross_salary", "deductions", "employer_costs", "accounting_period", "employee"}
            if protected.intersection(attrs):
                raise serializers.ValidationError(
                    {"detail": "Posted payroll payments make salary amounts immutable; reverse the payment first."}
                )
        return attrs

    def get_payments(self, obj):
        return PayrollPaymentSerializer(obj.payments.all(), many=True).data


class AdHocLabourPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdHocLabourPayment
        fields = "__all__"
        read_only_fields = (
            "created_by", "payment_status", "payment_date", "workflow_status", "expenditure", "approved_at", "approved_by",
            "posted_at", "reversed_at", "reversed_by", "reversal_reason", "created_at", "updated_at"
        )

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        cost_scope = attrs.get(
            "cost_scope",
            getattr(self.instance, "cost_scope", None),
        )
        batch = attrs.get("batch", getattr(self.instance, "batch", None))
        ensure_batch_not_finalized(batch, "batch", period)
        if cost_scope == CostScope.BATCH_DIRECT and batch is None:
            raise serializers.ValidationError(
                {"batch": "Batch is required for batch-direct labour."}
            )
        if cost_scope in {
            CostScope.SHARED_PRODUCTION,
            CostScope.FARM_ADMINISTRATION,
        } and batch is not None:
            raise serializers.ValidationError(
                {"batch": "This labour scope cannot be assigned to one batch."}
            )
        return attrs


class SharedExpenseSerializer(serializers.ModelSerializer):
    is_capital_expenditure = serializers.BooleanField(read_only=True)

    class Meta:
        model = SharedExpense
        fields = "__all__"
        read_only_fields = ("expenditure", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        scope = attrs.get("scope", getattr(self.instance, "scope", None))
        assigned_batch = attrs.get(
            "directly_assigned_batch",
            getattr(self.instance, "directly_assigned_batch", None),
        )
        ensure_batch_not_finalized(
            assigned_batch,
            "directly_assigned_batch",
            period,
        )
        if assigned_batch is not None and scope not in {
            SharedExpenseScope.SHARED_PRODUCTION,
            SharedExpenseScope.SELLING_EXPENSE,
        }:
            raise serializers.ValidationError(
                {
                    "directly_assigned_batch": (
                        "Only production or selling expenses can be assigned to a batch."
                    )
                }
            )
        if assigned_batch is not None:
            attrs["allocation_method"] = AllocationMethod.DIRECT
        return attrs


class SharedConsumableLotSerializer(serializers.ModelSerializer):
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = SharedConsumableLot
        fields = "__all__"
        read_only_fields = (
            "unit_cost",
            "quantity_available",
            "usd_equivalent",
            "created_by",
            "created_at",
            "updated_at",
        )


class ConsumableUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsumableUsage
        fields = "__all__"
        read_only_fields = (
            "recognized_cost",
            "recorded_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        usage_scope = attrs.get(
            "usage_scope",
            getattr(self.instance, "usage_scope", None),
        )
        batch = attrs.get("batch", getattr(self.instance, "batch", None))
        ensure_batch_not_finalized(batch, "batch", period)
        allocation_driver = attrs.get(
            "allocation_driver",
            getattr(self.instance, "allocation_driver", AllocationMethod.NONE),
        )
        if usage_scope == ConsumableUsageScope.BATCH_DIRECT and batch is None:
            raise serializers.ValidationError(
                {"batch": "Batch is required for direct consumable usage."}
            )
        if usage_scope in {
            ConsumableUsageScope.SHARED_PRODUCTION,
            ConsumableUsageScope.ADMINISTRATION,
        } and batch is not None:
            raise serializers.ValidationError(
                {"batch": "This usage scope cannot be assigned to one batch."}
            )
        if (
            batch is not None
            and usage_scope
            in {
                ConsumableUsageScope.BATCH_DIRECT,
                ConsumableUsageScope.SELLING_AND_DISTRIBUTION,
            }
            and allocation_driver != AllocationMethod.DIRECT
        ):
            raise serializers.ValidationError(
                {"allocation_driver": "Batch-assigned usage must use direct allocation."}
            )
        return attrs


class ConsumableItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsumableItem
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


class InventoryLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryLocation
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


class StockMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    batch_code = serializers.CharField(source="batch.batch_id", read_only=True)

    class Meta:
        model = StockMovement
        fields = "__all__"
        read_only_fields = (
            "total_cost", "item_name", "batch_code", "created_by", "created_at", "updated_at"
        )


class ExpenseRecognitionScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseRecognitionSchedule
        fields = "__all__"
        read_only_fields = (
            "usd_equivalent",
            "generated_at",
            "generated_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        return attrs


class PayrollPaymentFundingSerializer(serializers.ModelSerializer):
    funding_source_name = serializers.CharField(source="funding_source.__str__", read_only=True)

    class Meta:
        model = PayrollPaymentFunding
        fields = ("id", "funding_source", "funding_source_name", "amount")


class PayrollPaymentSerializer(serializers.ModelSerializer):
    funding_allocations = PayrollPaymentFundingSerializer(many=True, read_only=True)
    posted_by_name = serializers.CharField(
        source="posted_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = PayrollPayment
        fields = "__all__"


class EmployeeBatchWorkLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeBatchWorkLog
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


class BirdDaySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = BirdDaySnapshot
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


class CostAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostAllocation
        fields = "__all__"
        read_only_fields = ("generated_at", "generated_by", "created_at", "updated_at")


class AssetCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCategory
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = "__all__"
        read_only_fields = (
            "asset_code",
            "total_capitalized_cost",
            "usd_equivalent",
            "disposal_gain_loss",
            "created_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance and self.instance.depreciation_entries.exists():
            protected = {
                "purchase_price", "delivery_cost", "installation_cost", "non_refundable_tax_cost",
                "other_capitalized_cost", "residual_value", "useful_life_months", "depreciation_method",
                "available_for_use_date", "estimated_total_lifetime_units",
            }
            changed = [field for field in protected.intersection(attrs) if attrs[field] != getattr(self.instance, field)]
            if changed:
                raise serializers.ValidationError({
                    "detail": "Depreciation exists. Use a prospective estimate-change or controlled adjustment.",
                    "protected_fields": changed,
                })
        return attrs


class AssetLifecycleEventSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.get_username", read_only=True)

    class Meta:
        model = AssetLifecycleEvent
        fields = "__all__"
        read_only_fields = ("created_by", "created_by_name", "created_at", "updated_at")


class AssetCapitalizedCostSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetCapitalizedCost
        fields = "__all__"
        read_only_fields = (
            "usd_equivalent",
            "created_by",
            "created_at",
            "updated_at",
        )


class AssetUsageRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetUsageRecord
        fields = "__all__"
        read_only_fields = ("recorded_by", "created_at", "updated_at")

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        return attrs


class AssetDepreciationEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetDepreciationEntry
        fields = "__all__"
        read_only_fields = (
            "opening_carrying_amount",
            "depreciation_method_snapshot",
            "useful_life_snapshot",
            "residual_value_snapshot",
            "period_depreciation",
            "closing_carrying_amount",
            "usd_equivalent",
            "generated_at",
            "generated_by",
            "created_at",
            "updated_at",
        )


class AssetMaintenanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetMaintenanceRecord
        fields = "__all__"
        read_only_fields = ("usd_equivalent", "recorded_by", "created_at", "updated_at")


class AssetReplacementPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetReplacementPlan
        fields = "__all__"
        read_only_fields = ("usd_equivalent", "updated_by", "created_at", "updated_at")


class ReplacementReserveTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReplacementReserveTransaction
        fields = "__all__"
        read_only_fields = (
            "usd_equivalent",
            "authorized_by",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        period = attrs.get("accounting_period", getattr(self.instance, "accounting_period", None))
        ensure_period_open(period)
        return attrs


class BatchProfitabilitySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = BatchProfitabilitySnapshot
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")


def ensure_period_open(period):
    if period and period.status == PeriodStatus.CLOSED:
        raise serializers.ValidationError(
            {"accounting_period": "Closed accounting periods cannot be changed."}
        )


def ensure_batch_not_finalized(batch, field_name, period=None):
    if batch and batch.status == BatchStatus.CLOSED:
        correction_window_is_open = (
            period is not None
            and period.status == PeriodStatus.OPEN
            and batch.profitability_finalized_at is None
            and not batch.profitability_snapshots.filter(final=True).exists()
        )
        if correction_window_is_open:
            return
        raise serializers.ValidationError(
            {
                field_name: (
                    "This closed batch is finalized. Reopen its accounting period "
                    "before posting a controlled cost correction."
                )
            }
        )


# =============================================================================
# New serializers for Expenditure + Funding tracking
# =============================================================================

from .models import (
    Expenditure,
    ExpenditureCategory,
    FinanceActionEvent,
    FundingSource,
    FundingAllocation,
    FundingReceipt,
    FundingClassification,
    FundingSourceType,
    OwnerContributor,
    OwnerReceiptDesignation,
    SalePayment,
    AccountingNature,
    Customer,
    CustomerContributionLabel,
    CustomerCostAttribution,
    CustomerCostCategory,
    CustomerCostEvidenceStatus,
    CustomerCostSourceType,
)
from .permissions import has_owner_capital_access


class OwnerContributorSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = OwnerContributor
        fields = [
            "id", "public_id", "display_name", "notes", "is_active",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "public_id", "created_by", "created_by_name", "created_at", "updated_at",
        ]


class CustomerSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = Customer
        fields = [
            "id", "public_id", "display_name", "customer_type", "contact_name",
            "phone", "email", "notes", "is_active", "contribution_label",
            "review_notes", "reviewed_at", "reviewed_by", "reviewed_by_name",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "public_id", "contribution_label", "review_notes", "reviewed_at",
            "reviewed_by", "reviewed_by_name", "created_by", "created_by_name",
            "created_at", "updated_at",
        ]

    def validate_display_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("Enter at least 2 characters.")
        return value


class CustomerCostAttributionSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    sale_reference = serializers.CharField(source="sale.sale_id", read_only=True, allow_null=True)
    batch_code = serializers.CharField(source="batch.batch_id", read_only=True, allow_null=True)
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = CustomerCostAttribution
        fields = [
            "id", "customer", "customer_name", "sale", "sale_reference", "batch",
            "batch_code", "attribution_date", "accounting_period", "category", "amount",
            "source_type", "source_id", "economic_source_key", "source_label",
            "evidence_status", "attribution_basis", "reason", "status", "created_by",
            "created_by_name", "created_at", "reversed_at", "reversed_by",
            "reversed_by_name", "reversal_reason",
        ]
        read_only_fields = fields


class CustomerCostAttributionCommandSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True))
    sale_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    batch_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    attribution_date = serializers.DateField()
    category = serializers.ChoiceField(choices=CustomerCostCategory.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    source_type = serializers.ChoiceField(choices=CustomerCostSourceType.choices)
    source_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    evidence_status = serializers.ChoiceField(choices=CustomerCostEvidenceStatus.choices)
    attribution_basis = serializers.CharField(max_length=160)
    reason = serializers.CharField()
    idempotency_key = serializers.CharField(max_length=120)

    def validate_reason(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Document why this customer bears the cost.")
        return value


class CustomerReviewSerializer(serializers.Serializer):
    contribution_label = serializers.ChoiceField(choices=CustomerContributionLabel.choices)
    review_notes = serializers.CharField()

    def validate(self, attrs):
        notes = attrs["review_notes"].strip()
        if len(notes) < 3:
            raise serializers.ValidationError({"review_notes": "Record the review decision or next action."})
        attrs["review_notes"] = notes
        return attrs


class CustomerSaleLinkSerializer(serializers.Serializer):
    customer_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CustomerCostAttributionReverseSerializer(serializers.Serializer):
    reason = serializers.CharField()


class OwnerReceiptDesignationSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(
        source="receipt.funding_source.owner_id", read_only=True, allow_null=True
    )
    owner_name = serializers.CharField(
        source="receipt.funding_source.owner.display_name", read_only=True, allow_null=True
    )
    batch_code = serializers.CharField(source="batch.batch_id", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = OwnerReceiptDesignation
        fields = [
            "id", "receipt", "owner_id", "owner_name", "batch", "batch_code",
            "amount", "designation_date", "notes", "status", "created_by",
            "created_by_name", "created_at", "reversed_at", "reversed_by",
            "reversed_by_name", "reversal_reason",
        ]
        read_only_fields = fields


class FinanceActionEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.get_username", read_only=True)

    class Meta:
        model = FinanceActionEvent
        fields = [
            "id", "actor", "actor_name", "action", "entity_type", "entity_id",
            "before_data", "after_data", "reason", "created_at",
        ]
        read_only_fields = fields


class OwnerContributionCommandSerializer(serializers.Serializer):
    owner = serializers.PrimaryKeyRelatedField(
        queryset=OwnerContributor.objects.filter(is_active=True)
    )
    funding_source = serializers.PrimaryKeyRelatedField(
        queryset=FundingSource.objects.filter(
            source_type=FundingSourceType.OWNER_CAPITAL,
            is_active=True,
        ),
        required=False,
        allow_null=True,
    )
    source_description = serializers.CharField(required=False, allow_blank=True, default="")
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    receipt_date = serializers.DateField()
    reference = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.CharField(max_length=120)
    designation_date = serializers.DateField(required=False)
    designations = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )

    def validate(self, attrs):
        source = attrs.get("funding_source")
        owner = attrs["owner"]
        if source and source.owner_id != owner.pk:
            raise serializers.ValidationError(
                {"funding_source": "The selected source belongs to a different owner."}
            )
        return attrs


class OwnerDesignationCommandSerializer(serializers.Serializer):
    designation_date = serializers.DateField()
    designations = serializers.ListField(child=serializers.DictField(), allow_empty=False)


class FundingSourceSerializer(serializers.ModelSerializer):
    available_balance = serializers.SerializerMethodField()
    display_name = serializers.CharField(source="__str__", read_only=True)
    batch_code = serializers.CharField(source="batch.batch_id", read_only=True, allow_null=True)
    owner_public_id = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()

    class Meta:
        model = FundingSource
        fields = [
            "id", "source_type", "batch", "owner", "owner_public_id", "owner_name",
            "description", "notes", "is_active", "created_at", "updated_at",
            "available_balance", "display_name", "batch_code",
        ]
        read_only_fields = ["created_at", "updated_at", "available_balance"]

    def get_available_balance(self, obj):
        available_balances = self.context.get("available_balances")
        if available_balances is not None and obj.pk in available_balances:
            return str(available_balances[obj.pk])
        from .services.profitability import available_funding_source_cash
        return str(available_funding_source_cash(obj))

    def _may_view_owner(self):
        request = self.context.get("request")
        return has_owner_capital_access(getattr(request, "user", None))

    def get_owner_public_id(self, obj):
        return str(obj.owner.public_id) if obj.owner_id and self._may_view_owner() else None

    def get_owner_name(self, obj):
        return obj.owner.display_name if obj.owner_id and self._may_view_owner() else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._may_view_owner():
            data["owner"] = None
        return data

    def validate(self, attrs):
        source_type = attrs.get("source_type", getattr(self.instance, "source_type", None))
        batch = attrs.get("batch", getattr(self.instance, "batch", None))
        owner = attrs.get("owner", getattr(self.instance, "owner", None))
        if self.instance is None and source_type == "batch_collection":
            raise serializers.ValidationError(
                {"source_type": "Batch collection sources are created automatically from posted sale payments."}
            )
        if source_type != "batch_collection" and batch is not None:
            raise serializers.ValidationError(
                {"batch": "Only batch collection sources can reference a poultry batch."}
            )
        if owner is not None and source_type != FundingSourceType.OWNER_CAPITAL:
            raise serializers.ValidationError(
                {"owner": "Only owner-capital sources can reference an owner."}
            )
        if source_type == FundingSourceType.OWNER_CAPITAL and owner is not None and not owner.is_active:
            raise serializers.ValidationError({"owner": "Select an active owner."})
        if self.instance is None and source_type == FundingSourceType.OWNER_CAPITAL and owner is None:
            raise serializers.ValidationError(
                {"owner": "New owner-capital sources require a named owner."}
            )
        return attrs


class FundingReceiptSerializer(serializers.ModelSerializer):
    source_type = serializers.CharField(source="funding_source.source_type", read_only=True)
    source_display = serializers.CharField(source="funding_source.__str__", read_only=True)
    owner_id = serializers.SerializerMethodField()
    owner_name = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = FundingReceipt
        fields = [
            "id", "funding_source", "source_type", "source_display", "owner_id",
            "owner_name", "amount", "receipt_date", "reference", "notes", "status",
            "created_by", "created_by_name", "created_at", "reversed_at",
            "reversed_by", "reversed_by_name", "reversal_reason", "idempotency_key",
        ]
        read_only_fields = [
            "status", "created_by", "created_at", "reversed_at", "reversed_by",
            "reversal_reason", "idempotency_key",
        ]

    def _owner(self, obj):
        request = self.context.get("request")
        if not has_owner_capital_access(getattr(request, "user", None)):
            return None
        return obj.funding_source.owner

    def get_owner_id(self, obj):
        owner = self._owner(obj)
        return owner.pk if owner else None

    def get_owner_name(self, obj):
        owner = self._owner(obj)
        return owner.display_name if owner else None


class ExpenditureSerializer(serializers.ModelSerializer):
    funding_allocations = serializers.SerializerMethodField(read_only=True)
    total_funded = serializers.SerializerMethodField(read_only=True)
    funding_allocations_input = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
        )
    cost_allocations_input = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
    )
    category_detail = serializers.SerializerMethodField(read_only=True)
    funding_status = serializers.SerializerMethodField(read_only=True)
    amount_paid = serializers.SerializerMethodField(read_only=True)
    balance_due = serializers.SerializerMethodField(read_only=True)
    beneficiary_batches = serializers.SerializerMethodField(read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    posted_by_name = serializers.CharField(
        source="posted_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = Expenditure
        fields = [
            "id",
            "expenditure_date",
            "accounting_period",
            "amount",
            "category",
            "category_detail",
            "other_category_detail",
            "accounting_nature",
            "other_nature_detail",
            "description",
            "payee",
            "payment_method",
            "reference_number",
            "external_reference",
            "expenditure_reference",
            "status",
            "payment_status",
            "origin",
            "idempotency_key",
            "farm_module",
            "beneficiary_type",
            "beneficiary_detail",
            "cost_allocation_plan",
            "notes",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
            "posted_by",
            "posted_by_name",
            "posted_at",
            "reversed_at",
            "reversed_by",
            "reversed_by_name",
            "reversal_reason",
            "funding_allocations",
            "total_funded",
            "funding_status",
            "amount_paid",
            "balance_due",
            "beneficiary_batches",
            "funding_allocations_input",
            "cost_allocations_input",
        ]
        read_only_fields = [
            "created_at", "updated_at", "created_by", "posted_by", "posted_at",
            "reversed_at", "reversed_by", "reversal_reason",
            "funding_allocations", "total_funded", "category_detail",
            "funding_status", "cost_allocation_plan",
            "payment_status", "amount_paid", "balance_due", "beneficiary_batches",
        ]

    def get_funding_allocations(self, obj):
        return FundingAllocationSerializer(
            obj.funding_allocations.all(), many=True
        ).data

    def get_total_funded(self, obj):
        total = obj.funding_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return str(total)

    def get_funding_status(self, obj):
        total = obj.funding_allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        if obj.status == ExpenditureStatus.VOID:
            return "reversed"
        if Decimal(total) == obj.amount:
            return "funded"
        if Decimal(total) > Decimal("0.00"):
            return "partially_funded"
        return "unfunded"

    def get_amount_paid(self, obj):
        return self.get_total_funded(obj)

    def get_balance_due(self, obj):
        return str(max(obj.amount - Decimal(self.get_total_funded(obj)), Decimal("0.00")))

    def get_beneficiary_batches(self, obj):
        return [
            {
                "id": allocation.batch_id,
                "batch_id": allocation.batch.batch_id,
                "amount": str(allocation.allocated_amount),
            }
            for allocation in obj.cost_allocations.select_related("batch").all()
        ]

    def get_category_detail(self, obj):
        if obj.category:
            return {
                "id": obj.category.id,
                "name": obj.category.name,
                "code": obj.category.code,
                "default_accounting_nature": obj.category.default_accounting_nature,
                "requires_item_details": obj.category.requires_item_details,
                "requires_batch_beneficiary": obj.category.requires_batch_beneficiary,
            }
        return None

    def validate(self, attrs):
        if self.instance is None and attrs.get("status", ExpenditureStatus.DRAFT) != ExpenditureStatus.DRAFT:
            raise serializers.ValidationError({"status": "Create the expenditure as a draft, then post it with full funding."})
        category = attrs.get("category") or (self.instance.category if self.instance else None)
        accounting_nature = attrs.get("accounting_nature")

        # Auto populate accounting nature from category default if not explicitly set to something else
        if category and hasattr(category, "default_accounting_nature"):
            if not accounting_nature or accounting_nature == AccountingNature.OTHER:
                attrs["accounting_nature"] = category.default_accounting_nature or AccountingNature.OTHER

        if category and getattr(category, "name", "").lower() == "other":
            if not attrs.get("other_category_detail") and self.instance and self.instance.status == "posted":
                raise serializers.ValidationError({"other_category_detail": "Details required when category is Other."})

        if attrs.get("accounting_nature") == AccountingNature.OTHER:
            if not attrs.get("other_nature_detail") and self.instance and self.instance.status == "posted":
                raise serializers.ValidationError(
                    {"other_nature_detail": "Details required when nature is Other."}
                )
        owner_only = {
            FundingClassification.OWNER_CAPITAL_RETURN,
            FundingClassification.OWNER_DRAWING,
            FundingClassification.OWNER_COMPENSATION,
            FundingClassification.OWNER_DISTRIBUTION,
        }
        funding_rows = attrs.get("funding_allocations_input") or []
        request = self.context.get("request")
        all_source_ids = [row.get("funding_source") for row in funding_rows]
        uses_owner_cash = FundingSource.objects.filter(
            pk__in=all_source_ids,
            source_type=FundingSourceType.OWNER_CAPITAL,
        ).exists()
        if uses_owner_cash and not has_owner_capital_access(
            getattr(request, "user", None)
        ):
            raise serializers.ValidationError(
                {"funding_allocations_input": "Only administrators and directors can assign owner-capital cash."}
            )
        if any(row.get("classification") in owner_only for row in funding_rows):
            if not has_owner_capital_access(getattr(request, "user", None)):
                raise serializers.ValidationError(
                    {"funding_allocations_input": "Only administrators and directors can classify owner payments."}
                )
            source_ids = [
                row.get("funding_source")
                for row in funding_rows
                if row.get("classification") in owner_only
            ]
            non_owner_sources = FundingSource.objects.filter(
                pk__in=source_ids,
            ).exclude(source_type=FundingSourceType.OWNER_CAPITAL)
            if non_owner_sources.exists():
                raise serializers.ValidationError(
                    {"funding_allocations_input": "Owner payment classifications require an owner-capital source."}
                )
        equity_outflows = {
            FundingClassification.OWNER_CAPITAL_RETURN,
            FundingClassification.OWNER_DRAWING,
            FundingClassification.OWNER_DISTRIBUTION,
        }
        if any(row.get("classification") in equity_outflows for row in funding_rows):
            nature = attrs.get(
                "accounting_nature",
                self.instance.accounting_nature if self.instance else None,
            )
            if nature != AccountingNature.OWNER_WITHDRAWAL:
                raise serializers.ValidationError(
                    {
                        "accounting_nature": (
                            "Capital returns, drawings and profit distributions must "
                            "use Owner Withdrawal."
                        )
                    }
                )
            planned_costs = attrs.get("cost_allocations_input")
            if planned_costs is None and self.instance is not None:
                planned_costs = self.instance.cost_allocation_plan
            if planned_costs:
                raise serializers.ValidationError(
                    {
                        "cost_allocations_input": (
                            "Owner equity outflows cannot be charged to poultry batches."
                        )
                    }
                )
        return attrs

    def create(self, validated_data):
        funding_input = validated_data.pop("funding_allocations_input", []) or []
        cost_input = validated_data.pop("cost_allocations_input", []) or []
        validated_data["cost_allocation_plan"] = cost_input
        expenditure = super().create(validated_data)

        # Create draft funding allocations (will be validated on post)
        for f in funding_input:
            if f.get("funding_source") and f.get("amount"):
                FundingAllocation.objects.create(
                    expenditure=expenditure,
                    funding_source_id=f.get("funding_source"),
                    amount=f.get("amount"),
                    allocation_date=expenditure.expenditure_date or timezone.now().date(),
                    classification=f.get("classification", "reinvestment"),
                    created_by=self.context["request"].user if "request" in self.context else None,
                )

        return expenditure

    def update(self, instance, validated_data):
        funding_input = validated_data.pop("funding_allocations_input", None)
        cost_input = validated_data.pop("cost_allocations_input", None)
        if instance.status != ExpenditureStatus.DRAFT and (
            funding_input is not None or cost_input is not None
        ):
            raise serializers.ValidationError(
                "Funding and beneficiary allocations cannot be changed after posting."
            )
        if cost_input is not None:
            validated_data["cost_allocation_plan"] = cost_input
        instance = super().update(instance, validated_data)
        if funding_input is not None:
            instance.funding_allocations.all().delete()
            for row in funding_input:
                if row.get("funding_source") and row.get("amount"):
                    FundingAllocation.objects.create(
                        expenditure=instance,
                        funding_source_id=row["funding_source"],
                        amount=row["amount"],
                        allocation_date=instance.expenditure_date,
                        classification=row.get("classification", "reinvestment"),
                        created_by=self.context["request"].user,
                    )
        return instance


class FundingAllocationSerializer(serializers.ModelSerializer):
    funding_source_display = serializers.CharField(source="funding_source.__str__", read_only=True)
    funding_batch = serializers.IntegerField(source="funding_source.batch_id", read_only=True, allow_null=True)
    funding_source_type = serializers.CharField(
        source="funding_source.source_type", read_only=True
    )
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = FundingAllocation
        fields = [
            "id", "expenditure", "funding_source", "amount",
            "allocation_date", "classification", "notes", "created_by",
            "funding_source_display", "funding_batch", "funding_source_type",
            "payment_group_key", "created_at", "created_by_name",
        ]
        read_only_fields = ["created_by", "payment_group_key", "created_at"]


class SalePaymentSerializer(serializers.ModelSerializer):
    sale_id = serializers.CharField(source="sale.sale_id", read_only=True)
    batch = serializers.IntegerField(source="sale.batch_id", read_only=True)
    batch_code = serializers.CharField(source="sale.batch.batch_id", read_only=True)
    buyer_name = serializers.CharField(source="sale.buyer_name", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.get_username", read_only=True, allow_null=True
    )
    reversed_by_name = serializers.CharField(
        source="reversed_by.get_username", read_only=True, allow_null=True
    )

    class Meta:
        model = SalePayment
        fields = [
            "id", "sale", "sale_id", "batch", "batch_code", "buyer_name", "payment_reference",
            "idempotency_key", "amount", "payment_date", "payment_method",
            "external_reference", "received_by_name", "notes", "status",
            "created_by", "created_by_name", "created_at", "reversed_at", "reversed_by",
            "reversed_by_name",
            "reversal_reason",
        ]
        read_only_fields = [
            "payment_reference", "status", "created_by", "created_at",
            "reversed_at", "reversed_by", "reversal_reason",
        ]


class RecordSalePaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    payment_date = serializers.DateTimeField(default=timezone.now)
    payment_method = serializers.CharField(max_length=50)
    idempotency_key = serializers.CharField(max_length=120)
    external_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    received_by_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ExpenditureCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenditureCategory
        fields = [
            "id", "name", "code", "default_accounting_nature", "is_active",
            "display_order", "requires_item_details", "requires_batch_beneficiary",
        ]


class BatchRevenueUtilizationSerializer(serializers.Serializer):
    """Lightweight serializer for the revenue usage report."""
    batch_id = serializers.IntegerField()
    batch_code = serializers.CharField()
    cash_collected = serializers.DecimalField(max_digits=14, decimal_places=2)
    gross_collections = serializers.DecimalField(max_digits=14, decimal_places=2)
    refunds = serializers.DecimalField(max_digits=14, decimal_places=2)
    cash_used = serializers.DecimalField(max_digits=14, decimal_places=2)
    available_cash = serializers.DecimalField(max_digits=14, decimal_places=2)
    utilization_percent = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    by_category = serializers.DictField(child=serializers.DecimalField(max_digits=14, decimal_places=2))
    by_accounting_nature = serializers.DictField(child=serializers.DecimalField(max_digits=14, decimal_places=2))
    beneficiary_modules = serializers.ListField(child=serializers.CharField())
    transactions = serializers.ListField(child=serializers.DictField())
