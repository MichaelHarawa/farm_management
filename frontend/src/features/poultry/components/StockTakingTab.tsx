"use client";

import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";
import type { BirdStockTake, BirdStockTakeSummary, RecordBirdStockTakePayload } from "../types";
import { formatNumber } from "../utils/formatters";

export function StockTakingTab({ batchId, initialData, canRecord, blocked }: {
  batchId: number;
  initialData: BirdStockTakeSummary;
  canRecord: boolean;
  blocked: boolean;
}) {
  const router = useRouter();
  const [data, setData] = useState(initialData);
  const [physicalCount, setPhysicalCount] = useState("");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const attempt = useRef<{ fingerprint: string; id: string } | null>(null);
  const expected = data.expected_live_birds;
  const count = physicalCount === "" ? null : Number(physicalCount);
  const variance = count === null ? null : count - expected;
  const path = `/api/poultry/batches/${batchId}/stock-takes`;
  const latest = data.records[0];

  async function refresh() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      setData(await clientApiFetch<BirdStockTakeSummary>(path));
      // A fresh count must be verified against the newly loaded balance.
      setPhysicalCount("");
      attempt.current = null;
      router.refresh();
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (count === null || !Number.isInteger(count) || count < 0) {
      setError("Enter a whole number of birds, including zero if none remain.");
      return;
    }
    if (variance && !reason.trim()) {
      setError("Explain the shortage or surplus before confirming the count.");
      return;
    }
    const values = { expected_live_birds: expected, physical_count: count, reason: reason.trim(), notes: notes.trim() };
    const fingerprint = JSON.stringify(values);
    if (attempt.current?.fingerprint !== fingerprint) {
      attempt.current = { fingerprint, id: crypto.randomUUID() };
    }
    const payload: RecordBirdStockTakePayload = { ...values, request_id: attempt.current.id };
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const record = await clientApiFetch<BirdStockTake>(path, { method: "POST", body: JSON.stringify(payload) });
      setData({ expected_live_birds: record.physical_count, records: [record, ...data.records.filter((row) => row.id !== record.id)] });
      setPhysicalCount("");
      setReason("");
      setNotes("");
      attempt.current = null;
      setSuccess(record.shortage
        ? `Count saved. Shortage of ${formatNumber(record.shortage)} birds recorded; live birds updated to ${formatNumber(record.physical_count)}.`
        : `Count saved. Live birds: ${formatNumber(record.physical_count)}.`);
      router.refresh();
    } catch (failure) {
      setError(getApiErrorMessage(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-8 grid gap-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-extrabold">Compare live birds with the physical count</h2>
            <p className="mt-2 text-sm text-slate-600">Record a count now. Confirming a difference updates the batch&apos;s available birds.</p>
          </div>
          <button type="button" className="btn-secondary" onClick={refresh} disabled={busy}>Refresh live birds</button>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-3">
          {[
            ["Expected live birds", formatNumber(expected)],
            ["Physical count", count === null ? "Enter count below" : formatNumber(count)],
            ["Difference", variance === null ? "—" : variance === 0 ? "Matched" : `${formatNumber(Math.abs(variance))} ${variance < 0 ? "shortage" : "surplus"}`],
          ].map(([label, value]) => (
            <div key={label} className="rounded-2xl bg-slate-50 p-4">
              <p className="text-sm text-slate-600">{label}</p>
              <p className="mt-2 text-xl font-bold">{value}</p>
            </div>
          ))}
        </div>
        {error ? <p role="alert" className="mt-4 text-red-700">{error}</p> : null}
        {success ? <p role="status" className="mt-4 text-green-800">{success}</p> : null}
        {blocked ? <p className="mt-5 text-slate-600">Stock taking is available for active, mature, and selling batches before profitability is finalized.</p> : !canRecord ? (
          <p className="mt-5 text-slate-600">A farm supervisor or manager can confirm a stock count.</p>
        ) : expected < 0 ? <p className="mt-5 text-red-700">Resolve the negative flock balance before taking stock.</p> : (
          <form onSubmit={submit} className="mt-6 grid gap-5">
            <fieldset disabled={busy} className="grid gap-5 md:grid-cols-2">
              <label className="grid gap-2 text-sm font-semibold">
                Physical count of birds
                <input className="form-input" type="number" min="0" max="2147483647" step="1" required
                  value={physicalCount} onChange={(event) => { setPhysicalCount(event.target.value); setSuccess(""); }} />
              </label>
              <label className="grid gap-2 text-sm font-semibold">
                Reason {variance ? "(required for a difference)" : "(optional)"}
                <input className="form-input" maxLength={255} required={Boolean(variance)}
                  placeholder="For example: missing birds found during pen count"
                  value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <label className="grid gap-2 text-sm font-semibold md:col-span-2">
                Count notes (optional)
                <textarea className="form-input" rows={3} maxLength={5000}
                  placeholder="Pens checked, who counted, and any follow-up needed"
                  value={notes} onChange={(event) => setNotes(event.target.value)} />
              </label>
            </fieldset>
            <p className="text-sm text-slate-600">
              {variance ? `This confirms ${formatNumber(Math.abs(variance))} ${variance < 0 ? "missing" : "additional"} birds and changes live birds to ${formatNumber(count ?? 0)}. A shortage is recorded separately from mortality.`
                : "Matching counts are saved in the history without changing the flock."}
              {" "}The count time and your account are recorded automatically.
            </p>
            <button className="btn-primary justify-self-start" type="submit" disabled={busy || count === null}>
              {busy ? "Saving…" : variance ? "Confirm count and adjust birds" : "Save stock count"}
            </button>
          </form>
        )}
      </section>
      <section className="rounded-3xl border border-slate-200 bg-white p-6">
        <h2 className="text-2xl font-extrabold">Stock count and shortage history</h2>
        <p className="mt-2 text-sm text-slate-600">
          {latest ? `Last counted: ${new Date(latest.counted_at).toLocaleString()}.` : "No physical counts recorded yet."}
          {" "}Past counts remain as recorded. Later sales and mortality change the live balance.
        </p>
        {data.records.length ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead><tr>{["Counted", "Expected", "Physical", "Shortage / surplus", "Reason / notes", "Recorded by"].map((label) => (
                <th key={label} className="border-b p-3">{label}</th>
              ))}</tr></thead>
              <tbody>{data.records.map((record) => (
                <tr key={record.id}>
                  <td className="border-b p-3 whitespace-nowrap">{new Date(record.counted_at).toLocaleString()}</td>
                  <td className="border-b p-3">{formatNumber(record.expected_live_birds)}</td>
                  <td className="border-b p-3">{formatNumber(record.physical_count)}</td>
                  <td className={`border-b p-3 font-semibold ${record.shortage ? "text-red-700" : ""}`}>
                    {record.variance === 0 ? "Matched" : `${formatNumber(Math.abs(record.variance))} ${record.shortage ? "shortage" : "surplus"}`}
                  </td>
                  <td className="max-w-sm border-b p-3"><p>{record.reason || "—"}</p><p className="whitespace-pre-wrap text-slate-600">{record.notes}</p></td>
                  <td className="border-b p-3">{record.recorded_by_name}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
