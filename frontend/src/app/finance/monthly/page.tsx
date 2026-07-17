import { getMonthlyReport } from "@/features/finance/api/finance";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatNumber, formatPercent } from "@/features/finance/utils/formatters";
import type { MonthlyReport } from "@/features/finance/types";
import { BackendApiError } from "@/lib/server/backend-api";

export default async function FinanceMonthlyPage() {
  let report: MonthlyReport | null = null;

  try {
    report = await getMonthlyReport("/finance/monthly");
  } catch (error) {
    if (!(error instanceof BackendApiError && error.status === 404)) {
      throw error;
    }
  }

  return (
    <FinancePageShell
      eyebrow="Finance / Monthly"
      title="Monthly farm profitability."
      detail="Separate profitability, cash movement, receivables, and active-batch work in progress."
      actions={<FinanceNav />}
    >
      {report ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="Revenue" value={formatCurrency(report.revenue.total_revenue)} />
            <MetricCard label="Gross profit" value={formatCurrency(report.production.gross_profit)} />
            <MetricCard
              label="Operating profit"
              value={formatCurrency(report.operating_costs.operating_profit)}
            />
            <MetricCard
              label="Net before tax"
              value={formatCurrency(report.other_costs.net_profit_before_tax)}
            />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Production">
              <ReportRows
                rows={[
                  ["Direct batch costs", formatCurrency(report.production.direct_batch_costs)],
                  ["Allocated payroll", formatCurrency(report.production.allocated_production_payroll)],
                  ["Shared overhead", formatCurrency(report.production.shared_production_overhead)],
                  ["Active WIP", formatCurrency(report.production.active_batch_work_in_progress)],
                  ["Gross margin", formatPercent(report.production.gross_margin_percent)],
                ]}
              />
            </Panel>
            <Panel title="Cash And Receivables">
              <ReportRows
                rows={[
                  ["Cash received", formatCurrency(report.cash_flow.cash_received)],
                  ["Cash paid", formatCurrency(report.cash_flow.cash_paid)],
                  ["Net cash movement", formatCurrency(report.cash_flow.net_cash_movement)],
                  ["Receivables", formatCurrency(report.collections.accounts_receivable)],
                  ["Collection rate", formatPercent(report.collections.collection_rate_percent)],
                ]}
              />
            </Panel>
            <Panel title="Operations">
              <ReportRows
                rows={[
                  ["Batches active", formatNumber(report.operational_metrics.batches_active)],
                  ["Birds placed", formatNumber(report.operational_metrics.birds_placed)],
                  ["Birds sold", formatNumber(report.operational_metrics.birds_sold)],
                  ["Birds remaining", formatNumber(report.operational_metrics.birds_remaining)],
                  ["Mortality rate", formatPercent(report.operational_metrics.mortality_rate_percent)],
                ]}
              />
            </Panel>
            <Panel title="Warnings">
              {report.warnings.length ? (
                <ul className="grid gap-3">
                  {report.warnings.map((warning) => (
                    <li key={`${warning.code}-${warning.message}`} className="text-sm font-semibold">
                      {warning.message}
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState message="No allocation warnings for this period." />
              )}
            </Panel>
          </div>
        </>
      ) : (
        <Panel title="Monthly Report">
          <EmptyState message="No accounting period exists yet." />
        </Panel>
      )}
    </FinancePageShell>
  );
}

function ReportRows({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid gap-3">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-4 border-b border-[var(--line)] py-2">
          <dt className="text-sm text-[var(--navy-muted)]">{label}</dt>
          <dd className="text-sm font-extrabold text-[var(--navy)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
