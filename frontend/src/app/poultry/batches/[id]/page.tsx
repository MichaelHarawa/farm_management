import { notFound } from "next/navigation";

import {
  getBatchFeedInputCosts,
  getBatchFeedUsage,
  getBatchInputCosts,
  getBatchMortality,
  getBatchSales,
  getBatchVaccinations,
  getPoultryBatch,
} from "@/features/poultry/api/batches";

import {
  BatchDetailView,
} from "@/features/poultry/components/BatchDetailView";

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
};

export default async function BatchDetailPage({
  params,
}: BatchDetailPageProps) {
  const { id } = await params;
  const batchId = Number(id);

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

  return (
    <BatchDetailView
      batch={batch}
      inputCosts={inputCosts}
      feedInputCosts={feedInputCosts}
      sales={sales}
      mortalities={mortalities}
      feedUsages={feedUsages}
      vaccinations={vaccinations}
    />
  );
}
