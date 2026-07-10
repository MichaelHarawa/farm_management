import { apiFetch } from "@/lib/api";
import type {
  CreatePoultryBatchPayload,
  PaginatedResponse,
  PoultryBatch,
} from "../types";

const POULTRY_BATCHES_PATH = "/poultry-management/";

function normalizeBatchList( // to support both payloads either paginated or not
  data: PoultryBatch[] | PaginatedResponse<PoultryBatch>
): PoultryBatch[] {
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

  return normalizeBatchList(data);
}

export async function getPoultryBatch(id: number): Promise<PoultryBatch> {
  return apiFetch<PoultryBatch>(`${POULTRY_BATCHES_PATH}${id}/`, {
    cache: "no-store",
  });
}

export async function createPoultryBatch(
  payload: CreatePoultryBatchPayload
): Promise<PoultryBatch> {
  return apiFetch<PoultryBatch>(POULTRY_BATCHES_PATH, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}