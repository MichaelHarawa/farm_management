"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import { Dialog } from "@/components/ui";
import type { PoultryBatch } from "@/features/poultry/types";

import { MAX_BATCH_SELECTION } from "../constants";
import { formatDate, formatLabel } from "../utils/formatters";

export function BatchSelectionFilter({
  batches,
  selectedBatchIds,
}: {
  batches: PoultryBatch[];
  selectedBatchIds: number[];
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState(selectedBatchIds);
  const [pickerOpen, setPickerOpen] = useState(false);

  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const batchesById = useMemo(
    () => new Map(batches.map((batch) => [batch.id, batch])),
    [batches]
  );
  const normalizedQuery = query.trim().toLowerCase();
  const visibleBatches = batches.filter((batch) => {
    if (!normalizedQuery) return true;
    return [batch.batch_id, batch.bird_type, batch.status]
      .join(" ")
      .toLowerCase()
      .includes(normalizedQuery);
  });

  function toggleBatch(batchId: number) {
    setSelectedIds((current) => {
      if (current.includes(batchId)) {
        return current.filter((id) => id !== batchId);
      }
      return current.length < MAX_BATCH_SELECTION ? [...current, batchId] : current;
    });
  }

  function selectVisible() {
    setSelectedIds((current) =>
      [...new Set([...current, ...visibleBatches.map((batch) => batch.id)])].slice(
        0,
        MAX_BATCH_SELECTION
      )
    );
  }

  function applySelection() {
    if (!selectedIds.length || selectedIds.length > MAX_BATCH_SELECTION) return;
    const searchParams = new URLSearchParams();
    selectedIds.forEach((batchId) => searchParams.append("batch", String(batchId)));
    startTransition(() => {
      router.push(`/finance/batches?${searchParams.toString()}`);
    });
  }

  function clearSelection() {
    setSelectedIds([]);
    startTransition(() => {
      router.push("/finance/batches");
    });
  }

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-bold text-[var(--navy)]">
            Selected batches
          </p>
          <p className="text-xs text-[var(--navy-muted)]">
            {selectedIds.length} of max {MAX_BATCH_SELECTION}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPickerOpen(true)}
          className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-1.5 text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy)]"
        >
          Choose batches…
        </button>
      </div>

      {selectedIds.length ? (
        <div className="flex max-h-20 flex-wrap gap-2 overflow-y-auto" aria-label="Selected batches">
          {selectedIds.map((batchId) => (
            <button
              key={batchId}
              type="button"
              onClick={() => toggleBatch(batchId)}
              className="rounded-full border border-[var(--line)] bg-[var(--gold-soft)] px-3 py-1 text-xs font-extrabold text-[var(--navy)]"
              title="Remove from selection"
            >
              {batchesById.get(batchId)?.batch_id ?? `Batch ${batchId}`} ×
            </button>
          ))}
        </div>
      ) : (
        <p className="text-sm font-semibold text-[var(--danger)]">
          No batches selected. Open the chooser to pick one or more.
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={clearSelection}
          disabled={!selectedIds.length}
          className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy)] disabled:opacity-50"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={applySelection}
          disabled={
            !selectedIds.length ||
            selectedIds.length > MAX_BATCH_SELECTION ||
            isPending
          }
          className="finance-button disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isPending ? "Analyzing..." : "Analyze selected"}
        </button>
      </div>

      {selectedIds.length >= MAX_BATCH_SELECTION ? (
        <p className="text-sm font-semibold text-[var(--navy-muted)]">
          Limit reached: {MAX_BATCH_SELECTION} batches max.
        </p>
      ) : null}

      <Dialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="Choose poultry batches"
        size="lg"
      >
        <div className="grid gap-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <label className="grid flex-1 gap-2 text-sm font-bold text-[var(--navy)]">
              Search
              <input
                className="form-input"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Batch ID, bird type, or status"
              />
            </label>
            <p className="text-sm font-semibold text-[var(--navy-muted)]">
              {selectedIds.length} selected
            </p>
          </div>

          <div className="max-h-[22rem] overflow-y-auto rounded-lg border border-[var(--line)] bg-white/55 p-2">
            {visibleBatches.length ? (
              <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {visibleBatches.map((batch) => (
                  <li key={batch.id}>
                    <label className="flex cursor-pointer items-start gap-3 rounded-md px-3 py-2.5 transition hover:bg-[var(--gold-soft)]">
                      <input
                        className="mt-1 size-4 accent-[var(--navy)]"
                        type="checkbox"
                        checked={selected.has(batch.id)}
                        onChange={() => toggleBatch(batch.id)}
                      />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-extrabold text-[var(--navy)]">
                          {batch.batch_id}
                        </span>
                        <span className="mt-0.5 block text-xs text-[var(--navy-muted)]">
                          {formatLabel(batch.bird_type)} · {formatLabel(batch.status)} · {formatDate(batch.entry_date)}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-6 text-sm text-[var(--navy-muted)]">
                No batches match this search.
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-[var(--line)] pt-4">
            <button
              type="button"
              onClick={selectVisible}
              disabled={!visibleBatches.length}
              className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy)] disabled:opacity-50"
            >
              Select visible
            </button>
            <button
              type="button"
              onClick={() => {
                setSelectedIds([]);
              }}
              disabled={!selectedIds.length}
              className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy)] disabled:opacity-50"
            >
              Clear inside picker
            </button>
            <div className="flex-1" />
            <button
              type="button"
              onClick={() => setPickerOpen(false)}
              className="rounded-full border border-[var(--line)] bg-white/70 px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy)]"
            >
              Close
            </button>
            <button
              type="button"
              onClick={() => {
                applySelection();
                setPickerOpen(false);
              }}
              disabled={
                !selectedIds.length ||
                selectedIds.length > MAX_BATCH_SELECTION ||
                isPending
              }
              className="finance-button disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending ? "Analyzing..." : "Analyze & close"}
            </button>
          </div>

          <p className="text-xs text-[var(--navy-muted)]">
            Changes here update your selection. Click “Analyze selected” outside to refresh the report.
          </p>
        </div>
      </Dialog>
    </div>
  );
}
