import Link from "next/link";
import type { PoultryBatch } from "../types";

type BatchListProps = {
  batches: PoultryBatch[];
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

export function BatchList({ batches }: BatchListProps) {
  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-8 text-center shadow-[var(--shadow-card)]">
        <p className="text-label text-[var(--navy-muted)]">
          Batch Register / Empty
        </p>

        <h2 className="font-display mt-4 text-4xl text-[var(--navy)]">
          No batch records yet.
        </h2>

        <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-[var(--navy-muted)]">
          Once you create a poultry batch, it will appear in this workspace.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-4 border-b border-[var(--line)] px-6 py-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-label text-[var(--navy-muted)]">
            Live Workspace / 01
          </p>

          <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">
            Your batches, in motion.
          </h2>
        </div>

        <div className="flex gap-3">
          <button
            type="button"
            className="rounded-full border border-[var(--line)] px-5 py-2 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)]"
          >
            Last 30 Days
          </button>

          <button
            type="button"
            className="rounded-full bg-[var(--gold)] px-5 py-2 text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)]"
          >
            Export View
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="border-b border-[var(--line)]">
              <th className="px-7 py-4 text-left text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Batch ID
              </th>
              <th className="px-7 py-4 text-left text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Bird Type
              </th>
              <th className="px-7 py-4 text-right text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Quantity
              </th>
              <th className="px-7 py-4 text-left text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Entry Date
              </th>
              <th className="px-7 py-4 text-left text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Maturity Date
              </th>
              <th className="px-7 py-4 text-right text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
                Readout
              </th>
            </tr>
          </thead>

          <tbody>
            {batches.map((batch) => (
              <tr
                key={batch.id}
                className="border-b border-[var(--line)] transition hover:bg-[var(--surface-cream-soft)]"
              >
                <td className="whitespace-nowrap px-7 py-5 text-sm font-semibold text-[var(--navy)]">
                  {batch.batch_id}
                </td>

                <td className="whitespace-nowrap px-7 py-5 text-sm text-[var(--navy-soft)]">
                  {formatBirdType(batch.bird_type)}
                </td>

                <td className="whitespace-nowrap px-7 py-5 text-right text-sm font-semibold text-[var(--navy)]">
                  {batch.quantity.toLocaleString()}
                </td>

                <td className="whitespace-nowrap px-7 py-5 text-sm text-[var(--navy-soft)]">
                  {formatDate(batch.entry_date)}
                </td>

                <td className="whitespace-nowrap px-7 py-5 text-sm text-[var(--navy-soft)]">
                  {formatDate(batch.expected_maturity_date)}
                </td>

                <td className="whitespace-nowrap px-7 py-5 text-right">
                  <Link
                    href={`/poultry/batches/${batch.id}`}
                    className="inline-flex rounded-full bg-[var(--gold-soft)] px-4 py-1.5 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy)] transition hover:bg-[var(--gold)]"
                  >
                    Open
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between px-7 py-4">
        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          {batches.length} of {batches.length} records shown
        </p>

        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          Updated live
        </p>
      </div>
    </div>
  );
}
