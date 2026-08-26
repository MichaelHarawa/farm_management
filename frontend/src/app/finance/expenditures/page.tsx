"use client";
/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { clientApiFetch } from "@/lib/client-api";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";

type Expenditure = {
  id: number;
  expenditure_date: string;
  amount: string;
  description: string;
  accounting_nature: string;
  status: string;
  farm_module?: string;
  expenditure_reference?: string;
  category?: any;
  external_reference?: string;
  funding_status?: string;
  payment_status?: string;
  origin?: string;
  beneficiary_detail?: string;
  beneficiary_batches?: Array<{ id: number; batch_id: string; amount: string }>;
  funding_allocations?: Array<{ funding_source: number; funding_source_display?: string; amount: string }>;
  balance_due?: string;
};

type PaginatedExpenditures = {
  count: number;
  next: string | null;
  previous: string | null;
  results: Expenditure[];
};

const pageSizes = [10, 25, 50] as const;

export default function FinanceExpendituresClient() {
  const [expenditures, setExpenditures] = useState<Expenditure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [paymentFilter, setPaymentFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof pageSizes)[number]>(10);
  const [totalCount, setTotalCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (debouncedSearch) query.set("search", debouncedSearch);
      if (statusFilter) query.set("status", statusFilter);
      if (paymentFilter) query.set("payment_status", paymentFilter);

      const data = await clientApiFetch<PaginatedExpenditures>(
        `/api/finance/expenditures?${query.toString()}`,
      );
      if (data.results.length === 0 && data.count > 0 && page > 1) {
        setPage((current) => Math.max(1, current - 1));
        return;
      }
      setExpenditures(data.results);
      setTotalCount(data.count);
    } catch (e) {
      console.error(e);
      setError("Could not load expenditures. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [debouncedSearch, page, pageSize, paymentFilter, statusFilter]);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    void load();
  }, [load]);

  const voidExpenditure = async (id: number) => {
    const reason = prompt("Reversal reason?") || "Correction";
    try {
      await clientApiFetch(`/api/finance/expenditures/${id}/void`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await load();
      alert("Posted expenditure reversed.");
    } catch (e: any) {
      alert("Failed to reverse: " + (e?.message || e));
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const pageNumbers = useMemo(() => {
    const start = Math.max(1, Math.min(page - 2, totalPages - 4));
    const end = Math.min(totalPages, start + 4);
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  }, [page, totalPages]);
  const firstResult = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastResult = Math.min(page * pageSize, totalCount);

  const resetToFirstPage = () => setPage(1);

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <Link href="/finance" className="mb-5 inline-block text-sm font-bold underline">← Finance Dashboard</Link>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-extrabold">Expenditures</h1>
        <Link href="/finance/expenditures/new" className="finance-button">+ New Expenditure</Link>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <input aria-label="Search expenditures" placeholder="Search ref or description..." value={search} onChange={e => { setSearch(e.target.value); resetToFirstPage(); }} className="form-input min-w-64 flex-1" />
        <select aria-label="Filter by expenditure status" value={statusFilter} onChange={e => { setStatusFilter(e.target.value); resetToFirstPage(); }} className="form-input">
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="posted">Posted</option>
          <option value="void">Void</option>
        </select>
        <select aria-label="Filter by payment status" value={paymentFilter} onChange={e => { setPaymentFilter(e.target.value); resetToFirstPage(); }} className="form-input">
          <option value="">All payment states</option>
          <option value="paid">Paid</option>
          <option value="partial">Partially paid</option>
          <option value="unpaid">Outstanding payable</option>
          <option value="historical_unassigned">Historical source unassigned</option>
        </select>
      </div>

      {error ? <div role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-800">{error}</div> : null}

      <div className="overflow-hidden rounded-xl border border-[#ddd7c9] bg-white">
        <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-sm">
          <thead className="bg-[#f6f3eb]">
            <tr>
              <th className="p-3 text-left">Ref</th>
              <th className="p-3 text-left">Date</th>
              <th className="p-3 text-left">Description</th>
              <th className="p-3 text-right">Amount</th>
              <th className="p-3">Cost beneficiary</th>
              <th className="p-3">Payment source</th>
              <th className="p-3">Payment</th>
              <th className="p-3">Origin</th>
              <th className="p-3">Status</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={10} className="p-8 text-center text-[#747b8d]">Loading expenditures…</td></tr>
            )}
            {!loading && expenditures.length === 0 && (
              <tr><td colSpan={10} className="p-8 text-center text-[#747b8d]">No expenditures match these filters.</td></tr>
            )}
            {!loading && expenditures.map((exp) => (
              <tr key={exp.id} className="border-t">
                <td className="p-3 font-mono text-xs">{exp.expenditure_reference || `#${exp.id}`}</td>
                <td className="p-3">{formatDate(exp.expenditure_date)}</td>
                <td className="p-3 font-medium">{exp.description}{exp.external_reference ? ` (Ref: ${exp.external_reference})` : ""}</td>
                <td className="p-3 text-right font-mono">{formatCurrency(exp.amount)}</td>
                <td className="p-3 text-center">{exp.beneficiary_batches?.length ? exp.beneficiary_batches.map((batch) => <Link key={batch.id} href={`/poultry/batches/${batch.id}?tab=costs`} className="block font-bold underline">{batch.batch_id}</Link>) : exp.beneficiary_detail || "Non-batch"}</td>
                <td className="p-3 text-center">{exp.funding_allocations?.length ? exp.funding_allocations.map((row) => row.funding_source_display || `Source #${row.funding_source}`).join(", ") : "Not paid / unassigned"}</td>
                <td className="p-3 text-center"><span className={`rounded px-2 py-0.5 text-xs font-bold ${exp.payment_status === "paid" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-900"}`}>{formatLabel(exp.payment_status || "unpaid")}</span>{Number(exp.balance_due || 0) > 0 ? <span className="mt-1 block text-xs">Due {formatCurrency(exp.balance_due || 0)}</span> : null}</td>
                <td className="p-3 text-center">{formatLabel(exp.origin || "finance")}</td>
                <td className="p-3 text-center">
                  <span className={`text-xs px-2 py-0.5 rounded ${exp.status === "posted" ? "bg-green-100" : exp.status === "void" ? "bg-gray-200" : "bg-amber-100"}`}>
                    {exp.status}
                  </span>
                </td>
                <td className="p-3 flex gap-1">
                  <Link href={`/finance/expenditures/${exp.id}`} className="rounded border border-[#151f36] px-3 py-1 text-xs font-bold">{exp.status === "posted" && exp.payment_status !== "paid" ? "Record payment" : "Review"}</Link>
                  {exp.status === "posted" && (
                    <button onClick={() => voidExpenditure(exp.id)} className="text-xs bg-red-600 text-white px-2 py-1 rounded">Reverse</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        <div className="flex flex-col gap-4 border-t border-[#ddd7c9] bg-[#fbfaf6] px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-wrap items-center gap-3 text-sm text-[#5f6677]">
            <span aria-live="polite">Showing {firstResult}–{lastResult} of {totalCount}</span>
            <label className="flex items-center gap-2">
              Rows per page
              <select
                aria-label="Rows per page"
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value) as (typeof pageSizes)[number]);
                  resetToFirstPage();
                }}
                className="form-input py-2"
              >
                {pageSizes.map((size) => <option key={size} value={size}>{size}</option>)}
              </select>
            </label>
          </div>
          <nav aria-label="Expenditure pagination" className="flex flex-wrap items-center gap-1">
            <button type="button" onClick={() => setPage(1)} disabled={page === 1 || loading} className="rounded-lg border px-3 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40">First</button>
            <button type="button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page === 1 || loading} className="rounded-lg border px-3 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
            {pageNumbers.map((number) => (
              <button
                key={number}
                type="button"
                aria-current={number === page ? "page" : undefined}
                aria-label={`Page ${number}`}
                onClick={() => setPage(number)}
                disabled={loading}
                className={`min-w-10 rounded-lg border px-3 py-2 text-sm font-bold ${number === page ? "border-[#151f36] bg-[#151f36] text-white" : "bg-white"}`}
              >
                {number}
              </button>
            ))}
            <button type="button" onClick={() => setPage((current) => Math.min(totalPages, current + 1))} disabled={page >= totalPages || loading} className="rounded-lg border px-3 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40">Next</button>
            <button type="button" onClick={() => setPage(totalPages)} disabled={page >= totalPages || loading} className="rounded-lg border px-3 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-40">Last</button>
          </nav>
        </div>
      </div>

      <p className="mt-4 text-sm text-[#747b8d]">
        Each row is one authoritative transaction. Beneficiaries affect profitability; payment sources affect cash and Revenue Usage.
      </p>
      <div className="mt-2">
        <Link href="/finance/revenue-usage" className="text-sm underline">View Revenue Usage + Cross-Batch Report →</Link>
      </div>
    </div>
  );
}
