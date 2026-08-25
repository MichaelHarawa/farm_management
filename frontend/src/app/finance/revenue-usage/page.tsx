"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { clientApiFetch } from "@/lib/client-api";
import { formatCurrency, formatLabel, formatPercent } from "@/features/finance/utils/formatters";
import type { BatchRevenueUtilization, CrossBatchFlow } from "@/features/finance/types";
import type { PoultryBatch } from "@/features/poultry/types";

export default function RevenueUsagePage() {
  const [utilizations, setUtilizations] = useState<BatchRevenueUtilization[]>([]);
  const [crossFlows, setCrossFlows] = useState<CrossBatchFlow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const batchesRaw = await clientApiFetch<PoultryBatch[] | { results: PoultryBatch[] }>("/api/poultry/batches").catch(() => []);
        const batches: PoultryBatch[] = Array.isArray(batchesRaw) ? batchesRaw : (batchesRaw?.results || []);
        const results = (await Promise.all(batches.map(async (batch) => {
          try {
            return await clientApiFetch<BatchRevenueUtilization>(`/api/finance/reports/batches/${batch.id}/revenue-utilization`);
          } catch {
            return null;
          }
        }))).filter((item): item is BatchRevenueUtilization => item !== null);
        setUtilizations(results);

        const cross = await clientApiFetch<{ flows: CrossBatchFlow[] }>("/api/finance/reports/cross-batch-financing").catch(() => ({ flows: [] }));
        setCrossFlows(cross.flows || []);
      } catch (requestError: unknown) {
        setError(requestError instanceof Error ? requestError.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="p-8">Loading revenue usage...</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-3xl font-extrabold">Revenue Usage</h1>
        <Link href="/finance" className="text-sm font-bold underline">← Finance Dashboard</Link>
      </div>

      <p className="mb-4 text-sm text-[var(--navy-muted)]">
        Shows how much cash collected from each batch has been used via Funding Allocations to expenditures. Separate from profit accounting.
      </p>
      {error ? <p role="alert" className="mb-4 rounded-lg bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}

      <div className="bg-white border border-[#ddd7c9] rounded-xl overflow-hidden mb-8">
        <table className="w-full text-sm">
          <thead className="bg-[#f6f3eb]">
            <tr>
              <th className="p-3 text-left">Batch</th>
              <th className="p-3 text-right">Collected</th>
              <th className="p-3 text-right">Refunded</th>
              <th className="p-3 text-right">Spent</th>
              <th className="p-3 text-right">Remaining cash</th>
              <th className="p-3 text-right">Utilization</th>
              <th className="p-3">Used for</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {utilizations.length === 0 && (
              <tr><td colSpan={8} className="p-6 text-center text-[#747b8d]">No utilization data. Post expenditures funded from batch collections.</td></tr>
            )}
            {utilizations.map((u) => (
              <tr key={u.batch_id} className="border-t">
                <td className="p-3 font-medium">{u.batch_code}</td>
                <td className="p-3 text-right font-mono">{formatCurrency(u.cash_collected)}</td>
                <td className="p-3 text-right font-mono">{formatCurrency(u.refunds)}</td>
                <td className="p-3 text-right font-mono">{formatCurrency(u.cash_used)}</td>
                <td className="p-3 text-right font-mono text-green-700">{formatCurrency(u.available_cash)}</td>
                <td className="p-3 text-right">{formatPercent(u.utilization_percent)}</td>
                <td className="p-3 text-xs">{(u.beneficiary_modules || []).join(", ") || "—"}</td>
                <td className="p-3">
                  <Link href={`/finance/revenue-usage/${u.batch_id}`} className="text-xs font-bold underline">View spending</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="mb-3 text-xl font-bold">Revenue Usage Transactions</h2>
      <p className="mb-3 text-xs text-[var(--navy-muted)]">The funding source says where cash came from; the beneficiary says which batch or farm activity bears the cost.</p>
      <div className="mb-8 overflow-x-auto rounded-xl border border-[#ddd7c9] bg-white">
        <table className="min-w-[1000px] w-full text-sm"><thead className="bg-[#f6f3eb]"><tr><th className="p-3 text-left">Source batch</th><th className="p-3 text-left">Date</th><th className="p-3 text-left">Expenditure</th><th className="p-3 text-left">Category / nature</th><th className="p-3 text-left">Beneficiary / cost bearer</th><th className="p-3 text-right">Cash used</th></tr></thead><tbody>
          {utilizations.flatMap((utilization) => utilization.transactions.map((transaction) => ({ ...transaction, batch_code: utilization.batch_code }))).map((transaction) => <tr key={transaction.allocation_id} className="border-t"><td className="p-3 font-bold">{transaction.batch_code}</td><td className="p-3">{transaction.date}</td><td className="p-3"><Link href={`/finance/expenditures/${transaction.expenditure_id}`} className="font-bold underline">{transaction.expenditure_reference || transaction.description}</Link><div className="text-xs text-[var(--navy-muted)]">{transaction.description}</div></td><td className="p-3">{transaction.category} · {formatLabel(transaction.accounting_nature)}</td><td className="p-3">{transaction.beneficiary}</td><td className="p-3 text-right font-mono">{formatCurrency(transaction.amount)}</td></tr>)}
          {!utilizations.some((utilization) => utilization.transactions.length) ? <tr><td colSpan={6} className="p-6 text-center text-[#747b8d]">No posted batch-funded expenditure transactions.</td></tr> : null}
        </tbody></table>
      </div>

      {/* Cross-batch financing report */}
      <h2 className="text-xl font-bold mb-3">Cross-Batch Financing Report</h2>
      <p className="text-xs mb-3 text-[var(--navy-muted)]">
        Flows where cash collected from one batch funded an expenditure whose cost was allocated to a different batch.
      </p>

      <div className="bg-white border border-[#ddd7c9] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#f6f3eb]">
            <tr>
              <th className="p-3 text-left">From Batch (Funding)</th>
              <th className="p-3">Expenditure</th>
              <th className="p-3 text-right">Funded Amount</th>
              <th className="p-3 text-left">Allocated To Batch</th>
              <th className="p-3 text-right">Allocated Amount</th>
              <th className="p-3">Date</th>
            </tr>
          </thead>
          <tbody>
            {crossFlows.length === 0 && (
              <tr><td colSpan={6} className="p-6 text-center text-[#747b8d]">No cross-batch flows yet. Record expenditures with funding from one batch and cost allocation to another.</td></tr>
            )}
            {crossFlows.map((f, i) => (
              <tr key={i} className="border-t">
                <td className="p-3 font-medium">Batch {f.funding_batch_code} (#{f.funding_batch_id})</td>
                <td className="p-3">{f.expenditure_desc} (#{f.expenditure_id})</td>
                <td className="p-3 text-right font-mono">{formatCurrency(f.amount_funded)}</td>
                <td className="p-3">Batch #{f.allocated_to_batch_id}</td>
                <td className="p-3 text-right font-mono">{formatCurrency(f.allocated_amount)}</td>
                <td className="p-3 text-xs">{f.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4">
        <Link href="/finance/expenditures" className="finance-button inline-block text-sm">Manage Expenditures</Link>
      </div>
    </div>
  );
}
