import { clientApiFetch } from "@/lib/client-api";
import type { CreateSalePayload, PoultrySale } from "../types";

export async function createBatchSale(
  batchId: number,
  payload: CreateSalePayload
): Promise<PoultrySale> {
  return clientApiFetch<PoultrySale>(
    `/api/poultry/batches/${batchId}/sales`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
