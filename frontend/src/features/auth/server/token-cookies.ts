import "server-only";

import type { NextResponse } from "next/server";

export const ACCESS_TOKEN_COOKIE =
  "farm_access_token";

export const REFRESH_TOKEN_COOKIE =
  "farm_refresh_token";

const ACCESS_TOKEN_MAX_AGE = 15 * 60;

const REFRESH_TOKEN_MAX_AGE =
  7 * 24 * 60 * 60;

const secure =
  process.env.NODE_ENV === "production";

type TokenValues = {
  access: string;
  refresh?: string;
};

export function setAuthCookies(
  response: NextResponse,
  tokens: TokenValues
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
}