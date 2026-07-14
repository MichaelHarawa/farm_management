import { clientApiFetch } from "@/lib/client-api";
import type {
  CreateFeedUsagePayload,
  PoultryFeedUsage,
} from "../types";

export async function createBatchFeedUsage(
  batchId: number,
  payload: CreateFeedUsagePayload
): Promise<PoultryFeedUsage> {
  return clientApiFetch<PoultryFeedUsage>(
    `/api/poultry/batches/${batchId}/feed-usage`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
