import {
  NextRequest,
  NextResponse,
} from "next/server";

import {
  RouteAuthenticationError,
  routeAuthenticatedBackendFetch,
} from "@/features/auth/server/route-authenticated-backend";
import { BackendApiError } from "@/lib/server/backend-api";

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

const POULTRY_ROOT = "/poultry-management";

const ACTION_PATH_MAP: Record<string, string> = {
  "input-costs": "input_costs",
  "feed-usage": "feed_usage",
  vaccinations: "drugs_vaccine",
  "feed-input-costs": "feed_input_costs",
  "mark-delivered": "mark-delivered",
  "confirm-delivery": "confirm-delivery",
  mortality: "mortality",
  sales: "sales",
};

function toBackendPath(segments: string[]): string | null {
  if (segments.length === 0) {
    return null;
  }

  if (segments[0] !== "batches") {
    return null;
  }

  if (segments.length === 1) {
    return `${POULTRY_ROOT}/`;
  }

  const batchId = Number(segments[1]);

  if (!Number.isInteger(batchId) || batchId <= 0) {
    return null;
  }

  if (segments.length === 2) {
    return `${POULTRY_ROOT}/${batchId}`;
  }

  if (segments.length === 3) {
    const backendAction = ACTION_PATH_MAP[segments[2]];

    if (!backendAction) {
      return null;
    }

    return `${POULTRY_ROOT}/${batchId}/${backendAction}`;
  }

  return null;
}

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const backendPath = toBackendPath(path);

  if (!backendPath) {
    return NextResponse.json(
      { detail: "Poultry API route not found." },
      { status: 404 }
    );
  }

  const method = request.method;
  const hasBody = !["GET", "HEAD"].includes(method);
  const body = hasBody ? await request.text() : undefined;
  const search = request.nextUrl.search;

  try {
    const data = await routeAuthenticatedBackendFetch<unknown>(
      request,
      `${backendPath}${search}`,
      {
        method,
        body: body || undefined,
        cache: "no-store",
      }
    );

    return NextResponse.json(data, {
      status: method === "POST" ? 201 : 200,
    });
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

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return proxy(request, context);
}
