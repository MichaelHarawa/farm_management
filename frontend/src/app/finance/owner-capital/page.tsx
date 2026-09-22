import Link from "next/link";

import {
  getOwnerContributionReport,
  getOwnerContributors,
} from "@/features/finance/api/finance";
import {
  FinanceNav,
  FinancePageShell,
  MetricCard,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  OwnerCapitalActions,
  OwnerReceiptAction,
} from "@/features/finance/components/OwnerCapitalActions";
import { OwnerCapitalBatchFilter } from "@/features/finance/components/OwnerCapitalBatchFilter";
import {
  formatCurrency,
  formatDate,
  formatLabel,
} from "@/features/finance/utils/formatters";
import { getPoultryBatches } from "@/features/poultry/api/batches";

type Query = {
  owner?: string;
  batch?: string | string[];
  date_from?: string;
  date_to?: string;
  batch_page?: string;
  receipt_page?: string;
  timeline_page?: string;
};

type PageProps = { searchParams: Promise<Query> };

function buildQuery(query: Query, override: Record<string, string | null> = {}) {
  const params = new URLSearchParams();
  if (query.owner) params.set("owner", query.owner);
  if (query.date_from) params.set("date_from", query.date_from);
  if (query.date_to) params.set("date_to", query.date_to);
  const batches = query.batch
    ? Array.isArray(query.batch) ? query.batch : [query.batch]
    : [];
  batches.forEach((value) => params.append("batch", value));
  for (const key of ["batch_page", "receipt_page", "timeline_page"] as const) {
    if (query[key]) params.set(key, query[key]!);
  }
  Object.entries(override).forEach(([key, value]) => {
    if (value === null) params.delete(key);
    else params.set(key, value);
  });
  return params.toString();
}

function PageLinks({
  query,
  prefix,
  page,
}: {
  query: Query;
  prefix: "batch" | "receipt" | "timeline";
  page: { page: number; pages: number; previous: number | null; next: number | null };
}) {
  if (page.pages <= 1) return null;
  const key = `${prefix}_page`;
  return (
    <nav aria-label={`${prefix} pagination`} className="mt-4 flex items-center justify-end gap-3 text-sm font-bold">
      {page.previous ? <Link className="underline" href={`/finance/owner-capital?${buildQuery(query, { [key]: String(page.previous) })}`}>Previous</Link> : null}
      <span>Page {page.page} of {page.pages}</span>
      {page.next ? <Link className="underline" href={`/finance/owner-capital?${buildQuery(query, { [key]: String(page.next) })}`}>Next</Link> : null}
    </nav>
  );
}

export default async function OwnerCapitalPage({ searchParams }: PageProps) {
  const query = await searchParams;
  const reportQuery = buildQuery(query);
  const returnTo = `/finance/owner-capital${reportQuery ? `?${reportQuery}` : ""}`;
  const [owners, batches, report] = await Promise.all([
    getOwnerContributors(returnTo),
    getPoultryBatches(returnTo),
    getOwnerContributionReport(returnTo, reportQuery ? `?${reportQuery}` : ""),
  ]);
  const selectedBatches = query.batch
    ? Array.isArray(query.batch) ? query.batch : [query.batch]
    : [];

  return (
    <FinancePageShell
      eyebrow="Finance / Owner Capital"
      title="Owner contributions and use."
      detail="Trace cash introduced by each owner, its intended batch designation, actual expenditure use, capital returned, and remaining balance without counting one receipt more than once."
      actions={<FinanceNav />}
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <OwnerCapitalActions owners={owners} batches={batches} receipts={report.receipts} reportQuery={reportQuery ? `?${reportQuery}` : ""} />
        <Link href="/finance/expenditures/new" className="rounded-lg border border-[var(--navy)] px-4 py-3 font-bold text-[var(--navy)]">
          Record a return, drawing, or owner payment
        </Link>
      </div>

      <Panel title="Review Filters">
        <form method="get" className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <label className="text-sm font-bold">Owner<select name="owner" defaultValue={query.owner ?? ""} className="form-input mt-2 w-full"><option value="">All named and legacy owners</option><option value="unknown">Unknown legacy owner</option>{owners.map((owner) => <option key={owner.id} value={owner.id}>{owner.display_name}{owner.is_active ? "" : " (inactive)"}</option>)}</select></label>
          <OwnerCapitalBatchFilter
            batches={batches}
            initialSelectedIds={selectedBatches.map(Number).filter(Number.isFinite)}
          />
          <label className="text-sm font-bold">From<input type="date" name="date_from" defaultValue={query.date_from} className="form-input mt-2 w-full" /></label>
          <label className="text-sm font-bold">To<input type="date" name="date_to" defaultValue={query.date_to} className="form-input mt-2 w-full" /></label>
          <div className="flex items-end gap-3 lg:col-span-5"><button className="finance-button">Apply filters</button><Link className="rounded-lg border px-4 py-3 font-bold" href="/finance/owner-capital">Clear</Link></div>
        </form>
        <p className="mt-4 text-sm leading-6 text-[var(--navy-muted)]">{report.basis} Batch filters narrow the attribution table; cash ledger totals remain reconciled to the selected owner and dates.</p>
      </Panel>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Introduced to date" value={formatCurrency(report.summary.cash_introduced_to_date)} detail={`${formatCurrency(report.summary.cash_introduced_in_period)} in selected period`} />
        <MetricCard label="Actually spent" value={formatCurrency(report.summary.cash_used_to_date)} detail={`${formatCurrency(report.summary.cash_used_in_period)} in selected period`} />
        <MetricCard label="Owner cash remaining" value={formatCurrency(report.summary.closing_cash_balance)} tone="positive" detail="Receipts less posted expenditure and payroll funding" />
        <MetricCard label="Net contributed capital" value={formatCurrency(report.summary.net_contributed_capital)} detail={`${formatCurrency(report.summary.capital_returns_to_date)} explicitly returned`} />
        <MetricCard label="Designated to batches" value={formatCurrency(report.summary.designated_to_batches_as_of)} detail={`${formatCurrency(report.summary.unassigned_contributions_as_of)} not yet designated`} />
        <MetricCard label="Farm-wide use" value={formatCurrency(report.summary.farm_wide_use_to_date)} detail="Owner-funded cost without a batch beneficiary" />
        <MetricCard label="Owner drawings" value={formatCurrency(report.summary.owner_drawings_to_date)} />
        <MetricCard label="Profit distributions" value={formatCurrency(report.summary.profit_distributions_to_date)} />
      </div>

      {report.summary.unknown_owner_receipt_count ? (
        <div className="rounded-lg border border-[var(--gold)] bg-[var(--gold-soft)] p-4 text-sm">
          <strong>{report.summary.unknown_owner_receipt_count} legacy owner receipt(s)</strong> totaling {formatCurrency(report.summary.unknown_owner_receipt_amount)} have no reliable contributor identity. They remain separate until an administrator deliberately assigns them.
        </div>
      ) : null}

      {report.batch_filter.length ? (
        <Panel title="Selected Batch Totals">
          <div className="grid gap-4 sm:grid-cols-3">
            <MetricCard label="Designated to selected batches" value={formatCurrency(report.selected_batch_summary.designated_as_of)} detail={`${report.selected_batch_summary.batch_count} selected batch(es) represented`} />
            <MetricCard label="Spent in selected period" value={formatCurrency(report.selected_batch_summary.owner_cash_spent_in_period)} />
            <MetricCard label="Spent to date" value={formatCurrency(report.selected_batch_summary.owner_cash_spent_to_date)} />
          </div>
        </Panel>
      ) : null}

      <Panel title="Owner Accounts">
        <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Owner</th><th className="p-3 text-right">Introduced</th><th className="p-3 text-right">Designated</th><th className="p-3 text-right">Actually spent</th><th className="p-3 text-right">Capital returned</th><th className="p-3 text-right">Cash remaining</th></tr></thead><tbody>{report.owners.map((owner) => <tr className="border-b" key={owner.owner_id ?? "unknown"}><td className="p-3 font-bold">{owner.owner_name}</td><td className="p-3 text-right">{formatCurrency(owner.cash_introduced_to_date)}</td><td className="p-3 text-right">{formatCurrency(owner.designated_as_of)}</td><td className="p-3 text-right">{formatCurrency(owner.cash_used_to_date)}</td><td className="p-3 text-right">{formatCurrency(owner.capital_returns_to_date)}</td><td className="p-3 text-right font-bold">{formatCurrency(owner.remaining_cash)}</td></tr>)}</tbody></table></div>
      </Panel>

      <Panel title="Batch Attribution">
        <div className="overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Batch</th><th className="p-3 text-right">Designated</th><th className="p-3 text-right">Spent in period</th><th className="p-3 text-right">Spent to date</th><th className="p-3">Owner record</th></tr></thead><tbody>{report.batches.map((batch) => <tr className="border-b" key={batch.batch_id}><td className="p-3 font-bold"><Link className="underline" href={`/finance/batches/${batch.batch_id}`}>{batch.batch_code}</Link></td><td className="p-3 text-right">{formatCurrency(batch.designated_as_of)}</td><td className="p-3 text-right">{formatCurrency(batch.owner_cash_spent_in_period)}</td><td className="p-3 text-right">{formatCurrency(batch.owner_cash_spent_to_date)}</td><td className="p-3">{batch.has_unknown_owner ? "Includes legacy unknown" : `${batch.owners.length} named owner(s)`}</td></tr>)}</tbody></table></div>
        <PageLinks query={query} prefix="batch" page={report.batch_page} />
      </Panel>

      <Panel title="Contribution Receipts">
        <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Date</th><th className="p-3">Owner</th><th className="p-3">Reference</th><th className="p-3 text-right">Received</th><th className="p-3 text-right">Designated</th><th className="p-3 text-right">Unassigned</th><th className="p-3">Status</th><th className="p-3">Action</th></tr></thead><tbody>{report.receipts.map((receipt) => <tr className="border-b" key={receipt.id}><td className="p-3">{formatDate(receipt.receipt_date)}</td><td className="p-3 font-bold">{receipt.owner_name}</td><td className="p-3">{receipt.reference || `Receipt #${receipt.id}`}</td><td className="p-3 text-right">{formatCurrency(receipt.amount)}</td><td className="p-3 text-right">{formatCurrency(receipt.designated_as_of)}</td><td className="p-3 text-right">{formatCurrency(receipt.unassigned_as_of)}</td><td className="p-3">{formatLabel(receipt.current_status)}</td><td className="p-3"><OwnerReceiptAction receiptId={receipt.id} /></td></tr>)}</tbody></table></div>
        <PageLinks query={query} prefix="receipt" page={report.receipt_page} />
      </Panel>

      <Panel title="Cash And Capital Timeline">
        <p className="mb-4 text-sm text-[var(--navy-muted)]">Opening cash {formatCurrency(report.timeline_opening_cash_balance)} · opening net capital {formatCurrency(report.timeline_opening_net_contributed_capital)}</p>
        <div className="overflow-x-auto"><table className="w-full min-w-[980px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Date</th><th className="p-3">Owner</th><th className="p-3">Event</th><th className="p-3">Reference</th><th className="p-3 text-right">In</th><th className="p-3 text-right">Out</th><th className="p-3 text-right">Running cash</th><th className="p-3 text-right">Running net capital</th></tr></thead><tbody>{report.timeline.map((event, index) => <tr className="border-b" key={`${event.date}-${event.reference}-${index}`}><td className="p-3">{formatDate(event.date)}</td><td className="p-3">{event.owner_name}</td><td className="p-3">{formatLabel(event.event_type)}</td><td className="p-3">{event.source_href ? <Link className="underline" href={event.source_href}>{event.reference}</Link> : event.reference}</td><td className="p-3 text-right">{formatCurrency(event.inflow)}</td><td className="p-3 text-right">{formatCurrency(event.outflow)}</td><td className="p-3 text-right font-bold">{formatCurrency(event.running_cash_balance)}</td><td className="p-3 text-right">{formatCurrency(event.running_net_contributed_capital)}</td></tr>)}</tbody></table></div>
        <PageLinks query={query} prefix="timeline" page={report.timeline_page} />
      </Panel>
    </FinancePageShell>
  );
}
