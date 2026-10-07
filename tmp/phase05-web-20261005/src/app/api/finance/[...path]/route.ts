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

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const search = request.nextUrl.search;
  const backendPath = `/finance/${path.join("/")}${search}`;
  const method = request.method;
  const hasBody = !["GET", "HEAD"].includes(method);
  const body = hasBody ? await request.text() : undefined;

  try {
    const data = await routeAuthenticatedBackendFetch<unknown>(
      request,
      backendPath,
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
        { detail: error.message },
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
