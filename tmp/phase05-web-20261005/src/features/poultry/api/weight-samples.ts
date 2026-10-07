import "server-only";

import {
  authenticatedBackendFetch,
} from "@/features/auth/server/authenticated-backend";

import type {
  CreateWeightSamplePayload,
  PoultryWeightSample,
  WeightSamplesResponse,
} from "../types";

import {
  poultryApiPaths,
} from "./paths";

export async function getBatchWeightSamples(
  id: number,
  returnTo: string
): Promise<WeightSamplesResponse> {
  return authenticatedBackendFetch<WeightSamplesResponse>(
    poultryApiPaths.weightSamples(id),
    {
      returnTo,
      cache: "no-store",
    }
  );
}

export async function createWeightSample(
  batchId: number,
  payload: CreateWeightSamplePayload,
  returnTo: string
): Promise<PoultryWeightSample> {
  return authenticatedBackendFetch<PoultryWeightSample>(
    poultryApiPaths.weightSamples(batchId),
    {
      returnTo,
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
