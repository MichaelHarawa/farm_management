"use client";

import { Dialog } from "@/components/ui";
import { ArrowUpRight, ChevronRight, CircleAlert, Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import type { FinanceWarning } from "../types";

const severityStyles: Record<
  FinanceWarning["severity"],
  { label: string; border: string; badge: string; icon: string }
> = {
  info: {
    label: "Report guidance",
    border: "border-[var(--line)]",
    badge: "bg-[var(--page-cream)] text-[var(--navy-muted)]",
    icon: "text-[var(--navy-muted)]",
  },
  warning: {
    label: "Action recommended",
    border: "border-[var(--gold)]/60",
    badge: "bg-[var(--gold-soft)] text-[var(--navy)]",
    icon: "text-[#a66b00]",
  },
  critical: {
    label: "Urgent action",
    border: "border-[var(--danger)]/50",
    badge: "bg-red-50 text-[var(--danger)]",
    icon: "text-[var(--danger)]",
  },
};

export function FinanceWarningList({ warnings }: { warnings: FinanceWarning[] }) {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const selected = selectedIndex === null ? null : warnings[selectedIndex] ?? null;
  const selectedStyle = selected ? severityStyles[selected.severity] : null;

  return (
    <>
      <ul className="divide-y divide-[var(--line)] rounded-lg border border-[var(--line)] bg-white/40">
        {warnings.map((warning, index) => {
          const style = severityStyles[warning.severity];

          return (
            <li key={`${warning.code}-${warning.message}-${index}`}>
              <button
                type="button"
                aria-haspopup="dialog"
                onClick={() => setSelectedIndex(index)}
                className="group flex w-full items-center gap-3 px-3 py-2 text-left transition hover:bg-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--gold)]"
              >
                <span className={`shrink-0 ${style.icon}`} aria-hidden="true">
                  <WarningIcon severity={warning.severity} />
                </span>
                <span className="min-w-0 flex-1 truncate">
                  <span
                    className={`mr-2 inline-flex rounded px-1.5 py-0.5 text-[0.6rem] font-extrabold uppercase tracking-[0.1em] ${style.badge}`}
                  >
                    {style.label}
                  </span>
                  <span className="text-sm text-[var(--navy-soft)]">
                    {warning.message}
                  </span>
                </span>
                <span className="hidden shrink-0 items-center gap-1 text-xs font-extrabold uppercase tracking-[0.1em] text-[var(--navy)] sm:flex">
                  View
                  <ChevronRight
                    className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <Dialog
        open={Boolean(selected)}
        onClose={() => setSelectedIndex(null)}
        eyebrow={selectedStyle?.label}
        title={selected?.severity === "info" ? "Finance report guidance" : "Resolve finance warning"}
        size="md"
      >
        {selected ? (
          <div className="grid gap-5">
            <section>
              <h3 className="text-label text-[var(--navy-muted)]">What this means</h3>
              <p className="mt-2 text-base font-semibold leading-7 text-[var(--navy-soft)]">
                {selected.message}
              </p>
            </section>

            <section className="rounded-xl border border-[var(--gold)]/40 bg-[var(--gold-soft)]/55 p-5">
              <h3 className="text-label text-[var(--navy-muted)]">
                Recommended solution
              </h3>
              <p className="mt-2 text-sm leading-6 text-[var(--navy-soft)]">
                {selected.solution ||
                  "Review the underlying records and correct or complete the finance entry."}
              </p>
            </section>

            <div className="flex flex-col-reverse gap-3 border-t border-[var(--line)] pt-5 sm:flex-row sm:items-center sm:justify-between">
              <button
                type="button"
                onClick={() => setSelectedIndex(null)}
                className="rounded-lg px-4 py-3 text-sm font-extrabold text-[var(--navy-muted)] transition hover:bg-[var(--page-cream)] hover:text-[var(--navy)]"
              >
                Close
              </button>
              <Link
                href={selected.action_href || "/finance"}
                onClick={() => setSelectedIndex(null)}
                className="finance-button inline-flex items-center justify-center gap-2"
              >
                {selected.action_label || "Open finance dashboard"}
                <ArrowUpRight className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}

function WarningIcon({ severity }: { severity: FinanceWarning["severity"] }) {
  return severity === "info" ? (
    <Info className="h-5 w-5" />
  ) : (
    <CircleAlert className="h-5 w-5" />
  );
}
