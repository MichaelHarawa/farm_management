import Link from "next/link";

import {
  getCustomerContributionReport,
  getCustomerCostSources,
  getCustomers,
  getCustomerUnlinkedSales,
} from "@/features/finance/api/finance";
import { CustomerContributionActions } from "@/features/finance/components/CustomerContributionActions";
import { EmptyState, FinanceNav, FinancePageShell, MetricCard, Panel } from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatLabel, parseDecimal } from "@/features/finance/utils/formatters";

type Query = {
  search?: string;
  date_from?: string;
  date_to?: string;
  product_type?: string;
  customer_page?: string;
};

function queryString(query: Query, page?: number) {
  const params = new URLSearchParams();
  if (query.search) params.set("search", query.search);
  if (query.date_from) params.set("date_from", query.date_from);
  if (query.date_to) params.set("date_to", query.date_to);
  if (query.product_type) params.set("product_type", query.product_type);
  if (page) params.set("customer_page", String(page));
  return params.toString();
}

export default async function CustomerContributionPage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  const reportQuery = queryString(query, Number(query.customer_page) || undefined);
  const returnTo = `/finance/customers${reportQuery ? `?${reportQuery}` : ""}`;
  const [report, customers, unlinkedSales, costSources] = await Promise.all([
    getCustomerContributionReport(returnTo, reportQuery ? `?${reportQuery}` : ""),
    getCustomers(returnTo),
    getCustomerUnlinkedSales(returnTo),
    getCustomerCostSources(returnTo),
  ]);
  const page = report.page;

  return (
    <FinancePageShell
      eyebrow="Finance / Customers"
      title="Customer contribution."
      detail="See which customers create value after delivery, support, rework, and acquisition costs. Revenue and cash collection remain separate."
      actions={<FinanceNav />}
    >
      <CustomerContributionActions
        customers={customers}
        unlinkedSales={unlinkedSales}
        costSources={costSources}
        reportQuery={reportQuery ? `?${reportQuery}` : ""}
      />

      <Panel title="Review period">
        <form method="get" className="grid gap-4 md:grid-cols-2 lg:grid-cols-5">
          <label className="text-sm font-bold lg:col-span-2">Customer search<input name="search" defaultValue={query.search} className="form-input mt-2 w-full" placeholder="Name or contact" /></label>
          <label className="text-sm font-bold">Product<select name="product_type" defaultValue={query.product_type ?? ""} className="form-input mt-2 w-full"><option value="">All products</option><option value="live_chicken">Live chicken</option><option value="dressed_chicken">Dressed chicken</option><option value="eggs">Eggs</option><option value="manure">Manure</option></select></label>
          <label className="text-sm font-bold">From<input type="date" name="date_from" defaultValue={query.date_from} className="form-input mt-2 w-full" /></label>
          <label className="text-sm font-bold">To<input type="date" name="date_to" defaultValue={query.date_to} className="form-input mt-2 w-full" /></label>
          <div className="flex items-end gap-3 lg:col-span-5"><button className="finance-button">Apply</button><Link className="rounded-lg border px-4 py-3 font-bold" href="/finance/customers">Clear</Link></div>
        </form>
      </Panel>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="Recognized revenue" value={formatCurrency(report.summary.revenue)} detail="Recorded sales, whether paid or unpaid" />
        <MetricCard label="Customer contribution" value={formatCurrency(report.summary.contribution)} tone={parseDecimal(report.summary.contribution) < 0 ? "danger" : "positive"} detail={report.summary.margin_percent === null ? "Margin N/A" : `${report.summary.margin_percent}% margin`} />
        <MetricCard label="Cash collected" value={formatCurrency(report.summary.cash_collected)} detail="Posted customer receipts through the end date" />
        <MetricCard label="Still receivable" value={formatCurrency(report.summary.receivables)} tone={parseDecimal(report.summary.receivables) > 0 ? "warning" : "default"} detail="Recognized revenue not yet collected" />
      </div>

      {(report.summary.incomplete_customer_count || report.summary.unlinked_sale_count) ? (
        <div className="rounded-lg border border-[var(--gold)] bg-[var(--gold-soft)] p-4 text-sm leading-6">
          <strong>Analysis needs review.</strong> {report.summary.incomplete_customer_count} customer(s) have missing cost categories. {report.summary.unlinked_sale_count} sale(s), worth {formatCurrency(report.summary.unlinked_revenue)}, are not linked to a stable customer.
        </div>
      ) : null}

      <Panel title="Customers">
        {report.customers.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[850px] text-left text-sm">
              <thead><tr className="border-b"><th className="p-3">Customer</th><th className="p-3 text-right">Revenue</th><th className="p-3 text-right">Total customer costs</th><th className="p-3 text-right">Contribution</th><th className="p-3 text-right">Margin</th><th className="p-3">Coverage</th><th className="p-3">Review label</th></tr></thead>
              <tbody>{report.customers.map((row) => {
                const totalCosts = parseDecimal(row.direct_delivery_cost) + parseDecimal(row.support_cost) + parseDecimal(row.rework_cost) + parseDecimal(row.acquisition_cost);
                return <tr className="border-b" key={row.customer_id}><td className="p-3"><Link className="font-bold underline" href={`/finance/customers/${row.customer_id}?${queryString(query)}`}>{row.customer_name}</Link><span className="block text-xs text-[var(--navy-muted)]">{row.sale_count} sale(s) · {row.customer_concentration_percent ?? "N/A"}% of farm revenue</span></td><td className="p-3 text-right">{formatCurrency(row.revenue)}</td><td className="p-3 text-right">{formatCurrency(totalCosts)}</td><td className="p-3 text-right font-bold">{formatCurrency(row.contribution)}</td><td className="p-3 text-right">{row.margin_percent === null ? "N/A" : `${row.margin_percent}%`}</td><td className="p-3"><span className={row.coverage_status === "complete" ? "text-green-700" : "font-bold text-amber-800"}>{formatLabel(row.coverage_status)}</span></td><td className="p-3">{formatLabel(row.management_label || row.recommended_label)}</td></tr>;
              })}</tbody>
            </table>
          </div>
        ) : <EmptyState message="No customers match this reporting period and search." />}
        {page && page.pages > 1 ? <nav aria-label="Customer pages" className="mt-4 flex justify-end gap-3 text-sm font-bold">{page.previous ? <Link className="underline" href={`/finance/customers?${queryString(query, page.previous)}`}>Previous</Link> : null}<span>Page {page.page} of {page.pages}</span>{page.next ? <Link className="underline" href={`/finance/customers?${queryString(query, page.next)}`}>Next</Link> : null}</nav> : null}
      </Panel>

      <details className="rounded-lg border border-[var(--line)] bg-white/55 p-4 text-sm">
        <summary className="cursor-pointer font-bold">Calculation and product breakdown</summary>
        <p className="mt-3 leading-6 text-[var(--navy-muted)]"><strong>{report.formula}</strong>. {report.basis}</p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{report.products.map((product) => <div key={product.product_type} className="rounded-lg border p-3"><p className="font-bold">{formatLabel(product.product_type)}</p><p className="mt-1 text-[var(--navy-muted)]">{product.sale_count} sale(s)</p><p className="mt-2 font-extrabold">{formatCurrency(product.revenue)}</p></div>)}</div>
      </details>
    </FinancePageShell>
  );
}
