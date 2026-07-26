import type { ReactNode } from "react";

export type BadgeTone =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "gold";

type BadgeProps = {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
};

const toneClass: Record<BadgeTone, string> = {
  neutral: "badge-neutral",
  success: "badge-success",
  warning: "badge-warning",
  danger: "badge-danger",
  info: "badge-info",
  gold: "badge-gold",
};

export function Badge({
  children,
  tone = "neutral",
  className = "",
}: BadgeProps) {
  return (
    <span className={`badge ${toneClass[tone]} ${className}`.trim()}>
      {children}
    </span>
  );
}

export function statusTone(status: string | null | undefined): BadgeTone {
  const value = (status ?? "").toLowerCase();

  if (
    ["paid", "active", "closed", "available_for_use", "completed", "final"].includes(
      value
    )
  ) {
    return "success";
  }

  if (
    ["partial", "pending", "selling", "mature", "planned", "booked", "provisional"].includes(
      value
    )
  ) {
    return "warning";
  }

  if (
    [
      "unpaid",
      "cancelled",
      "inactive",
      "expired",
      "disposed",
      "impaired",
      "loan",
    ].includes(value)
  ) {
    return "danger";
  }

  if (["delivered", "open", "idle", "under_maintenance"].includes(value)) {
    return "info";
  }

  if (["draft", "capitalized"].includes(value)) {
    return "gold";
  }

  return "neutral";
}
