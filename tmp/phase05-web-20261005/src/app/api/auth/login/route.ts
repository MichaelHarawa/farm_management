import {
  NextRequest,
  NextResponse,
} from "next/server";

import { loginWithDjango } from "@/features/auth/server/django-auth";
import { setAuthCookies } from "@/features/auth/server/token-cookies";
import { loginSchema } from "@/features/auth/validation/login";
import { BackendApiError } from "@/lib/server/backend-api";

export async function POST(
  request: NextRequest
) {
  let requestBody: unknown;

  try {
    requestBody = await request.json();
  } catch {
    return NextResponse.json(
      {
        message:
          "The request body must contain valid JSON.",
      },
      {
        status: 400,
      }
    );
  }

  const validationResult =
    loginSchema.safeParse(requestBody);

  if (!validationResult.success) {
    return NextResponse.json(
      {
        message:
          "Please correct the login details.",
        fieldErrors:
          validationResult.error.flatten()
            .fieldErrors,
      },
      {
        status: 400,
      }
    );
  }

  try {
    const loginResult = await loginWithDjango(
      validationResult.data
    );

    const response = NextResponse.json(
      {
        user: loginResult.user,
      },
      {
        status: 200,
      }
    );

    setAuthCookies(response, {
      access: loginResult.access,
      refresh: loginResult.refresh,
    });

    response.headers.set(
      "Cache-Control",
      "no-store"
    );

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      if (error.status === 401) {
        return NextResponse.json(
          {
            message:
              "The username or password is incorrect.",
          },
          {
            status: 401,
          }
        );
      }

      console.error(
        "Django login request failed:",
        error.details
      );

      return NextResponse.json(
        {
          message:
            "The authentication service could not process the login.",
        },
        {
          status:
            error.status >= 500
              ? 502
              : error.status,
        }
      );
    }

    console.error(
      "Unexpected login error:",
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