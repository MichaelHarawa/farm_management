import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  RouteAuthenticationError,
  routeAuthenticatedBackendFetch,
} from "@/features/auth/server/route-authenticated-backend";
import { poultryApiPaths } from "@/features/poultry/api/paths";
import type { PoultryBatch } from "@/features/poultry/types";
import { BackendApiError } from "@/lib/server/backend-api";

export async function POST(request: NextRequest) {
  let payload: unknown;

  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Request body must be valid JSON." },
      { status: 400 }
    );
  }

  try {
    const batch = await routeAuthenticatedBackendFetch<PoultryBatch>(
      request,
      poultryApiPaths.batches,
      {
        method: "POST",
        body: JSON.stringify(payload),
        cache: "no-store",
      }
    );

    return NextResponse.json(batch, { status: 201 });
  } catch (error) {
    if (error instanceof RouteAuthenticationError) {
      return NextResponse.json(
        { message: error.message },
        { status: error.status }
      );
    }

    if (error instanceof BackendApiError) {
      return NextResponse.json(error.details ?? { detail: error.message }, {
        status: error.status,
      });
    }

    throw error;
  }
}
