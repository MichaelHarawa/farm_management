import { notFound } from "next/navigation";

import {
  getBatchProfitability,
} from "@/features/finance/api/finance";
import {
  getBatchFeedInputCosts,
  getBatchFeedUsage,
  getBatchInputCosts,
  getBatchMortality,
  getBatchSales,
  getBatchVaccinations,
  getPoultryBatch,
} from "@/features/poultry/api/batches";

// NOTE:
// We intentionally do NOT do a top-level static import of "@/features/poultry/api/weight-samples"
// because that module depends on "next/headers" (via authenticated-backend + "server-only").
// We load it with a dynamic import *inside* the server component function below.

// IMPORTANT: weight samples initial data must be fetched via dynamic import only.
// The module "@/features/poultry/api/weight-samples" uses next/headers (via authenticated-backend + "server-only").
// Static import from any client-reachable file (or the page module top-level) produces the build error you saw.

import {
  BatchDetailView,
  type BatchDetailTab,
} from "@/features/poultry/components/BatchDetailView";

import type {
  WeightSamplesResponse,
} from "@/features/poultry/types";

import type {
  PoultryBatch,
} from "@/features/poultry/types";

import {
  BackendApiError,
} from "@/lib/server/backend-api";

type BatchDetailPageProps = {
  params: Promise<{
    id: string;
  }>;
  searchParams: Promise<{
    tab?: string;
  }>;
};

const batchDetailTabs: BatchDetailTab[] = [
  "overview",
  "flock",
  "costs",
  "sales",
  "mortality",
  "feed",
  "vaccination",
  "growth",
];

export default async function BatchDetailPage({
  params,
  searchParams,
}: BatchDetailPageProps) {
  const { id } = await params;
  const { tab } = await searchParams;
  const batchId = Number(id);
  const initialTab = batchDetailTabs.includes(tab as BatchDetailTab)
    ? (tab as BatchDetailTab)
    : "overview";

  if (
    !Number.isInteger(batchId) ||
    batchId <= 0
  ) {
    notFound();
  }

  const returnTo =
    `/poultry/batches/${batchId}`;

  let batch: PoultryBatch;

  try {
    batch = await getPoultryBatch(
      batchId,
      returnTo
    );
  } catch (error) {
    if (
      error instanceof BackendApiError &&
      error.status === 404
    ) {
      notFound();
    }

    throw error;
  }

  const [
    inputCosts,
    feedInputCosts,
    sales,
    mortalities,
    feedUsages,
    vaccinations,
  ] = await Promise.all([
      getBatchInputCosts(
        batchId,
        returnTo
      ),
      getBatchFeedInputCosts(
        batchId,
        returnTo
      ),
      getBatchSales(
        batchId,
        returnTo
      ),
      getBatchMortality(
        batchId,
        returnTo
      ),
      getBatchFeedUsage(
        batchId,
        returnTo
      ),
      getBatchVaccinations(
        batchId,
        returnTo
      ),
    ]);

  // Dynamic import here guarantees that "next/headers" is only touched inside a Server Component.
  const { getBatchWeightSamples: fetchWeightSamples } = await import("@/features/poultry/api/weight-samples");
  const weightSamplesResponse = await fetchWeightSamples(batchId, returnTo).catch(() => null);

  const profitabilityReport = await getBatchProfitability(batchId, returnTo).catch(
    (error) => {
      if (
        error instanceof BackendApiError &&
        [403, 404].includes(error.status)
      ) {
        return null;
      }

      throw error;
    }
  );

  return (
    <BatchDetailView
      key={initialTab}
      batch={batch}
      initialTab={initialTab}
      profitabilityReport={profitabilityReport}
      inputCosts={inputCosts}
      feedInputCosts={feedInputCosts}
      sales={sales}
      mortalities={mortalities}
      feedUsages={feedUsages}
      vaccinations={vaccinations}
      weightSamplesResponse={weightSamplesResponse}
    />
  );
}
