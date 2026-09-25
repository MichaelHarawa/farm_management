import Link from "next/link";
import { notFound } from "next/navigation";

import {
  getCustomerContributionReport,
  getCustomerCostSources,
  getCustomer,
  getCustomers,
  getCustomerUnlinkedSales,
} from "@/features/finance/api/finance";
import { CustomerContributionActions, ReverseCustomerCostButton } from "@/features/finance/components/CustomerContributionActions";
import { FinanceNav, FinancePageShell, MetricCard, Panel } from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, formatLabel, parseDecimal } from "@/features/finance/utils/formatters";

type Query = { date_from?: string; date_to?: string; product_type?: string };

function buildQuery(customerId: number, query: Query) {
  const params = new URLSearchParams({ customer: String(customerId) });
  if (query.date_from) params.set("date_from", query.date_from);
  if (query.date_to) params.set("date_to", query.date_to);
  if (query.product_type) params.set("product_type", query.product_type);
  return params.toString();
}

export default async function CustomerContributionDetailPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<Query> }) {
  const { id } = await params;
  const query = await searchParams;
  const customerId = Number(id);
  if (!Number.isInteger(customerId) || customerId <= 0) notFound();
  const reportQuery = buildQuery(customerId, query);
  const returnTo = `/finance/customers/${customerId}?${reportQuery}`;
  const [report, customers, customerRecord, unlinkedSales, costSources] = await Promise.all([
    getCustomerContributionReport(returnTo, `?${reportQuery}&export=1`),
    getCustomers(returnTo),
    getCustomer(customerId, returnTo),
    getCustomerUnlinkedSales(returnTo),
    getCustomerCostSources(returnTo),
  ]);
  const customer = report.customers.find((row) => row.customer_id === customerId);
  if (!customer) notFound();
  const totalCosts = parseDecimal(customer.direct_delivery_cost) + parseDecimal(customer.support_cost) + parseDecimal(customer.rework_cost) + parseDecimal(customer.acquisition_cost);

  return (
    <FinancePageShell eyebrow="Finance / Customer Contribution" title={customer.customer_name} detail="Trace recognized sales, collections, production delivery share, and documented customer-specific costs." actions={<FinanceNav />}>
      <div className="flex flex-wrap items-center justify-between gap-4"><Link href="/finance/customers" className="font-bold underline">← All customers</Link><CustomerContributionActions customers={customers.some((item) => item.id === customerRecord.id) ? customers : [customerRecord, ...customers]} unlinkedSales={unlinkedSales} costSources={costSources} customer={customer} reportQuery={`?${reportQuery}`} /></div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><MetricCard label="Revenue" value={formatCurrency(customer.revenue)} detail={`${formatCurrency(customer.cash_collected)} collected`} /><MetricCard label="Customer costs" value={formatCurrency(totalCosts)} detail="Four non-overlapping cost categories" /><MetricCard label="Contribution" value={formatCurrency(customer.contribution)} tone={parseDecimal(customer.contribution) < 0 ? "danger" : "positive"} detail={customer.margin_percent === null ? "Margin N/A" : `${customer.margin_percent}% margin`} /><MetricCard label="Receivable" value={formatCurrency(customer.receivables)} tone={parseDecimal(customer.receivables) > 0 ? "warning" : "default"} detail="Collections do not change recognized revenue" /></div>

      <Panel title="Contribution breakdown">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{[["Direct delivery", customer.direct_delivery_cost, "Includes sold birds’ production-cost share"], ["Support", customer.support_cost, customer.category_coverage.support], ["Rework", customer.rework_cost, customer.category_coverage.rework], ["Acquisition", customer.acquisition_cost, customer.category_coverage.acquisition], ["Contribution", customer.contribution, customer.margin_percent === null ? "Margin N/A" : `${customer.margin_percent}% margin`]].map(([label, value, detail]) => <div className="rounded-lg border p-4" key={label}><p className="text-xs font-bold uppercase tracking-wide text-[var(--navy-muted)]">{label}</p><p className="mt-2 font-display text-2xl font-bold">{formatCurrency(value)}</p><p className="mt-2 text-xs text-[var(--navy-muted)]">{formatLabel(detail)}</p></div>)}</div>
        {customer.coverage_status !== "complete" ? <p className="mt-4 rounded-lg bg-[var(--gold-soft)] p-3 text-sm font-semibold">Missing categories are shown as not attributed, not assumed to be zero. Complete the source review before relying on this margin.</p> : null}
      </Panel>

      <Panel title="Management review"><div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-sm">System suggestion: <strong>{formatLabel(customer.recommended_label)}</strong></p><p className="mt-1 text-sm">Management label: <strong>{formatLabel(customer.management_label || "not reviewed")}</strong></p>{customer.review_notes ? <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--navy-muted)]">{customer.review_notes}</p> : null}</div><p className="text-xs text-[var(--navy-muted)]">{customer.reviewed_at ? `Reviewed ${formatDate(customer.reviewed_at)} by ${customer.reviewed_by || "N/A"}` : "Not yet reviewed"}</p></div></Panel>

      <Panel title="Sales">
        <div className="overflow-x-auto"><table className="w-full min-w-[800px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Sale</th><th className="p-3">Product</th><th className="p-3">Batch</th><th className="p-3 text-right">Revenue</th><th className="p-3 text-right">Collected</th><th className="p-3 text-right">Production delivery cost</th></tr></thead><tbody>{customer.sales.map((sale) => <tr className="border-b" key={sale.id}><td className="p-3 font-bold">{sale.sale_id}<span className="block text-xs font-normal text-[var(--navy-muted)]">{formatDate(sale.sale_date)}</span></td><td className="p-3">{formatLabel(sale.product_type)}</td><td className="p-3"><Link className="underline" href={`/poultry/batches/${sale.batch_id}?tab=sales`}>{sale.batch_code}</Link></td><td className="p-3 text-right">{formatCurrency(sale.revenue)}</td><td className="p-3 text-right">{formatCurrency(sale.cash_collected)}</td><td className="p-3 text-right">{sale.production_delivery_cost === null ? formatLabel(sale.production_cost_status) : formatCurrency(sale.production_delivery_cost)}</td></tr>)}</tbody></table></div>
      </Panel>

      <Panel title="Explicit customer cost attributions">
        {customer.attributions.length ? <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead><tr className="border-b"><th className="p-3">Date</th><th className="p-3">Category</th><th className="p-3">Source</th><th className="p-3">Evidence</th><th className="p-3 text-right">Amount</th><th className="p-3">Action</th></tr></thead><tbody>{customer.attributions.map((row) => <tr className="border-b" key={row.id}><td className="p-3">{formatDate(row.date)}</td><td className="p-3">{formatLabel(row.category)}</td><td className="p-3">{row.source_href ? <Link className="font-bold underline" href={row.source_href}>{row.source_label}</Link> : <span className="font-bold">{row.source_label}</span>}<span className="block text-xs text-[var(--navy-muted)]">{row.attribution_basis} · {row.reason}</span></td><td className="p-3">{formatLabel(row.evidence_status)}</td><td className="p-3 text-right font-bold">{formatCurrency(row.amount)}</td><td className="p-3"><ReverseCustomerCostButton attributionId={row.id} /></td></tr>)}</tbody></table></div> : <p className="text-sm text-[var(--navy-muted)]">No explicit support, rework, acquisition, or delivery costs have been attributed yet.</p>}
      </Panel>
    </FinancePageShell>
  );
}
