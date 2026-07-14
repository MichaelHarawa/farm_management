import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  BackendApiError,
  backendApiFetch,
} from "@/lib/server/backend-api";

import {
  ACCESS_TOKEN_COOKIE,
  REFRESH_TOKEN_COOKIE,
} from "./token-cookies";

import {
  buildLoginPath,
  buildRefreshPath,
} from "../utils/redirects";

type AuthenticatedBackendOptions =
  RequestInit & {
    returnTo: string;
  };

export async function authenticatedBackendFetch<T>(
  path: string,
  options: AuthenticatedBackendOptions
): Promise<T> {
  const {
    returnTo,
    ...requestOptions
  } = options;

  const cookieStore = await cookies();

  const accessToken = cookieStore.get(
    ACCESS_TOKEN_COOKIE
  )?.value;

  const refreshToken = cookieStore.get(
    REFRESH_TOKEN_COOKIE
  )?.value;

  if (!accessToken) {
    if (refreshToken) {
      redirect(buildRefreshPath(returnTo));
    }

    redirect(buildLoginPath(returnTo));
  }

  const headers = new Headers(
    requestOptions.headers
  );

  headers.set(
    "Authorization",
    `Bearer ${accessToken}`
  );

  try {
    return await backendApiFetch<T>(
      path,
      {
        ...requestOptions,
        headers,
      }
    );
  } catch (error) {
    if (
      error instanceof BackendApiError &&
      error.status === 401
    ) {
      if (refreshToken) {
        redirect(
          buildRefreshPath(returnTo)
        );
      }

      redirect(buildLoginPath(returnTo));
    }

    throw error;
  }
}