"use client";

import { Activity, Banknote, Bird, RefreshCw, Wheat } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { PaginatedTableBody } from "@/components/ui/PaginatedTableBody";
import type { PoultryDashboardBatch, PoultryDashboardResponse } from "@/features/poultry/types";
import { formatCurrency, formatDate, formatLabel, formatNumber, formatPercent, parseDecimal } from "@/features/finance/utils/formatters";

type Props = { dashboard: PoultryDashboardResponse };
type NumericRow = { date: string } & Record<string, string | number>;
type SeriesDefinition = { key: string; label: string; color: string };

const COLORS = {
  navy: "#172443",
  gold: "#d4a642",
  green: "#4e8b61",
  red: "#b4533a",
  muted: "#8b8272",
};

export default function PoultryDashboardClient({ dashboard }: Props) {
  const router = useRouter();
  const [dateFrom, setDateFrom] = useState(dashboard.filters.date_from);
  const [dateTo, setDateTo] = useState(dashboard.filters.date_to);
  const [batch, setBatch] = useState(
    dashboard.filters.batch_ids.length === 1 ? String(dashboard.filters.batch_ids[0]) : "all"
  );
  const [birdType, setBirdType] = useState(dashboard.filters.bird_type);
  const [stage, setStage] = useState(dashboard.filters.stage);
  const [feedStage, setFeedStage] = useState(dashboard.filters.feed_stage);

  const birdTypes = useMemo(
    () => [...new Set(dashboard.available_batches.map((row) => row.bird_type))].sort(),
    [dashboard.available_batches]
  );
  const stages = useMemo(
    () => [...new Set(dashboard.available_batches.map((row) => row.status))].sort(),
    [dashboard.available_batches]
  );

  function applyFilters(event: React.FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams({
      date_from: dateFrom,
      date_to: dateTo,
      bird_type: birdType,
      stage,
      feed_stage: feedStage,
    });
    if (batch !== "all") params.set("batch", batch);
    router.push("/poultry/dashboard?" + params.toString());
  }

  const overview = dashboard.overview;
  const growthText = dashboard.sales_growth.message ||
    (parseDecimal(dashboard.sales_growth.change_percent) >= 0 ? "+" : "") +
      formatPercent(dashboard.sales_growth.change_percent) +
      " vs preceding period";
  const recognizedCosts = dashboard.series.costs_and_profit.reduce(
    (sum, row) => sum + parseDecimal(row.recorded_costs),
    0,
  );
  const periodResult = dashboard.series.costs_and_profit.reduce(
    (sum, row) => sum + parseDecimal(row.actual_period_result),
    0,
  );
  const salesValue = parseDecimal(overview.sales);
  const cashCollections = parseDecimal(overview.cash_collections);
  const collectionRate = salesValue > 0 ? (cashCollections / salesValue) * 100 : 0;
  const resultMargin = salesValue > 0 ? (periodResult / salesValue) * 100 : 0;
  const performanceRows = consolidateFinancialSeries(dashboard.series.costs_and_profit);

  return (
    <div className="grid min-w-0 gap-5 sm:gap-6">
      <form onSubmit={applyFilters} className="min-w-0 rounded-xl border border-[var(--line)] bg-white/70 p-3.5 shadow-[var(--shadow-card)] sm:p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <InputFilter label="From" type="date" value={dateFrom} onChange={setDateFrom} />
          <InputFilter label="To" type="date" value={dateTo} onChange={setDateTo} />
          <SelectFilter label="Batch" value={batch} onChange={setBatch}>
            <option value="all">All matching batches</option>
            {dashboard.available_batches.map((row) => (
              <option key={row.id} value={row.id}>{row.batch_id}</option>
            ))}
          </SelectFilter>
          <SelectFilter label="Bird type" value={birdType} onChange={setBirdType}>
            <option value="all">All bird types</option>
            {birdTypes.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
          </SelectFilter>
          <SelectFilter label="Batch stage" value={stage} onChange={setStage}>
            <option value="production">In production</option>
            <option value="all">All stages</option>
            {stages.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
          </SelectFilter>
          <SelectFilter label="Feed stage" value={feedStage} onChange={setFeedStage}>
            <option value="all">All feed stages</option>
            {dashboard.available_feed_stages.map((value) => <option key={value} value={value}>{formatLabel(value)}</option>)}
          </SelectFilter>
        </div>
        <div className="mt-4 grid gap-3 border-t border-[var(--line)] pt-4 sm:flex sm:flex-wrap sm:items-center sm:justify-between">
          <p className="text-sm text-[var(--navy-muted)]">
            {dashboard.batches.length} batch{dashboard.batches.length === 1 ? "" : "es"} · {formatDate(dashboard.filters.date_from)}–{formatDate(dashboard.filters.date_to)}
          </p>
          <div className="grid grid-cols-2 gap-2 sm:flex">
            <button type="button" onClick={() => router.refresh()} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-[var(--line)] px-3 py-2 font-bold sm:px-4">
              <RefreshCw className="size-4" aria-hidden="true" /> Refresh
            </button>
            <button className="finance-button px-3 py-2 sm:px-5">Apply filters</button>
          </div>
        </div>
      </form>

      <section aria-label="Live business snapshot" className="grid gap-4 lg:grid-cols-2 xl:grid-cols-12">
        <ExecutiveMetric className="xl:col-span-4" icon={Activity} label="Period result" value={formatCurrency(periodResult)} detail={`${formatPercent(resultMargin)} margin · ${formatCurrency(recognizedCosts)} recognized costs`} tone={periodResult < 0 ? "negative" : "hero"} />
        <ExecutiveMetric className="xl:col-span-3" icon={Banknote} label="Sales and collection" value={formatCurrency(overview.sales)} detail={`${formatCurrency(overview.cash_collections)} collected · ${formatPercent(collectionRate)} collection rate · ${growthText}`} />
        <ExecutiveMetric className="xl:col-span-3" icon={Bird} label="Flock position" value={`${formatNumber(overview.current_birds)} live`} detail={`${formatNumber(overview.birds_sold)} sold · ${formatNumber(overview.deaths)} deaths · ${formatPercent(overview.mortality_rate_percent)} mortality`} />
        <ExecutiveMetric className="xl:col-span-2" icon={Wheat} label="Feed efficiency" value={`${formatNumber(overview.feed_issued_kg)} kg`} detail={`${overview.feed_per_bird_day_g ? `${formatNumber(overview.feed_per_bird_day_g)} g per bird-day` : "Rate unavailable"}${overview.latest_average_weight_g === null ? " · no recent weight" : ` · latest weight ${formatNumber(overview.latest_average_weight_g)} g`}`} />
      </section>

      <section>
        <LineChart
          title="Sales versus recognized cost"
          detail={`${performanceRows.length < dashboard.series.costs_and_profit.length ? "Weekly summary" : `${formatLabel(dashboard.series.bucket)} summary`} · use this to see whether revenue is keeping ahead of cost`}
          rows={performanceRows}
          series={[
            { key: "sales", label: "Sales", color: COLORS.green },
            { key: "recorded_costs", label: "Recognized costs", color: COLORS.gold },
          ]}
          valueLabel={formatCompactCurrency}
          exactLabel={formatCurrency}
          emptyMessage="No sales or recognized batch costs were recorded in this period."
          xLabel={(value) => value}
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-[1.4fr_0.6fr]">
        <CostBreakdown values={dashboard.cost_breakdown} />
        <details className="rounded-xl border border-[var(--line)] bg-white/70 p-5 shadow-[var(--shadow-card)]">
          <summary className="cursor-pointer text-lg font-extrabold">How these indicators are calculated</summary>
          <dl className="mt-4 grid gap-4 text-sm">
            <Note term="Current versus period">{dashboard.calculation_basis}</Note>
            <Note term="Feed conversion ratio">{overview.feed_conversion_note}</Note>
            <Note term="Sales growth">Compares {formatDate(dashboard.filters.date_from)}–{formatDate(dashboard.filters.date_to)} with {formatDate(dashboard.sales_growth.previous_period_start)}–{formatDate(dashboard.sales_growth.previous_period_end)}.</Note>
          </dl>
        </details>
      </section>

      <BatchComparison rows={dashboard.batches} />

      {dashboard.alerts.length ? (
        <section className="rounded-xl border border-red-200 bg-red-50/70 p-5">
          <h2 className="text-lg font-extrabold">Needs attention</h2>
          <div className="mt-3 grid gap-2">
            {dashboard.alerts.map((alert) => <Link key={alert.batch + alert.message} href={"/poultry/batches/" + alert.batch} className="rounded-lg bg-white/70 p-3 text-sm"><strong>{alert.batch_id}</strong> · {alert.message}</Link>)}
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 rounded-xl border border-[var(--line)] bg-[var(--navy)] p-5 text-white md:grid-cols-[1fr_auto] md:items-center">
        <div>
          <p className="font-bold">Last updated {new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(dashboard.generated_at))}</p>
          <p className="mt-1 text-sm text-white/65">Refresh to retrieve newly posted records. Missing observations are labelled unavailable rather than zero.</p>
        </div>
        <Link href="/poultry" className="rounded-lg bg-[var(--gold)] px-5 py-3 text-center font-bold text-[var(--navy)]">Open batch register</Link>
      </section>
    </div>
  );
}

function InputFilter({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (value: string) => void }) {
  return <label className="min-w-0 text-sm font-bold">{label}<input className="form-input mt-2 w-full bg-white" type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function SelectFilter({ label, value, onChange, children }: { label: string; value: string; onChange: (value: string) => void; children: React.ReactNode }) {
  return <label className="min-w-0 text-sm font-bold">{label}<select className="form-input mt-2 w-full bg-white" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select></label>;
}

function ExecutiveMetric({ icon: Icon, label, value, detail, tone = "default", className = "" }: { icon: typeof Activity; label: string; value: string; detail: string; tone?: "default" | "hero" | "negative"; className?: string }) {
  const emphasized = tone !== "default";
  const toneClass = tone === "negative"
    ? "border-[#9b473d] bg-[#7e352f] !text-white"
    : tone === "hero"
      ? "border-[var(--navy)] bg-[var(--navy)] !text-white"
      : "border-[var(--line)] bg-[var(--surface-cream)] text-[var(--navy)]";
  return <article className={`relative min-w-0 overflow-hidden rounded-2xl border p-4 shadow-[var(--shadow-card)] sm:p-5 ${toneClass} ${className}`}>
    <span className={`absolute inset-x-0 top-0 h-1 ${emphasized ? "bg-[var(--gold)]" : "bg-[var(--gold-soft)]"}`} />
    <div className="flex items-center gap-3">
      <span className={`grid size-10 shrink-0 place-items-center rounded-full ${emphasized ? "bg-white/12" : "bg-[var(--gold-soft)]"}`}><Icon className="size-5" aria-hidden="true" /></span>
      <p className={`text-label ${emphasized ? "!text-white/75" : "text-[var(--navy-muted)]"}`}>{label}</p>
    </div>
    <p className="font-display mt-5 break-words text-[clamp(1.5rem,2.2vw,2.35rem)] font-bold leading-none">{value}</p>
    <p className={`mt-4 text-sm leading-6 ${emphasized ? "!text-white/75" : "text-[var(--navy-muted)]"}`}>{detail}</p>
  </article>;
}

function LineChart({ title, detail, rows, series, valueLabel, exactLabel, emptyMessage, xLabel = formatDate }: {
  title: string;
  detail: string;
  rows: NumericRow[];
  series: SeriesDefinition[];
  valueLabel: (value: number) => string;
  exactLabel: (value: number) => string;
  emptyMessage: string;
  xLabel?: (value: string) => string;
}) {
  const values = rows.flatMap((row) => series.flatMap((item) => row[item.key] === undefined ? [] : [parseDecimal(row[item.key])]));
  const hasObservations = values.some((value) => value !== 0);
  const width = 720, height = 250, left = 72, right = 18, top = 18, bottom = 42;
  const min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (min === max) max = min + 1;
  const x = (index: number) => left + (rows.length <= 1 ? 0 : index * (width - left - right) / (rows.length - 1));
  const y = (value: number) => top + (max - value) * (height - top - bottom) / (max - min);
  const ticks = Array.from({ length: 5 }, (_, index) => max - index * (max - min) / 4);

  return <article className="min-w-0 rounded-xl border border-[var(--line)] bg-white/70 p-4 shadow-[var(--shadow-card)] sm:p-5">
    <h2 className="text-xl font-extrabold">{title}</h2><p className="mt-2 text-sm text-[var(--navy-muted)]">{detail}</p>
    {!hasObservations ? <Empty message={emptyMessage} /> : <>
      <div className="mt-4 flex flex-wrap gap-4 text-xs font-bold">{series.map((item) => <span key={item.key} className="flex items-center gap-2"><span className="size-2.5 rounded-full" style={{ background: item.color }} />{item.label}</span>)}</div>
      <div className="mt-2 min-w-0">
        <svg viewBox={"0 0 " + width + " " + height} className="h-auto w-full md:min-w-[620px]" role="img" aria-label={title}>
          {ticks.map((tick) => <g key={tick}><line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="#ded8ca" /><text x={left - 8} y={y(tick) + 4} textAnchor="end" fontSize="11" fill="#6b7280">{valueLabel(tick)}</text></g>)}
          {min < 0 && max > 0 ? <line x1={left} x2={width-right} y1={y(0)} y2={y(0)} stroke={COLORS.red} strokeWidth="1.5" /> : null}
          {series.map((item) => {
            const points = rows.flatMap((row, index) => row[item.key] === undefined ? [] : [x(index) + "," + y(parseDecimal(row[item.key]))]).join(" ");
            return <g key={item.key}><polyline points={points} fill="none" stroke={item.color} strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" />{rows.map((row, index) => row[item.key] === undefined ? null : <circle key={item.key + row.date} cx={x(index)} cy={y(parseDecimal(row[item.key]))} r="4" fill={item.color}><title>{xLabel(row.date)} · {item.label}: {exactLabel(parseDecimal(row[item.key]))}</title></circle>)}</g>;
          })}
          {rows.map((row, index) => (index === 0 || index === rows.length - 1 || index === Math.floor(rows.length / 2)) ? <text key={row.date} x={x(index)} y={height - 13} textAnchor={index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle"} fontSize="11" fill="#6b7280">{xLabel(row.date)}</text> : null)}
        </svg>
      </div>
    </>}
  </article>;
}

function CostBreakdown({ values }: { values: Record<string, string> }) {
  const rows = Object.entries(values).map(([label, value]) => [label, parseDecimal(value)] as const).filter(([, value]) => value !== 0).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const max = Math.max(0, ...rows.map(([, value]) => value));
  return <section className="min-w-0 rounded-xl border border-[var(--line)] bg-white/70 p-4 shadow-[var(--shadow-card)] sm:p-5"><h2 className="text-xl font-extrabold">Top cost drivers</h2><p className="mt-2 text-sm text-[var(--navy-muted)]">The five largest recognized costs for the selected batches and period.</p><div className="mt-5 grid gap-4">{rows.map(([label, value]) => <div key={label}><div className="grid gap-1 text-sm min-[420px]:grid-cols-[minmax(0,1fr)_auto] min-[420px]:items-end min-[420px]:gap-3"><span className="min-w-0 break-words">{formatLabel(label)}</span><strong className="break-words min-[420px]:whitespace-nowrap min-[420px]:text-right" title={formatCurrency(value)}>{formatCompactCurrency(value)}</strong></div><div className="mt-2 h-3 overflow-hidden rounded bg-[var(--surface-cream-soft)]"><div className="h-full rounded bg-[var(--gold)]" style={{ width: (max ? Math.max(value / max * 100, 2) : 0) + "%" }} /></div></div>)}{!rows.length ? <Empty message="No recognized batch costs were recorded in this period." /> : null}</div></section>;
}

function BatchComparison({ rows }: { rows: PoultryDashboardBatch[] }) {
  return <section className="overflow-hidden rounded-xl border border-[var(--line)] bg-white/70 shadow-[var(--shadow-card)]"><div className="p-4 sm:p-5"><h2 className="text-xl font-extrabold">Batch comparison</h2><p className="mt-2 text-sm text-[var(--navy-muted)]">Current flock balance alongside selected-period activity. Result is actual sales less recognized period costs, not a completion forecast.</p></div><MobileRecordList className="p-3 pt-0" emptyMessage="No batches match these filters." records={rows.map((row) => ({ key: row.id, title: row.batch_id, subtitle: `${formatLabel(row.status)} · day ${row.age_days}`, badge: <span className={`rounded-full px-2 py-1 text-xs font-bold ${parseDecimal(row.actual_period_result) < 0 ? "bg-red-50 text-[var(--danger)]" : "bg-green-50 text-green-800"}`}>{formatCurrency(row.actual_period_result)}</span>, fields: [{ label: "Current birds", value: formatNumber(row.current_live_birds) }, { label: "Birds sold", value: formatNumber(row.birds_sold_period) }, { label: "Sales", value: formatCurrency(row.sales_period) }, { label: "Recorded costs", value: formatCurrency(row.recorded_costs_period) }, { label: "Feed issued", value: `${formatNumber(row.feed_issued_period_kg)} kg` }, { label: "Mortality", value: formatNumber(row.mortality_period) }], actions: <Link href={"/poultry/batches/" + row.id} className="w-full rounded-lg bg-[var(--navy)] px-4 py-3 text-center font-bold !text-white">Open batch</Link> }))} /><div className="hidden overflow-x-auto md:block"><table className="min-w-[1100px] w-full text-sm"><thead className="bg-[var(--surface-cream-soft)] text-left"><tr>{["Batch / stage", "Current birds", "Birds sold", "Sales", "Recorded costs", "Feed issued", "Mortality", "Actual period result", "Analysis"].map((label) => <th key={label} className="p-3">{label}</th>)}</tr></thead><PaginatedTableBody columnCount={9} itemLabel="batch comparisons" emptyMessage="No batches match these filters.">{rows.map((row) => <tr key={row.id} className="border-t border-[var(--line)]"><td className="p-3"><strong>{row.batch_id}</strong><p className="text-xs text-[var(--navy-muted)]">{formatLabel(row.status)} · day {row.age_days}</p></td><td className="p-3">{formatNumber(row.current_live_birds)}</td><td className="p-3">{formatNumber(row.birds_sold_period)}</td><td className="p-3 whitespace-nowrap">{formatCurrency(row.sales_period)}</td><td className="p-3 whitespace-nowrap">{formatCurrency(row.recorded_costs_period)}</td><td className="p-3">{formatNumber(row.feed_issued_period_kg)} kg</td><td className="p-3">{formatNumber(row.mortality_period)}</td><td className={"p-3 whitespace-nowrap font-bold " + (parseDecimal(row.actual_period_result) < 0 ? "text-[var(--danger)]" : "text-[#315f3e]")}>{formatCurrency(row.actual_period_result)}</td><td className="p-3"><Link href={"/poultry/batches/" + row.id} className="font-bold underline">Open batch</Link></td></tr>)}</PaginatedTableBody></table></div></section>;
}

function Note({ term, children }: { term: string; children: React.ReactNode }) {
  return <div><dt className="font-bold text-[var(--navy)]">{term}</dt><dd className="mt-1 leading-6 text-[var(--navy-muted)]">{children}</dd></div>;
}

function Empty({ message }: { message: string }) {
  return <p className="mt-5 rounded-lg border border-dashed border-[var(--line)] p-5 text-sm text-[var(--navy-muted)]">{message}</p>;
}

function formatCompact(value: number) {
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatCompactCurrency(value: number) {
  return "MWK " + formatCompact(value);
}

function consolidateFinancialSeries(rows: PoultryDashboardResponse["series"]["costs_and_profit"]): NumericRow[] {
  if (rows.length <= 14) {
    return rows.map((row) => ({
      date: formatDate(row.date),
      sales: row.sales,
      recorded_costs: row.recorded_costs,
    }));
  }

  const groups: NumericRow[] = [];
  for (let index = 0; index < rows.length; index += 7) {
    const period = rows.slice(index, index + 7);
    const first = period[0];
    const last = period[period.length - 1];
    groups.push({
      date: first.date === last.date ? formatDate(first.date) : `${formatDate(first.date)}–${formatDate(last.date)}`,
      sales: period.reduce((sum, row) => sum + parseDecimal(row.sales), 0),
      recorded_costs: period.reduce((sum, row) => sum + parseDecimal(row.recorded_costs), 0),
    });
  }
  return groups;
}
