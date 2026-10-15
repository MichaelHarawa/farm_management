/** Private original invoice parents, not a financial replica or API integration. */
import { Decimal } from 'decimal.js';
import { z } from 'zod';
import { uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';

const id = uuid.refine(value => value === value.toLowerCase());
const digest = z.string().length(64).regex(/^[0-9a-f]{64}$/);
const instant = z.iso.datetime({ precision: undefined }).max(27)
  .regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/);
const money = z.string().regex(/^(0|[1-9][0-9]{0,11})\.[0-9]{2}$/).refine(value => value !== '0.00');
const quantity = z.string().regex(/^(0|[1-9][0-9]{0,11})\.[0-9]{4}$/).refine(value => value !== '0.0000');
const text = (max: number) => z.string().refine(value =>
  value.trim() === value && [...value].length >= 1 && [...value].length <= max);
const Exact = Decimal.clone({ precision: 40 });
const context = { invoice_reference_version: z.literal(1), deployment_id: id, device_id: id,
  scope_revision: digest, server_time: instant, access: z.literal('online_only_original_actor_finance_writer'),
  offline_cache_seconds: z.literal(0), financial_uploads: z.literal(false) };
const invoice = z.strictObject({ invoice_group_id: id, invoice_version: digest, supplier: text(160),
  invoice_reference: text(120), purchase_date: z.iso.date(), currency: z.literal('MWK'),
  original_total_purchase_cost: money, line_count: z.number().int().min(2).max(50), recorded_at: instant,
  evidence: z.literal('immutable_original_invoice'), balance_semantics: z.literal('original_purchase_not_current_outstanding') });
const line = z.strictObject({ invoice_line_index: z.number().int().min(0).max(49),
  original_item_name: text(160), original_location_name: text(160), captured_quantity: quantity,
  captured_unit: text(40), base_quantity: quantity, base_unit: text(40), original_line_cost: money,
  expiry_date: z.iso.date().nullable() });

export const invoiceReferencePage = z.strictObject({ ...context, catalog_version: digest,
  total_authorized_rows: z.number().int().min(0).max(100), rows: z.array(invoice).max(25),
  next_cursor: z.string().min(1).max(2048).nullable(),
}).superRefine((page, ctx) => {
  if (page.rows.length > page.total_authorized_rows ||
      page.next_cursor !== null && (page.rows.length === 0 || page.rows.length >= page.total_authorized_rows) ||
      page.rows.some((row, index) => {
        const previous = page.rows[index - 1];
        return previous !== undefined && row.invoice_group_id <= previous.invoice_group_id;
      }) || byteLength(JSON.stringify(page)) > 524288) {
    ctx.addIssue({ code: 'custom', message: 'Invalid original invoice page; never infer a whole payable total.' });
  }
});

export const invoiceReferenceDetail = z.strictObject({ ...context, detail_version: digest, invoice,
  lines: z.array(line).min(2).max(50), proof: z.literal('original_invoice_sources_and_purchase_journals'),
  label_semantics: z.literal('original_purchase_names_and_values'),
  payment_authority: z.literal('none_revalidate_payables_and_cash_on_posting'),
}).superRefine((detail, ctx) => {
  if (detail.lines.length !== detail.invoice.line_count ||
      detail.lines.some((row, index) => row.invoice_line_index !== index) ||
      !detail.lines.reduce((sum, row) => sum.plus(row.original_line_cost), new Exact(0)).equals(detail.invoice.original_total_purchase_cost) ||
      byteLength(JSON.stringify(detail)) > 65536) {
    ctx.addIssue({ code: 'custom', message: 'Original invoice membership/totals invalid; retain its original identity.' });
  }
});

interface Expectation { identity: StoreIdentity; scopeRevision?: string }
function checkContext(value: { deployment_id: string; device_id: string; scope_revision: string }, expected: Expectation) {
  if (value.deployment_id !== expected.identity.deploymentId || value.device_id !== expected.identity.deviceId ||
      expected.scopeRevision !== undefined && value.scope_revision !== digest.parse(expected.scopeRevision)) {
    throw new Error('invoice_reference_identity_or_scope_changed_retain_original');
  }
}

export function parseInvoiceReferencePage(value: unknown, expected: Expectation & { catalogVersion?: string }) {
  const page = invoiceReferencePage.parse(value);
  checkContext(page, expected);
  if (expected.catalogVersion !== undefined && page.catalog_version !== digest.parse(expected.catalogVersion)) {
    throw new Error('invoice_catalog_changed_retain_original');
  }
  return page;
}

/** In-memory completeness only. Does NOT grant sensitive offline access. */
export function verifyInvoiceReferencePages(values: unknown[], expected: Expectation) {
  if (values.length === 0 || values.length > 100) throw new Error('invoice_catalog_incomplete');
  const first = parseInvoiceReferencePage(values[0], expected);
  const pages = values.map(value => parseInvoiceReferencePage(value, { ...expected,
    scopeRevision: first.scope_revision, catalogVersion: first.catalog_version }));
  const rows = pages.flatMap(page => page.rows);
  if (rows.length !== first.total_authorized_rows || pages.some((page, index) =>
      page.total_authorized_rows !== first.total_authorized_rows ||
      (index === pages.length - 1 ? page.next_cursor !== null : page.next_cursor === null)) ||
      rows.some((row, index) => {
        const previous = rows[index - 1];
        return previous !== undefined && row.invoice_group_id <= previous.invoice_group_id;
      })) {
    throw new Error('invoice_catalog_incomplete_or_changed_retain_original');
  }
  return rows;
}

export function parseInvoiceReferenceDetail(value: unknown, expected: Expectation & { invoiceId: string; invoiceVersion: string }) {
  const detail = invoiceReferenceDetail.parse(value);
  checkContext(detail, expected);
  if (detail.invoice.invoice_group_id !== id.parse(expected.invoiceId) ||
      detail.invoice.invoice_version !== digest.parse(expected.invoiceVersion)) {
    throw new Error('invoice_parent_changed_retain_original');
  }
  return detail;
}
