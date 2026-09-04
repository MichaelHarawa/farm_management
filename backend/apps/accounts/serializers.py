from __future__ import annotations

from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from .models import AccountAuditEvent, Role, RoleChoices, User


class RoleSummarySerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = Role
        fields = (
            "slug",
            "name",
        )


class CurrentUserSerializer(
    serializers.ModelSerializer
):
    full_name = serializers.SerializerMethodField()
    roles = RoleSummarySerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "job_title",
            "department",
            "roles",
            "is_staff",
            "is_superuser",
        )
        read_only_fields = fields

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.username


class SystemUserSerializer(serializers.ModelSerializer):
    roles = RoleSummarySerializer(many=True, read_only=True)
    role_slugs = serializers.ListField(
        child=serializers.ChoiceField(choices=RoleChoices.choices),
        write_only=True,
        required=False,
    )
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    full_name = serializers.SerializerMethodField()
    employee_profile_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    employee_number = serializers.CharField(source="employee_profile.employee_number", read_only=True)

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "first_name", "last_name", "full_name",
            "job_title", "department", "role_slugs", "roles", "is_active",
            "is_staff", "is_superuser", "last_login", "date_joined", "password",
            "employee_profile_id", "employee_number",
        )
        read_only_fields = (
            "id", "roles", "full_name", "last_login", "date_joined", "is_superuser",
            "employee_number",
        )

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.username

    def create(self, validated_data):
        role_slugs = validated_data.pop("role_slugs", [])
        employee_id = validated_data.pop("employee_profile_id", None)
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "A temporary password is required."})
        user = User.objects.create_user(password=password, **validated_data)
        user.roles.set(Role.objects.filter(slug__in=role_slugs))
        self._link_employee(user, employee_id)
        return user

    def update(self, instance, validated_data):
        validated_data.pop("password", None)
        role_slugs = validated_data.pop("role_slugs", None)
        employee_id = validated_data.pop("employee_profile_id", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if role_slugs is not None:
            instance.roles.set(Role.objects.filter(slug__in=role_slugs))
        self._link_employee(instance, employee_id)
        return instance

    def _link_employee(self, user, employee_id):
        if employee_id is None:
            return
        from apps.finance.models import EmployeeProfile

        employee = EmployeeProfile.objects.filter(pk=employee_id).first()
        if employee is None:
            raise serializers.ValidationError({"employee_profile_id": "Employee was not found."})
        if employee.user_id and employee.user_id != user.pk:
            raise serializers.ValidationError({"employee_profile_id": "Employee already has login access."})
        employee.user = user
        employee.save(update_fields=["user", "updated_at"])


class UserAdministrationEventSerializer(serializers.ModelSerializer):
    performed_by = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = AccountAuditEvent
        fields = ("id", "action", "details", "performed_by", "created_at")
        read_only_fields = fields


class FarmTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        data["user"] = CurrentUserSerializer(
            self.user
        ).data

        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(
        write_only=True
    )

    def validate(self, attrs):
        refresh_value = attrs["refresh"]

        try:
            self.refresh_token = RefreshToken(
                refresh_value
            )
        except TokenError as error:
            raise serializers.ValidationError(
                {
                    "refresh": (
                        "The refresh token is invalid "
                        "or has expired."
                    )
                }
            ) from error

        return attrs

    def save(self, **kwargs):
        self.refresh_token.blacklist()
