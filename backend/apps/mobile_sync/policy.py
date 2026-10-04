from rest_framework.permissions import BasePermission, SAFE_METHODS

from .projections import checksum

OPERATORS = {"general_worker", "farm_supervisor", "farm_manager", "director", "admin"}
SUPERVISORS = OPERATORS - {"general_worker"}
READERS = OPERATORS | {"stake_holder"}


def permits(user, roles):
    return bool(user and user.is_authenticated and user.is_active and (user.is_superuser or user.role_slugs & roles))


def scope_revision(user, version=1):
    # Re-fetch through M2M; prefetched role summaries cannot grant stale access.
    roles = sorted(user.roles.values_list("slug", flat=True))
    value = {"policy": 1, "projections": 1, "roles": roles, "active": user.is_active,
             "superuser": user.is_superuser, "entities": ["poultry.batch", "poultry.mortality", "poultry.feed_usage"],
             "commands": ["poultry.mortality.record"]}
    if version == 2:
        from .projections import TYPES
        from .commands.registry import REGISTRY
        value.update(projections=2, entities=sorted(TYPES.values()),
                     commands=sorted(f"{kind}.{action}" for kind, action, _ in REGISTRY))
    return checksum(value)


class PoultryPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", "")
        financial = action in {"sales", "input_costs", "feed_input_costs", "sell_by_guidance"}
        # Operational worker reads must not expose BatchSerializer economics.
        if request.method in SAFE_METHODS:
            return permits(request.user, SUPERVISORS | {"stake_holder"}) if financial else permits(request.user, READERS)
        if action in {"mortality", "feed_usage", "drugs_vaccine", "weight_samples"}:
            return permits(request.user, OPERATORS)
        return permits(request.user, SUPERVISORS)
