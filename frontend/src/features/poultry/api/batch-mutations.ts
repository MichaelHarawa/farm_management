import { clientApiFetch } from "@/lib/client-api";

import type {
  CreatePoultryBatchPayload,
  PoultryBatch,
} from "../types";

export async function createPoultryBatch(
  payload: CreatePoultryBatchPayload
): Promise<PoultryBatch> {
  return clientApiFetch<PoultryBatch>(
    "/api/poultry/batches",
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
