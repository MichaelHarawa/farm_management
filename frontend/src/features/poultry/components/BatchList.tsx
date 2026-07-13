"use client";

import { CalendarDays, Eye, Table2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import type { PoultryBatch } from "../types";

type BatchListProps = {
  batches: PoultryBatch[];
  addBatchAction?: ReactNode;
};

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(value));
}

function formatBirdType(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getDaysToMaturity(value: string): number {
  const today = new Date();
  const maturityDate = new Date(value);
  const dayInMs = 24 * 60 * 60 * 1000;

  return Math.ceil(
    (maturityDate.getTime() - today.getTime()) / dayInMs
  );
}

export function BatchList({ batches, addBatchAction }: BatchListProps) {
  const [showLastThreeMonths, setShowLastThreeMonths] = useState(false);
  const visibleBatches = useMemo(() => {
    if (!showLastThreeMonths) {
      return batches;
    }

    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - 3);

    return batches.filter((batch) => new Date(batch.entry_date) >= startDate);
  }, [batches, showLastThreeMonths]);

  function exportView() {
    const columns = [
      "Batch ID",
      "Bird Type",
      "Quantity",
      "Entry Date",
      "Maturity Date",
      "Status",
    ];
    const rows = visibleBatches.map((batch) => {
      const daysToMaturity = getDaysToMaturity(batch.expected_maturity_date);

      return [
        batch.batch_id,
        formatBirdType(batch.bird_type),
        batch.quantity.toString(),
        formatDate(batch.entry_date),
        formatDate(batch.expected_maturity_date),
        daysToMaturity <= 0 ? "Review" : "Active",
      ];
    });
    const csvRows = [columns, ...rows].map((row) =>
      row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")
    );
    const blob = new Blob([csvRows.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = "poultry-batch-register.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-10 text-center shadow-[var(--shadow-card)]">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <Table2 className="h-5 w-5" aria-hidden="true" />
        </span>

        <p className="text-label mt-5 text-[var(--navy-muted)]">
          Batch Register / Empty
        </p>

        <h2 className="font-display mt-4 text-4xl text-[var(--navy)]">
          No production cycles yet.
        </h2>

        <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-[var(--navy-muted)]">
          Once a poultry batch is registered, it will appear here as a live
          operational readout.
        </p>

        {addBatchAction ? (
          <div className="mt-6 flex justify-center">{addBatchAction}</div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]">
      <div className="grid gap-5 border-b border-[var(--line)] px-6 py-6 lg:grid-cols-[1fr_auto] lg:items-end">
        <div>
          <p className="text-label text-[var(--navy-muted)]">
            Executive Register / Poultry
          </p>

          <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">
            Batch portfolio.
          </h2>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--navy-muted)]">
            Scan flock size, maturity timing, and operational status before
            opening the full batch workspace.
          </p>
        </div>

        <div className="flex flex-wrap gap-3">
          {addBatchAction}

          <button
            type="button"
            onClick={() => setShowLastThreeMonths((current) => !current)}
            className={`rounded-full border border-[var(--line)] px-5 py-2 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition ${
              showLastThreeMonths
                ? "bg-[var(--gold-soft)]"
                : "bg-white/40 hover:bg-white"
            }`}
          >
            Last 3 Months
          </button>

          <button
            type="button"
            onClick={exportView}
            disabled={visibleBatches.length === 0}
            className="rounded-full bg-[var(--gold)] px-5 py-2 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export View
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="border-b border-[var(--line)] bg-[var(--surface-cream-soft)]">
              <TableHead label="Batch" />
              <TableHead label="Flock" />
              <TableHead label="Placement" />
              <TableHead label="Maturity" />
              <TableHead label="Status" />
              <TableHead label="Readout" align="right" />
            </tr>
          </thead>

          <tbody>
            {visibleBatches.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-6 py-10 text-center text-sm text-[var(--navy-muted)]"
                >
                  No batches match the selected time window.
                </td>
              </tr>
            ) : null}

            {visibleBatches.map((batch) => {
              const daysToMaturity = getDaysToMaturity(
                batch.expected_maturity_date
              );
              const isMature = daysToMaturity <= 0;

              return (
                <tr
                  key={batch.id}
                  className="border-b border-[var(--line)] transition hover:bg-[var(--gold-soft)]/45"
                >
                  <td className="min-w-64 px-6 py-5">
                    <p className="text-sm font-extrabold text-[var(--navy)]">
                      {batch.batch_id}
                    </p>
                    <p className="mt-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
                      {formatBirdType(batch.bird_type)} cycle
                    </p>
                  </td>

                  <td className="min-w-48 px-6 py-5">
                    <p className="font-display text-3xl font-bold leading-none text-[var(--navy)]">
                      {batch.quantity.toLocaleString()}
                    </p>
                    <div className="mt-3 h-2 w-32 overflow-hidden rounded-full bg-[var(--surface-cream-soft)]">
                      <div className="h-full w-full rounded-full bg-[var(--gold)]" />
                    </div>
                  </td>

                  <td className="min-w-44 px-6 py-5 text-sm text-[var(--navy-soft)]">
                    <div className="flex items-center gap-2">
                      <CalendarDays className="h-4 w-4 text-[var(--navy-muted)]" />
                      {formatDate(batch.entry_date)}
                    </div>
                  </td>

                  <td className="min-w-48 px-6 py-5">
                    <p className="text-sm font-semibold text-[var(--navy)]">
                      {formatDate(batch.expected_maturity_date)}
                    </p>
                    <p className="mt-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
                      {isMature
                        ? "Maturity reached"
                        : `${daysToMaturity} days remaining`}
                    </p>
                  </td>

                  <td className="min-w-40 px-6 py-5">
                    <span
                      className={`inline-flex rounded-full px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em] ${
                        isMature
                          ? "bg-[var(--gold-soft)] text-[var(--navy)]"
                          : "bg-[#e7f4e7] text-[#4e8b61]"
                      }`}
                    >
                      {isMature ? "Review" : "Active"}
                    </span>
                  </td>

                  <td className="min-w-44 px-6 py-5 text-right">
                    <Link
                      href={`/poultry/batches/${batch.id}`}
                      aria-label={`View ${batch.batch_id}`}
                      title={`View ${batch.batch_id}`}
                      className="inline-grid h-10 w-14 place-items-center rounded-full bg-[var(--gold)] text-[var(--navy)] transition hover:bg-[var(--gold-soft)]"
                    >
                      <Eye className="h-5 w-5" aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-3 border-t border-[var(--line)] px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          {visibleBatches.length} of {batches.length} records shown
          {showLastThreeMonths ? " / last 3 months" : ""}
        </p>

        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          Updated live
        </p>
      </div>
    </div>
  );
}

type TableHeadProps = {
  label: string;
  align?: "left" | "right";
};

function TableHead({ label, align = "left" }: TableHeadProps) {
  const alignClass = align === "right" ? "text-right" : "text-left";

  return (
    <th
      className={`px-6 py-4 ${alignClass} text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]`}
    >
      {label}
    </th>
  );
}
