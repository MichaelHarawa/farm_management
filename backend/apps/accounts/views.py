from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    IsAuthenticated,
)
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    CurrentUserSerializer,
    LogoutSerializer,
    SystemUserSerializer,
    UserAdministrationEventSerializer,
)
from .models import AccountAuditEvent, RoleChoices, User


class IsSystemAdministrator(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.has_admin_access)


def active_administrator_count() -> int:
    return User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(roles__slug=RoleChoices.ADMIN)
    ).distinct().count()


class SystemUserViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Admin-only system account management, independent of employee/payroll records."""

    permission_classes = (IsSystemAdministrator,)
    serializer_class = SystemUserSerializer
    queryset = User.objects.prefetch_related("roles").order_by("username")

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        return queryset

    def _would_remove_last_admin(self, user, attrs) -> bool:
        if not user.is_active or not user.has_admin_access:
            return False
        remains_active = attrs.get("is_active", user.is_active)
        requested_roles = attrs.get("role_slugs")
        remains_admin = user.is_superuser or (
            requested_roles is None and user.has_admin_access
        ) or (requested_roles is not None and RoleChoices.ADMIN in requested_roles)
        return (not remains_active or not remains_admin) and active_administrator_count() <= 1

    @transaction.atomic
    def perform_create(self, serializer):
        user = serializer.save()
        AccountAuditEvent.objects.create(
            target_user=user,
            action="created",
            details={"roles": sorted(user.role_slugs), "active": user.is_active},
            actor=self.request.user,
        )

    @transaction.atomic
    def perform_update(self, serializer):
        if self._would_remove_last_admin(serializer.instance, serializer.validated_data):
            raise ValidationError({"detail": "The last active administrator cannot be deactivated or stripped of administrator access."})
        before = {
            "roles": sorted(serializer.instance.role_slugs),
            "active": serializer.instance.is_active,
        }
        user = serializer.save()
        AccountAuditEvent.objects.create(
            target_user=user,
            action="updated",
            details={"before": before, "after": {"roles": sorted(user.role_slugs), "active": user.is_active}},
            actor=self.request.user,
        )

    @action(detail=True, methods=["post"], url_path="reset-password")
    @transaction.atomic
    def reset_password(self, request, pk=None):
        user = self.get_object()
        temporary_password = str(request.data.get("temporary_password", ""))
        if len(temporary_password) < 8:
            raise ValidationError({"temporary_password": "Use at least 8 characters."})
        user.set_password(temporary_password)
        user.save(update_fields=["password", "updated_at"])
        AccountAuditEvent.objects.create(
            target_user=user,
            action="password_reset",
            details={"method": "administrator_temporary_password"},
            actor=request.user,
        )
        return Response({"detail": "Temporary password set. Share it securely with the user."})

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        events = self.get_object().account_audit_events.select_related("actor")
        return Response(UserAdministrationEventSerializer(events, many=True).data)


class CurrentUserView(RetrieveAPIView):
    serializer_class = CurrentUserSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data
        )
        serializer.is_valid(
            raise_exception=True
        )
        serializer.save()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )
