import { ArrowRight, BarChart3, Package, Sprout } from "lucide-react";
import Link from "next/link";
import type { ComponentType } from "react";

type ModuleCard = {
  name: string;
  description: string;
  href?: string;
  status: "Live" | "Planned";
  metric: string;
  icon: ComponentType<{
    className?: string;
    "aria-hidden"?: boolean | "true" | "false";
  }>;
};

const modules: ModuleCard[] = [
  {
    name: "Poultry",
    description:
      "Batches, input costs, sales, mortality, and feed tracking in one working module.",
    href: "/poultry",
    status: "Live",
    metric: "Batch performance",
    icon: BarChart3,
  },
  {
    name: "Crops",
    description:
      "Season planning, field activity, harvest records, and input usage.",
    status: "Planned",
    metric: "Season records",
    icon: Sprout,
  },
  {
    name: "Goats",
    description:
      "Herd movement, breeding events, health checks, purchases, and sales.",
    status: "Planned",
    metric: "Herd activity",
    icon: Package,
  },
];

export default function HomePage() {
  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto grid max-w-7xl gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[1fr_0.8fr]">
          <div>
            <p className="text-label text-[var(--navy-muted)]">
              Farmnotes / Module Workspace
            </p>

            <h1 className="font-display mt-4 max-w-4xl text-5xl leading-none text-[var(--navy)] sm:text-6xl">
              Farm production, organized by module.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--navy-soft)]">
              Start with poultry today and expand into crops, goats, and other
              farm operations without changing the working rhythm.
            </p>
          </div>

          <div className="grid content-end gap-4 sm:grid-cols-3 lg:grid-cols-1">
            <ToplineMetric label="Live Modules" value="01" />
            <ToplineMetric label="Next Modules" value="02" />
            <ToplineMetric label="Workspace" value="Farm" />
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-8 sm:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="grid gap-5 md:grid-cols-3">
            {modules.map((module) => (
              <ModuleTile key={module.name} module={module} />
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

type ToplineMetricProps = {
  label: string;
  value: string;
};

function ToplineMetric({ label, value }: ToplineMetricProps) {
  return (
    <div className="border-y border-[var(--line)] py-3">
      <p className="font-display text-3xl font-bold text-[var(--navy)]">
        {value}
      </p>
      <p className="text-label mt-1 text-[var(--navy-muted)]">{label}</p>
    </div>
  );
}

type ModuleTileProps = {
  module: ModuleCard;
};

function ModuleTile({ module }: ModuleTileProps) {
  const Icon = module.icon;
  const isLive = module.status === "Live";

  const content = (
    <>
      <div className="flex items-start justify-between gap-4">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>

        <span className="rounded-full border border-[var(--line)] px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
          {module.status}
        </span>
      </div>

      <div className="mt-6">
        <p className="text-label text-[var(--navy-muted)]">{module.metric}</p>
        <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">
          {module.name}
        </h2>
        <p className="mt-4 min-h-20 text-sm leading-6 text-[var(--navy-soft)]">
          {module.description}
        </p>
      </div>

      <div className="mt-6 flex items-center justify-between border-t border-[var(--line)] pt-4">
        <span className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
          {isLive ? "Open module" : "Coming later"}
        </span>
        <ArrowRight className="h-4 w-4 text-[var(--navy)]" aria-hidden="true" />
      </div>
    </>
  );

  if (!module.href) {
    return (
      <article className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 opacity-75 shadow-[var(--shadow-card)]">
        {content}
      </article>
    );
  }

  return (
    <Link
      href={module.href}
      className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)] transition hover:border-[var(--gold)] hover:bg-[var(--gold-soft)]"
    >
      {content}
    </Link>
  );
}
