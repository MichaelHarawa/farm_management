import Link from "next/link";

import { getFinanceDashboard } from "@/features/finance/api/finance";
import { FinanceForecast } from "@/features/finance/components/FinanceForecast";
import { FinanceWarningList } from "@/features/finance/components/FinanceWarningList";
import { EmptyState, FinanceBarChart, FinanceNav, FinancePageShell, Panel } from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, parseDecimal } from "@/features/finance/utils/formatters";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function FinanceDashboardPage({ searchParams }: { searchParams: SearchParams }) {
  const requested = await searchParams;
  const period = typeof requested.period === "string" ? requested.period : "";
  const query = period ? "?period=" + encodeURIComponent(period) : "";
  const dashboard = await getFinanceDashboard("/finance" + query, query);
  const overview = dashboard.overview;

  return (
    <FinancePageShell
      eyebrow="Finance / Business Intelligence"
      title="Farm finances."
      detail="Understand sales, profit, cash, unpaid balances, and poultry batch performance using one stated reporting period."
      actions={<FinanceNav />}
    >
      <form method="get" className="flex flex-col gap-3 rounded-xl border border-[var(--line)] bg-white/70 p-4 shadow-[var(--shadow-card)] sm:flex-row sm:items-end">
        <label className="flex-1 text-sm font-bold">
          Reporting period
          <select name="period" defaultValue={overview ? String(overview.period_id) : ""} className="form-input mt-2 w-full bg-white">
            {dashboard.available_periods.map((row) => (
              <option key={row.id} value={row.id}>{formatDate(row.period_start)}–{formatDate(row.period_end)} · {row.status}</option>
            ))}
          </select>
        </label>
        <button className="finance-button px-5 py-3">Review period</button>
        <p className="text-xs leading-5 text-[var(--navy-muted)] sm:max-w-xs">
          Last updated {new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(dashboard.generated_at))}
        </p>
      </form>

      {!overview ? (
        <EmptyState message="Create an accounting period to calculate the finance overview." />
      ) : (
        <>
          <section aria-labelledby="sales-profit-heading">
            <div className="mb-4">
              <p className="text-label text-[var(--navy-muted)]">Sales and profit</p>
              <h2 id="sales-profit-heading" className="mt-2 text-2xl font-extrabold">{formatDate(overview.period_start)}–{formatDate(overview.period_end)}</h2>
              <p className="mt-2 text-sm text-[var(--navy-muted)]">{overview.period_status === "closed" ? "Closed accounting period" : "Open, provisional accounting period"}</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <OverviewMetric label="Total sales" value={formatCurrency(overview.total_sales)} detail="Sales recorded in this period, including credit sales." href="/finance/receivables" />
              <OverviewMetric label="Cost of sales" value={formatCurrency(overview.cost_of_sales)} detail="Production cost attributable to products sold in this period." href="/finance/batches" />
              <OverviewMetric label="Gross profit" value={formatCurrency(overview.gross_profit)} detail="Total sales less cost of sales." href="/finance/monthly" tone={parseDecimal(overview.gross_profit) < 0 ? "danger" : "positive"} />
              <OverviewMetric label="Operating profit" value={formatCurrency(overview.operating_profit)} detail="Gross profit less operating expenses; finance costs and tax are excluded." href="/finance/monthly" tone={parseDecimal(overview.operating_profit) < 0 ? "danger" : "positive"} />
            </div>
            <details className="mt-4 rounded-lg border border-[var(--line)] bg-white/55 p-4 text-sm">
              <summary className="cursor-pointer font-bold">What operating expenses include</summary>
              <p className="mt-3 leading-6 text-[var(--navy-muted)]">{overview.operating_expense_basis}</p>
              <p className="mt-2 font-semibold">Operating expenses in this period: <span className="whitespace-nowrap">{formatCurrency(overview.operating_expenses)}</span></p>
            </details>
          </section>

          <section aria-labelledby="cash-balances-heading">
            <div className="mb-4">
              <p className="text-label text-[var(--navy-muted)]">Cash and unpaid balances</p>
              <h2 id="cash-balances-heading" className="mt-2 text-2xl font-extrabold">Position as of {formatDate(overview.as_of_date)}</h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <OverviewMetric label="Cash available" value={formatCurrency(overview.cash_available)} detail={overview.cash_basis} href="/finance/revenue-usage" />
              <OverviewMetric label="Customers owe" value={formatCurrency(overview.customers_owe)} detail={formatCurrency(overview.customers_overdue) + " is overdue."} href="/finance/receivables" tone={parseDecimal(overview.customers_overdue) > 0 ? "warning" : "default"} />
              <OverviewMetric label="Unpaid bills and wages" value={formatCurrency(overview.unpaid_bills_and_wages)} detail={formatCurrency(overview.supplier_payables) + " suppliers · " + formatCurrency(overview.payroll_payables) + " payroll."} href="/finance/expenditures" />
              <OverviewMetric label="Cash needed for payments due" value={formatCurrency(overview.cash_needed_for_payments_due)} detail={"Positive shortfall for obligations through " + formatDate(overview.payment_due_range_end) + "."} href="/finance/expenditures" tone={parseDecimal(overview.cash_needed_for_payments_due) > 0 ? "danger" : "positive"} />
            </div>

            <details className="mt-4 rounded-xl border border-[var(--line)] bg-[var(--surface-cream)] p-5 shadow-[var(--shadow-card)]">
              <summary className="cursor-pointer font-extrabold">Cash reconciliation</summary>
              <p className="mt-2 text-sm text-[var(--navy-muted)]">Explains movements that are not sales collections, so cash received less cash paid is not mistaken for the full change in cash.</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <ReconcileMetric label="Opening cash" value={overview.cash_reconciliation.opening_cash} />
                <ReconcileMetric label="Operating inflows" value={overview.cash_reconciliation.operating_inflows} />
                <ReconcileMetric label="Financing inflows" value={overview.cash_reconciliation.financing_inflows} />
                <ReconcileMetric label="Investing inflows" value={overview.cash_reconciliation.investing_inflows} />
                <ReconcileMetric label="Cash paid" value={overview.cash_reconciliation.cash_paid} negative />
                <ReconcileMetric label="Net movement" value={overview.cash_reconciliation.net_cash_movement} />
              </div>
              <p className="mt-4 text-sm font-bold">Closing cash: <span className="whitespace-nowrap">{formatCurrency(overview.cash_reconciliation.closing_cash)}</span> · {overview.cash_reconciliation.reconciles ? "Reconciled" : "Needs reconciliation"}</p>
            </details>
          </section>

          <section className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
            <Panel title="Costs in unfinished batches">
              <p className="font-display whitespace-nowrap text-3xl font-bold">{formatCurrency(overview.unfinished_batch_costs)}</p>
              <p className="mt-3 text-sm leading-6 text-[var(--navy-muted)]">{overview.unfinished_batch_cost_basis}</p>
              <Link href="/finance/batches" className="mt-4 inline-block font-bold underline">Review supporting batch costs</Link>
            </Panel>
            <Panel title="Batch performance">
              <p className="text-sm leading-6 text-[var(--navy-muted)]">Compare one batch or a combination of batches using revenue, costs, shared allocations, mortality, collections, and final or provisional results.</p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link href="/finance/batches" className="finance-button">Analyze batches</Link>
                <Link href="/poultry/dashboard" className="rounded-lg border border-[var(--line)] px-5 py-3 font-bold">Open poultry dashboard</Link>
              </div>
            </Panel>
          </section>

          <FinanceForecast forecast={dashboard.forecast} />

          {dashboard.latest_month ? (
            <Panel title="Period insights">
              <div className="grid gap-4 lg:grid-cols-2">
                <FinanceBarChart
                  title="Profit path"
                  detail="Sales, gross profit, and operating profit on the same accounting basis."
                  points={[
                    { label: "Total sales", value: parseDecimal(overview.total_sales), displayValue: formatCurrency(overview.total_sales), tone: "gold" },
                    { label: "Gross profit", value: parseDecimal(overview.gross_profit), displayValue: formatCurrency(overview.gross_profit), tone: "green" },
                    { label: "Operating profit", value: parseDecimal(overview.operating_profit), displayValue: formatCurrency(overview.operating_profit), tone: "navy" },
                  ]}
                />
                <FinanceBarChart
                  title="Financial position"
                  detail={"Balances as of " + formatDate(overview.as_of_date) + "; unfinished batch costs are work in progress."}
                  points={[
                    { label: "Cash", value: parseDecimal(overview.cash_available), displayValue: formatCurrency(overview.cash_available), tone: "green" },
                    { label: "Receivables", value: parseDecimal(overview.customers_owe), displayValue: formatCurrency(overview.customers_owe), tone: "gold" },
                    { label: "Unpaid bills and wages", value: parseDecimal(overview.unpaid_bills_and_wages), displayValue: formatCurrency(overview.unpaid_bills_and_wages), tone: "muted" },
                    { label: "Unfinished batch costs", value: parseDecimal(overview.unfinished_batch_costs), displayValue: formatCurrency(overview.unfinished_batch_costs), tone: "navy" },
                  ]}
                />
              </div>
            </Panel>
          ) : null}
        </>
      )}

      <Panel title="Warnings and actions">
        {dashboard.warnings.length ? <FinanceWarningList warnings={dashboard.warnings} /> : <EmptyState message="No finance warnings are currently open." />}
      </Panel>
    </FinancePageShell>
  );
}

function OverviewMetric({ label, value, detail, href, tone = "default" }: {
  label: string;
  value: string;
  detail: string;
  href: string;
  tone?: "default" | "positive" | "warning" | "danger";
}) {
  const classes = {
    default: "border-[var(--line)] bg-[var(--surface-cream)]",
    positive: "border-[#94b89d] bg-[#edf6ef]",
    warning: "border-[var(--gold)] bg-[var(--gold-soft)]",
    danger: "border-red-300 bg-red-50",
  };
  return <article className={"min-w-0 rounded-xl border p-5 shadow-[var(--shadow-card)] " + classes[tone]}>
    <p className="text-label text-[var(--navy-muted)]">{label}</p>
    <p className="font-display mt-3 whitespace-nowrap text-2xl font-bold leading-tight sm:text-3xl" title={value}>{value}</p>
    <p className="mt-3 text-sm leading-6 text-[var(--navy-muted)]">{detail}</p>
    <Link href={href} className="mt-4 inline-block text-sm font-bold underline">View supporting records</Link>
  </article>;
}

function ReconcileMetric({ label, value, negative = false }: { label: string; value: string; negative?: boolean }) {
  return <div className="rounded-lg bg-white/65 p-3"><p className="text-xs font-bold uppercase tracking-wide text-[var(--navy-muted)]">{label}</p><p className="mt-2 whitespace-nowrap font-extrabold">{negative ? "−" : ""}{formatCurrency(value)}</p></div>;
}
