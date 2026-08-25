"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import type { BatchRevenueUtilization } from "@/features/finance/types";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";

export default function BatchRevenueUsageDetailPage() {
  const params = useParams<{ id: string }>();
  const [report, setReport] = useState<BatchRevenueUtilization | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientApiFetch<BatchRevenueUtilization>(`/api/finance/reports/batches/${params.id}/revenue-utilization`)
      .then(setReport)
      .catch((requestError: unknown) => setError(getApiErrorMessage(requestError)));
  }, [params.id]);

  if (!report) return <main className="p-8">{error || "Loading revenue usage…"}</main>;

  return <main className="mx-auto max-w-[1320px] p-8">
    <Link href="/finance/revenue-usage" className="text-sm font-bold underline">← Revenue Usage</Link>
    <div className="mt-6"><p className="finance-eyebrow">Funding source / {report.batch_code}</p><h1 className="mt-2 text-4xl font-extrabold">Batch spending details</h1><p className="mt-3 text-[var(--navy-muted)]">Every posted expenditure funded from this batch&apos;s collected cash, including costs benefiting another batch or farm activity.</p></div>
    <section className="mt-8 grid gap-4 sm:grid-cols-4"><div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Cash collected</p><strong className="text-2xl">{formatCurrency(report.cash_collected)}</strong></div><div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Refunded / reversed</p><strong className="text-2xl">{formatCurrency(report.refunds)}</strong></div><div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Spent</p><strong className="text-2xl">{formatCurrency(report.cash_used)}</strong></div><div className="rounded-xl border bg-white p-5"><p className="text-sm text-[var(--navy-muted)]">Remaining cash</p><strong className="text-2xl">{formatCurrency(report.available_cash)}</strong></div></section>
    <section className="mt-6 overflow-x-auto rounded-xl border bg-white"><table className="min-w-[1180px] w-full text-sm"><thead className="bg-[#f6f3eb] text-left"><tr><th className="p-3">Reference</th><th className="p-3">Date</th><th className="p-3">Description</th><th className="p-3">Category</th><th className="p-3">Nature</th><th className="p-3 text-right">Expenditure total</th><th className="p-3 text-right">Funded by batch</th><th className="p-3">Beneficiary / cost bearer</th><th className="p-3">Status</th><th className="p-3 text-right">Cash after</th></tr></thead><tbody>
      {report.transactions.map((transaction) => <tr key={transaction.allocation_id} className="border-t"><td className="p-3"><Link href={`/finance/expenditures/${transaction.expenditure_id}`} className="font-bold underline">{transaction.expenditure_reference}</Link></td><td className="p-3">{formatDate(transaction.date)}</td><td className="p-3">{transaction.description}</td><td className="p-3">{transaction.category}</td><td className="p-3">{formatLabel(transaction.accounting_nature)}</td><td className="p-3 text-right">{formatCurrency(transaction.total_expenditure)}</td><td className="p-3 text-right font-bold">{formatCurrency(transaction.amount)}</td><td className="p-3">{transaction.beneficiary}</td><td className="p-3">{formatLabel(transaction.status)}</td><td className="p-3 text-right font-bold">{formatCurrency(transaction.remaining_cash_after)}</td></tr>)}
      {!report.transactions.length ? <tr><td colSpan={10} className="p-8 text-center text-[var(--navy-muted)]">No posted expenditures have used this batch&apos;s cash.</td></tr> : null}
    </tbody></table></section>
  </main>;
}
