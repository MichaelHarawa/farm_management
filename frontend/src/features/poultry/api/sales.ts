import { ApiError } from "@/lib/api";
import type { CreateSalePayload, PoultrySale } from "../types";

async function readResponseBody(response: Response): Promise<unknown> {
  const bodyText = await response.text();

  if (!bodyText) {
    return null;
  }

  try {
    return JSON.parse(bodyText) as unknown;
  } catch {
    return bodyText;
  }
}

export async function createBatchSale(
  batchId: number,
  payload: CreateSalePayload
): Promise<PoultrySale> {
  const response = await fetch(`/api/poultry/batches/${batchId}/sales`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const responseData = await readResponseBody(response);

  if (!response.ok) {
    throw new ApiError("Unable to record sale.", response.status, responseData);
  }

  return responseData as PoultrySale;
}
