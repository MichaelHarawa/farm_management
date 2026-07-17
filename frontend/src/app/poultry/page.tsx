import { BatchList } from "@/features/poultry/components/BatchList";
import { AddBatchDialog } from "@/features/poultry/components/AddBatchDialog";
import { getPoultryBatches } from "@/features/poultry/api/batches";
import Link from "next/link";

export default async function PoultryPage() {
  const batches = await getPoultryBatches("/poultry");
  const totalBirds = batches.reduce((total, batch) => total + batch.quantity, 0);
  const nextMaturityDate = batches
    .map((batch) => new Date(batch.expected_maturity_date))
    .sort((a, b) => a.getTime() - b.getTime())[0];

  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="self-center">
            <p className="text-label text-[var(--navy-muted)]">
              Poultry Intelligence / Executive Register
            </p>

            <h1 className="font-display mt-5 max-w-4xl text-5xl leading-none text-[var(--navy)] sm:text-7xl">
              Poultry production command view.
            </h1>

            <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--navy-soft)]">
              Review live batches, flock volume, maturity windows, and the
              operational readout for each production cycle.
            </p>
          </div>

          <div className="grid content-center gap-4">
            <HeroMetric
              label="Live batches"
              value={batches.length.toString().padStart(2, "0")}
              detail="Production cycles currently tracked"
            />
            <HeroMetric
              label="Birds placed"
              value={totalBirds.toLocaleString()}
              detail="Initial flock volume in register"
            />
            <HeroMetric
              label="Next maturity"
              value={
                nextMaturityDate
                  ? new Intl.DateTimeFormat("en", {
                      month: "short",
                      day: "2-digit",
                    }).format(nextMaturityDate)
                  : "-"
              }
              detail="Nearest expected maturity date"
            />
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-10 sm:px-8">
        <div className="mx-auto grid max-w-7xl gap-6">
          <div className="grid gap-4 md:grid-cols-3">
            <RegisterSignal
              label="Register quality"
              value="Current"
              detail="No stale client cache"
            />
            <RegisterSignal
              label="Financial workspace"
              value="Finance Control"
              detail="Open workforce, payroll, and profitability"
              href="/finance"
            />
            <RegisterSignal
              label="Care workspace"
              value="Flock notes"
              detail="Mortality and feed views ready"
            />
          </div>

          <BatchList batches={batches} addBatchAction={<AddBatchDialog />} />
        </div>
      </section>
    </main>
  );
}

type HeroMetricProps = {
  label: string;
  value: string;
  detail: string;
};

function HeroMetric({ label, value, detail }: HeroMetricProps) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-5 border-y border-[var(--line)] px-1 py-4">
      <div>
        <p className="text-label text-[var(--navy-muted)]">{label}</p>
        <p className="mt-2 text-sm leading-6 text-[var(--navy-muted)]">
          {detail}
        </p>
      </div>
      <p className="font-display text-4xl font-bold leading-none text-[var(--navy)]">
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
    <>
      <p className="text-label text-[var(--gold)]">{label}</p>
      <p className="mt-3 text-lg font-bold text-[var(--surface-cream)]">
        {value}
      </p>
      <p className="mt-2 text-sm leading-6 text-white/60">{detail}</p>
    </>
  );

  if (href) {
    return (
      <Link
        href={href}
        className="rounded-lg border border-white/10 bg-white/[0.04] px-5 py-4 transition hover:border-[var(--gold)] hover:bg-white/[0.08]"
      >
        {content}
      </Link>
    );
  }

  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] px-5 py-4">
      {content}
    </div>
  );
}
