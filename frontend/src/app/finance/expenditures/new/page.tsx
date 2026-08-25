"use client";
/* eslint-disable @typescript-eslint/no-explicit-any, react-hooks/set-state-in-effect */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";
import type { FundingSource } from "@/features/finance/types";

type FundingRow = { funding_source: number | ""; source_query: string; amount: string; classification: string };
type CostRow = { batch: number | ""; amount: string };

type PoultryBatch = { id: number; batch_id: string; status?: string };

const fundingSourceLabel = (source: FundingSource) =>
  `${source.display_name || source.description || source.source_type}${source.batch_code ? ` — ${source.batch_code}` : ""} — MWK ${Number(source.available_balance || 0).toLocaleString()} available`;

export default function NewExpenditurePage() {
  const router = useRouter();

  const [form, setForm] = useState({
    expenditure_date: new Date().toISOString().slice(0, 10),
    amount: "",
    category: "",  // will be category id
    accounting_nature: "",
    other_category_detail: "",
    other_nature_detail: "",
    description: "",
    payee: "",
    payment_method: "",
    reference_number: "",
    external_reference: "",
    farm_module: "",
    beneficiary_type: "",
    beneficiary_detail: "",
  });

  const [fundingRows, setFundingRows] = useState<FundingRow[]>([
    { funding_source: "", source_query: "", amount: "", classification: "reinvestment" },
  ]);
  const [costRows, setCostRows] = useState<CostRow[]>([
    { batch: "", amount: "" },
  ]);

  const [fundingSources, setFundingSources] = useState<FundingSource[]>([]);
  const [batches, setBatches] = useState<PoultryBatch[]>([]);
  const [categories, setCategories] = useState<any[]>([]);
  const [batchSearch, setBatchSearch] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFundingReceipt, setShowFundingReceipt] = useState(false);
  const [newFunds, setNewFunds] = useState({ source_type: "owner_capital", description: "", amount: "", reference: "" });

  const totalAmount = Number(form.amount) || 0;

  // Live totals
  const fundingTotal = useMemo(() => {
    return fundingRows.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);
  }, [fundingRows]);

  const costTotal = useMemo(() => {
    return costRows.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);
  }, [costRows]);

  const fundingDiff = (totalAmount - fundingTotal).toFixed(2);
  const costDiff = (totalAmount - costTotal).toFixed(2);

  const isValidSplits =
    totalAmount > 0 &&
    Math.abs(totalAmount - fundingTotal) < 0.01 &&
    Math.abs(totalAmount - costTotal) < 0.01;

  // Fetch sources and batches
  useEffect(() => {
    (async () => {
      try {
        const [fs, bsRaw, cats] = await Promise.all([
          clientApiFetch<FundingSource[]>("/api/finance/funding-sources").catch(() => []),
          clientApiFetch<any>("/api/poultry/batches").catch(() => []),
          clientApiFetch<any>("/api/finance/expenditure-categories").catch(() => []),
        ]);
        const bs = Array.isArray(bsRaw) ? bsRaw : (bsRaw?.results || []);
        setFundingSources(fs);
        const preferred = fs.length === 1 ? fs[0] : undefined;
        if (preferred) {
          setFundingRows([{
            funding_source: preferred.id,
            source_query: fundingSourceLabel(preferred),
            amount: "",
            classification: "reinvestment",
          }]);
        }
        setBatches(bs);  // include all non-deleted: active, closed, historical etc.
        setCategories(Array.isArray(cats) ? cats : (cats?.results || []));
      } catch {
        // ignore
      }
    })();
  }, []);

  useEffect(() => {
    if (totalAmount <= 0 || fundingSources.length <= 1 || fundingRows[0]?.funding_source) return;
    const contextBatch = Number(new URLSearchParams(window.location.search).get("batch"));
    const preferred = fundingSources.find(
      (source) => source.batch === contextBatch && Number(source.available_balance || 0) >= totalAmount,
    );
    if (preferred) {
      setFundingRows([{
        funding_source: preferred.id,
        source_query: fundingSourceLabel(preferred),
        amount: form.amount,
        classification: "reinvestment",
      }]);
    }
  }, [form.amount, fundingRows, fundingSources, totalAmount]);

  const filteredBatches = useMemo(() => {
    const q = batchSearch.toLowerCase().trim();
    if (!q) return batches;
    return batches.filter(
      (b) =>
        b.batch_id.toLowerCase().includes(q) ||
        String(b.id).includes(q)
    );
  }, [batches, batchSearch]);

  const addFundingRow = () => {
    setFundingRows((prev) => [...prev, { funding_source: "", source_query: "", amount: "", classification: "reinvestment" }]);
  };
  const removeFundingRow = (idx: number) => {
    setFundingRows((prev) => prev.filter((_, i) => i !== idx));
  };
  const updateFunding = (idx: number, key: keyof FundingRow, val: any) => {
    setFundingRows((prev) => {
      const copy = [...prev];
      (copy[idx] as any)[key] = val;
      return copy;
    });
  };

  const addCostRow = () => {
    setCostRows((prev) => [...prev, { batch: "", amount: "" }]);
  };
  const removeCostRow = (idx: number) => {
    setCostRows((prev) => prev.filter((_, i) => i !== idx));
  };
  const updateCost = (idx: number, key: keyof CostRow, val: any) => {
    setCostRows((prev) => {
      const copy = [...prev];
      (copy[idx] as any)[key] = val;
      return copy;
    });
  };

  const handleCategoryChange = (catId: string) => {
    const cat = categories.find((c: any) => String(c.id) === catId);
    const nextNature = cat?.default_accounting_nature || form.accounting_nature || "";
    setForm({ ...form, category: catId, accounting_nature: nextNature });
  };

  const addNonSalesFunds = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const source = await clientApiFetch<FundingSource>("/api/finance/funding-sources", {
        method: "POST",
        body: JSON.stringify({ source_type: newFunds.source_type, description: newFunds.description }),
      });
      await clientApiFetch("/api/finance/funding-receipts", {
        method: "POST",
        body: JSON.stringify({ funding_source: source.id, amount: newFunds.amount, reference: newFunds.reference }),
      });
      const refreshed = await clientApiFetch<FundingSource[]>("/api/finance/funding-sources");
      setFundingSources(refreshed);
      const fundedSource = refreshed.find((item) => item.id === source.id);
      if (fundedSource) setFundingRows([{ funding_source: fundedSource.id, source_query: fundingSourceLabel(fundedSource), amount: "", classification: "reinvestment" }]);
      setShowFundingReceipt(false);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidSplits && (fundingRows.some(f => f.amount) || costRows.some(c => c.amount))) {
      setError("Funding total and Cost allocation total must exactly match the Expenditure Amount.");
      return;
    }
    setSubmitting(true);
    setError(null);

    try {
      const cleanFunding = fundingRows
        .filter((f) => f.funding_source && f.amount)
        .map((f) => ({
          funding_source: Number(f.funding_source),
          amount: parseFloat(f.amount),
          classification: f.classification,
        }));

      const cleanCost = costRows
        .filter((c) => c.batch && c.amount)
        .map((c) => ({
          batch: Number(c.batch),
          amount: parseFloat(c.amount),
        }));

      const payload: any = {
        ...form,
        category: form.category ? Number(form.category) : null,
        amount: totalAmount,
        status: "draft",
        funding_allocations_input: cleanFunding,
        cost_allocations_input: cleanCost,
      };

      const created = await clientApiFetch<any>("/api/finance/expenditures", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      alert(`Draft saved. Reference: ${created.expenditure_reference || created.id}. Go to list to Review & Post (no balances changed yet).`);
      router.push("/finance/expenditures");
    } catch (err) {
      setError(getApiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="p-8 max-w-4xl mx-auto">
      <Link href="/finance/expenditures" className="mb-5 inline-block text-sm font-bold underline">← Expenditures</Link>
      <h1 className="text-2xl font-bold mb-2">Record New Expenditure</h1>
      <p className="text-sm text-[var(--navy-muted)] mb-6">
        Specify full funding sources (where money came from) and cost allocations (which batches/activities bear the cost). Totals must match.
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">
        {/* Header fields */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-sm font-bold">Date</span>
            <input
              type="date"
              value={form.expenditure_date}
              onChange={(e) => setForm({ ...form, expenditure_date: e.target.value })}
              className="form-input w-full"
              required
            />
          </label>
          <label className="block">
            <span className="text-sm font-bold">Total Amount</span>
            <input
              type="number"
              step="0.01"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
              className="form-input w-full"
              required
            />
          </label>
        </div>

        <label className="block">
          <span className="text-sm font-bold">Description</span>
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className="form-input w-full"
            required
          />
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-sm font-bold">Category</span>
            <select
              value={form.category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="form-input w-full"
              required
            >
              <option value="">Select category…</option>
              {categories.map((c: any) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-bold">Accounting Nature</span>
            <select
              value={form.accounting_nature}
              onChange={(e) => setForm({ ...form, accounting_nature: e.target.value })}
              className="form-input w-full"
            >
              <option value="">Select nature…</option>
              <option value="direct_cost">Direct Cost</option>
              <option value="indirect_operating_expense">Indirect Operating Expense</option>
              <option value="capital_expenditure">Capital Expenditure</option>
              <option value="loan_repayment">Loan Repayment</option>
              <option value="owner_withdrawal">Owner Withdrawal</option>
              <option value="transfer">Transfer</option>
              <option value="other">Other</option>
            </select>
          </label>
        </div>

        {form.category && categories.find((c: any) => String(c.id) === String(form.category))?.name?.toLowerCase() === "other" && (
          <label className="block">
            <span className="text-sm font-bold">Other Category Detail</span>
            <input
              value={form.other_category_detail}
              onChange={(e) => setForm({ ...form, other_category_detail: e.target.value })}
              className="form-input w-full"
              required
            />
          </label>
        )}

        {form.accounting_nature === "other" && (
          <label className="block">
            <span className="text-sm font-bold">Other Nature Detail</span>
            <input
              value={form.other_nature_detail}
              onChange={(e) => setForm({ ...form, other_nature_detail: e.target.value })}
              className="form-input w-full"
              required
            />
          </label>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <label className="block">
            <span className="text-sm font-bold">Payee</span>
            <input value={form.payee} onChange={(e) => setForm({ ...form, payee: e.target.value })} className="form-input w-full" />
          </label>
          <label className="block">
            <span className="text-sm font-bold">Payment Method</span>
            <select value={form.payment_method} onChange={(e) => setForm({ ...form, payment_method: e.target.value })} className="form-input w-full">
              <option value="">Select…</option>
              <option value="Cash">Cash</option>
              <option value="Bank transfer">Bank transfer</option>
              <option value="Mobile money">Mobile money</option>
              <option value="Cheque">Cheque</option>
              <option value="Credit">Credit</option>
              <option value="Other">Other</option>
            </select>
          </label>
          <label className="block">
            <span className="text-sm font-bold">Receipt / Invoice # (optional)</span>
            <input value={form.external_reference} onChange={(e) => setForm({ ...form, external_reference: e.target.value })} className="form-input w-full" />
          </label>
        </div>

        {/* Reference will be generated server-side as EXP-YYYYMMDD-#### and shown after save */}
        <label className="block">
          <span className="text-sm font-bold">Who benefits from this expenditure? (Beneficiary)</span>
          <select value={form.beneficiary_type} onChange={(e) => setForm({ ...form, beneficiary_type: e.target.value })} className="form-input w-full">
            <option value="">Select beneficiary type…</option>
            <option value="one_poultry_batch">One poultry batch</option>
            <option value="multiple_poultry_batches">Multiple poultry batches</option>
            <option value="whole_poultry">Whole poultry operation</option>
            <option value="crops">Crops</option>
            <option value="general_admin">General farm administration</option>
            <option value="capital_asset">Capital asset or construction project</option>
            <option value="other">Other farm activity</option>
          </select>
          {form.beneficiary_type && (
            <input
              className="form-input w-full mt-2"
              placeholder="Detail (batch id(s), description, asset...)"
              value={form.beneficiary_detail}
              onChange={(e) => setForm({ ...form, beneficiary_detail: e.target.value })}
            />
          )}
        </label>

        {/* FUNDING ALLOCATIONS - full multi + live validation + better picker */}
        <div className="border rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-bold">Funding Sources (where the money came from)</span>
            <span className={`text-sm font-mono ${totalAmount > 0 && Math.abs(fundingTotal - totalAmount) < 0.01 ? "text-green-700" : "text-amber-600"}`}>
              Total funded: {fundingTotal.toFixed(2)} / {totalAmount.toFixed(2)} {totalAmount > 0 && Math.abs(fundingTotal - totalAmount) < 0.01 ? "✓" : `(diff ${fundingDiff})`}
            </span>
          </div>

          <div className="mb-2 flex justify-end gap-2">
            <button type="button" onClick={() => setShowFundingReceipt(true)} className="text-sm px-3 py-1 border rounded">+ Add owner, farm, or loan funds</button>
            <button type="button" onClick={addFundingRow} className="text-sm px-3 py-1 border rounded">Split funding</button>
          </div>

          {fundingRows.map((row, idx) => (
            <div key={idx} className="flex flex-wrap gap-2 mb-2 items-end">
              <input
                aria-label="Where was this expenditure paid from?"
                list={`funding-options-${idx}`}
                value={row.source_query}
                placeholder="Search batch, owner, farm, or loan cash…"
                onChange={(e) => {
                  const selected = fundingSources.find((source) => fundingSourceLabel(source) === e.target.value);
                  setFundingRows((current) => current.map((item, rowIndex) => rowIndex === idx ? {
                    ...item,
                    source_query: e.target.value,
                    funding_source: selected?.id || "",
                  } : item));
                }}
                className="form-input w-72 text-sm"
              />
              <datalist id={`funding-options-${idx}`}>
                {fundingSources.map((source) => (
                  <option key={source.id} value={fundingSourceLabel(source)} />
                ))}
              </datalist>
              <input
                placeholder="Amount"
                type="number"
                step="0.01"
                value={row.amount}
                onChange={(e) => updateFunding(idx, "amount", e.target.value)}
                className="form-input w-28 text-sm"
              />
              <select
                value={row.classification}
                onChange={(e) => updateFunding(idx, "classification", e.target.value)}
                className="form-input text-sm"
              >
                <option value="reinvestment">Reinvestment</option>
                <option value="working_capital">Working Capital</option>
                <option value="owner_distribution">Owner Distribution</option>
                <option value="debt_service">Debt Service</option>
                <option value="other">Other</option>
              </select>
              <button type="button" onClick={() => removeFundingRow(idx)} className="text-red-600 text-xs px-2">×</button>
            </div>
          ))}

          {fundingSources.length === 0 && <div className="rounded-lg bg-amber-50 p-4 text-sm text-amber-900"><p>No collected or contributed cash is currently available.</p><div className="mt-3 flex flex-wrap gap-3"><Link href="/finance/receivables" className="font-bold underline">Record sales payment</Link><button type="button" onClick={() => setShowFundingReceipt(true)} className="font-bold underline">Add owner or farm funds</button></div></div>}
        </div>

        {/* COST ALLOCATIONS - full multi + live */}
        <div className="border rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-bold">Cost Allocations (which batches bear the cost)</span>
            <span className={`text-sm font-mono ${totalAmount > 0 && Math.abs(costTotal - totalAmount) < 0.01 ? "text-green-700" : "text-amber-600"}`}>
              Total allocated: {costTotal.toFixed(2)} / {totalAmount.toFixed(2)} {totalAmount > 0 && Math.abs(costTotal - totalAmount) < 0.01 ? "✓" : `(diff ${costDiff})`}
            </span>
          </div>

          <div className="mb-2 flex gap-2">
            <input
              placeholder="Search batches..."
              value={batchSearch}
              onChange={(e) => setBatchSearch(e.target.value)}
              className="form-input flex-1 text-sm"
            />
            <button type="button" onClick={addCostRow} className="text-sm px-3 py-1 border rounded">+ Add cost split</button>
          </div>

          {costRows.map((row, idx) => (
            <div key={idx} className="flex flex-wrap gap-2 mb-2 items-end">
              <select
                value={row.batch}
                onChange={(e) => updateCost(idx, "batch", e.target.value ? Number(e.target.value) : "")}
                className="form-input w-72 text-sm"
              >
                <option value="">Select batch…</option>
                {filteredBatches.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.batch_id} (#{b.id})
                  </option>
                ))}
              </select>
              <input
                placeholder="Allocated amount"
                type="number"
                step="0.01"
                value={row.amount}
                onChange={(e) => updateCost(idx, "amount", e.target.value)}
                className="form-input w-28 text-sm"
              />
              <button type="button" onClick={() => removeCostRow(idx)} className="text-red-600 text-xs px-2">×</button>
            </div>
          ))}

          <p className="text-xs text-[var(--navy-muted)]">Cost allocations will be automatically recorded as CostAllocation rows (source=expenditure) when you Post the expenditure.</p>
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={submitting || (totalAmount > 0 && !isValidSplits && (fundingRows.length > 1 || costRows.length > 1))}
            className="finance-button"
          >
            {submitting ? "Saving..." : "Save Draft (balances unchanged until Post)"}
          </button>
          <button type="button" onClick={() => router.push("/finance/expenditures")} className="px-4 py-2 border rounded">
            Cancel
          </button>
        </div>

        <p className="text-xs text-[var(--navy-muted)]">
          Drafts do not affect balances. Use the Expenditures list to Review &amp; Post after confirming funding sources and beneficiaries.
        </p>
      </form>
      {showFundingReceipt ? <div role="dialog" aria-modal="true" aria-labelledby="funding-receipt-title" className="fixed inset-0 z-50 grid place-items-center bg-[#151f36]/45 p-4"><form onSubmit={addNonSalesFunds} className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl"><div className="flex justify-between"><h2 id="funding-receipt-title" className="text-2xl font-extrabold">Add available funds</h2><button type="button" onClick={() => setShowFundingReceipt(false)} aria-label="Close funding form" className="text-2xl">×</button></div><p className="mt-2 text-sm text-[var(--navy-muted)]">This records a receipt. The available balance is always calculated from receipts minus posted spending.</p><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm font-bold">Source type<select value={newFunds.source_type} onChange={(event) => setNewFunds({ ...newFunds, source_type: event.target.value })} className="form-input mt-2 w-full"><option value="owner_capital">Owner capital</option><option value="general_farm_cash">General farm cash</option><option value="loan">Loan funding</option><option value="grant">Grant / subsidy</option><option value="other_income">Other income</option></select></label><label className="text-sm font-bold">Description<input required value={newFunds.description} onChange={(event) => setNewFunds({ ...newFunds, description: event.target.value })} className="form-input mt-2 w-full" /></label><label className="text-sm font-bold">Amount received<input required min="0.01" step="0.01" type="number" value={newFunds.amount} onChange={(event) => setNewFunds({ ...newFunds, amount: event.target.value })} className="form-input mt-2 w-full" /></label><label className="text-sm font-bold">Receipt reference<input value={newFunds.reference} onChange={(event) => setNewFunds({ ...newFunds, reference: event.target.value })} className="form-input mt-2 w-full" /></label></div><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={() => setShowFundingReceipt(false)} className="rounded-lg border px-5 py-3 font-bold">Cancel</button><button disabled={submitting} className="finance-button">Record funds</button></div></form></div> : null}
    </main>
  );
}
