"use client";

import { useEffect, useId, useState } from "react";

import { clientApiFetch } from "@/lib/client-api";

import type { FundingSource, PaginatedFundingSources } from "../types";
import { formatCurrency, formatLabel } from "../utils/formatters";

const sourceFilters = [
  { label: "All", value: "" },
  { label: "Batch sales", value: "batch_collection" },
  { label: "Owner equity", value: "owner_capital" },
  { label: "Farm cash", value: "general_farm_cash" },
  { label: "Loans", value: "loan" },
  { label: "Grants & other", value: "grant,other_income" },
] as const;

export function fundingSourceDisplayLabel(source: FundingSource): string {
  const name = source.batch_code
    ? `Batch ${source.batch_code} sales`
    : source.display_name || source.description || formatLabel(source.source_type);
  return `${name} — ${formatCurrency(source.available_balance)} available`;
}

export function FundingSourcePicker({
  value,
  displayValue,
  onSelect,
  ariaLabel,
  disabled = false,
}: {
  value: number | string;
  displayValue: string;
  onSelect: (source: FundingSource | null) => void;
  ariaLabel: string;
  disabled?: boolean;
}) {
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [draftQuery, setDraftQuery] = useState<string | null>(null);
  const [sourceType, setSourceType] = useState("");
  const [results, setResults] = useState<FundingSource[]>([]);
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const searchText = draftQuery ?? "";

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setError("");
      const query = new URLSearchParams({ page: "1", page_size: "20" });
      if (searchText.trim()) query.set("search", searchText.trim());
      if (sourceType) query.set("source_type", sourceType);
      clientApiFetch<PaginatedFundingSources>(
        `/api/finance/funding-sources?${query.toString()}`,
        { signal: controller.signal },
      )
        .then((response) => {
          setResults(response.results);
          setCurrentPage(1);
          setHasMore(Boolean(response.next));
        })
        .catch((requestError: unknown) => {
          if (!controller.signal.aborted) {
            setError(requestError instanceof Error ? requestError.message : "Could not load funding sources.");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [open, searchText, sourceType]);

  const loadMore = async () => {
    const nextPage = currentPage + 1;
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({ page: String(nextPage), page_size: "20" });
      if (searchText.trim()) query.set("search", searchText.trim());
      if (sourceType) query.set("source_type", sourceType);
      const response = await clientApiFetch<PaginatedFundingSources>(
        `/api/finance/funding-sources?${query.toString()}`,
      );
      setResults((current) => [
        ...current,
        ...response.results.filter(
          (source) => !current.some((existing) => existing.id === source.id),
        ),
      ]);
      setCurrentPage(nextPage);
      setHasMore(Boolean(response.next));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load more sources.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-w-0">
      <div className={`flex items-center rounded-lg border bg-white ${open ? "border-[var(--gold)] ring-2 ring-[var(--gold)]/20" : "border-[var(--line)]"}`}>
        <input
          role="combobox"
          aria-label={ariaLabel}
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          disabled={disabled}
          value={draftQuery ?? displayValue}
          onFocus={() => setOpen(true)}
          onBlur={() => window.setTimeout(() => setOpen(false), 180)}
          onChange={(event) => {
            setDraftQuery(event.target.value);
            onSelect(null);
            setOpen(true);
          }}
          placeholder="Search by batch ID or source name…"
          className="min-w-0 flex-1 bg-transparent px-4 py-3 outline-none disabled:opacity-50"
        />
        {value ? (
          <button
            type="button"
            aria-label={`Clear ${ariaLabel}`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              setDraftQuery("");
              onSelect(null);
              setOpen(true);
            }}
            className="px-3 py-2 text-lg text-[var(--navy-muted)]"
          >
            ×
          </button>
        ) : null}
      </div>

      {open ? (
        <div className="absolute z-40 mt-2 w-full min-w-0 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-[var(--line)] bg-white shadow-2xl sm:min-w-[22rem]">
          <div className="flex flex-wrap gap-2 border-b bg-[#f8f4e8] p-3">
            {sourceFilters.map((filter) => (
              <button
                key={filter.value}
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setSourceType(filter.value)}
                className={`rounded-full border px-3 py-1.5 text-xs font-bold ${sourceType === filter.value ? "border-[var(--navy)] bg-[var(--navy)] text-white" : "border-[var(--line)] bg-white text-[var(--navy)]"}`}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <div id={listboxId} role="listbox" className="max-h-72 overflow-y-auto p-2">
            {results.map((source) => (
              <button
                key={source.id}
                type="button"
                role="option"
                aria-selected={String(value) === String(source.id)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onSelect(source);
                  setDraftQuery(null);
                  setOpen(false);
                }}
                className={`flex w-full items-center justify-between gap-4 rounded-lg px-3 py-3 text-left hover:bg-[var(--gold-soft)] ${String(value) === String(source.id) ? "bg-[var(--gold-soft)]" : ""}`}
              >
                <span className="min-w-0">
                  <strong className="block truncate text-sm text-[var(--navy)]">{source.batch_code ? `Batch ${source.batch_code} sales` : source.display_name}</strong>
                  <span className="mt-1 block text-xs text-[var(--navy-muted)]">{formatLabel(source.source_type)}</span>
                </span>
                <span className="shrink-0 text-right text-sm font-bold text-green-700">{formatCurrency(source.available_balance)}<span className="block text-[0.65rem] font-medium uppercase tracking-wide text-[var(--navy-muted)]">available</span></span>
              </button>
            ))}
            {!loading && !results.length ? <p className="p-5 text-center text-sm text-[var(--navy-muted)]">No funded sources match this search.</p> : null}
            {error ? <p role="alert" className="p-3 text-sm text-red-700">{error}</p> : null}
            {loading ? <p className="p-3 text-center text-sm text-[var(--navy-muted)]">Searching sources…</p> : null}
            {hasMore && !loading ? <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => void loadMore()} className="w-full rounded-lg border px-3 py-2 text-sm font-bold">Load 20 more</button> : null}
          </div>
          <p className="border-t bg-[#fbfaf6] px-3 py-2 text-xs text-[var(--navy-muted)]">Only sources with available cash are shown. Search by batch ID, source name, or filter by source type.</p>
        </div>
      ) : null}
    </div>
  );
}
