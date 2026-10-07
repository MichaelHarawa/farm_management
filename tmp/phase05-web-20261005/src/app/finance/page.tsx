import Link from "next/link";

import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { PaginatedTableBody } from "@/components/ui/PaginatedTableBody";
import { getFinanceDashboard } from "@/features/finance/api/finance";
import { BatchAnalysisFilter } from "@/features/finance/components/BatchAnalysisFilter";
import { FinanceWarningList } from "@/features/finance/components/FinanceWarningList";
import { SalesTrendByAgeChart } from "@/features/finance/components/SalesTrendByAgeChart";
import { EmptyState, FinanceNav, FinancePageShell, MetricCard, Panel } from "@/features/finance/components/FinanceUI";
import type { FinanceDashboard } from "@/features/finance/types";
import { formatCurrency, formatLabel, parseDecimal } from "@/features/finance/utils/formatters";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function selectedValues(value: string | string[] | undefined) {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
}

export default async function FinanceDashboardPage({ searchParams }: { searchParams: SearchParams }) {
  const requested = await searchParams;
  const period = typeof requested.period === "string" ? requested.period : "";
  const selectedBatches = selectedValues(requested.batch);
  const params = new URLSearchParams();
  if (period) params.set("period", period);
  selectedBatches.forEach((batch) => params.append("batch", batch));
  const query = params.size ? `?${params.toString()}` : "";
  const dashboard = await getFinanceDashboard(`/finance${query}`, query);
  const analysis = dashboard.batch_analysis;
  const summary = analysis.portfolio.summary;
  const overview = dashboard.overview;

  return (
    <FinancePageShell
      eyebrow="Finance / Batch Performance"
      title="Batch performance."
      detail="Compare flock losses, costs, profit, funding, sales pace, and the minimum selling price for one batch, several batches, or the whole farm."
      actions={<FinanceNav />}
    >
      <Panel title="Choose batches">
        <BatchAnalysisFilter
          periods={dashboard.available_periods}
          batches={analysis.available_batches}
          selectedPeriod={period || (overview ? String(overview.period_id) : "")}
          selectedIds={selectedBatches.map(Number).filter(Number.isFinite)}
        />
      </Panel>

      {!analysis.portfolio.included_batch_count ? <EmptyState message="No production batches match this selection." /> : <>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Total mortality" value={String(summary.mortality)} tone={summary.mortality > 0 ? "warning" : "default"} detail={`${summary.mortality_rate_percent ?? "N/A"}% of birds placed`} />
          <MetricCard label="Total costs" value={formatCurrency(summary.total_attributed_cost)} detail="Production, selling, administration, finance, and tax" />
          <MetricCard label="Gross profit" value={formatCurrency(summary.batch_gross_profit)} tone={parseDecimal(summary.batch_gross_profit) < 0 ? "danger" : "positive"} detail="Sales less direct and allocated production costs" />
          <MetricCard label="Net profit" value={formatCurrency(summary.management_net_position)} tone={parseDecimal(summary.management_net_position) < 0 ? "danger" : "positive"} detail="After selling costs, salaries, administration, finance costs, and recorded tax" />
        </div>

        <section className="grid gap-5 xl:grid-cols-2">
          <Panel title="Where money used by these batches came from">
            <FundingPie mix={analysis.funding_mix} />
          </Panel>
          <Panel title="Sales trend by flock age">
            <SalesTrendByAgeChart rows={analysis.sales_trend} />
            <p className="mt-3 text-xs leading-5 text-[var(--navy-muted)]">{analysis.sales_trend_basis}</p>
          </Panel>
        </section>

        <Panel title="Performance by batch">
          <MobileRecordList
            desktopBreakpoint="xl"
            pageSize={10}
            emptyMessage="No batch performance records are available."
            records={analysis.portfolio.results.map((row) => ({
              key: row.batch,
              title: <Link className="underline" href={`/finance/batches/${row.batch}`}>{row.batch_id}</Link>,
              subtitle: formatLabel(row.profitability_status),
              badge: <span className={`rounded-full px-2 py-1 text-xs font-bold ${parseDecimal(row.management_net_position) < 0 ? "bg-red-50 text-[var(--danger)]" : "bg-green-50 text-green-800"}`}>{formatCurrency(row.management_net_position)}</span>,
              fields: [
                { label: "Mortality", value: `${row.mortality} · ${row.mortality_rate_percent ?? "N/A"}%` },
                { label: "Production cost", value: formatCurrency(row.total_production_cost) },
                { label: "Cost to sell", value: formatCurrency(row.total_selling_cost) },
                { label: "Gross profit", value: formatCurrency(row.batch_gross_profit) },
                { label: "Break-even / bird", value: row.break_even_price_per_bird_all_costs === null ? "N/A" : formatCurrency(row.break_even_price_per_bird_all_costs) },
                { label: "Remaining-bird price", value: row.break_even_selling_price_per_remaining_bird === null ? "N/A" : formatCurrency(row.break_even_selling_price_per_remaining_bird) },
              ],
            }))}
          />
          <div className="hidden overflow-x-auto xl:block">
            <table className="w-full min-w-[1120px] text-left text-sm">
              <thead><tr className="border-b"><th className="p-3">Batch</th><th className="p-3 text-right">Mortality</th><th className="p-3 text-right">Production cost</th><th className="p-3 text-right">Cost to sell</th><th className="p-3 text-right">Gross profit</th><th className="p-3 text-right">Net profit</th><th className="p-3 text-right">Break-even / bird</th><th className="p-3 text-right">Remaining-bird price needed</th></tr></thead>
              <PaginatedTableBody columnCount={8} itemLabel="batch results">{analysis.portfolio.results.map((row) => <tr key={row.batch} className="border-b">
                <td className="p-3"><Link className="font-bold underline" href={`/finance/batches/${row.batch}`}>{row.batch_id}</Link><span className="block text-xs text-[var(--navy-muted)]">{formatLabel(row.profitability_status)}</span></td>
                <td className="p-3 text-right">{row.mortality} <span className="block text-xs text-[var(--navy-muted)]">{row.mortality_rate_percent ?? "N/A"}%</span></td>
                <td className="p-3 text-right">{formatCurrency(row.total_production_cost)}</td>
                <td className="p-3 text-right">{formatCurrency(row.total_selling_cost)}</td>
                <td className="p-3 text-right font-bold">{formatCurrency(row.batch_gross_profit)}</td>
                <td className="p-3 text-right font-bold">{formatCurrency(row.management_net_position)}</td>
                <td className="p-3 text-right">{row.break_even_price_per_bird_all_costs === null ? "N/A" : formatCurrency(row.break_even_price_per_bird_all_costs)}</td>
                <td className="p-3 text-right">{row.break_even_selling_price_per_remaining_bird === null ? "N/A" : formatCurrency(row.break_even_selling_price_per_remaining_bird)}</td>
              </tr>)}</PaginatedTableBody>
            </table>
          </div>
          <p className="mt-4 rounded-lg bg-[var(--gold-soft)] p-4 text-sm leading-6"><strong>Pricing guide:</strong> the fully loaded break-even estimate is {summary.break_even_price_per_bird_all_costs === null ? "unavailable until a survivor denominator exists" : `${formatCurrency(summary.break_even_price_per_bird_all_costs)} per survived bird`}. The price needed on remaining birds is {summary.break_even_selling_price_per_remaining_bird === null ? "not applicable" : formatCurrency(summary.break_even_selling_price_per_remaining_bird)} based on costs already incurred and revenue already recorded.</p>
        </Panel>
      </>}

      {overview ? <details className="rounded-lg border border-[var(--line)] bg-white/55 p-4 text-sm">
        <summary className="cursor-pointer font-bold">Whole-farm cash and period obligations</summary>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <CompactFigure label="Cash available" value={overview.cash_available} />
          <CompactFigure label="Customers owe" value={overview.customers_owe} />
          <CompactFigure label="Unpaid bills and wages" value={overview.unpaid_bills_and_wages} />
          <CompactFigure label="Cash shortfall" value={overview.cash_needed_for_payments_due} />
        </div>
        <Link href="/finance/monthly" className="mt-4 inline-block font-bold underline">Open full period report</Link>
      </details> : null}

      {dashboard.warnings.length ? <Panel title={`Warnings (${dashboard.warnings.length})`}><FinanceWarningList warnings={dashboard.warnings} /></Panel> : null}
    </FinancePageShell>
  );
}

const chartColors = ["#151f36", "#d9a52e", "#4e8b61", "#b24a43", "#6f5da8", "#3f7c91"];

function formatCompactCurrency(value: number) {
  return `MWK ${new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value)}`;
}

function FundingPie({ mix }: { mix: FinanceDashboard["batch_analysis"]["funding_mix"] }) {
  const total = parseDecimal(mix.total_batch_expenditure);
  const visible = mix.groups
    .map((row, colorIndex) => ({ row, colorIndex }))
    .filter(({ row }) => parseDecimal(row.amount) > 0);
  const gradient = visible.map(({ row, colorIndex }, index) => {
    const priorAmount = visible
      .slice(0, index)
      .reduce((sum, item) => sum + parseDecimal(item.row.amount), 0);
    const start = total ? (priorAmount / total) * 360 : 0;
    const end = total ? ((priorAmount + parseDecimal(row.amount)) / total) * 360 : 0;
    return `${chartColors[colorIndex % chartColors.length]} ${start}deg ${end}deg`;
  }).join(", ");
  return <div className="grid min-w-0 gap-5 sm:grid-cols-[200px_minmax(0,1fr)] sm:items-center">
    <div className="grid min-w-0 gap-3">
      <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--line)] bg-white/70 px-4 py-3 sm:hidden">
        <span className="text-xs font-bold uppercase tracking-wide text-[var(--navy-muted)]">Total costs</span>
        <strong className="whitespace-nowrap text-base text-[var(--navy)]" title={formatCurrency(total)}>
          {formatCompactCurrency(total)}
        </strong>
      </div>
      <div
        className="mx-auto grid aspect-square w-40 place-items-center rounded-full sm:w-48"
        style={{ background: gradient ? `conic-gradient(${gradient})` : "#e7e4d9" }}
        role="img"
        aria-label={`Funding mix for total batch costs of ${formatCurrency(total)}`}
      >
        <div className="grid aspect-square w-[5.75rem] place-items-center rounded-full bg-white sm:w-28 sm:px-2 sm:text-center" title={`Total batch costs: ${formatCurrency(total)}`}>
          <span className="hidden text-[0.65rem] font-bold uppercase tracking-wide text-[var(--navy-muted)] sm:block">
            Total costs
            <strong className="mt-1 block whitespace-nowrap text-base leading-none tracking-tight text-[var(--navy)]">
              {formatCompactCurrency(total)}
            </strong>
          </span>
        </div>
      </div>
    </div>
    <div className="grid min-w-0 gap-3">{mix.groups.map((row, index) => <div key={row.key} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-3"><span className="flex min-w-0 items-start gap-2"><i className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: chartColors[index % chartColors.length] }} /><span className="min-w-0"><strong className="block break-words text-sm sm:text-base">{row.label}</strong><span className="text-xs text-[var(--navy-muted)]">{row.percent ?? "0.00"}%</span></span></span><strong className="whitespace-nowrap text-right text-sm" title={formatCurrency(row.amount)}><span className="sm:hidden">{formatCompactCurrency(parseDecimal(row.amount))}</span><span className="hidden sm:inline">{formatCurrency(row.amount)}</span></strong></div>)}</div>
    <p className="text-xs leading-5 text-[var(--navy-muted)] sm:col-span-2">{mix.basis}</p>
  </div>;
}

function CompactFigure({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-[var(--surface-cream)] p-3"><p className="text-xs font-bold text-[var(--navy-muted)]">{label}</p><p className="mt-2 font-extrabold">{formatCurrency(value)}</p></div>;
}
