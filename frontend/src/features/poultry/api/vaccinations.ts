import { ApiError } from "@/lib/api";
import type {
  CreateVaccinationPayload,
  PoultryVaccination,
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

export async function createBatchVaccination(
  batchId: number,
  payload: CreateVaccinationPayload
): Promise<PoultryVaccination> {
  const response = await fetch(`/api/poultry/batches/${batchId}/vaccinations`, {
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
      "Unable to record vaccination.",
      response.status,
      responseData
    );
  }

  return responseData as PoultryVaccination;
}
