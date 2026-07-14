import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  refreshDjangoTokens,
} from "@/features/auth/server/django-auth";

import {
  REFRESH_TOKEN_COOKIE,
  clearAuthCookies,
  setAuthCookies,
} from "@/features/auth/server/token-cookies";

import {
  buildLoginPath,
  getSafeInternalPath,
} from "@/features/auth/utils/redirects";

import {
  BackendApiError,
} from "@/lib/server/backend-api";

function redirectToLogin(
  request: NextRequest,
  returnTo: string
): NextResponse {
  const loginUrl = new URL(
    buildLoginPath(returnTo),
    request.url
  );

  const response =
    NextResponse.redirect(loginUrl);

  clearAuthCookies(response);

  return response;
}

export async function GET(
  request: NextRequest
) {
  const returnTo = getSafeInternalPath(
    request.nextUrl.searchParams.get("next")
  );

  const refreshToken =
    request.cookies.get(
      REFRESH_TOKEN_COOKIE
    )?.value;

  if (!refreshToken) {
    return redirectToLogin(
      request,
      returnTo
    );
  }

  try {
    const refreshedTokens =
      await refreshDjangoTokens(
        refreshToken
      );

    const destination = new URL(
      returnTo,
      request.url
    );

    const response =
      NextResponse.redirect(destination);

    setAuthCookies(response, {
      access: refreshedTokens.access,
      refresh: refreshedTokens.refresh,
    });

    response.headers.set(
      "Cache-Control",
      "no-store"
    );

    return response;
  } catch (error) {
    if (
      error instanceof BackendApiError &&
      error.status === 401
    ) {
      return redirectToLogin(
        request,
        returnTo
      );
    }

    console.error(
      "Authentication refresh failed:",
      error
    );

    return new NextResponse(
      "The authentication service is temporarily unavailable.",
      {
        status: 503,
      }
    );
  }
}