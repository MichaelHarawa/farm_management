"use client";

import { useMemo, useState } from "react";

import type { PoultryBatch } from "@/features/poultry/types";

import { formatDate, formatLabel } from "../utils/formatters";

export function OwnerCapitalBatchFilter({
  batches,
  initialSelectedIds,
}: {
  batches: PoultryBatch[];
  initialSelectedIds: number[];
}) {
  const [query, setQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState(initialSelectedIds);
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const normalizedQuery = query.trim().toLowerCase();
  const matchingBatches = useMemo(
    () =>
      batches.filter((batch) =>
        !normalizedQuery ||
        [batch.batch_id, batch.bird_type, batch.status]
          .join(" ")
          .toLowerCase()
          .includes(normalizedQuery)
      ),
    [batches, normalizedQuery]
  );
  const visibleBatches = matchingBatches.slice(0, 100);

  function toggle(batchId: number) {
    setSelectedIds((current) =>
      current.includes(batchId)
        ? current.filter((id) => id !== batchId)
        : [...current, batchId]
    );
  }

  return (
    <fieldset className="grid gap-2 lg:col-span-2">
      <legend className="text-sm font-bold">Batches</legend>
      {selectedIds.map((batchId) => (
        <input key={batchId} type="hidden" name="batch" value={batchId} />
      ))}
      <input
        className="form-input w-full"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search batch ID, bird type, or status"
        aria-label="Search batches"
      />
      <div className="max-h-32 overflow-y-auto rounded-lg border border-[var(--line)] bg-white/55 p-2">
        {visibleBatches.length ? (
          <div className="grid gap-1 sm:grid-cols-2">
            {visibleBatches.map((batch) => (
              <label
                className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 hover:bg-[var(--gold-soft)]"
                key={batch.id}
              >
                <input
                  className="mt-0.5 size-4 accent-[var(--navy)]"
                  type="checkbox"
                  checked={selected.has(batch.id)}
                  onChange={() => toggle(batch.id)}
                />
                <span className="min-w-0">
                  <span className="block truncate text-xs font-extrabold text-[var(--navy)]">
                    {batch.batch_id}
                  </span>
                  <span className="block truncate text-[0.68rem] font-normal text-[var(--navy-muted)]">
                    {formatLabel(batch.bird_type)} · {formatLabel(batch.status)} · {formatDate(batch.entry_date)}
                  </span>
                </span>
              </label>
            ))}
          </div>
        ) : (
          <p className="px-2 py-3 text-xs font-normal text-[var(--navy-muted)]">
            No batches match this search.
          </p>
        )}
      </div>
      <span className="text-xs font-normal text-[var(--navy-muted)]">
        {selectedIds.length
          ? `${selectedIds.length} batch(es) selected. Search again to add more.`
          : "No batch filter: the report includes all batches."}
        {matchingBatches.length > visibleBatches.length
          ? ` Showing the first ${visibleBatches.length} matches; refine the search for more.`
          : ""}
      </span>
    </fieldset>
  );
}
