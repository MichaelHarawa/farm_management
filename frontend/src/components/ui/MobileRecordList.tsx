import type { ReactNode } from "react";

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
}: {
  records: MobileRecord[];
  emptyMessage: string;
  className?: string;
}) {
  if (!records.length) {
    return <p className={`rounded-xl border border-dashed border-[var(--line)] bg-white/60 p-5 text-sm text-[var(--navy-muted)] md:hidden ${className}`}>{emptyMessage}</p>;
  }

  return (
    <div className={`grid gap-3 md:hidden ${className}`}>
      {records.map((record) => (
        <article key={record.key} className="min-w-0 rounded-xl border border-[var(--line)] bg-white p-4 shadow-sm">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="break-words font-extrabold text-[var(--navy)]">{record.title}</div>
              {record.subtitle ? <div className="mt-1 break-words text-xs leading-5 text-[var(--navy-muted)]">{record.subtitle}</div> : null}
            </div>
            {record.badge ? <div className="shrink-0">{record.badge}</div> : null}
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
            {record.fields.map((field, index) => (
              <div key={`${field.label}-${index}`} className="min-w-0 border-t border-[var(--line)] pt-2">
                <dt className="text-[0.65rem] font-extrabold uppercase tracking-[0.12em] text-[var(--navy-muted)]">{field.label}</dt>
                <dd className="mt-1 break-words text-sm font-semibold text-[var(--navy)]">{field.value}</dd>
              </div>
            ))}
          </dl>
          {record.actions ? <div className="mt-4 flex flex-wrap gap-2 border-t border-[var(--line)] pt-3">{record.actions}</div> : null}
        </article>
      ))}
    </div>
  );
}
