import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  inputCostSchema,
} from "@/features/poultry/validation/input-cost";

import type {
  InputCost,
} from "@/features/poultry/types";

import {
  poultryApiPaths,
} from "@/features/poultry/api/paths";

import {
  ACCESS_TOKEN_COOKIE,
} from "@/features/auth/server/token-cookies";

import {
  BackendApiError,
  backendApiFetch,
} from "@/lib/server/backend-api";

type RouteContext = {
  params: Promise<{
    id: string;
  }>;
};

export async function POST(
  request: NextRequest,
  context: RouteContext
) {
  const { id } = await context.params;
  const batchId = Number(id);

  if (
    !Number.isInteger(batchId) ||
    batchId <= 0
  ) {
    return NextResponse.json(
      {
        message:
          "The batch identifier is invalid.",
      },
      {
        status: 400,
      }
    );
  }

  const accessToken =
    request.cookies.get(
      ACCESS_TOKEN_COOKIE
    )?.value;

  if (!accessToken) {
    return NextResponse.json(
      {
        message:
          "Authentication is required.",
      },
      {
        status: 401,
      }
    );
  }

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
    inputCostSchema.safeParse(
      requestBody
    );

  if (!validationResult.success) {
    return NextResponse.json(
      {
        message:
          "Please correct the input-cost details.",
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
    const inputCost =
      await backendApiFetch<InputCost>(
        poultryApiPaths.inputCosts(
          batchId
        ),
        {
          method: "POST",
          headers: {
            Authorization:
              `Bearer ${accessToken}`,
          },
          body: JSON.stringify(
            validationResult.data
          ),
        }
      );

    const response = NextResponse.json(
      inputCost,
      {
        status: 201,
      }
    );

    response.headers.set(
      "Cache-Control",
      "no-store"
    );

    return response;
  } catch (error) {
    if (error instanceof BackendApiError) {
      const message =
        error.status === 401
          ? "Your session has expired."
          : "The input cost could not be saved.";

      return NextResponse.json(
        {
          message,
          details: error.details,
        },
        {
          status: error.status,
        }
      );
    }

    console.error(
      "Input-cost creation failed:",
      error
    );

    return NextResponse.json(
      {
        message:
          "The input-cost service is unavailable.",
      },
      {
        status: 503,
      }
    );
  }
}