import {
  clientApiFetch,
} from "@/lib/client-api";

import type {
  CreateInputCostPayload,
  InputCost,
} from "../types";

export async function createBatchInputCost(
  batchId: number,
  payload: CreateInputCostPayload
): Promise<InputCost> {
  return clientApiFetch<InputCost>(
    `/api/poultry/batches/${batchId}/input-costs`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}