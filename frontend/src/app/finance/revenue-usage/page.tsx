"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { clientApiFetch } from "@/lib/client-api";
import { formatCurrency, formatPercent } from "@/features/finance/utils/formatters";
import type { BatchRevenueUtilization, CrossBatchFlow } from "@/features/finance/types";

type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };

export default function RevenueUsagePage() {
  const [summaries, setSummaries] = useState<Page<BatchRevenueUtilization> | null>(null);
  const [flows, setFlows] = useState<Page<CrossBatchFlow> | null>(null);
  const [page, setPage] = useState(1);
  const [flowPage, setFlowPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      clientApiFetch<Page<BatchRevenueUtilization>>(`/api/finance/reports/revenue-utilization?page=${page}&page_size=10`),
      clientApiFetch<Page<CrossBatchFlow>>(`/api/finance/reports/cross-batch-financing?page=${flowPage}&page_size=10`),
    ]).then(([summaryData, flowData]) => {
      if (!active) return;
      setSummaries(summaryData);
      setFlows(flowData);
      setError(null);
    }).catch((requestError: unknown) => {
      if (active) setError(requestError instanceof Error ? requestError.message : "Unable to load revenue usage.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [page, flowPage]);

  const changePage = (setter: (page: number) => void) => (nextPage: number) => {
    setLoading(true);
    setter(nextPage);
  };

  return (
    <main className="bg-[var(--page-cream)] px-5 py-8 sm:px-8">
      <div className="mx-auto max-w-7xl">
        <Link href="/finance" className="text-sm font-bold underline">← Finance overview</Link>
        <h1 className="font-display mt-4 text-5xl text-[var(--navy)]">Revenue utilization.</h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--navy-muted)]">Funding source shows where cash came from. Cost allocation separately identifies the batch or farm activity bearing the cost.</p>
        {error ? <p role="alert" className="mt-5 rounded-lg bg-red-50 p-4 text-red-800">{error}</p> : null}
        {loading ? <p className="mt-8">Loading paginated finance records…</p> : null}

        {!loading && summaries ? <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
          <h2 className="text-xl font-extrabold">Batch collection summaries</h2>
          <div className="mt-4 overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="border-b text-left"><th className="p-3">Batch</th><th className="p-3 text-right">Collected</th><th className="p-3 text-right">Spent</th><th className="p-3 text-right">Available</th><th className="p-3 text-right">Use</th><th className="p-3">Action</th></tr></thead><tbody>
            {summaries.results.map((row) => <tr key={row.batch_id} className="border-b"><td className="p-3 font-bold">{row.batch_code}</td><td className="p-3 text-right">{formatCurrency(row.cash_collected)}</td><td className="p-3 text-right">{formatCurrency(row.cash_used)}</td><td className="p-3 text-right">{formatCurrency(row.available_cash)}</td><td className="p-3 text-right">{formatPercent(row.utilization_percent)}</td><td className="p-3"><Link className="font-bold underline" href={`/finance/revenue-usage/${row.batch_id}`}>View transactions</Link></td></tr>)}
            {!summaries.results.length ? <tr><td colSpan={6} className="p-6 text-center">No batch collection records.</td></tr> : null}
          </tbody></table></div>
          <Pager page={page} count={summaries.count} pageSize={10} onPage={changePage(setPage)} />
        </section> : null}

        {!loading && flows ? <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
          <h2 className="text-xl font-extrabold">Cross-batch financing</h2>
          <div className="mt-4 overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="border-b text-left"><th className="p-3">Funding batch</th><th className="p-3">Expenditure</th><th className="p-3">Cost-bearing batch</th><th className="p-3 text-right">Cash used</th><th className="p-3 text-right">Cost allocated</th><th className="p-3">Date</th></tr></thead><tbody>
            {flows.results.map((row, index) => <tr key={`${row.expenditure_id}-${row.allocated_to_batch_id}-${index}`} className="border-b"><td className="p-3 font-bold">{row.funding_batch_code}</td><td className="p-3"><Link href={`/finance/expenditures/${row.expenditure_id}`} className="underline">{row.expenditure_desc}</Link></td><td className="p-3">Batch #{row.allocated_to_batch_id}</td><td className="p-3 text-right">{formatCurrency(row.amount_funded)}</td><td className="p-3 text-right">{formatCurrency(row.allocated_amount)}</td><td className="p-3">{row.date}</td></tr>)}
            {!flows.results.length ? <tr><td colSpan={6} className="p-6 text-center">No cross-batch flows.</td></tr> : null}
          </tbody></table></div>
          <Pager page={flowPage} count={flows.count} pageSize={10} onPage={changePage(setFlowPage)} />
        </section> : null}
      </div>
    </main>
  );
}

function Pager({ page, count, pageSize, onPage }: { page: number; count: number; pageSize: number; onPage: (page: number) => void }) {
  const pages = Math.max(Math.ceil(count / pageSize), 1);
  const numbers = Array.from({ length: Math.min(pages, 5) }, (_, index) => Math.min(Math.max(page - 2, 1) + index, pages)).filter((value, index, list) => list.indexOf(value) === index);
  return <nav aria-label="Pagination" className="mt-5 flex flex-wrap items-center gap-2"><button disabled={page === 1} onClick={() => onPage(1)} className="rounded border px-3 py-2 disabled:opacity-40">First</button><button disabled={page === 1} onClick={() => onPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Previous</button>{numbers.map((number) => <button key={number} aria-current={number === page ? "page" : undefined} onClick={() => onPage(number)} className={`rounded border px-3 py-2 ${number === page ? "bg-[var(--navy)] text-white" : ""}`}>{number}</button>)}<button disabled={page === pages} onClick={() => onPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button><button disabled={page === pages} onClick={() => onPage(pages)} className="rounded border px-3 py-2 disabled:opacity-40">Last</button><span className="ml-2 text-sm text-[var(--navy-muted)]">{count} records</span></nav>;
}
