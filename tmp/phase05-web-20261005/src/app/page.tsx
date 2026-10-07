import {
  ArrowRight,
  BarChart3,
  Package,
  Settings,
  Sprout,
} from "lucide-react";
import Link from "next/link";
import type { ComponentType } from "react";

type ModuleCard = {
  name: string;
  description: string;
  href?: string;
  status: "Live" | "Planned";
  metric: string;
  signal: string;
  icon: ComponentType<{
    className?: string;
    "aria-hidden"?: boolean | "true" | "false";
  }>;
};

const modules: ModuleCard[] = [
  {
    name: "Poultry",
    description:
      "Batch placement, input spend, sales collection, flock movement, and care planning.",
    href: "/poultry",
    status: "Live",
    metric: "Batch performance",
    signal: "Operational",
    icon: BarChart3,
  },
  {
    name: "Crops",
    description:
      "Season budgets, field activity, harvest records, and input usage controls.",
    status: "Planned",
    metric: "Season records",
    signal: "Roadmap",
    icon: Sprout,
  },
  {
    name: "Goats",
    description:
      "Herd movement, breeding events, health checks, purchases, and sales history.",
    status: "Planned",
    metric: "Herd activity",
    signal: "Roadmap",
    icon: Package,
  },
  {
    name: "Administration",
    description:
      "Manage system users, access roles, account status, password resets, and technical oversight.",
    href: "/administration",
    status: "Live",
    metric: "System controls",
    signal: "Administrative",
    icon: Settings,
  },
];

export default function HomePage() {
  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto max-w-7xl px-5 py-6 sm:px-8 sm:py-8 lg:py-10">
          <div className="max-w-4xl">
            <p className="text-label text-[var(--navy-muted)]">
              Farmnotes / Executive Workspace
            </p>

            <h1 className="font-display mt-3 max-w-4xl text-4xl leading-[0.98] text-[var(--navy)] sm:text-5xl lg:mt-5 lg:text-7xl">
              Run the farm from one clear workspace.
            </h1>

            <p className="mt-4 max-w-2xl text-base leading-7 text-[var(--navy-soft)] lg:mt-6 lg:text-lg lg:leading-8">
              Manage poultry today, with more farm operations ready to join the same system.
            </p>
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-7 sm:px-8 lg:py-10">
        <div className="mx-auto max-w-7xl">
          <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-label text-[var(--gold)]">
                Module Portfolio
              </p>
              <h2 className="font-display mt-2 text-3xl leading-none text-[var(--surface-cream)] sm:text-4xl">
                Choose a working area.
              </h2>
            </div>
            <p className="hidden max-w-md text-sm leading-6 text-white/65 sm:block">
              Live modules are available now. Planned modules show where the
              system will expand next.
            </p>
          </div>

          <div className="grid gap-3 md:grid-cols-2 md:gap-5 lg:grid-cols-4">
            {modules.map((module) => (
              <ModuleTile key={module.name} module={module} />
            ))}
          </div>
        </div>
      </section>
    </main>
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
      <div className="flex items-center gap-3 md:hidden">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.65rem] font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">{module.status} · {module.metric}</p>
          <h2 className="font-display mt-1 truncate text-2xl font-bold leading-none text-[var(--navy)]">{module.name}</h2>
        </div>
        {isLive ? <ArrowRight className="h-5 w-5 shrink-0 text-[var(--navy)]" aria-hidden="true" /> : <span className="rounded-full border border-[var(--line)] px-2 py-1 text-[0.62rem] font-bold uppercase text-[var(--navy-muted)]">Planned</span>}
      </div>

      <div className="hidden md:block">
        <div className="flex items-start justify-between gap-4">
          <span className="grid h-11 w-11 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </span>

          <span
            className={`rounded-full border px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em] ${
              isLive
                ? "border-[var(--gold)] bg-[var(--gold-soft)] text-[var(--navy)]"
                : "border-[var(--line)] text-[var(--navy-muted)]"
            }`}
          >
            {module.status}
          </span>
        </div>

        <div className="mt-7">
          <p className="text-label text-[var(--navy-muted)]">{module.metric}</p>
          <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">{module.name}</h2>
          <p className="mt-4 min-h-24 text-sm leading-6 text-[var(--navy-soft)]">{module.description}</p>
        </div>

        <div className="mt-7 flex items-center justify-between border-t border-[var(--line)] pt-4">
          <div>
            <span className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">{isLive ? "Open module" : "Coming later"}</span>
            <p className="mt-1 text-sm font-semibold text-[var(--navy-soft)]">{module.signal}</p>
          </div>
          <ArrowRight className="h-5 w-5 text-[var(--navy)]" aria-hidden="true" />
        </div>
      </div>
    </>
  );

  if (!module.href) {
    return (
      <article className="rounded-xl border border-[var(--line)] bg-[var(--surface-cream)] p-4 opacity-70 shadow-[var(--shadow-card)] md:rounded-lg md:p-6">
        {content}
      </article>
    );
  }

  return (
    <Link
      href={module.href}
      className="rounded-xl border border-[var(--gold)] bg-[var(--surface-cream)] p-4 shadow-[var(--shadow-card)] transition hover:-translate-y-1 hover:bg-[var(--gold-soft)] md:rounded-lg md:p-6"
    >
      {content}
    </Link>
  );
}
