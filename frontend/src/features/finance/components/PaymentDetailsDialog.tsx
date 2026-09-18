"use client";

import Link from "next/link";

import { Dialog } from "@/components/ui";

import type { DecimalString } from "../types";
import { formatCurrency, formatDate, formatLabel } from "../utils/formatters";

export type PaymentDetailLink = {
  label: string;
  href?: string;
};

export type PaymentFundingLine = {
  id: number | string;
  source: string;
  amount: DecimalString | number;
};

export type PaymentDetail = {
  kind: "customer_collection" | "expenditure_payment" | "payroll_payment";
  identifier: string;
  source: PaymentDetailLink;
  partyLabel: "Buyer" | "Payee" | "Employee";
  party: string | null | undefined;
  batch?: PaymentDetailLink | null;
  beneficiaries?: PaymentDetailLink[];
  amount: DecimalString | number;
  paymentDate: string;
  method?: string | null;
  externalReference?: string | null;
  receivedBy?: string | null;
  recordedBy?: string | null;
  notes?: string | null;
  createdAt?: string | null;
  status: string;
  reversedAt?: string | null;
  reversedBy?: string | null;
  reversalReason?: string | null;
  fundingLines?: PaymentFundingLine[];
};

const detailKindLabel: Record<PaymentDetail["kind"], string> = {
  customer_collection: "Customer collection",
  expenditure_payment: "Expenditure payment",
  payroll_payment: "Payroll payment",
};

function text(value: string | null | undefined): string {
  return value?.trim() || "N/A";
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "N/A";
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function DetailLink({ item }: { item: PaymentDetailLink }) {
  if (!item.href) return <>{item.label}</>;
  return (
    <Link
      href={item.href}
      className="font-bold underline decoration-[var(--gold)] decoration-2 underline-offset-4"
    >
      {item.label}
    </Link>
  );
}

export function PaymentDetailsDialog({
  payment,
  onClose,
}: {
  payment: PaymentDetail | null;
  onClose: () => void;
}) {
  const fundingTotal =
    payment?.fundingLines?.reduce(
      (total, line) => total + Number(line.amount || 0),
      0,
    ) ?? 0;
  const fundingReconciles = payment?.fundingLines?.length
    ? Math.abs(fundingTotal - Number(payment.amount || 0)) < 0.01
    : null;

  return (
    <Dialog
      open={Boolean(payment)}
      onClose={onClose}
      eyebrow={payment ? detailKindLabel[payment.kind] : "Payment details"}
      title={payment?.identifier || "Payment details"}
      size="lg"
    >
      {payment ? (
        <div className="max-h-[70vh] overflow-y-auto pr-1">
          <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
            <Detail label="Source record">
              <DetailLink item={payment.source} />
            </Detail>
            <Detail label={payment.partyLabel}>{text(payment.party)}</Detail>
            <Detail label="Amount / currency">
              {formatCurrency(payment.amount)}
            </Detail>
            <Detail label="Payment date">{formatDate(payment.paymentDate)}</Detail>
            <Detail label="Payment method">
              {payment.method ? formatLabel(payment.method) : "N/A"}
            </Detail>
            <Detail label="External reference">
              {text(payment.externalReference)}
            </Detail>
            <Detail label="Received by">{text(payment.receivedBy)}</Detail>
            <Detail label="Recorded by">{text(payment.recordedBy)}</Detail>
            <Detail label="Created at">{formatDateTime(payment.createdAt)}</Detail>
            <Detail label="Status">{formatLabel(payment.status)}</Detail>
            {payment.batch ? (
              <Detail label="Poultry batch">
                <DetailLink item={payment.batch} />
              </Detail>
            ) : null}
            {payment.beneficiaries?.length ? (
              <Detail label="Cost beneficiaries">
                <span className="flex flex-wrap gap-x-2 gap-y-1">
                  {payment.beneficiaries.map((beneficiary, index) => (
                    <span key={`${beneficiary.label}-${index}`}>
                      <DetailLink item={beneficiary} />
                      {index < payment.beneficiaries!.length - 1 ? "," : ""}
                    </span>
                  ))}
                </span>
              </Detail>
            ) : null}
            <Detail label="Notes" wide>
              {text(payment.notes)}
            </Detail>
          </dl>

          {payment.fundingLines?.length ? (
            <section className="mt-7 rounded-xl border border-[var(--line)] bg-[#fbfaf6] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-extrabold text-[var(--navy)]">
                    Funding reconciliation
                  </h3>
                  <p className="mt-1 text-xs text-[var(--navy-muted)]">
                    All source lines belonging to this payment only.
                  </p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-bold ${
                    fundingReconciles
                      ? "bg-green-100 text-green-800"
                      : "bg-red-100 text-red-800"
                  }`}
                >
                  {fundingReconciles ? "Reconciled" : "Does not reconcile"}
                </span>
              </div>
              <div className="mt-4 grid gap-2">
                {payment.fundingLines.map((line) => (
                  <div
                    key={line.id}
                    className="flex items-center justify-between gap-4 border-b border-[var(--line)] py-2 text-sm"
                  >
                    <span>{line.source}</span>
                    <strong>{formatCurrency(line.amount)}</strong>
                  </div>
                ))}
                <div className="flex items-center justify-between gap-4 pt-2 text-sm font-extrabold">
                  <span>Funding line total</span>
                  <span>{formatCurrency(fundingTotal)}</span>
                </div>
              </div>
            </section>
          ) : null}

          {payment.status === "reversed" ||
          payment.reversedAt ||
          payment.reversalReason ? (
            <section className="mt-7 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
              <h3 className="font-extrabold">Reversal details</h3>
              <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                <Detail label="Reversed at">
                  {formatDateTime(payment.reversedAt)}
                </Detail>
                <Detail label="Reversed by">{text(payment.reversedBy)}</Detail>
                <Detail label="Reason" wide>
                  {text(payment.reversalReason)}
                </Detail>
              </dl>
            </section>
          ) : null}
        </div>
      ) : null}
    </Dialog>
  );
}

function Detail({
  label,
  wide = false,
  children,
}: {
  label: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : ""}>
      <dt className="text-xs font-bold uppercase tracking-[0.12em] text-[var(--navy-muted)]">
        {label}
      </dt>
      <dd className="mt-1 break-words text-sm font-medium text-[var(--navy)]">
        {children}
      </dd>
    </div>
  );
}
