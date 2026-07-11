import { apiFetch } from "@/lib/api";
import type {
  CreateInputCostPayload,
  InputCost,
} from "../types";
import { poultryApiPaths } from "./paths";

export async function createBatchInputCost(
  batchId: number,
  payload: CreateInputCostPayload
): Promise<InputCost> {
  return apiFetch<InputCost>(
    poultryApiPaths.inputCosts(batchId),
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}