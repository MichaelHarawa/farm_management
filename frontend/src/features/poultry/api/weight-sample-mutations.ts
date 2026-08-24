import { clientApiFetch } from "@/lib/client-api";

import type {
  CreateWeightSamplePayload,
  PoultryWeightSample,
  WeightSamplesResponse,
} from "../types";

export async function createWeightSample(
  batchId: number,
  payload: CreateWeightSamplePayload
): Promise<PoultryWeightSample> {
  return clientApiFetch<PoultryWeightSample>(
    `/api/poultry/batches/${batchId}/weight-samples`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export async function getBatchWeightSamples(
  batchId: number
): Promise<WeightSamplesResponse> {
  return clientApiFetch<WeightSamplesResponse>(
    `/api/poultry/batches/${batchId}/weight-samples`,
    {
      method: "GET",
    }
  );
}
