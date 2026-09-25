"use client";

import { useState, type ReactNode } from "react";

import { PaginationControls } from "./PaginationControls";

export type MobileRecord = {
  key: string | number;
  title: ReactNode;
  subtitle?: ReactNode;
  badge?: ReactNode;
  fields: Array<{ label: string; value: ReactNode }>;
  actions?: ReactNode;
};

export function MobileRecordList({
  records,
  emptyMessage,
  className = "",
  desktopBreakpoint = "md",
  pageSize,
  itemLabel = "records",
}: {
  records: MobileRecord[];
  emptyMessage: string;
  className?: string;
  desktopBreakpoint?: "md" | "lg";
  pageSize?: number;
  itemLabel?: string;
}) {
  const [currentPage, setCurrentPage] = useState(1);
  const desktopHiddenClass = desktopBreakpoint === "lg" ? "lg:hidden" : "md:hidden";
  const effectivePageSize = pageSize ?? Math.max(1, records.length);
  const totalPages = Math.max(1, Math.ceil(records.length / effectivePageSize));
  const safePage = Math.min(currentPage, totalPages);
  const startIndex = (safePage - 1) * effectivePageSize;
  const pageRecords = records.slice(startIndex, startIndex + effectivePageSize);

  if (!records.length) {
    return <p className={`rounded-xl border border-dashed border-[var(--line)] bg-white/60 p-5 text-sm text-[var(--navy-muted)] ${desktopHiddenClass} ${className}`}>{emptyMessage}</p>;
  }

  return (
    <div className={`min-w-0 grid gap-3 ${desktopHiddenClass} ${className}`}>
      {pageRecords.map((record) => (
        <article key={record.key} className="min-w-0 rounded-xl border border-[var(--line)] bg-white p-3.5 shadow-sm sm:p-4">
          <div className="flex min-w-0 flex-col items-start gap-2 min-[400px]:flex-row min-[400px]:justify-between min-[400px]:gap-3">
            <div className="min-w-0">
              <div className="break-words font-extrabold text-[var(--navy)]">{record.title}</div>
              {record.subtitle ? <div className="mt-1 break-words text-xs leading-5 text-[var(--navy-muted)]">{record.subtitle}</div> : null}
            </div>
            {record.badge ? <div className="max-w-full shrink-0 break-words">{record.badge}</div> : null}
          </div>
          <dl className="mt-4 grid grid-cols-1 gap-x-4 gap-y-3 min-[340px]:grid-cols-2">
            {record.fields.map((field, index) => (
              <div key={`${field.label}-${index}`} className="min-w-0 border-t border-[var(--line)] pt-2">
                <dt className="text-[0.65rem] font-extrabold uppercase tracking-[0.12em] text-[var(--navy-muted)]">{field.label}</dt>
                <dd className="mt-1 break-words text-sm font-semibold text-[var(--navy)]">{field.value}</dd>
              </div>
            ))}
          </dl>
          {record.actions ? <div className="mt-4 grid min-w-0 gap-2 border-t border-[var(--line)] pt-3 min-[400px]:flex min-[400px]:flex-wrap">{record.actions}</div> : null}
        </article>
      ))}
      <PaginationControls
        currentPage={safePage}
        totalPages={totalPages}
        totalItems={records.length}
        pageSize={effectivePageSize}
        itemLabel={itemLabel}
        onPageChange={setCurrentPage}
        className="rounded-xl border border-[var(--line)] bg-white px-4 py-3"
      />
    </div>
  );
}
