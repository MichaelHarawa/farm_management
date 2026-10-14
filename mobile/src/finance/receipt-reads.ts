/** Separate online-only financial reads. Not wired to app navigation or sync.
 * Financial receipt UUID/hash is NOT the operational outbox UUID/hash/mapping.
 * Parsing original acceptance never changes a balance or retires an overlay.
 */
import { Decimal } from 'decimal.js';
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';

const digest = z.string().regex(/^[0-9a-f]{64}$/);
const money = z.string().regex(/^(0|[1-9][0-9]{0,15})\.[0-9]{2}$/).refine(v => v !== '0.00');
const Exact = Decimal.clone({ precision: 40 });
const boundedText = (maximum: number) => z.string().refine(value =>
  value.trim() === value && [...value].length >= 1 && [...value].length <= maximum);
const context = {
  financial_read_version: z.literal(1), deployment_id: uuid, device_id: uuid,
  scope_revision: digest, server_time: instant, access: z.literal('online_only_original_actor'),
  offline_cache_seconds: z.literal(0),
};
export const financialReadCapabilities = z.strictObject({ ...context,
  reads: z.strictObject({ supplier_payment_status: z.literal(true), supplier_payment_summary: z.literal(true) }),
  financial_uploads: z.literal(false), packs: z.array(z.never()).max(0),
  limits: z.strictObject({ summary_bytes: z.literal(16384), summary_invoices: z.literal(10),
    summary_lines: z.literal(50), summary_funding_rows: z.literal(100), receipt_proof_bytes: z.literal(8388608) }),
});
export const supplierPaymentStatus = z.strictObject({ ...context, operation_id: uuid,
  identity_kind: z.literal('financial_command_receipt'), command: z.literal('inventory.supplier_payment.record'),
  outcome: z.literal('accepted'), evidence: z.literal('immutable_completed_receipt'),
  receipt_hash: digest, payment_version: digest, recorded_at: instant,
  balance_semantics: z.literal('historical_acceptance_not_current_balance'),
  recovery_action: z.literal('retain_original_id_do_not_resubmit'),
});
const summary = z.strictObject({ summary_version: z.literal(1), operation_id: uuid,
  payment_version: digest, recorded_at: instant, evidence_status: z.literal('accepted_original_payment'),
  balance_semantics: z.literal('historical_payment_not_current_balance'), currency: z.literal('MWK'),
  payment_date: z.iso.date(), amount: money, payee: boundedText(160),
  payment_method: z.enum(['cash', 'mobile_money', 'bank_transfer']),
  external_reference: boundedText(120), note_available: z.boolean(),
  invoices: z.array(z.strictObject({ invoice_id: uuid, invoice_version: digest, amount: money,
    lines: z.array(z.strictObject({ line_index: z.number().int().min(0).max(49), amount: money })).min(1).max(50),
  })).min(1).max(10),
}).superRefine((value, ctx) => {
  const sum = (amounts: string[]) => amounts.reduce((total, amount) => total.plus(amount), new Exact(0));
  if (new Set(value.invoices.map(row => row.invoice_id)).size !== value.invoices.length ||
      value.invoices.reduce((count, row) => count + row.lines.length, 0) > 50 ||
      !sum(value.invoices.map(row => row.amount)).equals(value.amount) ||
      value.invoices.some(row => new Set(row.lines.map(line => line.line_index)).size !== row.lines.length ||
        !sum(row.lines.map(line => line.amount)).equals(row.amount))) {
    ctx.addIssue({ code: 'custom', message: 'Invalid financial summary membership or exact totals.' });
  }
  if (byteLength(JSON.stringify(value)) > 16384) {
    ctx.addIssue({ code: 'custom', message: 'Financial summary exceeds the display budget; retain its original receipt.' });
  }
});
export const supplierPaymentSummary = z.strictObject({ ...context, summary });

interface ReadExpectation {
  identity: StoreIdentity;
  operationId: string;
  scopeRevision?: string;
  /** The original FINANCIAL receipt hash, never an operational outbox hash. */
  financialReceiptHash?: string;
  paymentVersion?: string;
}

function checkContext(value: z.infer<typeof supplierPaymentStatus> | z.infer<typeof supplierPaymentSummary>, expected: ReadExpectation) {
  if (value.deployment_id !== expected.identity.deploymentId || value.device_id !== expected.identity.deviceId) {
    throw new Error('financial_read_identity_mismatch');
  }
  if (expected.scopeRevision !== undefined && value.scope_revision !== digest.parse(expected.scopeRevision)) {
    throw new Error('financial_read_scope_changed');
  }
}

export function parseSupplierPaymentStatus(value: unknown, expected: ReadExpectation) {
  const status = supplierPaymentStatus.parse(value);
  checkContext(status, expected);
  if (status.operation_id !== expected.operationId ||
      expected.financialReceiptHash !== undefined && status.receipt_hash !== digest.parse(expected.financialReceiptHash) ||
      expected.paymentVersion !== undefined && status.payment_version !== digest.parse(expected.paymentVersion)) {
    throw new Error('financial_receipt_mismatch_retain_original');
  }
  return status;
}

export function parseSupplierPaymentSummary(value: unknown, expected: ReadExpectation) {
  const response = supplierPaymentSummary.parse(value);
  checkContext(response, expected);
  if (response.summary.operation_id !== expected.operationId ||
      expected.paymentVersion !== undefined && response.summary.payment_version !== digest.parse(expected.paymentVersion)) {
    throw new Error('financial_receipt_mismatch_retain_original');
  }
  return response;
}

export function supplierPaymentReadPath(operationId: string, part: 'status' | 'summary') {
  return `/mobile-sync/finance/supplier-payments/${uuid.parse(operationId)}/${z.enum(['status', 'summary']).parse(part)}`;
}
