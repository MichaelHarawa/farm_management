import {
  getFinanceDashboard,
} from "@/features/finance/api/finance";
import Link from "next/link";

import { FinanceWarningList } from "@/features/finance/components/FinanceWarningList";
import {
  EmptyState,
  FinanceBarChart,
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  parseDecimal,
} from "@/features/finance/utils/formatters";

export default async function FinanceDashboardPage() {
  const dashboard = await getFinanceDashboard("/finance");
  const latestMonth = dashboard.latest_month;

  return (
    <FinancePageShell
      eyebrow="Finance / Business Intelligence"
      title="Farm profitability control."
      detail="Review batch exposure, receivables, allocation warnings, and the latest monthly management result."
      actions={<FinanceNav />}
    >
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Active batches" value={dashboard.active_batches.toString()} />
        <MetricCard
          label="Current cash"
          value={formatCurrency(dashboard.current_cash)}
        />
        <MetricCard
          label="MTD net result"
          value={formatCurrency(dashboard.mtd_net_result)}
        />
        <MetricCard label="Overdue receivables" value={formatCurrency(dashboard.overdue_receivables)} />
      </div>

      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="Supplier payables" value={formatCurrency(dashboard.supplier_payables)} />
        <MetricCard label="Payroll liabilities" value={formatCurrency(dashboard.payroll_liabilities)} />
        <MetricCard label="Inventory" value={formatCurrency(dashboard.inventory_value)} detail={`${dashboard.low_stock_count} low-stock alerts`} />
        <MetricCard label="Fixed assets" value={formatCurrency(dashboard.fixed_asset_carrying_amount)} />
        <MetricCard label="Poultry WIP" value={formatCurrency(dashboard.poultry_wip_management_cost)} />
        <MetricCard label="Forecast batch result" value={formatCurrency(dashboard.active_batch_forecast_profit)} detail={`${dashboard.expiring_stock_count} lots expiring soon`} />
      </div>

      <Panel title="Poultry Batch Analysis">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-3xl text-sm leading-6 text-[var(--navy-muted)]">
            Select one poultry batch for a focused lifecycle result or combine batches to compare revenue, production cost, gross margin, collections, and mortality.
          </p>
          <Link href="/finance/batches" className="finance-button whitespace-nowrap">
            Analyze batches
          </Link>
        </div>
      </Panel>

      {latestMonth ? (
        <Panel title="Business Insights">
          <div className="grid gap-4 lg:grid-cols-2">
            <FinanceBarChart
              title="Profitability Path"
              detail="See how revenue moves through gross, operating, and pre-tax profit."
              points={[
                {
                  label: "Revenue",
                  value: parseDecimal(latestMonth.revenue.total_revenue),
                  displayValue: formatCurrency(latestMonth.revenue.total_revenue),
                  tone: "gold",
                },
                {
                  label: "Gross profit",
                  value: parseDecimal(latestMonth.production.gross_profit),
                  displayValue: formatCurrency(latestMonth.production.gross_profit),
                  tone: "green",
                },
                {
                  label: "Operating profit",
                  value: parseDecimal(latestMonth.operating_costs.operating_profit),
                  displayValue: formatCurrency(
                    latestMonth.operating_costs.operating_profit
                  ),
                  tone: "navy",
                },
                {
                  label: "Net before tax",
                  value: parseDecimal(latestMonth.other_costs.net_profit_before_tax),
                  displayValue: formatCurrency(
                    latestMonth.other_costs.net_profit_before_tax
                  ),
                  tone: "navy",
                },
              ]}
            />
            <FinanceBarChart
              title="Cash And Collections"
              detail="Compare cash received and paid with the balance still due from buyers."
              points={[
                {
                  label: "Cash received",
                  value: parseDecimal(latestMonth.cash_flow.cash_received),
                  displayValue: formatCurrency(latestMonth.cash_flow.cash_received),
                  tone: "green",
                },
                {
                  label: "Cash paid",
                  value: parseDecimal(latestMonth.cash_flow.cash_paid),
                  displayValue: formatCurrency(latestMonth.cash_flow.cash_paid),
                  tone: "gold",
                },
                {
                  label: "Receivables",
                  value: parseDecimal(latestMonth.collections.accounts_receivable),
                  displayValue: formatCurrency(
                    latestMonth.collections.accounts_receivable
                  ),
                  tone: "muted",
                },
                {
                  label: "Net movement",
                  value: parseDecimal(latestMonth.cash_flow.net_cash_movement),
                  displayValue: formatCurrency(
                    latestMonth.cash_flow.net_cash_movement
                  ),
                  tone: "navy",
                },
              ]}
            />
          </div>
        </Panel>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_0.85fr]">
        <Panel title="Latest Month">
          {latestMonth ? (
            <dl className="grid gap-4 sm:grid-cols-2">
              <ReportMetric
                label="Revenue"
                value={formatCurrency(latestMonth.revenue.total_revenue)}
              />
              <ReportMetric
                label="Gross profit"
                value={formatCurrency(latestMonth.production.gross_profit)}
              />
              <ReportMetric
                label="Operating profit"
                value={formatCurrency(latestMonth.operating_costs.operating_profit)}
              />
              <ReportMetric
                label="Net before tax"
                value={formatCurrency(latestMonth.other_costs.net_profit_before_tax)}
              />
            </dl>
          ) : (
            <EmptyState message="No accounting period has been created yet." />
          )}
        </Panel>

        <Panel title="Warnings">
          {dashboard.warnings.length ? (
            <FinanceWarningList warnings={dashboard.warnings} />
          ) : (
            <EmptyState message="No finance warnings are currently open." />
          )}
        </Panel>
      </div>
    </FinancePageShell>
  );
}

function ReportMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label text-[var(--navy-muted)]">{label}</dt>
      <dd className="mt-2 text-xl font-extrabold text-[var(--navy)]">{value}</dd>
    </div>
  );
}
