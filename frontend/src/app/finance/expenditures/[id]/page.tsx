"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { Expenditure, FundingSource } from "@/features/finance/types";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";

type FundingRow = { funding_source: number | ""; source_query: string; amount: string };

const blankRow = (): FundingRow => ({ funding_source: "", source_query: "", amount: "" });
const paymentKey = () => globalThis.crypto?.randomUUID?.() ?? `payment-${Date.now()}-${Math.random()}`;
const sourceLabel = (source: FundingSource) =>
  `${source.display_name || source.description || source.source_type}${source.batch_code ? ` — ${source.batch_code}` : ""} — ${formatCurrency(source.available_balance || 0)} available`;

export default function ExpenditureDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const expenditureId = Number(params.id);
  const [expenditure, setExpenditure] = useState<Expenditure | null>(null);
  const [sources, setSources] = useState<FundingSource[]>([]);
  const [rows, setRows] = useState<FundingRow[]>([blankRow()]);
  const [idempotencyKey, setIdempotencyKey] = useState(paymentKey);
  const [paymentDate, setPaymentDate] = useState(new Date().toISOString().slice(0, 10));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [record, availableSources] = await Promise.all([
        clientApiFetch<Expenditure>(`/api/finance/expenditures/${expenditureId}`),
        clientApiFetch<FundingSource[]>("/api/finance/funding-sources"),
      ]);
      setExpenditure(record);
      setSources(availableSources);
      if (record.status === "draft" && record.funding_allocations?.length) {
        setRows(record.funding_allocations.map((allocation) => {
          const source = availableSources.find((item) => item.id === allocation.funding_source);
          return { funding_source: allocation.funding_source, source_query: source ? sourceLabel(source) : `Funding source #${allocation.funding_source}`, amount: String(allocation.amount) };
        }));
      } else {
        const balance = Number(record.balance_due ?? record.amount);
        const first = availableSources.length === 1 ? availableSources[0] : undefined;
        setRows([{ funding_source: first?.id || "", source_query: first ? sourceLabel(first) : "", amount: balance > 0 ? String(balance) : "" }]);
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  useEffect(() => {
    if (Number.isFinite(expenditureId)) void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expenditureId]);

  const allocationTotal = useMemo(() => rows.reduce((total, row) => total + (Number(row.amount) || 0), 0), [rows]);
  const target = Number(expenditure?.status === "draft" ? expenditure?.amount : expenditure?.balance_due || 0);
  const validRows = rows.every((row) => row.funding_source && Number(row.amount) > 0);
  const fullPayment = target > 0 && Math.abs(target - allocationTotal) < 0.01 && validRows;
  const validLaterPayment = allocationTotal > 0 && allocationTotal <= target && validRows;
  const fundingPayload = rows.map((row) => ({ funding_source: Number(row.funding_source), amount: row.amount, classification: "reinvestment" }));

  const runAction = async (path: string, body: object) => {
    if (!expenditure) return;
    setBusy(true); setError(null);
    try {
      await clientApiFetch(`/api/finance/expenditures/${expenditure.id}/${path}`, { method: "POST", body: JSON.stringify(body) });
      setIdempotencyKey(paymentKey());
      await load();
      router.refresh();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  const saveDraft = async () => {
    if (!expenditure) return;
    setBusy(true); setError(null);
    try {
      await clientApiFetch(`/api/finance/expenditures/${expenditure.id}`, { method: "PATCH", body: JSON.stringify({ funding_allocations_input: fundingPayload }) });
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setBusy(false);
    }
  };

  if (!expenditure) return <main className="p-8">{error || "Loading expenditure…"}</main>;

  const canRecordPayment = expenditure.status === "posted" && Number(expenditure.balance_due || 0) > 0;
  const paymentRows = expenditure.funding_allocations || [];

  return (
    <main className="mx-auto max-w-5xl p-8">
      <Link href="/finance/expenditures" className="text-sm font-bold underline">← Expenditures</Link>
      <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="finance-eyebrow">Expenditure details · {formatLabel(expenditure.origin || "finance")}</p>
          <h1 className="mt-2 text-3xl font-extrabold">{expenditure.description}</h1>
          <p className="mt-2 text-sm text-[var(--navy-muted)]">{expenditure.expenditure_reference || `#${expenditure.id}`} · {formatDate(expenditure.expenditure_date)}</p>
        </div>
        <div className="text-right">
          <strong className="text-2xl">{formatCurrency(expenditure.amount)}</strong>
          <p className="text-sm">{formatLabel(expenditure.status)} · {formatLabel(expenditure.payment_status || "unpaid")}</p>
          <p className="text-sm text-[var(--navy-muted)]">Balance due {formatCurrency(expenditure.balance_due || 0)}</p>
        </div>
      </div>

      <section className="mt-6 grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-2">
        <div>
          <p className="text-xs font-bold uppercase text-[var(--navy-muted)]">Payment source · cash ledger</p>
          <p className="mt-1">{paymentRows.length ? paymentRows.map((row) => `${formatCurrency(row.amount)} from source #${row.funding_source}`).join("; ") : "Not paid or historical source unassigned"}</p>
        </div>
        <div>
          <p className="text-xs font-bold uppercase text-[var(--navy-muted)]">Cost assignment · profitability ledger</p>
          {expenditure.beneficiary_batches?.length ? expenditure.beneficiary_batches.map((beneficiary) => (
            <p key={beneficiary.id} className="mt-1"><Link href={`/poultry/batches/${beneficiary.id}?tab=costs`} className="font-bold underline">{beneficiary.batch_id}</Link> · {formatCurrency(beneficiary.amount)}</p>
          )) : <p className="mt-1">{expenditure.beneficiary_detail || formatLabel(expenditure.beneficiary_type || "not allocated")}</p>}
        </div>
      </section>

      {(expenditure.status === "draft" || canRecordPayment) ? (
        <section className="mt-6 rounded-xl border bg-white p-5">
          <div className="flex flex-wrap justify-between gap-3">
            <div><p className="finance-eyebrow">Cash payment</p><h2 className="mt-1 text-xl font-extrabold">{expenditure.status === "draft" ? "Fund and post" : "Record payment against this payable"}</h2></div>
            <span className={(expenditure.status === "draft" ? fullPayment : validLaterPayment) ? "font-bold text-green-700" : "font-bold text-amber-700"}>{formatCurrency(allocationTotal)} / {formatCurrency(target)}</span>
          </div>
          <div className="mt-4 grid gap-3">
            {rows.map((row, index) => (
              <div key={index} className="flex flex-wrap gap-3">
                <input aria-label={`Funding source ${index + 1}`} list={`detail-funding-${index}`} value={row.source_query} onChange={(event) => { const selected = sources.find((source) => sourceLabel(source) === event.target.value); setRows((current) => current.map((item, rowIndex) => rowIndex === index ? { ...item, source_query: event.target.value, funding_source: selected?.id || "" } : item)); }} className="form-input min-w-72 flex-1" placeholder="Search batch revenue, equity, farm cash, or loan…" />
                <datalist id={`detail-funding-${index}`}>{sources.map((source) => <option key={source.id} value={sourceLabel(source)} />)}</datalist>
                <input aria-label={`Payment amount ${index + 1}`} type="number" min="0.01" step="0.01" value={row.amount} onChange={(event) => setRows((current) => current.map((item, rowIndex) => rowIndex === index ? { ...item, amount: event.target.value } : item))} className="form-input w-40" placeholder="Amount" />
                {rows.length > 1 ? <button type="button" onClick={() => setRows((current) => current.filter((_, rowIndex) => rowIndex !== index))} className="font-bold text-red-700">Remove</button> : null}
              </div>
            ))}
            <button type="button" onClick={() => setRows((current) => [...current, blankRow()])} className="w-fit text-sm font-bold underline">Split across another source</button>
            {canRecordPayment ? <label className="text-sm font-bold">Payment date<input type="date" value={paymentDate} onChange={(event) => setPaymentDate(event.target.value)} className="form-input mt-2 block" /></label> : null}
          </div>
          {sources.length === 0 ? <p className="mt-4 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">No active cash source has a positive balance. Record a collection or funding receipt first.</p> : null}
        </section>
      ) : null}

      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-4 text-red-800">{error}</p> : null}

      {expenditure.status === "draft" ? (
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button type="button" disabled={busy || !validRows} onClick={() => void saveDraft()} className="rounded-lg border px-5 py-3 font-bold disabled:opacity-40">Save payment draft</button>
          <button type="button" disabled={busy} onClick={() => void runAction("post", { payment_status: "credit", funding_allocations: [] })} className="rounded-lg border border-amber-700 px-5 py-3 font-bold text-amber-800">Post as payable</button>
          <button type="button" disabled={busy || !fullPayment} onClick={() => void runAction("post", { funding_allocations: fundingPayload })} className="finance-button disabled:opacity-40">Post as paid</button>
        </div>
      ) : null}

      {canRecordPayment ? (
        <div className="mt-6 flex justify-end">
          <button type="button" disabled={busy || !validLaterPayment} onClick={() => void runAction("record-payment", { funding_allocations: fundingPayload, idempotency_key: idempotencyKey, payment_date: paymentDate })} className="finance-button disabled:opacity-40">Record payment</button>
        </div>
      ) : null}
    </main>
  );
}
