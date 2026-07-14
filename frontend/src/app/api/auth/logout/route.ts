import {
  NextRequest,
  NextResponse,
} from "next/server";

import { logoutFromDjango } from "@/features/auth/server/django-auth";

import {
  REFRESH_TOKEN_COOKIE,
  clearAuthCookies,
} from "@/features/auth/server/token-cookies";

export async function POST(
  request: NextRequest
) {
  const refreshToken =
    request.cookies.get(
      REFRESH_TOKEN_COOKIE
    )?.value;

  if (refreshToken) {
    try {
      await logoutFromDjango(
        refreshToken
      );
    } catch (error) {
      console.error(
        "Django token blacklist failed:",
        error
      );
    }
  }

  const response = new NextResponse(
    null,
    {
      status: 204,
    }
  );

  clearAuthCookies(response);

  return response;
}