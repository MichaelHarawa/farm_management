import type { AuthUser } from "../types";

const FINANCE_READ_ROLES = new Set([
  "admin",
  "director",
  "farm_manager",
  "farm_supervisor",
  "stake_holder",
]);

export function canAccessFinance(user: AuthUser | null): boolean {
  return Boolean(
    user &&
      (user.is_superuser || user.roles.some((role) => FINANCE_READ_ROLES.has(role.slug)))
  );
}

export function canAdministerUsers(user: AuthUser | null): boolean {
  return Boolean(
    user &&
      (user.is_superuser || user.roles.some((role) => role.slug === "admin"))
  );
}
