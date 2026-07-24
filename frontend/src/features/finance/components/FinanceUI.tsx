import Link from "next/link";
import type { ReactNode } from "react";

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
        <div className="mx-auto grid max-w-7xl gap-6 px-5 py-8 sm:px-8 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <p className="text-label text-[var(--navy-muted)]">{eyebrow}</p>
            <h1 className="font-display mt-4 text-4xl leading-none text-[var(--navy)] sm:text-6xl">
              {title}
            </h1>
            <p className="mt-4 max-w-3xl text-sm leading-6 text-[var(--navy-soft)]">
              {detail}
            </p>
          </div>
          {actions ? <div className="flex flex-wrap gap-3">{actions}</div> : null}
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
    ["Employees", "/finance/employees"],
    ["Payroll", "/finance/payroll"],
    ["Labour", "/finance/labour"],
    ["Expenses", "/finance/expenses"],
    ["Consumables", "/finance/consumables"],
    ["Assets", "/finance/assets"],
    ["Monthly", "/finance/monthly"],
  ];

  return (
    <nav className="flex flex-wrap gap-2">
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
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-5 shadow-[var(--shadow-card)]">
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
