import { ApiError, apiFetch } from "@/lib/api";
import type {
  CreatePoultryBatchPayload,
  InputCost,
  PaginatedResponse,
  PoultryBatch,
  PoultrySale,
} from "../types";
import { poultryApiPaths } from "./paths";

function normalizeList<T>(
  data: T[] | PaginatedResponse<T>
): T[] {
  if (Array.isArray(data)) {
    return data;
  }

  return data.results;
}

async function readResponseBody(response: Response): Promise<unknown> {
  const bodyText = await response.text();

  if (!bodyText) {
    return null;
  }

  try {
    return JSON.parse(bodyText) as unknown;
  } catch {
    return bodyText;
  }
}

export async function getPoultryBatches(): Promise<PoultryBatch[]> {
  const data = await apiFetch<
    PoultryBatch[] | PaginatedResponse<PoultryBatch>
  >(poultryApiPaths.batches, {
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getPoultryBatch(
  id: number
): Promise<PoultryBatch> {
  return apiFetch<PoultryBatch>(
    poultryApiPaths.batch(id),
    {
      cache: "no-store",
    }
  );
}

export async function getBatchInputCosts(
  id: number
): Promise<InputCost[]> {
  const data = await apiFetch<
    InputCost[] | PaginatedResponse<InputCost>
  >(poultryApiPaths.inputCosts(id), {
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getBatchSales(
  id: number
): Promise<PoultrySale[]> {
  const data = await apiFetch<
    PoultrySale[] | PaginatedResponse<PoultrySale>
  >(poultryApiPaths.sales(id), {
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function createPoultryBatch(
  payload: CreatePoultryBatchPayload
): Promise<PoultryBatch> {
  const response = await fetch("/api/poultry/batches", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const responseData = await readResponseBody(response);

  if (!response.ok) {
    throw new ApiError(
      "Unable to create poultry batch.",
      response.status,
      responseData
    );
  }

  return responseData as PoultryBatch;
}
