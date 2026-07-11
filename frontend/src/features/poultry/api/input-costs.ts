import { ApiError } from "@/lib/api";
import type {
  CreateInputCostPayload,
  InputCost,
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

export async function createBatchInputCost(
  batchId: number,
  payload: CreateInputCostPayload
): Promise<InputCost> {
  const response = await fetch(
    `/api/poultry/batches/${batchId}/input-costs`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  );

  const responseData = await readResponseBody(response);

  if (!response.ok) {
    throw new ApiError(
      "Unable to record input cost.",
      response.status,
      responseData
    );
  }

  return responseData as InputCost;
}
