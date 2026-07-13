import { notFound } from "next/navigation";
import {
  getBatchFeedUsage,
  getBatchInputCosts,
  getBatchMortality,
  getBatchSales,
  getBatchVaccinations,
  getPoultryBatch,
} from "@/features/poultry/api/batches";
import { BatchDetailView } from "@/features/poultry/components/BatchDetailView";
import type { PoultryBatch } from "@/features/poultry/types";
import { ApiError } from "@/lib/api";

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

  if (!Number.isInteger(batchId) || batchId <= 0) {
    notFound();
  }

  let batch: PoultryBatch;

  try {
    batch = await getPoultryBatch(batchId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }

    throw error;
  }

  const [inputCosts, sales, mortalities, feedUsages, vaccinations] =
    await Promise.all([
    getBatchInputCosts(batchId),
    getBatchSales(batchId),
    getBatchMortality(batchId),
    getBatchFeedUsage(batchId),
    getBatchVaccinations(batchId),
  ]);

  return (
    <BatchDetailView
      batch={batch}
      inputCosts={inputCosts}
      sales={sales}
      mortalities={mortalities}
      feedUsages={feedUsages}
      vaccinations={vaccinations}
    />
  );
}
