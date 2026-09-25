import Link from "next/link";

import { getFinanceDashboard } from "@/features/finance/api/finance";
import { FinanceWarningList } from "@/features/finance/components/FinanceWarningList";
import { EmptyState, FinanceNav, FinancePageShell, MetricCard, Panel } from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, parseDecimal } from "@/features/finance/utils/formatters";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function FinanceDashboardPage({ searchParams }: { searchParams: SearchParams }) {
  const requested = await searchParams;
  const period = typeof requested.period === "string" ? requested.period : "";
  const query = period ? `?period=${encodeURIComponent(period)}` : "";
  const dashboard = await getFinanceDashboard(`/finance${query}`, query);
  const overview = dashboard.overview;

  return (
    <FinancePageShell
      eyebrow="Finance"
      title="Financial position."
      detail="A short view of sales, profit, cash, and amounts requiring action. Open a supporting area only when you need detail."
      actions={<FinanceNav />}
    >
      <form method="get" className="flex flex-col gap-3 rounded-lg border border-[var(--line)] bg-white/70 p-4 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm font-bold">Reporting period<select name="period" defaultValue={overview ? String(overview.period_id) : ""} className="form-input mt-2 w-full bg-white">{dashboard.available_periods.map((row) => <option key={row.id} value={row.id}>{formatDate(row.period_start)}–{formatDate(row.period_end)} · {row.status}</option>)}</select></label>
        <button className="finance-button px-5 py-3">Review</button>
      </form>

      {!overview ? <EmptyState message="Create an accounting period to calculate the finance overview." /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Sales" value={formatCurrency(overview.total_sales)} detail="Recognized in this period" />
            <MetricCard label="Operating profit" value={formatCurrency(overview.operating_profit)} tone={parseDecimal(overview.operating_profit) < 0 ? "danger" : "positive"} detail="After operating expenses; before finance cost and tax" />
            <MetricCard label="Cash available" value={formatCurrency(overview.cash_available)} detail={`As of ${formatDate(overview.as_of_date)}`} />
            <MetricCard label="Customers owe" value={formatCurrency(overview.customers_owe)} tone={parseDecimal(overview.customers_overdue) > 0 ? "warning" : "default"} detail={`${formatCurrency(overview.customers_overdue)} overdue`} />
          </div>

          <section className="grid gap-5 lg:grid-cols-2">
            <Panel title="What needs attention">
              <div className="grid gap-3">
                <ActionRow label="Overdue customer balances" value={overview.customers_overdue} href="/finance/receivables" urgent={parseDecimal(overview.customers_overdue) > 0} />
                <ActionRow label="Unpaid bills and wages" value={overview.unpaid_bills_and_wages} href="/finance/expenditures" urgent={parseDecimal(overview.unpaid_bills_and_wages) > 0} />
                <ActionRow label="Cash shortfall for due payments" value={overview.cash_needed_for_payments_due} href="/finance/expenditures" urgent={parseDecimal(overview.cash_needed_for_payments_due) > 0} />
              </div>
            </Panel>
            <Panel title="Common tasks">
              <div className="grid gap-3 sm:grid-cols-2">
                <TaskLink href="/finance/customers" label="Review customers" detail="Contribution and cost coverage" />
                <TaskLink href="/finance/receivables" label="Manage collections" detail="Sales and outstanding balances" />
                <TaskLink href="/finance/expenditures" label="Record or pay a cost" detail="Purchases, payables, and funding" />
                <TaskLink href="/finance/batches" label="Compare batches" detail="Production and net position" />
              </div>
            </Panel>
          </section>

          <details className="rounded-lg border border-[var(--line)] bg-white/55 p-4 text-sm">
            <summary className="cursor-pointer font-bold">More period detail</summary>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <CompactFigure label="Cost of sales" value={overview.cost_of_sales} />
              <CompactFigure label="Gross profit" value={overview.gross_profit} />
              <CompactFigure label="Operating expenses" value={overview.operating_expenses} />
              <CompactFigure label="Unfinished batch costs" value={overview.unfinished_batch_costs} />
            </div>
            <div className="mt-4 border-t border-[var(--line)] pt-4">
              <p className="font-bold">Cash reconciliation</p>
              <p className="mt-2 leading-6 text-[var(--navy-muted)]">Opening {formatCurrency(overview.cash_reconciliation.opening_cash)} + inflows {formatCurrency(parseDecimal(overview.cash_reconciliation.operating_inflows) + parseDecimal(overview.cash_reconciliation.financing_inflows) + parseDecimal(overview.cash_reconciliation.investing_inflows))} − payments {formatCurrency(overview.cash_reconciliation.cash_paid)} = closing {formatCurrency(overview.cash_reconciliation.closing_cash)}. {overview.cash_reconciliation.reconciles ? "Reconciled." : "Review reconciliation."}</p>
              <Link href="/finance/monthly" className="mt-3 inline-block font-bold underline">Open full period report</Link>
            </div>
          </details>
        </>
      )}

      {dashboard.warnings.length ? (
        <Panel title={`Warnings (${dashboard.warnings.length})`}><FinanceWarningList warnings={dashboard.warnings} /></Panel>
      ) : null}
    </FinancePageShell>
  );
}

function ActionRow({ label, value, href, urgent }: { label: string; value: string; href: string; urgent: boolean }) {
  return <Link href={href} className="flex items-center justify-between gap-4 rounded-lg border p-4 hover:bg-[var(--gold-soft)]"><span className="font-bold">{label}</span><span className={urgent ? "font-extrabold text-[var(--danger)]" : "font-extrabold text-green-700"}>{formatCurrency(value)}</span></Link>;
}

function TaskLink({ href, label, detail }: { href: string; label: string; detail: string }) {
  return <Link href={href} className="rounded-lg border border-[var(--line)] p-4 hover:bg-[var(--gold-soft)]"><span className="font-bold">{label}</span><span className="mt-1 block text-xs text-[var(--navy-muted)]">{detail}</span></Link>;
}

function CompactFigure({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-[var(--surface-cream)] p-3"><p className="text-xs font-bold text-[var(--navy-muted)]">{label}</p><p className="mt-2 font-extrabold">{formatCurrency(value)}</p></div>;
}
