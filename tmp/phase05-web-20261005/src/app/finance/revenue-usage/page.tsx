"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type {
  BatchFundingMix,
  BatchRevenueUtilization,
  CrossBatchFlow,
} from "@/features/finance/types";
import {
  formatCurrency,
  formatPercent,
  parseDecimal,
} from "@/features/finance/utils/formatters";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";
import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { BackLink } from "@/components/ui";

type Page<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export default function RevenueUsagePage() {
  const [mixes, setMixes] = useState<Page<BatchFundingMix> | null>(null);
  const [summaries, setSummaries] = useState<Page<BatchRevenueUtilization> | null>(null);
  const [flows, setFlows] = useState<Page<CrossBatchFlow> | null>(null);
  const [mixPage, setMixPage] = useState(1);
  const [summaryPage, setSummaryPage] = useState(1);
  const [flowPage, setFlowPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      clientApiFetch<Page<BatchFundingMix>>(
        `/api/finance/reports/batch-funding-mix?page=${mixPage}&page_size=10`,
      ),
      clientApiFetch<Page<BatchRevenueUtilization>>(
        `/api/finance/reports/revenue-utilization?page=${summaryPage}&page_size=10`,
      ),
      clientApiFetch<Page<CrossBatchFlow>>(
        `/api/finance/reports/cross-batch-financing?page=${flowPage}&page_size=10`,
      ),
    ])
      .then(([mixData, summaryData, flowData]) => {
        if (!active) return;
        setMixes(mixData);
        setSummaries(summaryData);
        setFlows(flowData);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (active) setError(getApiErrorMessage(requestError));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [flowPage, mixPage, summaryPage]);

  return (
    <main className="bg-[var(--page-cream)] px-5 py-8 sm:px-8">
      <div className="mx-auto max-w-7xl">
        <BackLink href="/finance">Finance overview</BackLink>
        <div className="mt-5 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="finance-eyebrow">Finance / Funding and expenditure use</p>
            <h1 className="font-display mt-3 text-4xl text-[var(--navy)] sm:text-5xl">
              Track where batch money comes from and goes.
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--navy-muted)]">
              Review which sources paid each batch&apos;s expenditures, and separately see how each batch&apos;s collected sales cash was spent.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/finance/expenditures" className="finance-button">
              View all expenditures
            </Link>
            <Link href="/finance/expenditures/new" className="rounded-lg border border-[var(--navy)] bg-white px-5 py-3 font-bold text-[var(--navy)]">
              Record expenditure
            </Link>
          </div>
        </div>

        {error ? <p role="alert" className="mt-5 rounded-lg bg-red-50 p-4 text-red-800">{error}</p> : null}
        {loading ? <p className="mt-8">Loading funding and expenditure records…</p> : null}

        {!loading && mixes ? (
          <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
            <div className="max-w-3xl">
              <p className="finance-eyebrow">Cost-bearing view</p>
              <h2 className="mt-2 text-2xl font-extrabold">How each batch&apos;s expenditures were funded</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--navy-muted)]">
                This is the view for questions such as: “Did Batch 1 use 60% from other batches&apos; sales and 40% from owner capital or another source?”
              </p>
            </div>
            <MobileRecordList className="mt-5" records={mixes.results.map((row) => ({
              key: row.batch_id,
              title: row.batch_code,
              subtitle: `${formatPercent(row.funding_coverage_percent)} of expenditure traced to payment sources`,
              badge: <span className="rounded-full bg-[var(--gold-soft)] px-2 py-1 text-xs font-bold">{formatCurrency(row.total_batch_expenditure)}</span>,
              fields: [
                { label: "Paid / traced", value: formatCurrency(row.total_paid_for_batch) },
                { label: "Own sales", value: `${formatCurrency(row.own_batch_sales)} · ${formatPercent(row.own_batch_sales_percent)}` },
                { label: "Other batch sales", value: `${formatCurrency(row.other_batch_sales)} · ${formatPercent(row.other_batch_sales_percent)}` },
                { label: "Owner capital", value: `${formatCurrency(row.owner_capital)} · ${formatPercent(row.owner_capital_percent)}` },
                { label: "Other funds", value: `${formatCurrency(row.non_owner_sources)} · ${formatPercent(row.non_owner_sources_percent)}` },
                { label: "Funding mix", value: <FundingMixBar row={row} /> },
              ],
              actions: <Link className="w-full rounded-lg bg-[var(--navy)] px-4 py-3 text-center font-bold text-white" href={`/finance/revenue-usage/${row.batch_id}`}>View funding and expenditures</Link>,
            }))} emptyMessage="No poultry batches are available." />
            <div className="mt-5 hidden overflow-x-auto md:block">
              <table className="w-full min-w-[1120px] text-sm">
                <thead>
                  <tr className="border-b text-left">
                    <th className="p-3">Cost-bearing batch</th>
                    <th className="p-3 text-right">Batch expenditure</th>
                    <th className="p-3 text-right">Paid / traced</th>
                    <th className="p-3 text-right">Own sales</th>
                    <th className="p-3 text-right">Other batch sales</th>
                    <th className="p-3 text-right">Owner capital</th>
                    <th className="p-3 text-right">Other non-sales funds</th>
                    <th className="p-3">Funding mix</th>
                    <th className="p-3">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {mixes.results.map((row) => (
                    <tr key={row.batch_id} className="border-b align-top">
                      <td className="p-3 font-bold">{row.batch_code}</td>
                      <td className="p-3 text-right">{formatCurrency(row.total_batch_expenditure)}</td>
                      <td className="p-3 text-right">
                        {formatCurrency(row.total_paid_for_batch)}
                        <span className="block text-xs text-[var(--navy-muted)]">{formatPercent(row.funding_coverage_percent)} covered</span>
                      </td>
                      <td className="p-3 text-right">{formatCurrency(row.own_batch_sales)}<span className="block text-xs">{formatPercent(row.own_batch_sales_percent)}</span></td>
                      <td className="p-3 text-right">{formatCurrency(row.other_batch_sales)}<span className="block text-xs">{formatPercent(row.other_batch_sales_percent)}</span></td>
                      <td className="p-3 text-right">{formatCurrency(row.owner_capital)}<span className="block text-xs">{formatPercent(row.owner_capital_percent)}</span></td>
                      <td className="p-3 text-right">{formatCurrency(row.non_owner_sources)}<span className="block text-xs">{formatPercent(row.non_owner_sources_percent)}</span></td>
                      <td className="w-52 p-3"><FundingMixBar row={row} /></td>
                      <td className="p-3"><Link className="font-bold underline" href={`/finance/revenue-usage/${row.batch_id}`}>View funding and expenditures</Link></td>
                    </tr>
                  ))}
                  {!mixes.results.length ? <tr><td colSpan={9} className="p-6 text-center">No poultry batches are available.</td></tr> : null}
                </tbody>
              </table>
            </div>
            <Pager page={mixPage} count={mixes.count} pageSize={10} onPage={setMixPage} />
          </section>
        ) : null}

        {!loading && summaries ? (
          <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
            <p className="finance-eyebrow">Cash-source view</p>
            <h2 className="mt-2 text-2xl font-extrabold">How each batch&apos;s sales collections were used</h2>
            <p className="mt-2 text-sm text-[var(--navy-muted)]">This follows cash outward from the batch that generated it, even when another batch bears the cost.</p>
            <MobileRecordList className="mt-4" records={summaries.results.map((row) => ({ key: row.batch_id, title: row.batch_code, subtitle: `${formatPercent(row.utilization_percent)} of collections used`, badge: <span className="rounded-full bg-green-50 px-2 py-1 text-xs font-bold text-green-800">{formatCurrency(row.available_cash)} available</span>, fields: [{ label: "Collected", value: formatCurrency(row.cash_collected) }, { label: "Spent", value: formatCurrency(row.cash_used) }], actions: <Link className="w-full rounded-lg bg-[var(--navy)] px-4 py-3 text-center font-bold text-white" href={`/finance/revenue-usage/${row.batch_id}`}>View cash use</Link> }))} emptyMessage="No batch collection records." />
            <div className="mt-4 hidden overflow-x-auto md:block"><table className="min-w-full text-sm"><thead><tr className="border-b text-left"><th className="p-3">Funding batch</th><th className="p-3 text-right">Collected</th><th className="p-3 text-right">Spent</th><th className="p-3 text-right">Available</th><th className="p-3 text-right">Use</th><th className="p-3">Action</th></tr></thead><tbody>
              {summaries.results.map((row) => <tr key={row.batch_id} className="border-b"><td className="p-3 font-bold">{row.batch_code}</td><td className="p-3 text-right">{formatCurrency(row.cash_collected)}</td><td className="p-3 text-right">{formatCurrency(row.cash_used)}</td><td className="p-3 text-right">{formatCurrency(row.available_cash)}</td><td className="p-3 text-right">{formatPercent(row.utilization_percent)}</td><td className="p-3"><Link className="font-bold underline" href={`/finance/revenue-usage/${row.batch_id}`}>View cash use</Link></td></tr>)}
              {!summaries.results.length ? <tr><td colSpan={6} className="p-6 text-center">No batch collection records.</td></tr> : null}
            </tbody></table></div>
            <Pager page={summaryPage} count={summaries.count} pageSize={10} onPage={setSummaryPage} />
          </section>
        ) : null}

        {!loading && flows ? (
          <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
            <h2 className="text-xl font-extrabold">Cross-batch financing</h2>
            <p className="mt-2 text-sm text-[var(--navy-muted)]">Sales cash from one batch paying an expenditure whose cost belongs to another batch.</p>
            <MobileRecordList className="mt-4" records={flows.results.map((row, index) => ({ key: `${row.expenditure_id}-${row.allocated_to_batch_id}-${index}`, title: row.funding_batch_code, subtitle: row.expenditure_desc, fields: [{ label: "Cost-bearing batch", value: row.allocated_to_batch_code }, { label: "Cash used", value: formatCurrency(row.amount_funded) }, { label: "Cost allocated", value: formatCurrency(row.allocated_amount) }, { label: "Date", value: row.date }], actions: <Link className="w-full rounded-lg border border-[var(--navy)] px-4 py-3 text-center font-bold" href={`/finance/expenditures/${row.expenditure_id}`}>View expenditure</Link> }))} emptyMessage="No cross-batch flows." />
            <div className="mt-4 hidden overflow-x-auto md:block"><table className="min-w-full text-sm"><thead><tr className="border-b text-left"><th className="p-3">Funding batch</th><th className="p-3">Expenditure</th><th className="p-3">Cost-bearing batch</th><th className="p-3 text-right">Cash used</th><th className="p-3 text-right">Cost allocated</th><th className="p-3">Date</th></tr></thead><tbody>
              {flows.results.map((row, index) => <tr key={`${row.expenditure_id}-${row.allocated_to_batch_id}-${index}`} className="border-b"><td className="p-3 font-bold">{row.funding_batch_code}</td><td className="p-3"><Link href={`/finance/expenditures/${row.expenditure_id}`} className="underline">{row.expenditure_desc}</Link></td><td className="p-3">{row.allocated_to_batch_code}</td><td className="p-3 text-right">{formatCurrency(row.amount_funded)}</td><td className="p-3 text-right">{formatCurrency(row.allocated_amount)}</td><td className="p-3">{row.date}</td></tr>)}
              {!flows.results.length ? <tr><td colSpan={6} className="p-6 text-center">No cross-batch flows.</td></tr> : null}
            </tbody></table></div>
            <Pager page={flowPage} count={flows.count} pageSize={10} onPage={setFlowPage} />
          </section>
        ) : null}
      </div>
    </main>
  );
}

function FundingMixBar({ row }: { row: BatchFundingMix }) {
  const own = parseDecimal(row.own_batch_sales_percent);
  const crossBatch = parseDecimal(row.other_batch_sales_percent);
  const owner = parseDecimal(row.owner_capital_percent);
  const other = parseDecimal(row.non_owner_sources_percent);
  if (own + crossBatch + owner + other === 0) return <span className="text-xs text-[var(--navy-muted)]">No paid source recorded</span>;
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-[#ebe7dc]" title={`Own sales ${own}% · Other batch sales ${crossBatch}% · Owner capital ${owner}% · Other funds ${other}%`}>
        <span className="bg-[#4e8b61]" style={{ width: `${own}%` }} />
        <span className="bg-[var(--gold)]" style={{ width: `${crossBatch}%` }} />
        <span className="bg-[#7655a3]" style={{ width: `${owner}%` }} />
        <span className="bg-[var(--navy)]" style={{ width: `${other}%` }} />
      </div>
      <p className="mt-2 text-xs leading-5 text-[var(--navy-muted)]">Green: own sales · Gold: other batch sales · Purple: owner capital · Navy: other funds</p>
    </div>
  );
}

function Pager({ page, count, pageSize, onPage }: { page: number; count: number; pageSize: number; onPage: (page: number) => void }) {
  const pages = Math.max(Math.ceil(count / pageSize), 1);
  const numbers = Array.from({ length: Math.min(pages, 5) }, (_, index) => Math.min(Math.max(page - 2, 1) + index, pages)).filter((value, index, list) => list.indexOf(value) === index);
  return <nav aria-label="Pagination" className="mt-5 flex flex-wrap items-center gap-2"><button disabled={page === 1} onClick={() => onPage(1)} className="rounded border px-3 py-2 disabled:opacity-40">First</button><button disabled={page === 1} onClick={() => onPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Previous</button>{numbers.map((number) => <button key={number} aria-current={number === page ? "page" : undefined} onClick={() => onPage(number)} className={`rounded border px-3 py-2 ${number === page ? "bg-[var(--navy)] text-white" : ""}`}>{number}</button>)}<button disabled={page === pages} onClick={() => onPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button><button disabled={page === pages} onClick={() => onPage(pages)} className="rounded border px-3 py-2 disabled:opacity-40">Last</button><span className="ml-2 text-sm text-[var(--navy-muted)]">{count} records</span></nav>;
}
