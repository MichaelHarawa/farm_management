"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { clientApiFetch } from "@/lib/client-api";
import type { PoultryBatch } from "@/features/poultry/types";
import type { PayrollEntry, PayrollPayment } from "../types";
import { FundingSourcePicker, fundingSourceDisplayLabel } from "./FundingSourcePicker";
import { PaymentDetailsDialog, type PaymentDetail } from "./PaymentDetailsDialog";
import { formatCurrency, formatDate } from "../utils/formatters";

type FundingRow = { funding_source: string; source_query: string; amount: string };
type CostRow = { beneficiary_type: "batch" | "administration"; batch: string; amount: string };

export function PayrollLedgerManager({ entries, batches }: { entries: PayrollEntry[]; batches: PoultryBatch[] }) {
  const router = useRouter();
  const [active, setActive] = useState<PayrollEntry | null>(null);
  const [mode, setMode] = useState<"payment" | "allocation">("payment");
  const [paymentKind, setPaymentKind] = useState<"advance" | "salary">("salary");
  const [funding, setFunding] = useState<FundingRow[]>([{ funding_source: "", source_query: "", amount: "" }]);
  const [costs, setCosts] = useState<CostRow[]>([{ beneficiary_type: "administration", batch: "", amount: "" }]);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("Bank transfer");
  const [reference, setReference] = useState("");
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedPayment, setSelectedPayment] = useState<PaymentDetail | null>(null);

  const updateFunding = (index: number, patch: Partial<FundingRow>) => setFunding((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));
  const updateCost = (index: number, patch: Partial<CostRow>) => setCosts((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row));

  function defaultCosts(entry: PayrollEntry): CostRow[] {
    return entry.cost_allocation_plan?.length
      ? entry.cost_allocation_plan.map((row) => ({ ...row, batch: row.batch ? String(row.batch) : "" }))
      : [{ beneficiary_type: "administration", batch: "", amount: entry.total_employer_cost }];
  }

  function openPayment(entry: PayrollEntry, kind: "advance" | "salary") {
    const suggestedAmount = kind === "salary" ? entry.outstanding_salary : "";
    setActive(entry);
    setMode("payment");
    setPaymentKind(kind);
    setAmount(suggestedAmount);
    setFunding([{ funding_source: "", source_query: "", amount: suggestedAmount }]);
    setReference("");
    setError("");
  }

  function openAllocation(entry: PayrollEntry) {
    setActive(entry);
    setMode("allocation");
    setCosts(defaultCosts(entry));
    setError("");
  }

  async function submitPayment() {
    if (!active) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(`/api/finance/payroll-entries/${active.id}/record-payment`, {
        method: "POST",
        body: JSON.stringify({
          amount,
          payment_date: paymentDate,
          payment_method: method,
          payment_kind: paymentKind,
          external_reference: reference,
          idempotency_key: crypto.randomUUID(),
          funding_allocations: funding.map((row) => ({ funding_source: Number(row.funding_source), amount: row.amount })),
        }),
      });
      setActive(null);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Payment failed.");
    } finally {
      setBusy(false);
    }
  }

  async function submitCosts() {
    if (!active) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(`/api/finance/payroll-entries/${active.id}/allocate-costs`, {
        method: "POST",
        body: JSON.stringify({ cost_allocations: costs.map((row) => ({
          beneficiary_type: row.beneficiary_type,
          batch: row.beneficiary_type === "batch" ? Number(row.batch) : null,
          amount: row.amount,
        })) }),
      });
      setActive(null);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Allocation failed.");
    } finally {
      setBusy(false);
    }
  }

  function openPaymentDetails(entry: PayrollEntry, payment: PayrollPayment) {
    const beneficiaries = entry.cost_allocation_plan?.map((row) => {
      if (row.beneficiary_type === "administration") return { label: "Farm administration" };
      const batch = batches.find((candidate) => candidate.id === row.batch);
      return { label: batch?.batch_id || `Batch #${row.batch}`, href: row.batch ? `/poultry/batches/${row.batch}?tab=costs` : undefined };
    });
    setSelectedPayment({
      kind: "payroll_payment",
      identifier: `${payment.payment_kind === "advance" ? "Salary advance" : "Salary payment"} #${payment.id}`,
      source: { label: `Payroll entry #${entry.id}`, href: "/finance/payroll" },
      partyLabel: "Employee",
      party: entry.employee_name,
      beneficiaries,
      amount: payment.amount,
      paymentDate: payment.payment_date,
      method: payment.payment_method,
      externalReference: payment.external_reference,
      recordedBy: payment.posted_by_name,
      createdAt: payment.created_at,
      status: payment.status,
      reversedAt: payment.reversed_at,
      reversedBy: payment.reversed_by_name,
      reversalReason: payment.reversal_reason,
      fundingLines: payment.funding_allocations.map((line) => ({ id: line.id, source: line.funding_source_name, amount: line.amount })),
    });
  }

  return <>
    <MobileRecordList
      emptyMessage="No payroll entries have been generated."
      records={entries.map((entry) => ({
        key: entry.id,
        title: entry.employee_name,
        subtitle: `Payroll entry #${entry.id}`,
        badge: <span className={`rounded-full px-2 py-1 text-xs font-bold ${Number(entry.outstanding_salary) > 0 ? "bg-amber-100 text-amber-900" : "bg-green-100 text-green-800"}`}>{entry.payment_status.replaceAll("_", " ")}</span>,
        fields: [
          { label: "Gross salary", value: formatCurrency(entry.gross_salary) },
          { label: "Net payable", value: formatCurrency(entry.net_salary_payable) },
          { label: "Paid", value: formatCurrency(entry.amount_paid) },
          { label: "Outstanding", value: formatCurrency(entry.outstanding_salary) },
        ],
        actions: <><button disabled={Number(entry.outstanding_salary) <= 0} className="rounded-lg border border-[var(--navy)] px-3 py-2 text-sm font-bold disabled:opacity-40" onClick={() => openPayment(entry, "advance")}>Record advance</button><button disabled={Number(entry.outstanding_salary) <= 0} className="flex-1 rounded-lg bg-[var(--gold)] px-3 py-2 text-sm font-extrabold text-[var(--navy)] disabled:opacity-40" onClick={() => openPayment(entry, "salary")}>Pay salary</button><button className="rounded-lg bg-[var(--navy)] px-3 py-2 text-sm font-bold text-white" onClick={() => openAllocation(entry)}>Allocate</button></>,
      }))}
    />
    <div className="hidden overflow-x-auto md:block"><table className="min-w-full border-collapse text-sm">
      <thead><tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]"><th className="py-3 pr-4">Employee / period</th><th className="py-3 pr-4">Gross</th><th className="py-3 pr-4">Deductions / net</th><th className="py-3 pr-4">Paid / outstanding</th><th className="py-3 pr-4">Status</th><th className="py-3">Action</th></tr></thead>
      <tbody>{entries.map((entry) => <tr key={entry.id} className="border-b border-[var(--line)]">
        <td className="py-4 pr-4 font-bold">{entry.employee_name}</td><td className="py-4 pr-4">{formatCurrency(entry.gross_salary)}</td><td className="py-4 pr-4">{formatCurrency(entry.deductions)} / {formatCurrency(entry.net_salary_payable)}</td><td className="py-4 pr-4">{formatCurrency(entry.amount_paid)} / {formatCurrency(entry.outstanding_salary)}</td><td className="py-4 pr-4 capitalize">{entry.payment_status.replaceAll("_", " ")}</td>
        <td className="py-4"><div className="flex flex-wrap gap-2"><button disabled={Number(entry.outstanding_salary) <= 0} className="rounded-lg border border-[var(--navy)] px-3 py-2 font-bold disabled:opacity-40" onClick={() => openPayment(entry, "advance")}>Record advance</button><button disabled={Number(entry.outstanding_salary) <= 0} className="rounded-lg bg-[var(--gold)] px-3 py-2 font-extrabold text-[var(--navy)] disabled:opacity-40" onClick={() => openPayment(entry, "salary")}>Pay remaining salary</button><button className="rounded-lg bg-[var(--navy)] px-3 py-2 font-bold text-white" onClick={() => openAllocation(entry)}>Allocate cost</button></div></td>
      </tr>)}</tbody>
    </table></div>

    {active ? <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-2 sm:p-4" role="dialog" aria-modal="true"><div className="max-h-[96vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[var(--line)] bg-[var(--surface-white)] p-4 shadow-2xl sm:max-h-[90vh] sm:rounded-3xl sm:p-6">
      <div className="flex justify-between"><div><p className="text-xs font-bold uppercase tracking-widest">{mode === "allocation" ? "Payroll cost allocation" : paymentKind === "advance" ? "Salary advance" : "Salary payment"}</p><h2 className="mt-2 text-2xl font-extrabold">{active.employee_name}</h2></div><button onClick={() => setActive(null)} aria-label="Close">×</button></div>
      <p className="mt-2 text-sm">Net payable {formatCurrency(active.net_salary_payable)} · Outstanding {formatCurrency(active.outstanding_salary)}</p>
      {error ? <p className="mt-4 rounded-lg bg-red-50 p-3 text-red-700">{error}</p> : null}

      {mode === "payment" ? <section className="mt-6 border-t pt-5"><h3 className="font-extrabold">{paymentKind === "advance" ? "Record advance payment" : "Pay the remaining salary"}</h3><p className="mt-1 text-sm text-[var(--navy-muted)]">This reduces the outstanding salary and consumes cash from the selected funding source.</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2"><input className="form-input" type="number" min="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="Payment amount"/><input className="form-input" type="date" value={paymentDate} onChange={(event) => setPaymentDate(event.target.value)}/><input className="form-input" value={method} onChange={(event) => setMethod(event.target.value)} placeholder="Payment method"/><input className="form-input" value={reference} onChange={(event) => setReference(event.target.value)} placeholder="External reference"/></div>
        <p className="mt-4 text-xs font-bold uppercase tracking-widest">Funding sources (must equal payment)</p>
        {funding.map((row, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-[1fr_180px_auto]"><FundingSourcePicker ariaLabel={`Payroll funding source ${index + 1}`} value={row.funding_source} displayValue={row.source_query} onSelect={(selected) => updateFunding(index, { funding_source: selected ? String(selected.id) : "", source_query: selected ? fundingSourceDisplayLabel(selected) : "" })} /><input className="form-input" type="number" min="0.01" value={row.amount} onChange={(event) => updateFunding(index, { amount: event.target.value })} placeholder="Amount"/><button type="button" className="text-red-700" onClick={() => setFunding((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>Remove</button></div>)}
        <button type="button" className="mt-3 underline" onClick={() => setFunding((rows) => [...rows, { funding_source: "", source_query: "", amount: "" }])}>Split across another source</button>
        <button type="button" disabled={busy || !amount || Number(active.outstanding_salary) <= 0} className="mt-4 block rounded-full bg-[var(--gold)] px-5 py-3 font-extrabold text-[var(--navy)] disabled:opacity-50" onClick={submitPayment}>{paymentKind === "advance" ? "Post salary advance" : "Pay remaining salary"}</button>
      </section> : null}

      {mode === "allocation" ? <section className="mt-6 border-t pt-5"><h3 className="font-extrabold">Allocate salary cost (gross + employer costs)</h3><p className="text-sm text-[var(--navy-muted)]">This is independent of which cash source funds the payment. Allocations must total {formatCurrency(active.total_employer_cost)}.</p>
        {costs.map((row, index) => <div key={index} className="mt-2 grid gap-2 md:grid-cols-[180px_1fr_180px_auto]"><select className="form-input" value={row.beneficiary_type} onChange={(event) => updateCost(index, { beneficiary_type: event.target.value as CostRow["beneficiary_type"] })}><option value="batch">Poultry batch</option><option value="administration">General administration</option></select>{row.beneficiary_type === "batch" ? <select className="form-input" value={row.batch} onChange={(event) => updateCost(index, { batch: event.target.value })}><option value="">Select batch</option>{batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.batch_id}</option>)}</select> : <div className="form-input">Farm administration</div>}<input className="form-input" type="number" value={row.amount} onChange={(event) => updateCost(index, { amount: event.target.value })} placeholder="Amount"/><button type="button" className="text-red-700" onClick={() => setCosts((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}>Remove</button></div>)}
        <button type="button" className="mt-3 underline" onClick={() => setCosts((rows) => [...rows, { beneficiary_type: "batch", batch: "", amount: "" }])}>Add beneficiary</button><button type="button" disabled={busy} className="mt-4 block rounded-full bg-[var(--navy)] px-5 py-3 font-extrabold text-white disabled:opacity-50" onClick={submitCosts}>Save cost allocation</button>
      </section> : null}

      {active.payments?.length ? <section className="mt-7 border-t pt-5"><h3 className="font-extrabold">Payment history</h3><div className="mt-3 grid gap-2">{active.payments.map((payment) => <button key={payment.id} type="button" onClick={() => openPaymentDetails(active, payment)} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--line)] p-3 text-left transition hover:bg-[var(--gold-soft)]"><span>{formatDate(payment.payment_date)} · {payment.payment_method} · <strong>{payment.payment_kind === "advance" ? "Advance" : "Salary"}</strong> · <span className="capitalize">{payment.status}</span></span><span className="text-right"><strong className="block">{formatCurrency(payment.amount)}</strong><span className="text-xs font-bold text-[var(--navy-muted)]">View payment details</span></span></button>)}</div></section> : null}
    </div></div> : null}
    <PaymentDetailsDialog payment={selectedPayment} onClose={() => setSelectedPayment(null)} />
  </>;
}
