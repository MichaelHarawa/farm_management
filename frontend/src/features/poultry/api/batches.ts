import { apiFetch } from "@/lib/api";
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
  return apiFetch<PoultryBatch>(
    poultryApiPaths.batches,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}