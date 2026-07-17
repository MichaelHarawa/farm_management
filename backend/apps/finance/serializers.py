from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import Role, RoleChoices
from apps.accounts.serializers import RoleSummarySerializer

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
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
        if self.instance and "password" in attrs:
            raise serializers.ValidationError(
                {"password": "Password can only be supplied during account creation."}
            )

        if not self.instance:
            for field in ("username", "email", "password"):
                if not attrs.get(field):
                    raise serializers.ValidationError({field: "This field is required."})

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
        user_data = {
            "username": validated_data.pop("username"),
            "email": validated_data.pop("email"),
            "first_name": validated_data.pop("first_name", ""),
            "last_name": validated_data.pop("last_name", ""),
        }
        password = validated_data.pop("password")
        user = User.objects.create_user(**user_data, password=password)
        if role_slugs:
            user.roles.set(resolve_roles(role_slugs))

        profile = EmployeeProfile.objects.create(user=user, **validated_data)
        profile.full_clean()
        return profile

    @transaction.atomic
    def update(self, instance, validated_data):
        role_slugs = validated_data.pop("role_slugs", None)
        user_fields = {
            key: validated_data.pop(key)
            for key in ("username", "email", "first_name", "last_name")
            if key in validated_data
        }
        for key, value in user_fields.items():
            setattr(instance.user, key, value)
        if user_fields:
            instance.user.save(update_fields=[*user_fields.keys(), "updated_at"])
        if role_slugs is not None:
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

    class Meta:
        model = PayrollEntry
        fields = "__all__"
        read_only_fields = (
            "total_employer_cost",
            "created_by",
            "created_at",
            "updated_at",
        )


class AdHocLabourPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdHocLabourPayment
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "updated_at")


class SharedExpenseSerializer(serializers.ModelSerializer):
    is_capital_expenditure = serializers.BooleanField(read_only=True)

    class Meta:
        model = SharedExpense
        fields = "__all__"
        read_only_fields = ("created_by", "created_at", "updated_at")


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


class BatchProfitabilitySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = BatchProfitabilitySnapshot
        fields = "__all__"
        read_only_fields = ("created_at", "updated_at")
