import Link from "next/link";

import { getReceivables } from "@/features/finance/api/finance";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  formatDate,
  formatLabel,
} from "@/features/finance/utils/formatters";

export default async function FinanceReceivablesPage() {
  const report = await getReceivables("/finance/receivables");
  const averageBalance = report.count
    ? Number(report.total_receivable) / report.count
    : 0;

  return (
    <FinancePageShell
      eyebrow="Finance / Receivables"
      title="Buyer balances."
      detail="Review outstanding poultry sales, follow up collections, and open the originating batch record without changing closed-period cash history."
      actions={<FinanceNav />}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <MetricCard label="Open sales" value={report.count.toString()} />
        <MetricCard
          label="Total receivable"
          value={formatCurrency(report.total_receivable)}
        />
        <MetricCard
          label="Average open balance"
          value={formatCurrency(averageBalance)}
        />
      </div>

      <Panel title="Receivables Register">
        {report.results.length ? (
          <div className="grid gap-5">
            <p className="rounded-lg border border-[var(--gold)]/40 bg-[var(--gold-soft)]/55 px-4 py-3 text-sm leading-6 text-[var(--navy-soft)]">
              Collection control: this register shows the current balance stored on each
              sale. Do not back-post later cash by changing a historical sale. Keep the
              dated receipt and reference in the farm&apos;s controlled accounting process
              until a receipt ledger is added here.
            </p>
            <div className="overflow-x-auto">
              <table className="min-w-[980px] border-collapse text-sm">
                <thead className="text-left text-[var(--navy-muted)]">
                  <tr className="border-b border-[var(--line)]">
                    <th className="py-3 pr-4">Sale</th>
                    <th className="py-3 pr-4">Buyer</th>
                    <th className="py-3 pr-4">Batch</th>
                    <th className="py-3 pr-4">Sale date</th>
                    <th className="py-3 pr-4">Status</th>
                    <th className="py-3 pr-4 text-right">Sale total</th>
                    <th className="py-3 pr-4 text-right">Paid</th>
                    <th className="py-3 pr-4 text-right">Balance</th>
                    <th className="py-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {report.results.map((sale) => (
                    <tr key={sale.sale_id} className="border-b border-[var(--line)]">
                      <td className="py-4 pr-4 font-extrabold text-[var(--navy)]">
                        {sale.sale_id}
                      </td>
                      <td className="py-4 pr-4">
                        {sale.buyer_name || "Not recorded"}
                      </td>
                      <td className="py-4 pr-4">
                        <Link
                          href={`/poultry/batches/${sale.batch}?tab=sales`}
                          className="font-extrabold text-[var(--navy)] underline decoration-[var(--gold)] decoration-2 underline-offset-4"
                        >
                          {sale.batch_id}
                        </Link>
                      </td>
                      <td className="py-4 pr-4">{formatDate(sale.sale_date)}</td>
                      <td className="py-4 pr-4">
                        {formatLabel(sale.payment_status)}
                      </td>
                      <td className="py-4 pr-4 text-right">
                        {formatCurrency(sale.sale_total)}
                      </td>
                      <td className="py-4 pr-4 text-right">
                        {formatCurrency(sale.amount_paid)}
                      </td>
                      <td className="py-4 pr-4 text-right font-extrabold text-[var(--navy)]">
                        {formatCurrency(sale.balance)}
                      </td>
                      <td className="py-4 text-right">
                        <Link
                          href={`/poultry/batches/${sale.batch}?tab=sales`}
                          className="whitespace-nowrap font-extrabold text-[var(--navy)] underline decoration-[var(--gold)] decoration-2 underline-offset-4"
                        >
                          Open batch sales
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <EmptyState message="No buyer balances are currently outstanding." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
