import { notFound } from "next/navigation";

import { getBatchProfitability } from "@/features/finance/api/finance";
import {
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  formatNumber,
  formatPercent,
} from "@/features/finance/utils/formatters";
import type { BatchProfitabilityReport } from "@/features/finance/types";
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
  try {
    report = await getBatchProfitability(batchId, `/finance/batches/${batchId}`);
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
      detail="Revenue, cash collected, receivables, production cost, bird balance, and provisional or final profit."
      actions={<FinanceNav />}
    >
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label="Revenue" value={formatCurrency(report.revenue)} />
        <MetricCard label="Gross profit" value={formatCurrency(report.batch_gross_profit)} />
        <MetricCard label="Remaining birds" value={formatNumber(report.remaining_live_birds)} />
        <MetricCard label="Status" value={report.profitability_status.toUpperCase()} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Production Profit">
          <Rows
            rows={[
              ["Direct batch cost", formatCurrency(report.direct_batch_cost)],
              ["Allocated production", formatCurrency(report.allocated_production_cost)],
              ["Total production cost", formatCurrency(report.total_production_cost)],
              ["Gross margin", formatPercent(report.batch_gross_margin_percent)],
              ["Profit per bird sold", formatCurrency(report.profit_per_bird_sold)],
            ]}
          />
        </Panel>
        <Panel title="Collections And BI">
          <Rows
            rows={[
              ["Cash collected", formatCurrency(report.cash_collected)],
              ["Receivables", formatCurrency(report.accounts_receivable)],
              ["Collection rate", formatPercent(report.collection_rate_percent)],
              ["Break-even remaining bird", formatCurrency(report.break_even_selling_price_per_remaining_bird)],
              ["Revenue needed", formatCurrency(report.additional_revenue_required_to_break_even)],
            ]}
          />
        </Panel>
      </div>
    </FinancePageShell>
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
