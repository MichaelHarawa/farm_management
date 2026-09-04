import { getAccountingPeriods, getMonthlyReport } from "@/features/finance/api/finance";
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
  formatDate,
  formatNumber,
  formatPercent,
  parseDecimal,
} from "@/features/finance/utils/formatters";
import type { MonthlyReport } from "@/features/finance/types";
import { BackendApiError } from "@/lib/server/backend-api";

type PageProps = { searchParams: Promise<{ period?: string }> };

export default async function FinanceMonthlyPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const periods = await getAccountingPeriods("/finance/monthly");
  const selected = periods.find((period) => String(period.id) === query.period) ?? periods[0];
  let report: MonthlyReport | null = null;

  try {
    report = await getMonthlyReport(
      selected ? `/finance/monthly?period=${selected.id}` : "/finance/monthly",
      selected?.period_start.slice(0, 7)
    );
  } catch (error) {
    if (!(error instanceof BackendApiError && error.status === 404)) {
      throw error;
    }
  }

  return (
    <FinancePageShell
      eyebrow="Finance / Period Reports & Close"
      title="Period reports and close."
      detail="Accrual performance, classified cash movement, balances, ageing, and close readiness on one period-correct basis."
      actions={<FinanceNav />}
    >
      <Panel title="Reporting Period">
        <form method="get" className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1 text-sm font-bold text-[var(--navy)]">
            Period
            <select name="period" defaultValue={selected?.id} className="form-input mt-2 w-full">
              {periods.map((period) => (
                <option key={period.id} value={period.id}>
                  {formatDate(period.period_start)} – {formatDate(period.period_end)} · {period.status}
                </option>
              ))}
            </select>
          </label>
          <button className="finance-button" type="submit">Review period</button>
        </form>
        {report ? (
          <p className="mt-3 text-sm text-[var(--navy-muted)]">
            {report.reporting_basis} · as of {formatDate(report.as_of)} · policy {report.reporting_policy ?? "not configured"}
            {report.snapshot_version ? ` · immutable snapshot v${report.snapshot_version}` : ""}
          </p>
        ) : null}
      </Panel>
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
          <Panel title="Business Insights">
            <div className="grid gap-4 lg:grid-cols-2">
              <FinanceBarChart
                title="Revenue Mix"
                detail="Compare the products contributing to this month's farm revenue."
                points={[
                  {
                    label: "Bird sales",
                    value: parseDecimal(report.revenue.bird_sales),
                    displayValue: formatCurrency(report.revenue.bird_sales),
                    tone: "gold",
                  },
                  {
                    label: "Egg sales",
                    value: parseDecimal(report.revenue.egg_sales),
                    displayValue: formatCurrency(report.revenue.egg_sales),
                    tone: "green",
                  },
                  {
                    label: "Manure sales",
                    value: parseDecimal(report.revenue.manure_sales),
                    displayValue: formatCurrency(report.revenue.manure_sales),
                    tone: "muted",
                  },
                  {
                    label: "Other batch revenue",
                    value: parseDecimal(report.revenue.other_batch_revenue),
                    displayValue: formatCurrency(
                      report.revenue.other_batch_revenue
                    ),
                    tone: "navy",
                  },
                ]}
              />
              <FinanceBarChart
                title="Asset And Replacement Position"
                detail="Compare asset value with depreciation, reserves, and the replacement funding gap."
                points={[
                  {
                    label: "Gross asset cost",
                    value: parseDecimal(report.asset_reporting.gross_asset_cost),
                    displayValue: formatCurrency(
                      report.asset_reporting.gross_asset_cost
                    ),
                    tone: "gold",
                  },
                  {
                    label: "Accumulated depreciation",
                    value: parseDecimal(
                      report.asset_reporting.accumulated_depreciation
                    ),
                    displayValue: formatCurrency(
                      report.asset_reporting.accumulated_depreciation
                    ),
                    tone: "muted",
                  },
                  {
                    label: "Carrying amount",
                    value: parseDecimal(report.asset_reporting.carrying_amount),
                    displayValue: formatCurrency(
                      report.asset_reporting.carrying_amount
                    ),
                    tone: "navy",
                  },
                  {
                    label: "Reserve balance",
                    value: parseDecimal(report.asset_reporting.reserve_balance),
                    displayValue: formatCurrency(
                      report.asset_reporting.reserve_balance
                    ),
                    tone: "green",
                  },
                  {
                    label: "Replacement funding gap",
                    value: parseDecimal(
                      report.asset_reporting.replacement_funding_gap
                    ),
                    displayValue: formatCurrency(
                      report.asset_reporting.replacement_funding_gap
                    ),
                    tone: "danger",
                  },
                ]}
              />
            </div>
          </Panel>
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
                  ["Opening cash", formatCurrency(report.cash_flow.opening_cash)],
                  ["Cash received this period", formatCurrency(report.cash_flow.cash_received)],
                  ["Cash paid from dated ledgers", formatCurrency(report.cash_flow.cash_paid)],
                  ["Net cash movement", formatCurrency(report.cash_flow.net_cash_movement)],
                  ["Closing cash", formatCurrency(report.cash_flow.closing_cash)],
                  ["Receivables", formatCurrency(report.collections.accounts_receivable)],
                  ["Sales-cohort collection rate", formatPercent(report.collections.collection_rate_percent)],
                ]}
              />
            </Panel>
            <Panel title="Classified Cash Flow">
              <ReportRows rows={[
                ["Operating inflows", formatCurrency(report.cash_flow.operating.inflows)],
                ["Operating outflows", formatCurrency(report.cash_flow.operating.outflows)],
                ["Investing net movement", formatCurrency(report.cash_flow.investing.net)],
                ["Financing net movement", formatCurrency(report.cash_flow.financing.net)],
                ["Cash reconciliation", report.cash_flow.reconciles ? "Reconciled" : "Action required"],
              ]} />
            </Panel>
            <Panel title="Receivables Roll-forward">
              <ReportRows rows={[
                ["Opening receivables", formatCurrency(report.collections.roll_forward.opening_receivables)],
                ["Current-period sales", formatCurrency(report.collections.roll_forward.current_period_sales)],
                ["Collections against opening", formatCurrency(report.collections.roll_forward.collections_against_opening)],
                ["Collections against current sales", formatCurrency(report.collections.roll_forward.collections_against_current_sales)],
                ["Closing receivables", formatCurrency(report.collections.roll_forward.closing_receivables)],
                ["Identified cohort overpayment", formatCurrency(report.collections.collection_overpayment)],
              ]} />
            </Panel>
            <Panel title="Operating Cost Breakdown">
              <ReportRows
                rows={[
                  [
                    "Administration payroll",
                    formatCurrency(report.operating_costs.administration_payroll),
                  ],
                  [
                    "Administration temporary labour",
                    formatCurrency(
                      report.operating_costs.administration_ad_hoc_labour
                    ),
                  ],
                  [
                    "Administration consumables",
                    formatCurrency(
                      report.operating_costs.administration_consumables
                    ),
                  ],
                  [
                    "Other administration expenses",
                    formatCurrency(
                      report.operating_costs.general_operating_expenses
                    ),
                  ],
                  [
                    "Selling and distribution",
                    formatCurrency(
                      report.operating_costs.selling_distribution_costs
                    ),
                  ],
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
            <Panel title="Deferred Balances">
              <ReportRows
                rows={[
                  ["Consumables purchased", formatCurrency(report.deferred_balances.consumables_purchased)],
                  ["Consumables consumed", formatCurrency(report.deferred_balances.consumables_consumed)],
                  ["Closing inventory", formatCurrency(report.deferred_balances.closing_consumable_inventory)],
                  ["Prepaid recognized", formatCurrency(report.deferred_balances.prepaid_expense_recognized)],
                  ["Prepaid closing", formatCurrency(report.deferred_balances.prepaid_expense_closing_balance)],
                ]}
              />
            </Panel>
            <Panel title="Assets And Reserves">
              <ReportRows
                rows={[
                  ["Asset additions", formatCurrency(report.asset_reporting.additions)],
                  ["Gross asset cost", formatCurrency(report.asset_reporting.gross_asset_cost)],
                  ["Accumulated depreciation", formatCurrency(report.asset_reporting.accumulated_depreciation)],
                  ["Carrying amount", formatCurrency(report.asset_reporting.carrying_amount)],
                  ["Reserve balance", formatCurrency(report.asset_reporting.reserve_balance)],
                  ["Replacement funding gap", formatCurrency(report.asset_reporting.replacement_funding_gap)],
                ]}
              />
            </Panel>
            <Panel title="Statement Of Financial Position">
              <ReportRows rows={[
                ["Cash", formatCurrency(report.statement_of_financial_position.cash)],
                ["Receivables", formatCurrency(report.statement_of_financial_position.receivables)],
                ["Consumable inventory", formatCurrency(report.statement_of_financial_position.consumable_inventory)],
                ["Poultry WIP / biological management cost", formatCurrency(report.statement_of_financial_position.poultry_wip_management_cost)],
                ["Fixed assets, net", formatCurrency(report.statement_of_financial_position.fixed_assets_net)],
                ["Supplier payables", formatCurrency(report.statement_of_financial_position.supplier_payables)],
                ["Payroll and statutory liabilities", formatCurrency(report.statement_of_financial_position.payroll_and_statutory_liabilities)],
                ["Loans", formatCurrency(report.statement_of_financial_position.loans)],
                ["Net assets", formatCurrency(report.statement_of_financial_position.net_assets)],
              ]} />
              <p className="mt-3 text-xs text-[var(--navy-muted)]">{report.statement_of_financial_position.basis}</p>
            </Panel>
            <Panel title="Comparatives And Close Readiness">
              <ReportRows rows={[
                ["Previous-period revenue", formatCurrency(report.comparatives.previous_period_revenue)],
                ["Current-period revenue", formatCurrency(report.comparatives.current_period_revenue)],
                ["Revenue change", formatCurrency(report.comparatives.revenue_change)],
                ["Year-to-date revenue", formatCurrency(report.comparatives.ytd_revenue)],
                ["Unresolved warnings", formatNumber(report.close_readiness.unresolved_warning_count)],
              ]} />
              <ul className="mt-4 grid gap-2 text-sm text-[var(--navy-muted)]">
                {report.close_readiness.checklist.map((item) => <li key={item}>• {item}</li>)}
              </ul>
            </Panel>
            <Panel title="Warnings">
              {report.warnings.length ? (
                <FinanceWarningList warnings={report.warnings} />
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
