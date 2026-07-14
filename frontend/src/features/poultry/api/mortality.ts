import { clientApiFetch } from "@/lib/client-api";
import type {
  CreateMortalityPayload,
  PoultryMortality,
} from "../types";

export async function createBatchMortality(
  batchId: number,
  payload: CreateMortalityPayload
): Promise<PoultryMortality> {
  return clientApiFetch<PoultryMortality>(
    `/api/poultry/batches/${batchId}/mortality`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
