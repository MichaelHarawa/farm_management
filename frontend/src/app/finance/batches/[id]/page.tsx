import Link from "next/link";
import { notFound } from "next/navigation";

import { getBatchProfitability, getBatchRevenueUtilization } from "@/features/finance/api/finance";
import {
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  formatLabel,
  formatPercent,
} from "@/features/finance/utils/formatters";
import type { BatchProfitabilityReport, BatchRevenueUtilization } from "@/features/finance/types";
import { BackendApiError } from "@/lib/server/backend-api";

type PageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function FinanceBatchProfitabilityPage({ params }: PageProps) {
  const { id } = await params;
  const batchId = Number(id);

  if (!Number.isInteger(batchId) || batchId <= 0) {
    notFound();
  }

  let report: BatchProfitabilityReport;
  let utilization: BatchRevenueUtilization | null = null;
  try {
    report = await getBatchProfitability(batchId, `/finance/batches/${batchId}`);
    utilization = await getBatchRevenueUtilization(batchId, `/finance/batches/${batchId}`).catch(() => null);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  return (
    <FinancePageShell
      eyebrow={`Finance / Batch ${report.batch_id}`}
      title="Batch profitability."
      detail="A complete batch result including production, selling, administration, finance, tax, cash collection, and receivables."
      actions={<FinanceNav />}
    >
      <div className="flex justify-end">
        <Link
          href={`/finance/batches?batch=${report.batch}`}
          className="finance-button"
        >
          Compare with other batches
        </Link>
      </div>
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Revenue" value={formatCurrency(report.revenue)} />
        <MetricCard label="Full attributed cost" value={formatCurrency(report.total_attributed_cost)} />
        <MetricCard label="Net position" value={formatCurrency(report.management_net_position)} />
        <MetricCard label="Status" value={formatLabel(report.profitability_status)} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Production Result">
          <Rows
            rows={[
              ["Direct batch cost", formatCurrency(report.direct_batch_cost)],
              ["Allocated production", formatCurrency(report.allocated_production_cost)],
              ["Total production cost", formatCurrency(report.total_production_cost)],
              ["Production gross profit", formatCurrency(report.batch_gross_profit)],
              ["Gross margin", formatPercent(report.batch_gross_margin_percent)],
              ["Profit per bird sold", formatCurrency(report.profit_per_bird_sold)],
            ]}
          />
        </Panel>
        <Panel title="Full Net Position">
          <Rows
            rows={[
              ["Revenue", formatCurrency(report.revenue)],
              ["Less: production cost", formatCurrency(report.total_production_cost)],
              ["Less: selling and distribution", formatCurrency(report.total_selling_cost)],
              ["Less: farm administration", formatCurrency(report.allocated_administration_cost)],
              ["Less: finance costs", formatCurrency(report.allocated_finance_cost)],
              ["Less: tax", formatCurrency(report.allocated_tax)],
              ["Total attributed cost", formatCurrency(report.total_attributed_cost)],
              ["Net position", formatCurrency(report.management_net_position)],
              ["Net margin", formatPercent(report.management_net_margin_percent)],
            ]}
          />
          <p className="mt-4 text-xs leading-5 text-[var(--navy-muted)]">
            Production follows its stored allocation drivers. Administration uses
            bird-days; selling, finance costs, and tax use revenue share (falling back
            to bird-days where a period has no sales).
          </p>
        </Panel>
        <Panel title="Collections And BI">
          <Rows
            rows={[
              ["Cash collected", formatCurrency(report.cash_collected)],
              ["Receivables", formatCurrency(report.accounts_receivable)],
              ["Collection rate", formatPercent(report.collection_rate_percent)],
              ["Contribution break-even per remaining bird", formatCurrency(report.break_even_selling_price_per_remaining_bird)],
              ["Revenue needed for contribution break-even", formatCurrency(report.additional_revenue_required_to_break_even)],
            ]}
          />
        </Panel>

        <Panel title="Batch Cash Position (Revenue Utilization)">
          <Rows
            rows={[
              ["Cash collected from this batch", formatCurrency(report.cash_collected)],
              ["Cash used (funding allocations)", formatCurrency(report.cash_used_from_batch ?? utilization?.cash_used ?? "0")],
              ["Available cash from this batch", formatCurrency(report.available_batch_cash ?? utilization?.available_cash ?? report.cash_collected)],
            ]}
          />
          {utilization && (
            <div className="mt-3 text-xs">
              <div>By category: {Object.keys(utilization.by_category || {}).join(", ") || "—"}</div>
            </div>
          )}
          <p className="mt-3 text-xs text-[var(--navy-muted)]">
            This shows how much of the money collected from this batch&apos;s sales is still available.
            It is separate from accounting profit.
          </p>
        </Panel>

        <Panel title="Actual-To-Date And Forecast">
          <Rows rows={[
            ["Actual management net position", formatCurrency(report.management_net_position)],
            ["Forecast revenue at completion", formatCurrency(report.forecast_revenue_at_completion)],
            ["Forecast cost at completion", formatCurrency(report.forecast_cost_at_completion)],
            ["Forecast final profit", formatCurrency(report.forecast_final_profit)],
          ]} />
          <p className="mt-3 text-xs leading-5 text-[var(--navy-muted)]">
            {report.result_interpretation} {report.forecast_basis}
          </p>
        </Panel>
      </div>

      <Panel title="Complete Cost Breakdown">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead>
              <tr className="border-b border-[var(--line)] text-xs uppercase tracking-[0.12em] text-[var(--navy-muted)]">
                <th className="py-3 pr-5">Cost layer</th>
                <th className="py-3 pr-5">Allocation basis</th>
                <th className="py-3 text-right">Amount</th>
              </tr>
            </thead>
            <tbody>
              {report.management_cost_breakdown.map((line) => (
                <CostLine key={line.key} line={line} />
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-5 text-xs leading-5 text-[var(--navy-muted)]">
          Capital purchases, loan principal, owner withdrawals, and internal cash
          transfers are excluded from profit. Asset depreciation is included instead
          of the original capital purchase.
        </p>
        <p className="mt-2 text-xs leading-5 text-[var(--navy-muted)]">
          Salary expenditures are payment records for their linked payroll entries.
          Production, selling, and administration show mutually exclusive portions of
          that payroll cost—the expenditure amount is not added again.
        </p>
      </Panel>
      {report.allocation_trace.length ? (
        <Panel title="Allocation Driver Audit Trail">
          <div className="overflow-x-auto">
            <table className="min-w-[900px] text-left text-sm">
              <thead><tr className="border-b border-[var(--line)] text-[var(--navy-muted)]">
                <th className="py-3 pr-4">Source period</th><th className="py-3 pr-4">Admin driver</th>
                <th className="py-3 pr-4 text-right">Numerator / denominator</th><th className="py-3 pr-4 text-right">Admin share</th>
                <th className="py-3 pr-4">Selling / finance / tax driver</th><th className="py-3 text-right">Share</th>
              </tr></thead>
              <tbody>{report.allocation_trace.map((trace) => (
                <tr key={trace.source_period} className="border-b border-[var(--line)]">
                  <td className="py-3 pr-4">{trace.period_start} – {trace.period_end}</td>
                  <td className="py-3 pr-4">{formatLabel(trace.administration_driver)}</td>
                  <td className="py-3 pr-4 text-right">{trace.administration_numerator} / {trace.administration_denominator}</td>
                  <td className="py-3 pr-4 text-right">{formatPercent(trace.administration_percentage)}</td>
                  <td className="py-3 pr-4">{formatLabel(trace.selling_finance_tax_driver)}</td>
                  <td className="py-3 text-right">{formatPercent(trace.selling_percentage)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      ) : null}
    </FinancePageShell>
  );
}

function CostLine({ line }: { line: BatchProfitabilityReport["management_cost_breakdown"][number] }) {
  return (
    <>
      <tr className="border-b border-[var(--line)]">
        <th className="py-4 pr-5 font-extrabold text-[var(--navy)]">{line.label}</th>
        <td className="py-4 pr-5 text-[var(--navy-muted)]">{line.basis}</td>
        <td className="py-4 text-right font-extrabold text-[var(--navy)]">
          {formatCurrency(line.amount)}
        </td>
      </tr>
      {line.components?.filter((component) => Number(component.amount) !== 0).map((component) => (
        <tr key={`${line.key}-${component.label}`} className="border-b border-[var(--line)]/60 bg-black/[0.015]">
          <td className="py-2.5 pl-5 pr-5 text-[var(--navy-muted)]">{component.label}</td>
          <td className="py-2.5 pr-5 text-xs text-[var(--navy-muted)]">Included above</td>
          <td className="py-2.5 text-right font-bold text-[var(--navy-muted)]">
            {formatCurrency(component.amount)}
          </td>
        </tr>
      ))}
    </>
  );
}

function Rows({ rows }: { rows: Array<[string, string]> }) {
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
