import "server-only";

import { NextRequest } from "next/server";

import {
  backendApiFetch,
} from "@/lib/server/backend-api";

import { ACCESS_TOKEN_COOKIE } from "./token-cookies";

export class RouteAuthenticationError extends Error {
  status = 401;

  constructor() {
    super("Authentication is required.");
    this.name = "RouteAuthenticationError";
  }
}

export async function routeAuthenticatedBackendFetch<T>(
  request: NextRequest,
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const accessToken = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;

  if (!accessToken) {
    throw new RouteAuthenticationError();
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);

  return backendApiFetch<T>(path, {
    ...options,
    headers,
  });
}
