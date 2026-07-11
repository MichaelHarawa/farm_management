import { NextResponse } from "next/server";

import { poultryApiPaths } from "@/features/poultry/api/paths";
import type { PoultrySale } from "@/features/poultry/types";
import { ApiError, apiFetch } from "@/lib/api";

type RouteContext = {
  params: Promise<{
    id: string;
  }>;
};

export async function POST(request: Request, { params }: RouteContext) {
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
    const sale = await apiFetch<PoultrySale>(poultryApiPaths.sales(batchId), {
      method: "POST",
      body: JSON.stringify(payload),
      cache: "no-store",
    });

    return NextResponse.json(sale, { status: 201 });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(error.details ?? { detail: error.message }, {
        status: error.status,
      });
    }

    throw error;
  }
}
