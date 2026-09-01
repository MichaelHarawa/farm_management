"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { clientApiFetch } from "@/lib/client-api";
import type { PoultryBatch } from "@/features/poultry/types";
import type { FundingSource, PayrollEntry } from "../types";
import { formatCurrency, formatDate } from "../utils/formatters";

type Row = { funding_source: string; amount: string };
type CostRow = { beneficiary_type: "batch" | "administration"; batch: string; amount: string };

export function PayrollLedgerManager({ entries, batches }: { entries: PayrollEntry[]; batches: PoultryBatch[] }) {
  const router = useRouter();
  const [active, setActive] = useState<PayrollEntry | null>(null);
  const [sources, setSources] = useState<FundingSource[]>([]);
  const [funding, setFunding] = useState<Row[]>([{ funding_source: "", amount: "" }]);
  const [costs, setCosts] = useState<CostRow[]>([{ beneficiary_type: "administration", batch: "", amount: "" }]);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("Bank transfer");
  const [reference, setReference] = useState("");
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    clientApiFetch<FundingSource[] | { results: FundingSource[] }>("/api/finance/funding-sources")
      .then((data) => setSources(Array.isArray(data) ? data : data.results))
      .catch(() => setSources([]));
  }, []);

  const updateFunding = (index: number, patch: Partial<Row>) =>
    setFunding((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));
  const updateCost = (index: number, patch: Partial<CostRow>) =>
    setCosts((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));

  async function submitPayment() {
    if (!active) return;
    setBusy(true); setError("");
    try {
      await clientApiFetch(`/api/finance/payroll-entries/${active.id}/record-payment`, {
        method: "POST",
        body: JSON.stringify({
          amount,
          payment_date: paymentDate,
          payment_method: method,
          external_reference: reference,
          idempotency_key: crypto.randomUUID(),
          funding_allocations: funding.map((row) => ({ funding_source: Number(row.funding_source), amount: row.amount })),
        }),
      });
      setActive(null); router.refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Payment failed."); }
    finally { setBusy(false); }
  }

  async function submitCosts() {
    if (!active) return;
    setBusy(true); setError("");
    try {
      await clientApiFetch(`/api/finance/payroll-entries/${active.id}/allocate-costs`, {
        method: "POST",
        body: JSON.stringify({ cost_allocations: costs.map((row) => ({
          beneficiary_type: row.beneficiary_type,
          batch: row.beneficiary_type === "batch" ? Number(row.batch) : null,
          amount: row.amount,
        })) }),
      });
      setActive(null); router.refresh();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Allocation failed."); }
    finally { setBusy(false); }
  }

  return <>
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead><tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
          <th className="py-3 pr-4">Employee / period</th><th className="py-3 pr-4">Gross</th>
          <th className="py-3 pr-4">Deductions / net</th><th className="py-3 pr-4">Paid / outstanding</th>
          <th className="py-3 pr-4">Status</th><th className="py-3">Action</th>
        </tr></thead>
        <tbody>{entries.map((entry) => <tr key={entry.id} className="border-b border-[var(--line)]">
          <td className="py-4 pr-4 font-bold">{entry.employee_name}</td>
          <td className="py-4 pr-4">{formatCurrency(entry.gross_salary)}</td>
          <td className="py-4 pr-4">{formatCurrency(entry.deductions)} / {formatCurrency(entry.net_salary_payable)}</td>
          <td className="py-4 pr-4">{formatCurrency(entry.amount_paid)} / {formatCurrency(entry.outstanding_salary)}</td>
          <td className="py-4 pr-4 capitalize">{entry.payment_status.replaceAll("_", " ")}</td>
          <td className="py-4"><button className="rounded-full bg-[var(--gold)] px-4 py-2 font-extrabold text-[var(--navy)]" onClick={() => {
            setActive(entry); setAmount(entry.outstanding_salary); setCosts(entry.cost_allocation_plan?.length ? entry.cost_allocation_plan.map((row) => ({ ...row, batch: row.batch ? String(row.batch) : "" })) : [{ beneficiary_type: "administration", batch: "", amount: entry.total_employer_cost }]);
          }}>Manage salary</button></td>
        </tr>)}</tbody>
      </table>
    </div>
    {active ? <div className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4" role="dialog" aria-modal="true">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-3xl bg-[var(--surface)] p-6 shadow-2xl">
        <div className="flex justify-between"><div><p className="text-xs font-bold uppercase tracking-widest">Payroll payment and cost allocation</p><h2 className="mt-2 text-2xl font-extrabold">{active.employee_name}</h2></div><button onClick={() => setActive(null)} aria-label="Close">✕</button></div>
        <p className="mt-2 text-sm">Net payable {formatCurrency(active.net_salary_payable)} · Outstanding {formatCurrency(active.outstanding_salary)}</p>
        {error ? <p className="mt-4 rounded-lg bg-red-50 p-3 text-red-700">{error}</p> : null}
        <section className="mt-6 border-t pt-5"><h3 className="font-extrabold">Record cash payment</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2"><input className="form-input" type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Payment amount"/><input className="form-input" type="date" value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)}/><input className="form-input" value={method} onChange={(e) => setMethod(e.target.value)} placeholder="Payment method"/><input className="form-input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="External reference"/></div>
          <p className="mt-4 text-xs font-bold uppercase tracking-widest">Funding sources (must equal payment)</p>
          {funding.map((row, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-[1fr_180px_auto]"><select className="form-input" value={row.funding_source} onChange={(e) => updateFunding(index, { funding_source: e.target.value })}><option value="">Select source</option>{sources.filter((source) => source.is_active !== false).map((source) => <option key={source.id} value={source.id}>{source.display_name} — {formatCurrency(source.available_balance ?? "0")}</option>)}</select><input className="form-input" type="number" value={row.amount} onChange={(e) => updateFunding(index, { amount: e.target.value })} placeholder="Amount"/><button className="text-red-700" onClick={() => setFunding((rows) => rows.filter((_, i) => i !== index))}>Remove</button></div>)}
          <button className="mt-3 underline" onClick={() => setFunding((rows) => [...rows, { funding_source: "", amount: "" }])}>Split across another source</button>
          <button disabled={busy || Number(active.outstanding_salary) <= 0} className="mt-4 block rounded-full bg-[var(--gold)] px-5 py-3 font-extrabold text-[var(--navy)] disabled:opacity-50" onClick={submitPayment}>Post payment</button>
        </section>
        <section className="mt-7 border-t pt-5"><h3 className="font-extrabold">Allocate salary cost (gross + employer costs)</h3><p className="text-sm text-[var(--navy-muted)]">Independent of which account funds the payment. Allocations must total {formatCurrency(active.total_employer_cost)}.</p>
          {costs.map((row, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-[180px_1fr_180px_auto]"><select className="form-input" value={row.beneficiary_type} onChange={(e) => updateCost(index, { beneficiary_type: e.target.value as CostRow["beneficiary_type"] })}><option value="batch">Poultry batch</option><option value="administration">General administration</option></select>{row.beneficiary_type === "batch" ? <select className="form-input" value={row.batch} onChange={(e) => updateCost(index, { batch: e.target.value })}><option value="">Select batch</option>{batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.batch_id}</option>)}</select> : <div className="form-input">Farm administration</div>}<input className="form-input" type="number" value={row.amount} onChange={(e) => updateCost(index, { amount: e.target.value })} placeholder="Amount"/><button className="text-red-700" onClick={() => setCosts((rows) => rows.filter((_, i) => i !== index))}>Remove</button></div>)}
          <button className="mt-3 underline" onClick={() => setCosts((rows) => [...rows, { beneficiary_type: "batch", batch: "", amount: "" }])}>Add beneficiary</button>
          <button disabled={busy} className="mt-4 block rounded-full bg-[var(--navy)] px-5 py-3 font-extrabold text-white disabled:opacity-50" onClick={submitCosts}>Save cost allocation</button>
        </section>
        {active.payments?.length ? <section className="mt-7 border-t pt-5"><h3 className="font-extrabold">Payment history</h3>{active.payments.map((payment) => <p key={payment.id} className="mt-2 text-sm">{formatDate(payment.payment_date)} · {formatCurrency(payment.amount)} · {payment.payment_method} · <span className="capitalize">{payment.status}</span></p>)}</section> : null}
      </div>
    </div> : null}
  </>;
}
