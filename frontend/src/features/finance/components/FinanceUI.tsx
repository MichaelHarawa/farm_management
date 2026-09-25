import Link from "next/link";
import type { ReactNode } from "react";
import { getOptionalCurrentUser } from "@/features/auth/server/current-user";
import { canAccessOwnerCapital } from "@/features/auth/utils/permissions";

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
            <h1 className="font-display mt-3 text-3xl leading-tight text-[var(--navy)] sm:text-5xl">
              {title}
            </h1>
            <p className="mx-auto mt-3 max-w-3xl text-sm leading-6 text-[var(--navy-soft)]">
              {detail}
            </p>
          </div>
          {actions ? (
            <div className="mt-5 w-full min-w-0">{actions}</div>
          ) : null}
        </div>
      </section>
      <section className="min-w-0 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto grid min-w-0 max-w-7xl gap-6">{children}</div>
      </section>
    </main>
  );
}

export async function FinanceNav() {
  const user = await getOptionalCurrentUser();
  const primaryLinks = [
    ["Overview", "/finance"],
    ["Sales", "/finance/receivables"],
    ["Spending", "/finance/expenditures"],
    ["Batches", "/finance/batches"],
    ["Reports", "/finance/monthly"],
  ];
  const secondaryLinks = [
    ["Funding & Use", "/finance/revenue-usage"],
    ...(canAccessOwnerCapital(user)
      ? [["Owner Capital", "/finance/owner-capital"]]
      : []),
    ["Payroll", "/finance/payroll"],
    ["Inventory", "/finance/consumables"],
    ["Assets", "/finance/assets"],
  ];


  return (
    <nav className="grid w-full min-w-0 justify-items-center gap-3">
      <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-center">
        {primaryLinks.map(([label, href]) => (
          <Link key={href} href={href} className="inline-flex min-h-10 min-w-0 items-center justify-center rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-center text-[0.68rem] font-extrabold uppercase tracking-[0.1em] text-[var(--navy-muted)] transition hover:border-[var(--gold)] hover:bg-[var(--gold-soft)] hover:text-[var(--navy)] sm:rounded-full sm:px-4 sm:text-xs sm:tracking-[0.14em]">{label}</Link>
        ))}
      </div>
      <details className="w-full text-center sm:w-auto">
        <summary className="mx-auto flex min-h-9 w-full cursor-pointer list-none items-center justify-center rounded-xl border border-dashed border-[var(--line)] bg-white/35 px-4 text-xs font-bold text-[var(--navy-muted)] transition hover:bg-white/70 sm:w-fit sm:border-0 sm:bg-transparent sm:underline">More finance tools</summary>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-center">
          {secondaryLinks.map(([label, href]) => (
            <Link key={href} href={href} className="inline-flex min-h-10 min-w-0 items-center justify-center rounded-xl border border-[var(--line)] bg-white/70 px-3 py-2 text-center text-xs font-bold text-[var(--navy-muted)] hover:bg-[var(--gold-soft)] sm:rounded-full sm:px-4">{label}</Link>
          ))}
        </div>
      </details>
    </nav>
  );
}

export function MetricCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: string;
  detail?: string;
  tone?: "default" | "positive" | "warning" | "danger";
}) {
  const toneClass = {
    default: "border-[var(--line)] bg-[var(--surface-cream)]",
    positive: "border-[#94b89d] bg-[#edf6ef]",
    warning: "border-[var(--gold)] bg-[var(--gold-soft)]",
    danger: "border-[var(--danger)]/45 bg-red-50",
  }[tone];
  return (
    <div className={`min-w-0 rounded-lg border p-4 shadow-[var(--shadow-card)] sm:p-5 ${toneClass}`}>
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
    <section id={id} className="min-w-0 overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-4 shadow-[var(--shadow-card)] sm:p-5">
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
              <div className="grid min-w-0 gap-1 text-sm min-[420px]:grid-cols-[minmax(0,1fr)_auto] min-[420px]:items-end min-[420px]:gap-4">
                <span className="min-w-0 break-words font-semibold text-[var(--navy-soft)]">
                  {point.label}
                </span>
                <span
                  className={`break-words font-extrabold min-[420px]:text-right ${
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
