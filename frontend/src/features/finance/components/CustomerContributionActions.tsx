"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Dialog } from "@/components/ui/Dialog";
import { clientApiFetch, ClientApiError } from "@/lib/client-api";
import type {
  Customer,
  CustomerContributionLabel,
  CustomerContributionReport,
  CustomerContributionRow,
  CustomerCostSource,
  CustomerUnlinkedSale,
  PaginatedResponse,
} from "@/features/finance/types";
import { formatCurrency, formatLabel } from "../utils/formatters";

type DialogKind = "customer" | "link" | "cost" | "review" | null;

function today() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function message(error: unknown) {
  if (error instanceof ClientApiError && error.details && typeof error.details === "object") {
    const first = Object.values(error.details as Record<string, unknown>)[0];
    if (Array.isArray(first)) return String(first[0]);
    if (typeof first === "string") return first;
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function normalizeCustomers(data: Customer[] | PaginatedResponse<Customer>) {
  return Array.isArray(data) ? data : data.results;
}

export function CustomerContributionActions({
  customers: initialCustomers,
  unlinkedSales: initialSales,
  costSources: initialSources,
  customer,
  reportQuery,
}: {
  customers: Customer[];
  unlinkedSales: CustomerUnlinkedSale[];
  costSources: CustomerCostSource[];
  customer?: CustomerContributionRow;
  reportQuery: string;
}) {
  const router = useRouter();
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customers, setCustomers] = useState(initialCustomers);
  const [unlinkedSales, setUnlinkedSales] = useState(initialSales);
  const [costSources, setCostSources] = useState(initialSources);
  const [customerSearch, setCustomerSearch] = useState("");
  const [saleSearch, setSaleSearch] = useState("");
  const [sourceSearch, setSourceSearch] = useState("");
  const [newCustomer, setNewCustomer] = useState({
    display_name: "", customer_type: "", contact_name: "", phone: "", email: "", notes: "",
  });
  const [link, setLink] = useState({ customer_id: customer ? String(customer.customer_id) : "", sale_id: "", reason: "" });
  const [cost, setCost] = useState({
    sale_id: "",
    attribution_date: today(),
    category: "support",
    amount: "",
    source: "",
    evidence_status: "actual",
    attribution_basis: "",
    reason: "",
  });
  const [review, setReview] = useState({
    contribution_label: (customer?.management_label || customer?.recommended_label || "review") as CustomerContributionLabel,
    review_notes: customer?.review_notes || "",
  });

  useEffect(() => {
    if (dialog !== "link") return;
    const timer = window.setTimeout(async () => {
      try {
        const [customerData, saleData] = await Promise.all([
          clientApiFetch<Customer[] | PaginatedResponse<Customer>>(
            `/api/finance/customers?page_size=100&search=${encodeURIComponent(customerSearch)}`
          ),
          clientApiFetch<CustomerUnlinkedSale[]>(
            `/api/finance/customer-unlinked-sales?search=${encodeURIComponent(saleSearch)}`
          ),
        ]);
        setCustomers(normalizeCustomers(customerData));
        setUnlinkedSales(saleData);
      } catch (requestError) {
        setError(message(requestError));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [customerSearch, saleSearch, dialog]);

  useEffect(() => {
    if (dialog !== "cost") return;
    const timer = window.setTimeout(async () => {
      try {
        setCostSources(
          await clientApiFetch<CustomerCostSource[]>(
            `/api/finance/customer-cost-sources?search=${encodeURIComponent(sourceSearch)}`
          )
        );
      } catch (requestError) {
        setError(message(requestError));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [sourceSearch, dialog]);

  const selectedSource = useMemo(
    () => costSources.find((item) => `${item.source_type}:${item.source_id}` === cost.source),
    [cost.source, costSources]
  );
  const customerRecord = customer
    ? customers.find((item) => item.id === customer.customer_id)
    : undefined;

  function close() {
    if (!busy) {
      setDialog(null);
      setError("");
    }
  }

  async function submit(path: string, body: unknown) {
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(path, { method: "POST", body: JSON.stringify(body) });
      setDialog(null);
      router.refresh();
    } catch (requestError) {
      setError(message(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function createCustomer(event: FormEvent) {
    event.preventDefault();
    await submit("/api/finance/customers", { ...newCustomer, is_active: true });
  }

  async function linkSale(event: FormEvent) {
    event.preventDefault();
    if (!link.sale_id || !link.customer_id) return;
    await submit(`/api/finance/customer-sale-links/${link.sale_id}`, {
      customer_id: Number(link.customer_id), reason: link.reason,
    });
  }

  async function addCost(event: FormEvent) {
    event.preventDefault();
    if (!customer) return;
    const manualEstimate = cost.source === "manual_estimate";
    await submit("/api/finance/customer-cost-attributions", {
      customer: customer.customer_id,
      sale_id: cost.sale_id ? Number(cost.sale_id) : null,
      attribution_date: cost.attribution_date,
      category: cost.category,
      amount: cost.amount,
      source_type: manualEstimate ? "manual_estimate" : selectedSource?.source_type,
      source_id: manualEstimate ? null : selectedSource?.source_id,
      evidence_status: manualEstimate ? "estimated" : cost.evidence_status,
      attribution_basis: cost.attribution_basis,
      reason: cost.reason,
      idempotency_key: crypto.randomUUID(),
    });
  }

  async function saveReview(event: FormEvent) {
    event.preventDefault();
    if (!customer) return;
    await submit(`/api/finance/customers/${customer.customer_id}/review`, review);
  }

  async function toggleCustomerStatus() {
    if (!customerRecord) return;
    const nextActive = !customerRecord.is_active;
    if (!window.confirm(`${nextActive ? "Reactivate" : "Deactivate"} ${customerRecord.display_name}? Existing sales and history will be preserved.`)) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(`/api/finance/customers/${customerRecord.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: nextActive }),
      });
      router.refresh();
    } catch (requestError) {
      setError(message(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function exportCsv() {
    setBusy(true);
    setError("");
    try {
      const separator = reportQuery ? "&" : "?";
      const report = await clientApiFetch<CustomerContributionReport>(
        `/api/finance/reports/customer-contributions${reportQuery}${separator}export=1`
      );
      const safe = (value: unknown) => {
        let text = value === null || value === undefined ? "" : String(value);
        if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
        return `"${text.replace(/"/g, '""')}"`;
      };
      const header = [
        "customer", "revenue", "cash_collected", "receivables", "direct_delivery",
        "support", "rework", "acquisition", "contribution", "margin_percent",
        "coverage", "recommended_label", "management_label",
      ];
      const rows = report.customers.map((row) => [
        row.customer_name, row.revenue, row.cash_collected, row.receivables,
        row.direct_delivery_cost, row.support_cost, row.rework_cost,
        row.acquisition_cost, row.contribution, row.margin_percent,
        row.coverage_status, row.recommended_label, row.management_label,
      ]);
      const csv = [header, ...rows].map((row) => row.map(safe).join(",")).join("\r\n");
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `customer-contribution-${report.date_to}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(message(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="finance-button" onClick={() => setDialog("customer")}>Add customer</button>
        <button type="button" className="rounded-lg border border-[var(--navy)] px-4 py-3 font-bold" onClick={() => setDialog("link")}>Link historical sale</button>
        {customer ? <button type="button" className="rounded-lg border border-[var(--navy)] px-4 py-3 font-bold" onClick={() => setDialog("cost")}>Attribute customer cost</button> : null}
        {customer ? <button type="button" className="rounded-lg border border-[var(--navy)] px-4 py-3 font-bold" onClick={() => setDialog("review")}>Review customer</button> : null}
        {customerRecord ? <button type="button" disabled={busy} className="rounded-lg border border-[var(--line)] px-4 py-3 font-bold" onClick={toggleCustomerStatus}>{customerRecord.is_active ? "Deactivate" : "Reactivate"}</button> : null}
        <button type="button" disabled={busy} className="rounded-lg border border-[var(--navy)] px-4 py-3 font-bold" onClick={exportCsv}>Export filtered CSV</button>
      </div>
      {error && !dialog ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}

      <Dialog open={dialog === "customer"} onClose={close} title="Add customer" eyebrow="Stable customer record" size="md">
        <form className="grid gap-4" onSubmit={createCustomer}>
          <label className="text-sm font-bold">Customer name<input required className="form-input mt-2 w-full" value={newCustomer.display_name} onChange={(event) => setNewCustomer({ ...newCustomer, display_name: event.target.value })} /></label>
          <label className="text-sm font-bold">Customer type<input className="form-input mt-2 w-full" placeholder="Retail, market vendor, distributor..." value={newCustomer.customer_type} onChange={(event) => setNewCustomer({ ...newCustomer, customer_type: event.target.value })} /></label>
          <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-bold">Contact person<input className="form-input mt-2 w-full" value={newCustomer.contact_name} onChange={(event) => setNewCustomer({ ...newCustomer, contact_name: event.target.value })} /></label><label className="text-sm font-bold">Phone<input className="form-input mt-2 w-full" value={newCustomer.phone} onChange={(event) => setNewCustomer({ ...newCustomer, phone: event.target.value })} /></label></div>
          <label className="text-sm font-bold">Email<input type="email" className="form-input mt-2 w-full" value={newCustomer.email} onChange={(event) => setNewCustomer({ ...newCustomer, email: event.target.value })} /></label>
          <label className="text-sm font-bold">Notes<textarea className="form-input mt-2 min-h-20 w-full" value={newCustomer.notes} onChange={(event) => setNewCustomer({ ...newCustomer, notes: event.target.value })} /></label>
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy} className="finance-button justify-self-end">Save customer</button>
        </form>
      </Dialog>

      <Dialog open={dialog === "link"} onClose={close} title="Link a sale to a customer" eyebrow="Identity review" size="lg">
        <form className="grid gap-4" onSubmit={linkSale}>
          <label className="text-sm font-bold">Find customer<input type="search" className="form-input mt-2 w-full" value={customerSearch} onChange={(event) => setCustomerSearch(event.target.value)} placeholder="Search name or contact" /></label>
          <label className="text-sm font-bold">Customer<select required className="form-input mt-2 w-full" value={link.customer_id} onChange={(event) => setLink({ ...link, customer_id: event.target.value })}><option value="">Choose customer</option>{customers.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>
          <label className="text-sm font-bold">Find unlinked sale<input type="search" className="form-input mt-2 w-full" value={saleSearch} onChange={(event) => setSaleSearch(event.target.value)} placeholder="Sale ID, buyer, or batch" /></label>
          <label className="text-sm font-bold">Sale<select required className="form-input mt-2 w-full" value={link.sale_id} onChange={(event) => setLink({ ...link, sale_id: event.target.value })}><option value="">Choose sale</option>{unlinkedSales.map((sale) => <option key={sale.id} value={sale.id}>{sale.sale_id} · {sale.buyer_name} · {formatCurrency(sale.revenue)}</option>)}</select></label>
          <label className="text-sm font-bold">Review note<textarea className="form-input mt-2 min-h-20 w-full" value={link.reason} onChange={(event) => setLink({ ...link, reason: event.target.value })} placeholder="Source document checked or reason for relinking" /></label>
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy || !link.sale_id || !link.customer_id} className="finance-button justify-self-end">Link sale</button>
        </form>
      </Dialog>

      <Dialog open={dialog === "cost"} onClose={close} title={`Attribute cost to ${customer?.customer_name ?? "customer"}`} eyebrow="Customer contribution" size="lg">
        <form className="grid gap-4" onSubmit={addCost}>
          <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-bold">Cost category<select className="form-input mt-2 w-full" value={cost.category} onChange={(event) => setCost({ ...cost, category: event.target.value })}><option value="direct_delivery">Direct delivery</option><option value="support">Support</option><option value="rework">Rework</option><option value="acquisition">Acquisition</option></select></label><label className="text-sm font-bold">Attribution date<input required type="date" className="form-input mt-2 w-full" value={cost.attribution_date} onChange={(event) => setCost({ ...cost, attribution_date: event.target.value })} /></label></div>
          <label className="text-sm font-bold">Optional sale<select className="form-input mt-2 w-full" value={cost.sale_id} onChange={(event) => setCost({ ...cost, sale_id: event.target.value })}><option value="">Customer-level cost</option>{customer?.sales.map((sale) => <option key={sale.id} value={sale.id}>{sale.sale_id} · {formatLabel(sale.product_type)} · {formatCurrency(sale.revenue)}</option>)}</select></label>
          <label className="text-sm font-bold">Find recognized cost<input type="search" className="form-input mt-2 w-full" value={sourceSearch} onChange={(event) => setSourceSearch(event.target.value)} placeholder="Expenditure reference, description, or payee" /></label>
          <label className="text-sm font-bold">Cost source<select required className="form-input mt-2 w-full" value={cost.source} onChange={(event) => setCost({ ...cost, source: event.target.value, evidence_status: event.target.value === "manual_estimate" ? "estimated" : cost.evidence_status })}><option value="">Choose recognized cost</option><option value="manual_estimate">Documented estimate (does not create an expense)</option>{costSources.map((source) => <option key={`${source.source_type}:${source.source_id}`} value={`${source.source_type}:${source.source_id}`}>{source.label} · {formatCurrency(source.available_amount)} available</option>)}</select></label>
          <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-bold">Amount<input required type="number" min="0.01" step="0.01" className="form-input mt-2 w-full" value={cost.amount} onChange={(event) => setCost({ ...cost, amount: event.target.value })} /></label><label className="text-sm font-bold">Evidence<select disabled={cost.source === "manual_estimate"} className="form-input mt-2 w-full" value={cost.source === "manual_estimate" ? "estimated" : cost.evidence_status} onChange={(event) => setCost({ ...cost, evidence_status: event.target.value })}><option value="actual">Actual / source linked</option><option value="estimated">Estimated share of source</option></select></label></div>
          <label className="text-sm font-bold">Attribution basis<input required className="form-input mt-2 w-full" value={cost.attribution_basis} onChange={(event) => setCost({ ...cost, attribution_basis: event.target.value })} placeholder="Delivery invoice, support hours, campaign basis..." /></label>
          <label className="text-sm font-bold">Reason<textarea required className="form-input mt-2 min-h-20 w-full" value={cost.reason} onChange={(event) => setCost({ ...cost, reason: event.target.value })} placeholder="Why this customer bears this cost" /></label>
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy || !cost.source} className="finance-button justify-self-end">Record attribution</button>
        </form>
      </Dialog>

      <Dialog open={dialog === "review"} onClose={close} title={`Review ${customer?.customer_name ?? "customer"}`} eyebrow="Management decision" size="md">
        <form className="grid gap-4" onSubmit={saveReview}>
          <p className="text-sm text-[var(--navy-muted)]">System suggestion: <strong>{formatLabel(customer?.recommended_label || "review")}</strong>. The management label is a documented decision, not an automated termination.</p>
          <label className="text-sm font-bold">Management label<select className="form-input mt-2 w-full" value={review.contribution_label} onChange={(event) => setReview({ ...review, contribution_label: event.target.value as CustomerContributionLabel })}><option value="ideal">Ideal</option><option value="healthy">Healthy</option><option value="review">Review</option><option value="unprofitable">Unprofitable</option><option value="strategic_exception">Strategic exception</option></select></label>
          <label className="text-sm font-bold">Decision and next action<textarea required className="form-input mt-2 min-h-28 w-full" value={review.review_notes} onChange={(event) => setReview({ ...review, review_notes: event.target.value })} /></label>
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy} className="finance-button justify-self-end">Save review</button>
        </form>
      </Dialog>
    </>
  );
}

export function ReverseCustomerCostButton({ attributionId }: { attributionId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function reverse() {
    const reason = window.prompt("Why is this customer cost attribution being reversed?");
    if (!reason?.trim()) return;
    setBusy(true);
    try {
      await clientApiFetch(`/api/finance/customer-cost-attributions/${attributionId}/reverse`, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      router.refresh();
    } finally {
      setBusy(false);
    }
  }
  return <button type="button" disabled={busy} onClick={reverse} className="font-bold text-[var(--danger)] underline">{busy ? "Reversing..." : "Reverse"}</button>;
}
