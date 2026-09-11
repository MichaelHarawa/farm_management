"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  BatchFundingMix,
  BatchRevenueUtilization,
} from "@/features/finance/types";
import {
  formatCurrency,
  formatDate,
  formatLabel,
  formatPercent,
} from "@/features/finance/utils/formatters";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";

export default function BatchRevenueUsageDetailPage() {
  const params = useParams<{ id: string }>();
  const [cashUse, setCashUse] = useState<BatchRevenueUtilization | null>(null);
  const [fundingMix, setFundingMix] = useState<BatchFundingMix | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cashPage, setCashPage] = useState(1);
  const [mixPage, setMixPage] = useState(1);

  useEffect(() => {
    Promise.all([
      clientApiFetch<BatchRevenueUtilization>(
        `/api/finance/reports/batches/${params.id}/revenue-utilization?page=${cashPage}&page_size=20`,
      ),
      clientApiFetch<BatchFundingMix>(
        `/api/finance/reports/batches/${params.id}/funding-mix?page=${mixPage}&page_size=20`,
      ),
    ])
      .then(([cashData, mixData]) => {
        setCashUse(cashData);
        setFundingMix(mixData);
        setError(null);
      })
      .catch((requestError: unknown) => setError(getApiErrorMessage(requestError)));
  }, [cashPage, mixPage, params.id]);

  if (!cashUse || !fundingMix) {
    return <main className="p-8">{error || "Loading funding and expenditure use…"}</main>;
  }

  return (
    <main className="mx-auto max-w-[1320px] p-5 sm:p-8">
      <Link href="/finance/revenue-usage" className="text-sm font-bold underline">← Funding &amp; Expenditure Use</Link>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="finance-eyebrow">Funding and expenditure / {fundingMix.batch_code}</p>
          <h1 className="mt-2 text-4xl font-extrabold">Batch funding trail</h1>
          <p className="mt-3 max-w-3xl text-[var(--navy-muted)]">Two views kept separate: the sources that paid this batch&apos;s costs, and the expenditures paid from this batch&apos;s own sales collections.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/finance/expenditures" className="finance-button">View all expenditures</Link>
          <Link href="/finance/expenditures/new" className="rounded-lg border border-[var(--navy)] px-5 py-3 font-bold">Record expenditure</Link>
        </div>
      </div>

      <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
        <p className="finance-eyebrow">Cost-bearing view</p>
        <h2 className="mt-2 text-2xl font-extrabold">Sources used to pay {fundingMix.batch_code}&apos;s expenditures</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <Metric label="Batch expenditure" value={formatCurrency(fundingMix.total_batch_expenditure)} detail={`${formatPercent(fundingMix.funding_coverage_percent)} payment source traced`} />
          <Metric label="Own batch sales" value={formatCurrency(fundingMix.own_batch_sales)} detail={formatPercent(fundingMix.own_batch_sales_percent)} />
          <Metric label="Other batch sales" value={formatCurrency(fundingMix.other_batch_sales)} detail={formatPercent(fundingMix.other_batch_sales_percent)} />
          <Metric label="Other sources" value={formatCurrency(fundingMix.other_sources)} detail={formatPercent(fundingMix.other_sources_percent)} />
          <Metric label="Unpaid / unassigned" value={formatCurrency(fundingMix.unpaid_or_unassigned)} detail="Cost not yet linked to a payment source" />
        </div>
        <p className="mt-5 rounded-lg bg-[#f6f3eb] p-4 text-sm leading-6 text-[var(--navy-muted)]">{fundingMix.basis}</p>

        <div className="mt-6 overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">Funding source</th><th className="p-3">Source type</th><th className="p-3">Group</th><th className="p-3 text-right">Used by batch</th><th className="p-3 text-right">Share</th></tr></thead>
            <tbody>
              {fundingMix.sources.map((source) => <tr key={source.funding_source_id} className="border-t"><td className="p-3 font-bold">{source.source_label}</td><td className="p-3">{source.source_type_label}</td><td className="p-3">{formatLabel(source.source_group)}</td><td className="p-3 text-right">{formatCurrency(source.amount)}</td><td className="p-3 text-right font-bold">{formatPercent(source.percent)}</td></tr>)}
              {!fundingMix.sources.length ? <tr><td colSpan={5} className="p-7 text-center text-[var(--navy-muted)]">No payment sources have been assigned to this batch&apos;s expenditures.</td></tr> : null}
            </tbody>
          </table>
        </div>

        <h3 className="mt-7 text-xl font-extrabold">Supporting expenditure allocations</h3>
        <div className="mt-3 overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[1100px] text-sm">
            <thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">Expenditure</th><th className="p-3">Date</th><th className="p-3">Description</th><th className="p-3">Funding source</th><th className="p-3 text-right">Batch cost</th><th className="p-3 text-right">Source payment</th><th className="p-3 text-right">Attributed to batch</th></tr></thead>
            <tbody>
              {fundingMix.transactions.map((transaction) => <tr key={`${transaction.cost_allocation_id}-${transaction.funding_allocation_id}`} className="border-t"><td className="p-3"><Link href={`/finance/expenditures/${transaction.expenditure_id}`} className="font-bold underline">{transaction.expenditure_reference}</Link></td><td className="p-3">{formatDate(transaction.expenditure_date)}</td><td className="p-3">{transaction.description}</td><td className="p-3">{transaction.source_label}</td><td className="p-3 text-right">{formatCurrency(transaction.batch_cost_amount)}</td><td className="p-3 text-right">{formatCurrency(transaction.funding_payment_amount)}</td><td className="p-3 text-right font-bold">{formatCurrency(transaction.attributed_amount)}</td></tr>)}
              {!fundingMix.transactions.length ? <tr><td colSpan={7} className="p-7 text-center text-[var(--navy-muted)]">No funded expenditure allocations recorded.</td></tr> : null}
            </tbody>
          </table>
        </div>
        {fundingMix.transaction_page ? <Pager page={mixPage} pageInfo={fundingMix.transaction_page} onPage={setMixPage} label="funding allocations" /> : null}
      </section>

      <section className="mt-8 rounded-xl border border-[var(--line)] bg-white p-5">
        <p className="finance-eyebrow">Cash-source view</p>
        <h2 className="mt-2 text-2xl font-extrabold">Where {cashUse.batch_code}&apos;s sales cash was spent</h2>
        <section className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Cash collected" value={formatCurrency(cashUse.cash_collected)} />
          <Metric label="Refunded / reversed" value={formatCurrency(cashUse.refunds)} />
          <Metric label="Spent" value={formatCurrency(cashUse.cash_used)} detail={formatPercent(cashUse.utilization_percent)} />
          <Metric label="Remaining cash" value={formatCurrency(cashUse.available_cash)} />
        </section>
        <div className="mt-6 overflow-x-auto rounded-lg border"><table className="min-w-[1180px] w-full text-sm"><thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">Reference</th><th className="p-3">Date</th><th className="p-3">Description</th><th className="p-3">Category</th><th className="p-3">Nature</th><th className="p-3 text-right">Expenditure total</th><th className="p-3 text-right">Funded by batch</th><th className="p-3">Beneficiary / cost bearer</th><th className="p-3">Status</th><th className="p-3 text-right">Cash after</th></tr></thead><tbody>
          {cashUse.transactions.map((transaction) => <tr key={transaction.allocation_id} className="border-t"><td className="p-3"><Link href={`/finance/expenditures/${transaction.expenditure_id}`} className="font-bold underline">{transaction.expenditure_reference}</Link></td><td className="p-3">{formatDate(transaction.date)}</td><td className="p-3">{transaction.description}</td><td className="p-3">{transaction.category}</td><td className="p-3">{formatLabel(transaction.accounting_nature)}</td><td className="p-3 text-right">{formatCurrency(transaction.total_expenditure)}</td><td className="p-3 text-right font-bold">{formatCurrency(transaction.amount)}</td><td className="p-3">{transaction.beneficiary}</td><td className="p-3">{formatLabel(transaction.status)}</td><td className="p-3 text-right font-bold">{formatCurrency(transaction.remaining_cash_after)}</td></tr>)}
          {!cashUse.transactions.length ? <tr><td colSpan={10} className="p-8 text-center text-[var(--navy-muted)]">No posted expenditures have used this batch&apos;s cash.</td></tr> : null}
        </tbody></table></div>
        {cashUse.transaction_page ? <Pager page={cashPage} pageInfo={cashUse.transaction_page} onPage={setCashPage} label="cash-use transactions" /> : null}
      </section>
    </main>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">{label}</p><strong className="mt-2 block text-2xl">{value}</strong>{detail ? <span className="mt-2 block text-xs text-[var(--navy-muted)]">{detail}</span> : null}</div>;
}

function Pager({ page, pageInfo, onPage, label }: { page: number; pageInfo: { count: number; pages: number }; onPage: (page: number) => void; label: string }) {
  if (pageInfo.pages <= 1) return null;
  return <nav aria-label={`${label} pagination`} className="mt-5 flex flex-wrap gap-2"><button disabled={page === 1} onClick={() => onPage(1)} className="rounded border px-3 py-2 disabled:opacity-40">First</button><button disabled={page === 1} onClick={() => onPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Previous</button><span className="self-center px-2 text-sm">Page {page} of {pageInfo.pages}</span><button disabled={page === pageInfo.pages} onClick={() => onPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button><button disabled={page === pageInfo.pages} onClick={() => onPage(pageInfo.pages)} className="rounded border px-3 py-2 disabled:opacity-40">Last</button><span className="self-center text-sm text-[var(--navy-muted)]">{pageInfo.count} {label}</span></nav>;
}
