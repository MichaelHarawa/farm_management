from __future__ import annotations

from rest_framework import serializers
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Role, User


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