import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  RouteAuthenticationError,
  routeAuthenticatedBackendFetch,
} from "@/features/auth/server/route-authenticated-backend";
import { poultryApiPaths } from "@/features/poultry/api/paths";
import type { PoultryMortality } from "@/features/poultry/types";
import { BackendApiError } from "@/lib/server/backend-api";

type RouteContext = {
  params: Promise<{
    id: string;
  }>;
};

export async function POST(request: NextRequest, { params }: RouteContext) {
  const { id } = await params;
  const batchId = Number(id);

  if (!Number.isInteger(batchId) || batchId <= 0) {
    return NextResponse.json(
      { detail: "Invalid batch id." },
      { status: 400 }
    );
  }

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
    const mortality = await routeAuthenticatedBackendFetch<PoultryMortality>(
      request,
      poultryApiPaths.mortality(batchId),
      {
        method: "POST",
        body: JSON.stringify(payload),
        cache: "no-store",
      }
    );

    return NextResponse.json(mortality, { status: 201 });
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
