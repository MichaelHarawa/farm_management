import { ApiError } from "@/lib/api";
import type {
  CreateMortalityPayload,
  PoultryMortality,
} from "../types";

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

export async function createBatchMortality(
  batchId: number,
  payload: CreateMortalityPayload
): Promise<PoultryMortality> {
  const response = await fetch(`/api/poultry/batches/${batchId}/mortality`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const responseData = await readResponseBody(response);

  if (!response.ok) {
    throw new ApiError(
      "Unable to record mortality.",
      response.status,
      responseData
    );
  }

  return responseData as PoultryMortality;
}
