import Link from "next/link";

import { getBatchPortfolioReport } from "@/features/finance/api/finance";
import { BatchSelectionFilter } from "@/features/finance/components/BatchSelectionFilter";
import { FinanceWarningList } from "@/features/finance/components/FinanceWarningList";
import { MAX_BATCH_SELECTION } from "@/features/finance/constants";
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
  formatLabel,
  formatNumber,
  formatPercent,
  parseDecimal,
} from "@/features/finance/utils/formatters";
import { getPoultryBatches } from "@/features/poultry/api/batches";

type PageProps = {
  searchParams: Promise<{
    batch?: string | string[];
  }>;
};

export default async function FinanceBatchAnalysisPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const rawSelections = query.batch
    ? Array.isArray(query.batch)
      ? query.batch
      : [query.batch]
    : [];
  const returnToParams = new URLSearchParams();
  rawSelections.forEach((value) => returnToParams.append("batch", value));
  const returnTo = returnToParams.size
    ? `/finance/batches?${returnToParams.toString()}`
    : "/finance/batches";

  const batches = await getPoultryBatches(returnTo);
  const availableIds = new Set(batches.map((batch) => batch.id));
  const parsedSelections = rawSelections.map((value) => Number(value));
  const malformedSelections = rawSelections.filter(
    (_, index) =>
      !Number.isInteger(parsedSelections[index]) || parsedSelections[index] <= 0
  );
  const unknownSelections = parsedSelections.filter(
    (batchId) => Number.isInteger(batchId) && batchId > 0 && !availableIds.has(batchId)
  );
  const selectedBatchIds = [
    ...new Set(
      parsedSelections.filter(
        (batchId) => Number.isInteger(batchId) && batchId > 0 && availableIds.has(batchId)
      )
    ),
  ];
  const selectionIsValid =
    malformedSelections.length === 0 &&
    unknownSelections.length === 0 &&
    selectedBatchIds.length <= MAX_BATCH_SELECTION;
  const report =
    selectionIsValid && selectedBatchIds.length
      ? await getBatchPortfolioReport(selectedBatchIds, returnTo)
      : null;

  return (
    <FinancePageShell
      eyebrow="Finance / Poultry"
      title="Batch performance analysis."
      detail="Review one flock or combine selected flocks with the same complete production, overhead, asset, finance, and tax cost basis."
      actions={<FinanceNav />}
    >
      <Panel title="Choose Poultry Batches">
        <BatchSelectionFilter
          key={selectedBatchIds.join("-")}
          batches={batches}
          selectedBatchIds={selectedBatchIds}
        />
        {!selectionIsValid ? (
          <p className="mt-4 rounded-lg border border-[var(--danger)]/30 bg-white/70 px-4 py-3 text-sm font-semibold text-[var(--danger)]">
            {selectedBatchIds.length > MAX_BATCH_SELECTION
              ? `Choose no more than ${MAX_BATCH_SELECTION} batches at a time.`
              : "The URL contains an invalid or unavailable batch. Choose batches from the list and apply the filter again."}
          </p>
        ) : null}
      </Panel>

      {report ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <MetricCard
              label="Selected batches"
              value={formatNumber(report.selected_batch_count)}
              detail={`${report.included_batch_count} included · ${formatLabel(report.profitability_status)} basis`}
            />
            <MetricCard label="Revenue" value={formatCurrency(report.summary.revenue)} />
            <MetricCard
              label="Full attributed cost"
              value={formatCurrency(report.summary.total_attributed_cost)}
            />
            <MetricCard
              label="Net position"
              value={formatCurrency(report.summary.management_net_position)}
              detail={`${formatPercent(report.summary.management_net_margin_percent)} net margin`}
            />
            <MetricCard
              label="Receivables"
              value={formatCurrency(report.summary.accounts_receivable)}
              detail={`${formatPercent(report.summary.collection_rate_percent)} collected`}
            />
          </div>

          <Panel title="Poultry Business Insights">
            <div className="grid gap-4 lg:grid-cols-2">
              <FinanceBarChart
                title="Revenue To Net Position"
                detail="The complete management bridge uses the same cost basis as each individual batch finance page."
                points={[
                  {
                    label: "Revenue",
                    value: parseDecimal(report.summary.revenue),
                    displayValue: formatCurrency(report.summary.revenue),
                    tone: "gold",
                  },
                  {
                    label: "Direct batch cost",
                    value: parseDecimal(report.summary.direct_batch_cost),
                    displayValue: formatCurrency(report.summary.direct_batch_cost),
                    tone: "muted",
                  },
                  {
                    label: "Allocated production",
                    value: parseDecimal(report.summary.allocated_production_cost),
                    displayValue: formatCurrency(report.summary.allocated_production_cost),
                    tone: "navy",
                  },
                  {
                    label: "Selling and distribution",
                    value: parseDecimal(report.summary.total_selling_cost),
                    displayValue: formatCurrency(report.summary.total_selling_cost),
                    tone: "muted",
                  },
                  {
                    label: "Administration",
                    value: parseDecimal(report.summary.allocated_administration_cost),
                    displayValue: formatCurrency(report.summary.allocated_administration_cost),
                    tone: "muted",
                  },
                  {
                    label: "Net position",
                    value: parseDecimal(report.summary.management_net_position),
                    displayValue: formatCurrency(report.summary.management_net_position),
                    tone: parseDecimal(report.summary.management_net_position) < 0 ? "danger" : "green",
                  },
                ]}
              />
              <FinanceBarChart
                title="Net Position By Batch"
                detail="Up to ten selected batches are ranked after all attributed costs."
                points={[...report.results]
                  .filter((batch) => batch.included_in_portfolio_summary)
                  .sort(
                    (left, right) =>
                      parseDecimal(right.management_net_position) -
                      parseDecimal(left.management_net_position)
                  )
                  .slice(0, 10)
                  .map((batch) => ({
                    label: batch.batch_id,
                    value: parseDecimal(batch.management_net_position),
                    displayValue: formatCurrency(batch.management_net_position),
                    tone: (parseDecimal(batch.management_net_position) < 0 ? "danger" : "green") as "danger" | "green",
                  }))}
              />
            </div>
          </Panel>

          <Panel title="Combined Cost Breakdown">
            <ReportRows
              rows={[
                ...report.summary.management_cost_breakdown.map((line) => [
                  line.label,
                  formatCurrency(line.amount),
                ] as [string, string]),
                ["Total attributed cost", formatCurrency(report.summary.total_attributed_cost)],
                ["Net position", formatCurrency(report.summary.management_net_position)],
                ["Forecast revenue at completion", formatCurrency(report.summary.forecast_revenue_at_completion)],
                ["Forecast cost at completion", formatCurrency(report.summary.forecast_cost_at_completion)],
                ["Forecast final profit", formatCurrency(report.summary.forecast_final_profit)],
              ]}
            />
            <p className="mt-4 text-xs leading-5 text-[var(--navy-muted)]">
              Administration uses bird-day share. Selling, finance costs, and tax use
              period revenue share. Asset purchase prices and owner withdrawals are excluded;
              applicable asset depreciation is included.
            </p>
            <p className="mt-2 text-xs leading-5 text-[var(--navy-muted)]">
              Linked salary expenditures provide payment history only. Their payroll
              allocation is recognized once and split between production, selling, and
              administration.
            </p>
          </Panel>

          <div className="grid gap-6 lg:grid-cols-2">
            <Panel title="Combined Flock Economics">
              <ReportRows
                rows={[
                  ["Birds placed", formatNumber(report.summary.birds_placed)],
                  ["Bird units sold", formatNumber(report.summary.valid_bird_units_sold)],
                  ["Remaining live birds", formatNumber(report.summary.remaining_live_birds)],
                  ["Mortality", formatNumber(report.summary.mortality)],
                  ["Mortality rate", formatPercent(report.summary.mortality_rate_percent)],
                  [
                    "Production cost / saleable bird",
                    formatCurrency(report.summary.production_cost_per_saleable_bird),
                  ],
                  ["Gross profit / bird sold", formatCurrency(report.summary.profit_per_bird_sold)],
                  [
                    "Revenue needed for contribution break-even",
                    formatCurrency(report.summary.additional_revenue_required_to_break_even),
                  ],
                ]}
              />
            </Panel>
            <Panel title="Report Basis And Warnings">
              <FinanceWarningList warnings={report.warnings} />
            </Panel>
          </div>

          <Panel title="Selected Batch Comparison">
            <div className="max-h-[36rem] overflow-auto">
              <table className="min-w-[1050px] border-collapse text-sm">
                <thead className="sticky top-0 bg-[var(--surface-cream)] text-left text-[var(--navy-muted)]">
                  <tr className="border-b border-[var(--line)]">
                    <th className="py-3 pr-4">Batch</th>
                    <th className="py-3 pr-4">Basis</th>
                    <th className="py-3 pr-4 text-right">Birds</th>
                    <th className="py-3 pr-4 text-right">Mortality</th>
                    <th className="py-3 pr-4 text-right">Revenue</th>
                    <th className="py-3 pr-4 text-right">Production cost</th>
                    <th className="py-3 pr-4 text-right">Full cost</th>
                    <th className="py-3 pr-4 text-right">Net position</th>
                    <th className="py-3 pr-4 text-right">Receivables</th>
                    <th className="py-3 text-right">Details</th>
                  </tr>
                </thead>
                <tbody>
                  {report.results.map((batch) => (
                    <tr key={batch.batch} className="border-b border-[var(--line)]">
                      <td className="py-4 pr-4 font-extrabold text-[var(--navy)]">
                        {batch.batch_id}
                      </td>
                      <td className="py-4 pr-4 capitalize">
                        {formatLabel(batch.profitability_status)}
                        {!batch.included_in_portfolio_summary ? " · excluded" : ""}
                      </td>
                      <td className="py-4 pr-4 text-right">{formatNumber(batch.birds_placed)}</td>
                      <td className="py-4 pr-4 text-right">
                        {formatPercent(batch.mortality_rate_percent)}
                      </td>
                      <td className="py-4 pr-4 text-right">{formatCurrency(batch.revenue)}</td>
                      <td className="py-4 pr-4 text-right">
                        {formatCurrency(batch.total_production_cost)}
                      </td>
                      <td className="py-4 pr-4 text-right font-bold">
                        {formatCurrency(batch.total_attributed_cost)}
                      </td>
                      <td className="py-4 pr-4 text-right">
                        {formatCurrency(batch.management_net_position)}
                      </td>
                      <td className="py-4 pr-4 text-right">
                        {formatCurrency(batch.accounts_receivable)}
                      </td>
                      <td className="py-4 text-right">
                        <Link
                          href={`/finance/batches/${batch.batch}`}
                          className="font-extrabold text-[var(--navy)] underline decoration-[var(--gold)] decoration-2 underline-offset-4"
                        >
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      ) : (
        <EmptyState message="Select one batch for a focused lifecycle result, or select several batches to compare and combine their performance." />
      )}
    </FinancePageShell>
  );
}

function ReportRows({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="grid gap-3">
      {rows.map(([label, value]) => (
        <div
          key={label}
          className="flex items-center justify-between gap-4 border-b border-[var(--line)] py-2"
        >
          <dt className="text-sm text-[var(--navy-muted)]">{label}</dt>
          <dd className="text-right text-sm font-extrabold text-[var(--navy)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
