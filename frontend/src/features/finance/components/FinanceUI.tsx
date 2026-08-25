import Link from "next/link";
import type { ReactNode } from "react";

export type FinanceChartPoint = {
  label: string;
  value: number;
  displayValue: string;
  tone?: "navy" | "gold" | "green" | "muted" | "danger";
};

const chartToneClass: Record<
  NonNullable<FinanceChartPoint["tone"]>,
  string
> = {
  navy: "bg-[var(--navy)]",
  gold: "bg-[var(--gold)]",
  green: "bg-[#4e8b61]",
  muted: "bg-[var(--navy-muted)]",
  danger: "bg-[var(--danger)]",
};

export function FinancePageShell({
  eyebrow,
  title,
  detail,
  actions,
  children,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <main className="bg-[var(--page-cream)]">
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto flex max-w-7xl flex-col items-center px-5 py-6 text-center sm:px-8 sm:py-7">
          <div className="max-w-4xl">
            <p className="text-label text-[var(--navy-muted)]">{eyebrow}</p>
            <h1 className="font-display mt-3 text-4xl leading-tight text-[var(--navy)] sm:text-5xl">
              {title}
            </h1>
            <p className="mx-auto mt-3 max-w-3xl text-sm leading-6 text-[var(--navy-soft)]">
              {detail}
            </p>
          </div>
          {actions ? (
            <div className="mt-5 flex w-full justify-center">{actions}</div>
          ) : null}
        </div>
      </section>
      <section className="px-5 py-8 sm:px-8">
        <div className="mx-auto grid max-w-7xl gap-6">{children}</div>
      </section>
    </main>
  );
}

export function FinanceNav() {
  const links = [
    ["Dashboard", "/finance"],
    ["Expenditures", "/finance/expenditures"],
    ["Revenue Usage", "/finance/revenue-usage"],
    ["Batch Analysis", "/finance/batches"],
    ["Receivables", "/finance/receivables"],
    ["Employees", "/finance/employees"],
    ["Payroll", "/finance/payroll"],
    ["Labour", "/finance/labour"],
    ["Expenses", "/finance/expenses"],
    ["Consumables", "/finance/consumables"],
    ["Assets", "/finance/assets"],
    ["Monthly", "/finance/monthly"],
  ];


  return (
    <nav className="flex flex-wrap justify-center gap-2">
      {links.map(([label, href]) => (
        <Link
          key={href}
          href={href}
          className="rounded-full border border-[var(--line)] bg-white/60 px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}

export function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-5 shadow-[var(--shadow-card)]">
      <p className="text-label text-[var(--navy-muted)]">{label}</p>
      <p className="font-display mt-3 max-w-full overflow-hidden break-words text-2xl font-bold leading-tight text-[var(--navy)] sm:text-3xl">
        {value}
      </p>
      {detail ? (
        <p className="mt-3 text-sm leading-6 text-[var(--navy-muted)]">{detail}</p>
      ) : null}
    </div>
  );
}

export function Panel({
  id,
  title,
  children,
}: {
  id?: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-5 shadow-[var(--shadow-card)]">
      <h2 className="text-lg font-extrabold text-[var(--navy)]">{title}</h2>
      <div className="mt-5">{children}</div>
    </section>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-dashed border-[var(--line)] bg-white/50 px-4 py-6 text-sm text-[var(--navy-muted)]">
      {message}
    </p>
  );
}

export function FinanceBarChart({
  title,
  detail,
  points,
}: {
  title: string;
  detail: string;
  points: FinanceChartPoint[];
}) {
  const maxMagnitude = Math.max(
    0,
    ...points.map((point) => Math.abs(point.value))
  );
  const hasDangerValue = points.some(
    (point) => point.value < 0 || point.tone === "danger"
  );

  return (
    <figure
      aria-label={title}
      className="rounded-lg border border-[var(--line)] bg-white/55 p-4 sm:p-5"
    >
      <figcaption>
        <h3 className="text-base font-extrabold text-[var(--navy)]">{title}</h3>
        <p className="mt-2 text-sm leading-6 text-[var(--navy-muted)]">
          {detail}
        </p>
      </figcaption>
      <ul className="mt-5 grid gap-4">
        {points.map((point) => {
          const relativeWidth =
            maxMagnitude === 0
              ? 0
              : Math.max((Math.abs(point.value) / maxMagnitude) * 100, 2);
          const tone = point.value < 0 ? "danger" : point.tone ?? "navy";

          return (
            <li key={point.label}>
              <div className="flex items-end justify-between gap-4 text-sm">
                <span className="font-semibold text-[var(--navy-soft)]">
                  {point.label}
                </span>
                <span
                  className={`text-right font-extrabold ${
                    point.value < 0
                      ? "text-[var(--danger)]"
                      : "text-[var(--navy)]"
                  }`}
                >
                  {point.displayValue}
                </span>
              </div>
              <div
                className="mt-2 h-3 overflow-hidden rounded-full bg-[var(--page-cream)]"
                aria-hidden="true"
              >
                <div
                  className={`h-full rounded-full ${chartToneClass[tone]}`}
                  style={{ width: `${relativeWidth}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      {hasDangerValue ? (
        <p className="mt-4 text-xs font-semibold text-[var(--navy-muted)]">
          Red bars identify losses or unfavourable gaps; bar length compares absolute amounts.
        </p>
      ) : null}
    </figure>
  );
}
