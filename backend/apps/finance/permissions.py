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

OWNER_CAPITAL_ROLES = {
    RoleChoices.ADMIN,
    RoleChoices.DIRECTOR,
}


def has_owner_capital_access(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.has_any_role(OWNER_CAPITAL_ROLES)
    )


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

        if action in {
            "generate_payroll",
            "generate_depreciation",
            "allocate_depreciation",
            "recalculate",
            "from_expense",
            "impair",
            "dispose",
        }:
            return user.has_any_role(FINANCE_MANAGEMENT_ROLES)

        return user.has_any_role(FINANCE_WRITE_ROLES)


class FinanceReadOnlyOrManagement(FinancePermission):
    pass


class OwnerCapitalPermission(BasePermission):
    """Owner identities and capital movements are limited to senior roles."""

    def has_permission(self, request, view) -> bool:
        return has_owner_capital_access(request.user)
