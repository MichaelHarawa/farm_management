from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import RoleChoices


FINANCE_READ_ROLES = {
    RoleChoices.ADMIN,
    RoleChoices.DIRECTOR,
    RoleChoices.FARM_MANAGER,
    RoleChoices.FARM_SUPERVISOR,
    RoleChoices.STAKE_HOLDER,
}

FINANCE_WRITE_ROLES = {
    RoleChoices.ADMIN,
    RoleChoices.DIRECTOR,
    RoleChoices.FARM_MANAGER,
    RoleChoices.FARM_SUPERVISOR,
}

FINANCE_CLOSE_ROLES = {
    RoleChoices.ADMIN,
    RoleChoices.DIRECTOR,
    RoleChoices.FARM_MANAGER,
}

FINANCE_MANAGEMENT_ROLES = {
    RoleChoices.ADMIN,
    RoleChoices.DIRECTOR,
    RoleChoices.FARM_MANAGER,
}


class FinancePermission(BasePermission):
    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False

        action = getattr(view, "action", "")

        if request.method in SAFE_METHODS:
            return user.has_any_role(FINANCE_READ_ROLES)

        if action in {"close", "reopen"}:
            return user.has_any_role(FINANCE_CLOSE_ROLES)

        if action in {"generate_payroll", "recalculate"}:
            return user.has_any_role(FINANCE_MANAGEMENT_ROLES)

        return user.has_any_role(FINANCE_WRITE_ROLES)


class FinanceReadOnlyOrManagement(FinancePermission):
    pass
