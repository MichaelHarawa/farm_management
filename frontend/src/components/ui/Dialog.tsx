"use client";

import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
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

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function Dialog({
  open,
  onClose,
  eyebrow,
  title,
  children,
  size = "xl",
}: DialogProps) {
  const titleId = useId();
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const overlay = overlayRef.current;
    const backgroundElements = Array.from(document.body.children)
      .filter(
        (element): element is HTMLElement =>
          element instanceof HTMLElement && element !== overlay
      )
      .map((element) => ({ element, wasInert: element.inert }));

    document.body.style.overflow = "hidden";
    backgroundElements.forEach(({ element }) => {
      element.inert = true;
    });

    const focusFrame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current;
      const firstFocusable = dialog?.querySelector<HTMLElement>(
        focusableSelector
      );

      (firstFocusable ?? dialog)?.focus();
    });

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const dialog = dialogRef.current;

      if (!dialog) {
        return;
      }

      const focusableElements = Array.from(
        dialog.querySelectorAll<HTMLElement>(focusableSelector)
      ).filter(
        (element) =>
          element.tabIndex >= 0 && element.getClientRects().length > 0
      );

      if (focusableElements.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (
        event.shiftKey &&
        (activeElement === firstFocusable || !dialog.contains(activeElement))
      ) {
        event.preventDefault();
        lastFocusable.focus();
      } else if (!event.shiftKey && activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable.focus();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      backgroundElements.forEach(({ element, wasInert }) => {
        element.inert = wasInert;
      });
      window.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [open]);

  if (!open || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[100] overflow-y-auto bg-[var(--overlay)] px-4 py-8 backdrop-blur-[7px]"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
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
