import "server-only";

import {
  authenticatedBackendFetch,
} from "@/features/auth/server/authenticated-backend";

import type {
  CreatePoultryBatchPayload,
  InputCost,
  PaginatedResponse,
  PoultryBatch,
  PoultryFeedUsage,
  PoultryMortality,
  PoultrySale,
  PoultryVaccination,
} from "../types";

import {
  poultryApiPaths,
} from "./paths";

function normalizeList<T>(
  data: T[] | PaginatedResponse<T>
): T[] {
  if (Array.isArray(data)) {
    return data;
  }

  return data.results;
}

export async function getPoultryBatches(
  returnTo: string
): Promise<PoultryBatch[]> {
  const data = await authenticatedBackendFetch<
    PoultryBatch[] |
    PaginatedResponse<PoultryBatch>
  >(
    poultryApiPaths.batches,
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getPoultryBatch(
  id: number,
  returnTo: string
): Promise<PoultryBatch> {
  return authenticatedBackendFetch<PoultryBatch>(
    poultryApiPaths.batch(id),
    {
      returnTo,
      cache: "no-store",
    }
  );
}

export async function getBatchInputCosts(
  id: number,
  returnTo: string
): Promise<InputCost[]> {
  const data = await authenticatedBackendFetch<
    InputCost[] |
    PaginatedResponse<InputCost>
  >(
    poultryApiPaths.inputCosts(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchFeedInputCosts(
  id: number,
  returnTo: string
): Promise<InputCost[]> {
  const data = await authenticatedBackendFetch<
    InputCost[] |
    PaginatedResponse<InputCost>
  >(
    poultryApiPaths.feedInputCosts(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchSales(
  id: number,
  returnTo: string
): Promise<PoultrySale[]> {
  const data = await authenticatedBackendFetch<
    PoultrySale[] |
    PaginatedResponse<PoultrySale>
  >(
    poultryApiPaths.sales(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchMortality(
  id: number,
  returnTo: string
): Promise<PoultryMortality[]> {
  const data = await authenticatedBackendFetch<
    PoultryMortality[] |
    PaginatedResponse<PoultryMortality>
  >(
    poultryApiPaths.mortality(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchFeedUsage(
  id: number,
  returnTo: string
): Promise<PoultryFeedUsage[]> {
  const data = await authenticatedBackendFetch<
    PoultryFeedUsage[] |
    PaginatedResponse<PoultryFeedUsage>
  >(
    poultryApiPaths.feedUsage(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function getBatchVaccinations(
  id: number,
  returnTo: string
): Promise<PoultryVaccination[]> {
  const data = await authenticatedBackendFetch<
    PoultryVaccination[] |
    PaginatedResponse<PoultryVaccination>
  >(
    poultryApiPaths.vaccinations(id),
    {
      returnTo,
      cache: "no-store",
    }
  );

  return normalizeList(data);
}

export async function createPoultryBatch(
  payload: CreatePoultryBatchPayload,
  returnTo: string
): Promise<PoultryBatch> {
  return authenticatedBackendFetch<PoultryBatch>(
    poultryApiPaths.batches,
    {
      returnTo,
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}
