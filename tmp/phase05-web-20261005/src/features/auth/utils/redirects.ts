export function getSafeInternalPath(
  value: string | string[] | null | undefined,
  fallback = "/poultry"
): string {
  const candidate = Array.isArray(value)
    ? value[0]
    : value;

  if (
    typeof candidate === "string" &&
    candidate.startsWith("/") &&
    !candidate.startsWith("//")
  ) {
    return candidate;
  }

  return fallback;
}

export function buildLoginPath(
  returnTo: string
): string {
  const safeReturnTo = getSafeInternalPath(
    returnTo
  );

  return `/login?next=${encodeURIComponent(
    safeReturnTo
  )}`;
}

export function buildRefreshPath(
  returnTo: string
): string {
  const safeReturnTo = getSafeInternalPath(
    returnTo
  );

  return `/auth/refresh?next=${encodeURIComponent(
    safeReturnTo
  )}`;
}