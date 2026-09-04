"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";

import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";
import type { ReceivableSale, ReceivablesReport } from "@/features/finance/types";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";

type BatchOption = { id: number; batch_id: string };

const nowForInput = () => {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 16);
};

export default function FinanceReceivablesPage() {
  const [report, setReport] = useState<ReceivablesReport | null>(null);
  const [batches, setBatches] = useState<BatchOption[]>([]);
  const [selectedBatches, setSelectedBatches] = useState<number[]>([]);
  const [buyer, setBuyer] = useState("");
  const [status, setStatus] = useState("open");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [focusedSale, setFocusedSale] = useState("");
  const [page, setPage] = useState(1);
  const [paymentSale, setPaymentSale] = useState<ReceivableSale | null>(null);
  const [expandedSale, setExpandedSale] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [payment, setPayment] = useState({
    amount: "",
    payment_date: nowForInput(),
    payment_method: "cash",
    external_reference: "",
    received_by_name: "",
    notes: "",
  });

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const batchIds = query.getAll("batch").map(Number).filter(Number.isFinite);
    setSelectedBatches(batchIds);
    setFocusedSale(query.get("sale") || "");
    clientApiFetch<BatchOption[] | { results: BatchOption[] }>("/api/poultry/batches")
      .then((data) => setBatches(Array.isArray(data) ? data : data.results))
      .catch(() => setBatches([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const query = new URLSearchParams();
    selectedBatches.forEach((id) => query.append("batch", String(id)));
    if (buyer.trim()) query.set("buyer", buyer.trim());
    if (status) query.set("status", status);
    if (dateFrom) query.set("date_from", dateFrom);
    if (dateTo) query.set("date_to", dateTo);
    if (focusedSale) query.set("sale", focusedSale);
    query.set("page", String(page));
    query.set("page_size", "20");
    try {
      const data = await clientApiFetch<ReceivablesReport>(`/api/finance/receivables?${query}`);
      setReport(data);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [buyer, dateFrom, dateTo, focusedSale, page, selectedBatches, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const averageBalance = useMemo(
    () => report?.count ? Number(report.total_receivable) / report.count : 0,
    [report],
  );
  const backHref = selectedBatches.length === 1
    ? `/poultry/batches/${selectedBatches[0]}?tab=sales`
    : "/finance";
  const backLabel = selectedBatches.length === 1 ? "Sales & Collections" : "Finance Dashboard";

  const openPayment = (sale: ReceivableSale) => {
    setPaymentSale(sale);
    setPayment((current) => ({ ...current, amount: sale.balance, payment_date: nowForInput() }));
  };

  const submitPayment = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!paymentSale) return;
    setSubmitting(true);
    setError(null);
    try {
      await clientApiFetch(`/api/finance/receivables/${paymentSale.id}/payments`, {
        method: "POST",
        body: JSON.stringify({
          ...payment,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setPaymentSale(null);
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setSubmitting(false);
    }
  };

  const reversePayment = async (paymentId: number) => {
    const reason = window.prompt("Why is this payment being reversed?")?.trim();
    if (!reason) return;
    try {
      await clientApiFetch(`/api/finance/payments/${paymentId}/reverse`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  return (
    <main className="mx-auto max-w-[1320px] px-5 py-8 sm:px-8 lg:px-12">
      <Link href={backHref} className="text-sm font-extrabold text-[var(--navy)] underline decoration-[var(--gold)] decoration-2 underline-offset-4">
        ← {backLabel}
      </Link>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="finance-eyebrow">Finance / Receivables</p>
          <h1 className="mt-3 text-4xl font-extrabold text-[var(--navy)]">Buyer balances</h1>
          <p className="mt-3 text-[var(--navy-muted)]">Record dated collections without changing the original sale.</p>
        </div>
      </div>

      <section className="mt-8 grid gap-3 rounded-xl border border-[var(--line)] bg-white p-5 md:grid-cols-3 lg:grid-cols-6">
        <label className="text-sm font-bold">Batches
          <select multiple value={selectedBatches.map(String)} onChange={(event) => setSelectedBatches(Array.from(event.target.selectedOptions, (option) => Number(option.value)))} className="form-input mt-2 h-28 w-full" aria-label="Filter by one or more batches">
            {batches.map((batch) => <option key={batch.id} value={batch.id}>{batch.batch_id}</option>)}
          </select>
        </label>
        <label className="text-sm font-bold">Buyer
          <input value={buyer} onChange={(event) => setBuyer(event.target.value)} className="form-input mt-2 w-full" placeholder="Search buyer" />
        </label>
        <label className="text-sm font-bold">Sale reference
          <input value={focusedSale} onChange={(event) => setFocusedSale(event.target.value)} className="form-input mt-2 w-full" placeholder="SALE-…" />
        </label>
        <label className="text-sm font-bold">Status
          <select value={status} onChange={(event) => setStatus(event.target.value)} className="form-input mt-2 w-full">
            <option value="open">All outstanding</option><option value="partial">Partially paid</option><option value="unpaid">Unpaid</option><option value="overdue">Overdue</option><option value="paid">Paid</option><option value="cancelled">Cancelled</option><option value="all">All sales</option>
          </select>
        </label>
        <label className="text-sm font-bold">Due from
          <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="form-input mt-2 w-full" />
        </label>
        <label className="text-sm font-bold">Due to
          <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="form-input mt-2 w-full" />
        </label>
        <button type="button" onClick={() => { setSelectedBatches([]); setBuyer(""); setStatus("open"); setDateFrom(""); setDateTo(""); setFocusedSale(""); }} className="text-left text-sm font-bold underline">Clear filters</button>
      </section>

      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Open sales</p><strong className="text-2xl">{report?.count ?? 0}</strong></div>
        <div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Total remaining</p><strong className="text-2xl">{formatCurrency(report?.total_receivable ?? 0)}</strong></div>
        <div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Average balance</p><strong className="text-2xl">{formatCurrency(averageBalance)}</strong></div>
      </div>

      <section className="mt-6 overflow-x-auto rounded-xl border border-[var(--line)] bg-white">
        <table className="min-w-[1180px] w-full text-sm">
          <thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">Sale</th><th className="p-3">Buyer</th><th className="p-3">Batch</th><th className="p-3">Sale date</th><th className="p-3">Age</th><th className="p-3">Status</th><th className="p-3 text-right">Sale total</th><th className="p-3 text-right">Paid</th><th className="p-3 text-right">Remaining</th><th className="p-3">Actions</th></tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={10} className="p-8 text-center">Loading receivables…</td></tr> : null}
            {!loading && !report?.results.length ? <tr><td colSpan={10} className="p-8 text-center text-[var(--navy-muted)]">No sales match these filters.</td></tr> : null}
            {report?.results.map((sale) => (
              <Fragment key={sale.sale_id}>
                <tr id={`sale-${sale.sale_id}`} className={`border-t ${focusedSale === sale.sale_id ? "bg-[var(--gold-soft)]" : ""}`}>
                  <td className="p-3 font-bold">{sale.sale_id}</td><td className="p-3">{sale.buyer_name || "Not recorded"}</td>
                  <td className="p-3"><Link href={`/poultry/batches/${sale.batch}?tab=sales`} className="font-bold underline">{sale.batch_id}</Link></td>
                  <td className="p-3">{formatDate(sale.sale_date)}</td><td className="p-3">{sale.is_overdue ? `${sale.days_overdue} days overdue` : `${sale.age_days} days old`}</td>
                  <td className="p-3">{formatLabel(sale.receivable_status)}</td>
                  <td className="p-3 text-right">{formatCurrency(sale.sale_total)}</td><td className="p-3 text-right">{formatCurrency(sale.amount_paid)}</td><td className="p-3 text-right font-bold">{formatCurrency(sale.balance)}</td>
                  <td className="p-3"><div className="flex gap-2"><button type="button" onClick={() => openPayment(sale)} disabled={Number(sale.balance) <= 0} className="rounded bg-[#151f36] px-3 py-2 text-xs font-bold text-white disabled:opacity-40">Record payment</button><button type="button" onClick={() => setExpandedSale(expandedSale === sale.sale_id ? null : sale.sale_id)} className="text-xs font-bold underline">{expandedSale === sale.sale_id ? "Hide history" : "Payment history"}</button></div></td>
                </tr>
                {expandedSale === sale.sale_id ? <tr key={`${sale.sale_id}-payments`} className="bg-[#faf8f2]"><td colSpan={10} className="p-4"><div className="grid gap-2">{sale.payments.length ? sale.payments.map((item) => <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-white p-3"><span><strong>{item.payment_reference}</strong> · {formatDate(item.payment_date)} · {formatLabel(item.payment_method)} · {formatCurrency(item.amount)} · {formatLabel(item.status)}</span>{item.status === "posted" ? <button type="button" onClick={() => void reversePayment(item.id)} className="text-xs font-bold text-red-700 underline">Reverse payment</button> : <span className="text-xs text-red-700">{item.reversal_reason}</span>}</div>) : <p>No payments recorded.</p>}</div></td></tr> : null}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>
      {report && report.pages > 1 ? <nav aria-label="Receivables pagination" className="mt-5 flex flex-wrap gap-2">
        <button disabled={page === 1} onClick={() => setPage(1)} className="rounded border px-3 py-2 disabled:opacity-40">First</button>
        <button disabled={page === 1} onClick={() => setPage(page - 1)} className="rounded border px-3 py-2 disabled:opacity-40">Previous</button>
        {Array.from({length: report.pages}, (_, index) => index + 1).slice(Math.max(page - 3, 0), Math.max(page - 3, 0) + 5).map((number) => <button key={number} onClick={() => setPage(number)} aria-current={number === page ? "page" : undefined} className={`rounded border px-3 py-2 ${number === page ? "bg-[var(--navy)] text-white" : ""}`}>{number}</button>)}
        <button disabled={page === report.pages} onClick={() => setPage(page + 1)} className="rounded border px-3 py-2 disabled:opacity-40">Next</button>
        <button disabled={page === report.pages} onClick={() => setPage(report.pages)} className="rounded border px-3 py-2 disabled:opacity-40">Last</button>
        <span className="self-center text-sm text-[var(--navy-muted)]">{report.count} sales</span>
      </nav> : null}

      {paymentSale ? <div role="dialog" aria-modal="true" aria-labelledby="payment-title" className="fixed inset-0 z-50 grid place-items-center bg-[#151f36]/45 p-4"><form onSubmit={submitPayment} className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"><div className="flex items-start justify-between"><div><p className="finance-eyebrow">Collection receipt</p><h2 id="payment-title" className="mt-2 text-2xl font-extrabold">Record payment for {paymentSale.sale_id}</h2><p className="mt-2 text-sm text-[var(--navy-muted)]">Outstanding: {formatCurrency(paymentSale.balance)}</p></div><button type="button" onClick={() => setPaymentSale(null)} aria-label="Close payment form" className="text-2xl">×</button></div><div className="mt-6 grid gap-4 sm:grid-cols-2">
        <label className="text-sm font-bold">Amount<input required type="number" min="0.01" max={paymentSale.balance} step="0.01" value={payment.amount} onChange={(event) => setPayment({ ...payment, amount: event.target.value })} className="form-input mt-2 w-full" /></label>
        <label className="text-sm font-bold">Payment date<input required type="datetime-local" value={payment.payment_date} onChange={(event) => setPayment({ ...payment, payment_date: event.target.value })} className="form-input mt-2 w-full" /></label>
        <label className="text-sm font-bold">Method<select value={payment.payment_method} onChange={(event) => setPayment({ ...payment, payment_method: event.target.value })} className="form-input mt-2 w-full"><option value="cash">Cash</option><option value="mobile_money">Mobile money</option><option value="bank_transfer">Bank transfer</option><option value="credit">Credit</option></select></label>
        <label className="text-sm font-bold">External reference<input value={payment.external_reference} onChange={(event) => setPayment({ ...payment, external_reference: event.target.value })} className="form-input mt-2 w-full" /></label>
        <label className="text-sm font-bold">Received by<input value={payment.received_by_name} onChange={(event) => setPayment({ ...payment, received_by_name: event.target.value })} className="form-input mt-2 w-full" /></label>
        <label className="text-sm font-bold">Notes<textarea value={payment.notes} onChange={(event) => setPayment({ ...payment, notes: event.target.value })} className="form-input mt-2 w-full" /></label>
      </div><div className="mt-6 flex justify-end gap-3"><button type="button" onClick={() => setPaymentSale(null)} className="rounded-lg border px-5 py-3 font-bold">Cancel</button><button disabled={submitting} className="finance-button">{submitting ? "Recording…" : "Record payment"}</button></div></form></div> : null}
    </main>
  );
}
