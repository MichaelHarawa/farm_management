import "server-only";

import { backendApiFetch } from "@/lib/server/backend-api";

import type {
  AuthUser,
  DjangoLoginResponse,
  DjangoRefreshResponse,
  LoginPayload,
} from "../types";

const djangoAuthPaths = {
  login: "/auth/login",
  refresh: "/auth/refresh",
  me: "/auth/me",
  logout: "/auth/logout",
} as const;

export async function loginWithDjango(
  payload: LoginPayload
): Promise<DjangoLoginResponse> {
  return backendApiFetch<DjangoLoginResponse>(
    djangoAuthPaths.login,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function refreshDjangoTokens(
  refreshToken: string
): Promise<DjangoRefreshResponse> {
  return backendApiFetch<DjangoRefreshResponse>(
    djangoAuthPaths.refresh,
    {
      method: "POST",
      body: JSON.stringify({
        refresh: refreshToken,
      }),
    }
  );
}

export async function getDjangoCurrentUser(
  accessToken: string
): Promise<AuthUser> {
  return backendApiFetch<AuthUser>(
    djangoAuthPaths.me,
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
      },
    }
  );
}

export async function logoutFromDjango(
  refreshToken: string
): Promise<null> {
  return backendApiFetch<null>(
    djangoAuthPaths.logout,
    {
      method: "POST",
      body: JSON.stringify({
        refresh: refreshToken,
      }),
    }
  );
}