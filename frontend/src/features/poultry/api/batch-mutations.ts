import { clientApiFetch } from "@/lib/client-api";

import type {
  ConfirmBatchDeliveryPayload,
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

export async function markPoultryBatchDelivered(
  batchId: number
): Promise<PoultryBatch> {
  return clientApiFetch<PoultryBatch>(
    `/api/poultry/batches/${batchId}/mark-delivered`,
    {
      method: "POST",
      body: JSON.stringify({ status: "delivered" }),
    }
  );
}

export async function confirmPoultryBatchDelivery(
  batchId: number,
  payload: ConfirmBatchDeliveryPayload
): Promise<PoultryBatch> {
  return clientApiFetch<PoultryBatch>(
    `/api/poultry/batches/${batchId}/confirm-delivery`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
