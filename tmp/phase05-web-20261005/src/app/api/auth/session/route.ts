import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  getDjangoCurrentUser,
  refreshDjangoTokens,
} from "@/features/auth/server/django-auth";

import {
  ACCESS_TOKEN_COOKIE,
  AUTH_LAST_ACTIVITY_COOKIE,
  REFRESH_TOKEN_COOKIE,
  clearAuthCookies,
  isSessionIdleExpired,
  setAuthCookies,
  touchAuthActivityCookie,
} from "@/features/auth/server/token-cookies";

import { BackendApiError } from "@/lib/server/backend-api";

function unauthorizedResponse(): NextResponse {
  const response = NextResponse.json(
    {
      message: "Authentication is required.",
    },
    {
      status: 401,
    }
  );

  clearAuthCookies(response);

  return response;
}

export async function GET(
  request: NextRequest
) {
  const shouldTouch =
    request.nextUrl.searchParams.get("touch") !== "0";
  const accessToken =
    request.cookies.get(
      ACCESS_TOKEN_COOKIE
    )?.value;

  const refreshToken =
    request.cookies.get(
      REFRESH_TOKEN_COOKIE
    )?.value;
  const lastActivity =
    request.cookies.get(
      AUTH_LAST_ACTIVITY_COOKIE
    )?.value;

  if (!accessToken && !refreshToken) {
    return unauthorizedResponse();
  }

  if (refreshToken && isSessionIdleExpired(lastActivity)) {
    return unauthorizedResponse();
  }

  if (accessToken) {
    try {
      const user =
        await getDjangoCurrentUser(
          accessToken
        );

      const response = NextResponse.json(
        {
          user,
        }
      );

      if (shouldTouch) {
        touchAuthActivityCookie(response);
      }

      response.headers.set(
        "Cache-Control",
        "no-store"
      );

      return response;
    } catch (error) {
      const isExpiredOrInvalid =
        error instanceof BackendApiError &&
        error.status === 401;

      if (!isExpiredOrInvalid) {
        console.error(
          "Current-user request failed:",
          error
        );

        return NextResponse.json(
          {
            message:
              "The user session could not be loaded.",
          },
          {
            status: 502,
          }
        );
      }
    }
  }

  if (!refreshToken) {
    return unauthorizedResponse();
  }

  try {
    const refreshedTokens =
      await refreshDjangoTokens(
        refreshToken
      );

    const user =
      await getDjangoCurrentUser(
        refreshedTokens.access
      );

    const response = NextResponse.json(
      {
        user,
      }
    );

    setAuthCookies(response, {
      access: refreshedTokens.access,
      refresh:
        refreshedTokens.refresh,
    }, {
      touch: shouldTouch,
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
      return unauthorizedResponse();
    }

    console.error(
      "Token refresh failed:",
      error
    );

    return NextResponse.json(
      {
        message:
          "The authentication service is currently unavailable.",
      },
      {
        status: 503,
      }
    );
  }
}
