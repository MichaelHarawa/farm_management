export function parseDecimal(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") {
    return 0;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function formatCurrency(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en", {
    style: "currency",
    currency: "MWK",
    maximumFractionDigits: 2,
  }).format(parseDecimal(value));
}

export function formatNumber(value: string | number | null | undefined): string {
  return new Intl.NumberFormat("en").format(parseDecimal(value));
}

export function formatPercent(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }

  return `${formatNumber(value)}%`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(value));
}

export function formatLabel(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
