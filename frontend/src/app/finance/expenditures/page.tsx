"use client";
/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */

import { useEffect, useState } from "react";
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

export default function FinanceExpendituresClient() {
  const [expenditures, setExpenditures] = useState<Expenditure[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [paymentFilter, setPaymentFilter] = useState("");

  const load = async () => {
    try {
      const data = await clientApiFetch<Expenditure[]>("/api/finance/expenditures");
      setExpenditures(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

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

  const filtered = expenditures.filter(e => {
    const q = search.toLowerCase();
    const matchesSearch = !q || (e.description || "").toLowerCase().includes(q) || (e.expenditure_reference || "").toLowerCase().includes(q);
    const matchesStatus = !statusFilter || e.status === statusFilter;
    const matchesPayment = !paymentFilter || e.payment_status === paymentFilter;
    return matchesSearch && matchesStatus && matchesPayment;
  });

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <Link href="/finance" className="mb-5 inline-block text-sm font-bold underline">← Finance Dashboard</Link>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-extrabold">Expenditures</h1>
        <Link href="/finance/expenditures/new" className="finance-button">+ New Expenditure</Link>
      </div>

      <div className="flex gap-2 mb-4">
        <input placeholder="Search ref or desc..." value={search} onChange={e => setSearch(e.target.value)} className="form-input w-64" />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="form-input">
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="posted">Posted</option>
          <option value="void">Void</option>
        </select>
        <select value={paymentFilter} onChange={e => setPaymentFilter(e.target.value)} className="form-input">
          <option value="">All payment states</option>
          <option value="paid">Paid</option>
          <option value="partial">Partially paid</option>
          <option value="unpaid">Outstanding payable</option>
          <option value="historical_unassigned">Historical source unassigned</option>
        </select>
      </div>

      <div className="bg-white border border-[#ddd7c9] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
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
            {filtered.length === 0 && (
              <tr><td colSpan={10} className="p-6 text-center text-[#747b8d]">No expenditures match filters.</td></tr>
            )}
            {filtered.map((exp) => (
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

      <p className="mt-4 text-sm text-[#747b8d]">
        Each row is one authoritative transaction. Beneficiaries affect profitability; payment sources affect cash and Revenue Usage.
      </p>
      <div className="mt-2">
        <Link href="/finance/revenue-usage" className="text-sm underline">View Revenue Usage + Cross-Batch Report →</Link>
      </div>
    </div>
  );
}
