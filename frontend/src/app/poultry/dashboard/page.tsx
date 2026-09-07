import Link from "next/link";

import { getPoultryDashboard } from "@/features/poultry/api/batches";

import PoultryDashboardClient from "./PoultryDashboardClient";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function PoultryDashboardPage({ searchParams }: { searchParams: SearchParams }) {
  const requested = await searchParams;
  const query = new URLSearchParams();
  Object.entries(requested).forEach(([key, value]) => {
    (Array.isArray(value) ? value : value ? [value] : []).forEach((item) => query.append(key, item));
  });
  const dashboard = await getPoultryDashboard(
    `/poultry/dashboard${query.size ? `?${query}` : ""}`,
    query.size ? `?${query}` : ""
  );

  return (
    <main className="min-h-screen bg-[var(--page-cream)] text-[var(--navy)]">
      <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8">
        <div className="mb-7 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <Link
              href="/poultry"
              className="text-sm font-bold uppercase tracking-wide hover:underline"
            >
              ← Back to Poultry Register
            </Link>
            <p className="text-label mt-6 text-[var(--navy-muted)]">
              Poultry Intelligence / Live Operations
            </p>
            <h1 className="font-display mt-3 text-5xl leading-none">
              Poultry dashboard.
            </h1>
            <p className="mt-4 max-w-3xl text-[var(--navy-muted)]">
              Period activity, current flock balances, growth, feed, sales, and batch economics in one operating view.
            </p>
          </div>
          <Link href="/poultry" className="finance-button whitespace-nowrap">
            View all batches
          </Link>
        </div>

        <PoultryDashboardClient dashboard={dashboard} />
      </div>
    </main>
  );
}
