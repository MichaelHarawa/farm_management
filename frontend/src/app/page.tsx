import {
  ArrowRight,
  BarChart3,
  Package,
  ShieldCheck,
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
];

const operatingSignals = [
  {
    label: "Live Module",
    value: "Poultry",
    detail: "Production cycle tracking",
    icon: ShieldCheck,
  },
  {
    label: "Next Focus",
    value: "Crops",
    detail: "Season planning workspace",
    icon: Sprout,
  },
  {
    label: "Next Module",
    value: "Goats",
    detail: "Herd activity workspace",
    icon: Package,
  },
];

export default function HomePage() {
  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-10 sm:px-8 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="self-center">
            <p className="text-label text-[var(--navy-muted)]">
              Farmnotes / Executive Workspace
            </p>

            <h1 className="font-display mt-5 max-w-4xl text-5xl leading-none text-[var(--navy)] sm:text-7xl">
              Farm operations, held in one calm view.
            </h1>

            <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--navy-soft)]">
              Start with poultry production today and expand into crops, goats,
              and other farm modules with the same reporting rhythm.
            </p>
          </div>

          <div className="grid content-center gap-4">
            {operatingSignals.map((signal) => (
              <SignalRow key={signal.label} signal={signal} />
            ))}
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-10 sm:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-label text-[var(--gold)]">
                Module Portfolio
              </p>
              <h2 className="font-display mt-3 text-4xl leading-none text-[var(--surface-cream)]">
                Choose a working area.
              </h2>
            </div>
            <p className="max-w-md text-sm leading-6 text-white/65">
              Live modules are available now. Planned modules show where the
              system will expand next.
            </p>
          </div>

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

type SignalRowProps = {
  signal: (typeof operatingSignals)[number];
};

function SignalRow({ signal }: SignalRowProps) {
  const Icon = signal.icon;

  return (
    <div className="grid grid-cols-[auto_1fr] gap-4 border-y border-[var(--line)] bg-[rgba(255,255,255,0.18)] px-4 py-4">
      <span className="grid h-11 w-11 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div>
        <p className="text-label text-[var(--navy-muted)]">{signal.label}</p>
        <p className="font-display mt-1 text-3xl font-bold leading-none text-[var(--navy)]">
          {signal.value}
        </p>
        <p className="mt-2 text-sm text-[var(--navy-muted)]">{signal.detail}</p>
      </div>
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
        <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">
          {module.name}
        </h2>
        <p className="mt-4 min-h-24 text-sm leading-6 text-[var(--navy-soft)]">
          {module.description}
        </p>
      </div>

      <div className="mt-7 flex items-center justify-between border-t border-[var(--line)] pt-4">
        <div>
          <span className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
            {isLive ? "Open module" : "Coming later"}
          </span>
          <p className="mt-1 text-sm font-semibold text-[var(--navy-soft)]">
            {module.signal}
          </p>
        </div>
        <ArrowRight className="h-5 w-5 text-[var(--navy)]" aria-hidden="true" />
      </div>
    </>
  );

  if (!module.href) {
    return (
      <article className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 opacity-70 shadow-[var(--shadow-card)]">
        {content}
      </article>
    );
  }

  return (
    <Link
      href={module.href}
      className="rounded-lg border border-[var(--gold)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)] transition hover:-translate-y-1 hover:bg-[var(--gold-soft)]"
    >
      {content}
    </Link>
  );
}
