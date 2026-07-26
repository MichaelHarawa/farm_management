"use client";

import { X } from "lucide-react";
import {
  useEffect,
  useId,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

type DialogProps = {
  open: boolean;
  onClose: () => void;
  eyebrow?: string;
  title: string;
  children: ReactNode;
  size?: "md" | "lg" | "xl";
};

const sizeClass: Record<NonNullable<DialogProps["size"]>, string> = {
  md: "max-w-2xl",
  lg: "max-w-4xl",
  xl: "max-w-5xl",
};

export function Dialog({
  open,
  onClose,
  eyebrow,
  title,
  children,
  size = "xl",
}: DialogProps) {
  const titleId = useId();

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] overflow-y-auto bg-[var(--overlay)] px-4 py-8 backdrop-blur-[7px]"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`relative mx-auto mt-8 w-full ${sizeClass[size]} overflow-hidden rounded-[1.5rem] border border-white/90 bg-[var(--surface-white)] shadow-[var(--shadow-modal)]`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-[var(--gold-soft)]/70 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-[#f3f5fa] blur-3xl" />

        <div className="relative px-6 py-7 sm:px-10 sm:py-9">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              {eyebrow ? (
                <p className="text-label text-[var(--navy-muted)]">{eyebrow}</p>
              ) : null}
              <h2
                id={titleId}
                className="mt-2 text-2xl font-extrabold leading-tight text-[var(--navy)] sm:text-3xl"
              >
                {title}
              </h2>
            </div>

            <button
              type="button"
              aria-label="Close dialog"
              title="Close"
              onClick={onClose}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>

          <div className="mt-7 border-t border-[var(--line)] pt-7">{children}</div>
        </div>
      </div>
    </div>,
    document.body
  );
}
