import { apiFetch } from "@/lib/api";
import type {
  CreatePoultryBatchPayload,
  InputCost,
  PaginatedResponse,
  PoultryBatch,
  PoultrySale,
} from "../types";

const POULTRY_BATCHES_PATH = "/poultry-management/";

function normalizeList<T>(data: T[] | PaginatedResponse<T>): T[] {
  if (Array.isArray(data)) {
    return data;
  }

  return data.results;
}

export async function getPoultryBatches(): Promise<PoultryBatch[]> {
  const data = await apiFetch<PoultryBatch[] | PaginatedResponse<PoultryBatch>>(
    POULTRY_BATCHES_PATH,
    {
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getPoultryBatch(id: number): Promise<PoultryBatch> {
  return apiFetch<PoultryBatch>(`${POULTRY_BATCHES_PATH}${id}`, {
    cache: "no-store",
  });
}

export async function getBatchInputCosts(id: number): Promise<InputCost[]> {
  const data = await apiFetch<InputCost[] | PaginatedResponse<InputCost>>(
    `${POULTRY_BATCHES_PATH}${id}/input_costs`,
    {
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchSales(id: number): Promise<PoultrySale[]> {
  const data = await apiFetch<PoultrySale[] | PaginatedResponse<PoultrySale>>(
    `${POULTRY_BATCHES_PATH}${id}/sales`,
    {
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function createPoultryBatch(
  payload: CreatePoultryBatchPayload
): Promise<PoultryBatch> {
  return apiFetch<PoultryBatch>(POULTRY_BATCHES_PATH, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}