import {
  getFinanceDashboard,
} from "@/features/finance/api/finance";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
} from "@/features/finance/utils/formatters";

export default async function FinanceDashboardPage() {
  const dashboard = await getFinanceDashboard("/finance");

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
          label="Active cost exposure"
          value={formatCurrency(dashboard.active_batch_cost_exposure)}
        />
        <MetricCard
          label="Closed-batch profit"
          value={formatCurrency(dashboard.closed_batch_profit)}
        />
        <MetricCard label="Receivables" value={formatCurrency(dashboard.receivables)} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.85fr]">
        <Panel title="Latest Month">
          {dashboard.latest_month ? (
            <dl className="grid gap-4 sm:grid-cols-2">
              <ReportMetric
                label="Revenue"
                value={formatCurrency(dashboard.latest_month.revenue.total_revenue)}
              />
              <ReportMetric
                label="Gross profit"
                value={formatCurrency(dashboard.latest_month.production.gross_profit)}
              />
              <ReportMetric
                label="Operating profit"
                value={formatCurrency(
                  dashboard.latest_month.operating_costs.operating_profit
                )}
              />
              <ReportMetric
                label="Net before tax"
                value={formatCurrency(
                  dashboard.latest_month.other_costs.net_profit_before_tax
                )}
              />
            </dl>
          ) : (
            <EmptyState message="No accounting period has been created yet." />
          )}
        </Panel>

        <Panel title="Warnings">
          {dashboard.warnings.length ? (
            <ul className="grid gap-3">
              {dashboard.warnings.map((warning) => (
                <li
                  key={`${warning.code}-${warning.message}`}
                  className="rounded-lg border border-[var(--line)] bg-white/60 px-4 py-3 text-sm font-semibold text-[var(--navy-soft)]"
                >
                  {warning.message}
                </li>
              ))}
            </ul>
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
