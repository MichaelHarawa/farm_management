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

const sourceLabel = (source: FundingSource) =>
  `${source.display_name || source.description || source.source_type}${source.batch_code ? ` — ${source.batch_code}` : ""} — ${formatCurrency(source.available_balance || 0)} available`;

export default function ExpenditureDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const expenditureId = Number(params.id);
  const [expenditure, setExpenditure] = useState<Expenditure | null>(null);
  const [sources, setSources] = useState<FundingSource[]>([]);
  const [rows, setRows] = useState<FundingRow[]>([{ funding_source: "", source_query: "", amount: "" }]);
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
      if (record.funding_allocations?.length) {
        setRows(record.funding_allocations.map((allocation) => {
          const source = availableSources.find((item) => item.id === allocation.funding_source);
          return { funding_source: allocation.funding_source, source_query: source ? sourceLabel(source) : `Funding source #${allocation.funding_source}`, amount: allocation.amount };
        }));
      } else if (availableSources.length === 1) {
        setRows([{ funding_source: availableSources[0].id, source_query: sourceLabel(availableSources[0]), amount: record.amount }]);
      }
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    }
  };

  useEffect(() => {
    if (Number.isFinite(expenditureId)) void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expenditureId]);

  const funded = useMemo(() => rows.reduce((total, row) => total + (Number(row.amount) || 0), 0), [rows]);
  const fullyFunded = Boolean(expenditure) && Number(expenditure?.amount) > 0 && Math.abs(Number(expenditure?.amount) - funded) < 0.01 && rows.every((row) => row.funding_source && Number(row.amount) > 0);
  const fundingPayload = rows.map((row) => ({ funding_source: Number(row.funding_source), amount: row.amount, classification: "reinvestment" }));

  const saveDraft = async () => {
    if (!expenditure) return;
    setBusy(true); setError(null);
    try {
      await clientApiFetch(`/api/finance/expenditures/${expenditure.id}`, { method: "PATCH", body: JSON.stringify({ funding_allocations_input: fundingPayload }) });
      await load();
    } catch (requestError) { setError(getApiErrorMessage(requestError)); } finally { setBusy(false); }
  };

  const postOrReconcile = async () => {
    if (!expenditure || !fullyFunded) return;
    setBusy(true); setError(null);
    const action = expenditure.status === "posted" ? "assign-funding" : "post";
    try {
      await clientApiFetch(`/api/finance/expenditures/${expenditure.id}/${action}`, { method: "POST", body: JSON.stringify({ funding_allocations: fundingPayload }) });
      router.push("/finance/expenditures");
      router.refresh();
    } catch (requestError) { setError(getApiErrorMessage(requestError)); } finally { setBusy(false); }
  };

  if (!expenditure) return <main className="p-8">{error || "Loading expenditure…"}</main>;

  const editableFunding = expenditure.status === "draft" || expenditure.funding_status === "unfunded";
  return <main className="mx-auto max-w-4xl p-8">
    <Link href="/finance/expenditures" className="text-sm font-bold underline">← Expenditures</Link>
    <div className="mt-6 flex flex-wrap items-start justify-between gap-4"><div><p className="finance-eyebrow">Expenditure details</p><h1 className="mt-2 text-3xl font-extrabold">{expenditure.description}</h1><p className="mt-2 text-sm text-[var(--navy-muted)]">{expenditure.expenditure_reference || `#${expenditure.id}`} · {formatDate(expenditure.expenditure_date)}</p></div><div className="text-right"><strong className="text-2xl">{formatCurrency(expenditure.amount)}</strong><p className="text-sm">{formatLabel(expenditure.status)} · {formatLabel(expenditure.funding_status || "unfunded")}</p></div></div>
    <section className="mt-6 grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-2"><div><p className="text-xs font-bold uppercase text-[var(--navy-muted)]">Funding source</p><p>Where the cash was paid from</p></div><div><p className="text-xs font-bold uppercase text-[var(--navy-muted)]">Beneficiary / cost bearer</p><p>{expenditure.beneficiary_detail || formatLabel(expenditure.beneficiary_type || "not allocated")}</p></div></section>
    <section className="mt-6 rounded-xl border bg-white p-5"><div className="flex justify-between"><h2 className="text-xl font-extrabold">Where was this expenditure paid from?</h2><span className={fullyFunded ? "font-bold text-green-700" : "font-bold text-amber-700"}>{formatCurrency(funded)} / {formatCurrency(expenditure.amount)}{fullyFunded ? " ✓" : ""}</span></div>
      {!editableFunding ? <p className="mt-4 text-sm text-[var(--navy-muted)]">Posted funding allocations are locked for audit.</p> : <div className="mt-4 grid gap-3">{rows.map((row, index) => <div key={index} className="flex flex-wrap gap-3"><input aria-label="Funding source" list={`detail-funding-${index}`} value={row.source_query} onChange={(event) => { const selected = sources.find((source) => sourceLabel(source) === event.target.value); setRows((current) => current.map((item, rowIndex) => rowIndex === index ? { ...item, source_query: event.target.value, funding_source: selected?.id || "" } : item)); }} className="form-input min-w-72 flex-1" placeholder="Search batch, owner, farm, or loan cash…" /><datalist id={`detail-funding-${index}`}>{sources.map((source) => <option key={source.id} value={sourceLabel(source)} />)}</datalist><input type="number" min="0.01" step="0.01" value={row.amount} onChange={(event) => setRows((current) => current.map((item, rowIndex) => rowIndex === index ? { ...item, amount: event.target.value } : item))} className="form-input w-40" placeholder="Amount" />{rows.length > 1 ? <button type="button" onClick={() => setRows((current) => current.filter((_, rowIndex) => rowIndex !== index))} className="text-red-700">Remove</button> : null}</div>)}<button type="button" onClick={() => setRows((current) => [...current, { funding_source: "", source_query: "", amount: "" }])} className="w-fit text-sm font-bold underline">+ Split across another source</button></div>}
      {sources.length === 0 && editableFunding ? <p className="mt-4 rounded-lg bg-amber-50 p-4 text-sm text-amber-900">No cash source has a positive balance. Record a sale collection, or add an owner, farm, or loan funding receipt before posting.</p> : null}
    </section>
    {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-4 text-red-800">{error}</p> : null}
    {editableFunding ? <div className="mt-6 flex justify-end gap-3">{expenditure.status === "draft" ? <button type="button" disabled={busy} onClick={() => void saveDraft()} className="rounded-lg border px-5 py-3 font-bold">Save funding draft</button> : null}<button type="button" disabled={busy || !fullyFunded} onClick={() => void postOrReconcile()} className="finance-button disabled:opacity-40">{expenditure.status === "posted" ? "Assign historical funding" : "Post expenditure"}</button></div> : null}
  </main>;
}
