"use client";

import { useMemo, useState } from "react";

import { formatDate, formatLabel } from "../utils/formatters";

type PeriodOption = {
  id: number;
  period_start: string;
  period_end: string;
  status: "open" | "closed";
};

type BatchOption = {
  id: number;
  batch_id: string;
  bird_type: string;
  status: string;
  entry_date: string;
};

export function BatchAnalysisFilter({
  periods,
  batches,
  selectedPeriod,
  selectedIds,
}: {
  periods: PeriodOption[];
  batches: BatchOption[];
  selectedPeriod: string;
  selectedIds: number[];
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(selectedIds);
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return batches
      .filter((batch) => !term || `${batch.batch_id} ${batch.bird_type} ${batch.status}`.toLowerCase().includes(term))
      .slice(0, 60);
  }, [batches, query]);

  function toggle(batchId: number) {
    setSelected((current) => current.includes(batchId)
      ? current.filter((id) => id !== batchId)
      : [...current, batchId]);
  }

  return (
    <form method="get" className="grid min-w-0 gap-4 overflow-hidden">
      {selected.map((batchId) => <input key={batchId} type="hidden" name="batch" value={batchId} />)}
      <div className="grid min-w-0 gap-4 lg:grid-cols-[0.7fr_1.3fr]">
        <label className="min-w-0 text-sm font-bold">
          Reporting period
          <select name="period" defaultValue={selectedPeriod} className="form-input mt-2 min-w-0 max-w-full bg-white">
            {periods.map((row) => (
              <option key={row.id} value={row.id}>
                {formatDate(row.period_start)}–{formatDate(row.period_end)} · {formatLabel(row.status)}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-sm font-bold">
          Find a batch
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="form-input mt-2 min-w-0 max-w-full bg-white"
            placeholder="Search batch ID, bird type, or status…"
          />
        </label>
      </div>

      <div className="min-w-0 overflow-hidden rounded-xl border border-[var(--line)] bg-white/60">
        <div className="flex min-w-0 flex-col gap-2 border-b border-[var(--line)] px-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-4">
          <p className="min-w-0 text-sm">
            <strong>{selected.length ? `${selected.length} batch${selected.length === 1 ? "" : "es"} selected` : "All batches selected"}</strong>
            <span className="ml-2 hidden text-[var(--navy-muted)] sm:inline">No individual selection analyzes every batch.</span>
          </p>
          {selected.length ? <button type="button" className="w-fit text-sm font-bold underline" onClick={() => setSelected([])}>Use all batches</button> : null}
        </div>
        <div className="grid max-h-64 min-w-0 gap-1 overflow-y-auto p-2 sm:grid-cols-2 xl:grid-cols-3">
          {visible.map((batch) => {
            const checked = selected.includes(batch.id);
            return (
              <label key={batch.id} className={`flex min-w-0 cursor-pointer items-start gap-3 rounded-lg border p-3 ${checked ? "border-[var(--gold)] bg-[var(--gold-soft)]" : "border-transparent hover:bg-white"}`}>
                <input type="checkbox" checked={checked} onChange={() => toggle(batch.id)} className="mt-1 size-4 shrink-0" />
                <span className="min-w-0">
                  <strong className="block break-all text-sm">{batch.batch_id}</strong>
                  <span className="text-xs text-[var(--navy-muted)]">{formatLabel(batch.bird_type)} · {formatLabel(batch.status)} · {formatDate(batch.entry_date)}</span>
                </span>
              </label>
            );
          })}
          {!visible.length ? <p className="p-3 text-sm text-[var(--navy-muted)]">No batch matches this search.</p> : null}
        </div>
        {batches.length > visible.length ? <p className="border-t border-[var(--line)] px-4 py-2 text-xs text-[var(--navy-muted)]">Showing the first {visible.length} matches. Refine the search to find another batch.</p> : null}
      </div>

      <div><button className="finance-button w-full px-6 py-3 sm:w-auto">Analyze selected batches</button></div>
    </form>
  );
}
