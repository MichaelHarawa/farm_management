import { BatchList } from "@/features/poultry/components/BatchList";
import { BookChicksDialog } from "@/features/poultry/components/AddBatchDialog";
import { getPoultryBatches } from "@/features/poultry/api/batches";
import { ArrowUpRight, LockKeyhole } from "lucide-react";
import Link from "next/link";
import { getOptionalCurrentUser } from "@/features/auth/server/current-user";
import { canAccessFinance } from "@/features/auth/utils/permissions";

export default async function PoultryPage() {
  const [batches, user] = await Promise.all([
    getPoultryBatches("/poultry"),
    getOptionalCurrentUser(),
  ]);
  const productionBatches = batches.filter(
    (batch) => batch.status !== "booked" && batch.status !== "delivered"
  );
  const bookedBatches = batches.filter((batch) => batch.status === "booked");
  const totalBirds = productionBatches.reduce(
    (total, batch) => total + batch.quantity,
    0
  );
  const nextMaturityDate = productionBatches
    .map((batch) => new Date(batch.expected_maturity_date))
    .sort((a, b) => a.getTime() - b.getTime())[0];
  const nextDeliveryDate = bookedBatches
    .map((batch) =>
      batch.estimated_chick_arrival_date
        ? new Date(batch.estimated_chick_arrival_date)
        : null
    )
    .filter((date): date is Date => date !== null)
    .sort((a, b) => a.getTime() - b.getTime())[0];

  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto grid max-w-7xl gap-7 px-5 py-7 sm:px-8 sm:py-9 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:gap-12">
          <div className="self-center">
            <p className="text-label text-[var(--navy-muted)]">Poultry / Overview</p>

            <h1 className="font-display mt-4 max-w-3xl text-4xl leading-[0.96] tracking-[-0.04em] text-[var(--navy)] sm:text-6xl">
              Production overview.
            </h1>

            <p className="mt-4 max-w-xl text-base leading-7 text-[var(--navy-soft)] sm:text-lg">
              Active flocks, upcoming milestones, and the next action in one place.
            </p>
          </div>

          <div className="grid grid-cols-3 divide-x divide-[var(--line)] rounded-xl border border-[var(--line)] bg-white/45 px-3 py-4 sm:px-5 sm:py-5">
            <HeroMetric
              label="Live batches"
              value={productionBatches.length.toString().padStart(2, "0")}
            />
            <HeroMetric
              label="Birds placed"
              value={totalBirds.toLocaleString()}
            />
            <HeroMetric
              label={nextDeliveryDate ? "Next delivery" : "Next maturity"}
              value={
                nextDeliveryDate || nextMaturityDate
                  ? new Intl.DateTimeFormat("en", {
                      month: "short",
                      day: "2-digit",
                    }).format(nextDeliveryDate ?? nextMaturityDate)
                  : "-"
              }
            />
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-7 sm:px-8 sm:py-9">
        <div className="mx-auto grid max-w-7xl gap-5">
          <div className="grid gap-3 md:grid-cols-3">
            <RegisterSignal
              label="FLOCK DASHBOARD"
              value="Live Metrics"
              detail="Status, trends, sales, mortality, feed &amp; more"
              href="/poultry/dashboard"
            />
            <RegisterSignal
              label="FINANCIAL WORKSPACE"
              value={canAccessFinance(user) ? "Finance Control" : "Restricted by Role"}
              detail={canAccessFinance(user) ? "Open workforce, payroll, and profitability" : "Ask an administrator for a finance-enabled role"}
              href={canAccessFinance(user) ? "/finance" : undefined}
            />
            <RegisterSignal
              label="OPERATIONS GUIDE"
              value="Help Center"
              detail="How to use the system, record data, and best practices"
              href="/poultry/guides"
            />
          </div>

          <BatchList batches={batches} addBatchAction={<BookChicksDialog />} />
        </div>
      </section>
    </main>
  );
}

type HeroMetricProps = {
  label: string;
  value: string;
};

function HeroMetric({ label, value }: HeroMetricProps) {
  return (
    <div className="min-w-0 px-2 sm:px-4">
      <div>
        <p className="truncate text-[0.6rem] font-extrabold uppercase tracking-[0.13em] text-[var(--navy-muted)] sm:text-label">{label}</p>
      </div>
      <p className="mt-2 truncate font-display text-2xl font-bold leading-none text-[var(--navy)] sm:text-4xl">
        {value}
      </p>
    </div>
  );
}

type RegisterSignalProps = {
  label: string;
  value: string;
  detail: string;
  href?: string;
};

function RegisterSignal({ label, value, detail, href }: RegisterSignalProps) {
  const content = (
    <div className="flex min-h-28 flex-col justify-between gap-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[0.62rem] font-extrabold uppercase tracking-[0.18em] text-[var(--gold)]">{label}</p>
          <p className="mt-2 text-base font-bold text-[var(--surface-cream)] sm:text-lg">{value}</p>
        </div>
        <span className="grid size-9 shrink-0 place-items-center rounded-full border border-white/15 bg-white/[0.06] text-white/65 transition group-hover:border-[var(--gold)] group-hover:bg-[var(--gold)] group-hover:text-[var(--navy)]">
          {href ? <ArrowUpRight className="size-4" aria-hidden="true" /> : <LockKeyhole className="size-4" aria-hidden="true" />}
        </span>
      </div>
      <p className="text-xs leading-5 text-white/65 sm:text-sm">{detail}</p>
    </div>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="group rounded-2xl border border-white/15 bg-white/[0.07] px-4 py-4 shadow-[0_12px_26px_rgba(3,9,25,0.12)] transition hover:-translate-y-0.5 hover:border-[var(--gold)] hover:bg-white/[0.11] hover:shadow-[0_16px_30px_rgba(3,9,25,0.2)] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[var(--gold)]/30 sm:px-5 sm:py-5"
      >
        {content}
      </Link>
    );
  }

  return (
    <div className="group rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-4 opacity-85 sm:px-5 sm:py-5">
      {content}
    </div>
  );
}
