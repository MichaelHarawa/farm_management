import { NextRequest, NextResponse } from "next/server";

import {
  RouteAuthenticationError,
  routeAuthenticatedBackendFetch,
} from "@/features/auth/server/route-authenticated-backend";
import { BackendApiError } from "@/lib/server/backend-api";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const backendPath = `/auth/administration/${path.join("/")}/${request.nextUrl.search}`;
  const method = request.method;
  try {
    const data = await routeAuthenticatedBackendFetch<unknown>(request, backendPath, {
      method,
      body: ["GET", "HEAD"].includes(method) ? undefined : (await request.text()) || undefined,
      cache: "no-store",
    });
    return NextResponse.json(data, { status: method === "POST" ? 201 : 200 });
  } catch (error) {
    if (error instanceof RouteAuthenticationError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    if (error instanceof BackendApiError) {
      return NextResponse.json(error.details ?? { detail: error.message }, { status: error.status });
    }
    throw error;
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
