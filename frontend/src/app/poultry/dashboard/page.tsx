import Link from "next/link";
import {
  getPoultryBatches,
  getBatchSales,
  getBatchMortality,
  getBatchFeedUsage,
} from "@/features/poultry/api/batches";
import type { PoultryBatch, PoultrySale, PoultryMortality, PoultryFeedUsage } from "@/features/poultry/types";
import PoultryDashboardClient from "./PoultryDashboardClient";

export default async function PoultryDashboardPage() {
  const batches = await getPoultryBatches("/poultry/dashboard");
  const productionBatches = batches.filter(
    (b) => b.status !== "booked" && b.status !== "delivered"
  );

  // Fetch real data for all batches (live from DB via API)
  const [salesArrays, mortArrays, feedArrays] = await Promise.all([
    Promise.all(
      batches.map(async (b) => {
        try {
          return await getBatchSales(b.id, "/poultry/dashboard");
        } catch {
          return [] as PoultrySale[];
        }
      })
    ),
    Promise.all(
      batches.map(async (b) => {
        try {
          return await getBatchMortality(b.id, "/poultry/dashboard");
        } catch {
          return [] as PoultryMortality[];
        }
      })
    ),
    Promise.all(
      batches.map(async (b) => {
        try {
          return await getBatchFeedUsage(b.id, "/poultry/dashboard");
        } catch {
          return [] as PoultryFeedUsage[];
        }
      })
    ),
  ]);

  const allSales = salesArrays.flat();
  const allMortalities = mortArrays.flat();
  const allFeedUsages = feedArrays.flat();

  return (
    <main className="min-h-screen bg-[#f6f3eb] text-[#151926]">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <Link href="/poultry" className="text-sm font-bold uppercase tracking-wide text-[#151926] hover:underline">
              ← Back to Poultry Register
            </Link>
            <h1 className="mt-2 text-4xl font-extrabold tracking-[-0.02em]">Flock Dashboard</h1>
            <p className="text-[#747b8d]">Aggregated visuals across batches • Sales, mortality, feed, growth &amp; more</p>
          </div>
          <Link href="/poultry" className="rounded-lg bg-[#151f36] px-4 py-2 text-sm font-bold text-white">View All Batches</Link>
        </div>

        <PoultryDashboardClient
          batches={batches}
          productionBatches={productionBatches}
          allSales={allSales}
          allMortalities={allMortalities}
          allFeedUsages={allFeedUsages}
        />
      </div>
    </main>
  );
}
