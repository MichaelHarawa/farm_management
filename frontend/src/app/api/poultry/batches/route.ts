import { NextResponse } from "next/server";

import { poultryApiPaths } from "@/features/poultry/api/paths";
import type { PoultryBatch } from "@/features/poultry/types";
import { ApiError, apiFetch } from "@/lib/api";

export async function POST(request: Request) {
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
    const batch = await apiFetch<PoultryBatch>(poultryApiPaths.batches, {
      method: "POST",
      body: JSON.stringify(payload),
      cache: "no-store",
    });

    return NextResponse.json(batch, { status: 201 });
  } catch (error) {
    if (error instanceof ApiError) {
      return NextResponse.json(error.details ?? { detail: error.message }, {
        status: error.status,
      });
    }

    throw error;
  }
}
