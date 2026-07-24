import "server-only";

import type { NextResponse } from "next/server";

export const ACCESS_TOKEN_COOKIE =
  "farm_access_token";

export const REFRESH_TOKEN_COOKIE =
  "farm_refresh_token";

export const AUTH_LAST_ACTIVITY_COOKIE =
  "farm_last_activity";

const ACCESS_TOKEN_MAX_AGE = 15 * 60;

const REFRESH_TOKEN_MAX_AGE =
  Number(process.env.AUTH_REFRESH_TOKEN_MAX_AGE_SECONDS ?? 12 * 60 * 60);

export const SESSION_IDLE_TIMEOUT_SECONDS =
  Number(process.env.AUTH_IDLE_TIMEOUT_SECONDS ?? 2 * 60 * 60);

const secure =
  process.env.NODE_ENV === "production";

type TokenValues = {
  access: string;
  refresh?: string;
};

type SetAuthCookieOptions = {
  touch?: boolean;
};

export function isSessionIdleExpired(
  lastActivityValue: string | undefined
): boolean {
  if (!lastActivityValue) {
    return true;
  }

  const lastActivity = Number(lastActivityValue);

  if (!Number.isFinite(lastActivity)) {
    return true;
  }

  return Date.now() - lastActivity > SESSION_IDLE_TIMEOUT_SECONDS * 1000;
}

export function touchAuthActivityCookie(
  response: NextResponse
): void {
  response.cookies.set({
    name: AUTH_LAST_ACTIVITY_COOKIE,
    value: Date.now().toString(),
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_TOKEN_MAX_AGE,
  });
}

export function setAuthCookies(
  response: NextResponse,
  tokens: TokenValues,
  options: SetAuthCookieOptions = {}
): void {
  response.cookies.set({
    name: ACCESS_TOKEN_COOKIE,
    value: tokens.access,
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: ACCESS_TOKEN_MAX_AGE,
  });

  if (tokens.refresh) {
    response.cookies.set({
      name: REFRESH_TOKEN_COOKIE,
      value: tokens.refresh,
      httpOnly: true,
      secure,
      sameSite: "lax",
      path: "/",
      maxAge: REFRESH_TOKEN_MAX_AGE,
    });
  }

  if (options.touch !== false) {
    touchAuthActivityCookie(response);
  }
}

export function clearAuthCookies(
  response: NextResponse
): void {
  response.cookies.set({
    name: ACCESS_TOKEN_COOKIE,
    value: "",
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });

  response.cookies.set({
    name: REFRESH_TOKEN_COOKIE,
    value: "",
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });

  response.cookies.set({
    name: AUTH_LAST_ACTIVITY_COOKIE,
    value: "",
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
}
