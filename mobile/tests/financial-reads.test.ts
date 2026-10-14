import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AuthClient } from '../src/auth/client';
import { result as operationalResult } from '../src/sync/protocol';
import { financialReadCapabilities, parseSupplierPaymentStatus, parseSupplierPaymentSummary,
  supplierPaymentReadPath, supplierPaymentStatus, supplierPaymentSummary } from '../src/finance/receipt-reads';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const operation = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const invoice = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const version = 'a'.repeat(64);
const hash = 'b'.repeat(64);
const scope = 'c'.repeat(64);
const context = { financial_read_version: 1, deployment_id: deployment, device_id: device,
  scope_revision: scope, server_time: '2026-10-14T07:00:00.000000Z',
  access: 'online_only_original_actor', offline_cache_seconds: 0 };
const status = { ...context, operation_id: operation, identity_kind: 'financial_command_receipt',
  command: 'inventory.supplier_payment.record', outcome: 'accepted', evidence: 'immutable_completed_receipt',
  receipt_hash: hash, payment_version: version, recorded_at: '2026-10-14T06:00:00.000000Z',
  balance_semantics: 'historical_acceptance_not_current_balance', recovery_action: 'retain_original_id_do_not_resubmit' };
const summary = { ...context, summary: { summary_version: 1, operation_id: operation, payment_version: version,
  recorded_at: status.recorded_at, evidence_status: 'accepted_original_payment', balance_semantics: 'historical_payment_not_current_balance',
  currency: 'MWK', payment_date: '2026-01-12', amount: '150.00', payee: 'Synthetic supplier',
  payment_method: 'bank_transfer', external_reference: 'SYNTHETIC-001', note_available: true,
  invoices: [{ invoice_id: invoice, invoice_version: version, amount: '150.00',
    lines: [{ line_index: 0, amount: '100.00' }, { line_index: 1, amount: '50.00' }] }] } };
const expected = { identity: { deploymentId: deployment, actorId: operation, deviceId: device },
  operationId: operation, scopeRevision: scope, financialReceiptHash: hash, paymentVersion: version };

test('financial reads validate separate original receipt identities without modifying the input', () => {
  const before = structuredClone([status, summary]);
  assert.deepEqual(parseSupplierPaymentStatus(status, expected), status);
  assert.deepEqual(parseSupplierPaymentSummary(summary, expected), summary);
  assert.deepEqual([status, summary], before);
  assert.equal(operationalResult.safeParse(status).success, false);
});

test('financial read capabilities never permit uploads packs or offline cache', () => {
  const capabilities = { ...context, reads: { supplier_payment_status: true, supplier_payment_summary: true },
    financial_uploads: false, packs: [], limits: { summary_bytes: 16384, summary_invoices: 10,
      summary_lines: 50, summary_funding_rows: 100, receipt_proof_bytes: 8388608 } };
  assert.deepEqual(financialReadCapabilities.parse(capabilities), capabilities);
  for (const extra of [{ financial_uploads: true }, { offline_cache_seconds: 86400 },
      { packs: ['finance-current'] }, { access: 'shared_farm' }]) {
    assert.equal(financialReadCapabilities.safeParse({ ...capabilities, ...extra }).success, false);
  }
});

test('financial reads reject foreign deployment device operation hash version or scope', () => {
  for (const changed of [{ deployment_id: operation }, { device_id: operation },
      { operation_id: device }, { receipt_hash: version }, { payment_version: hash }, { scope_revision: hash }]) {
    assert.throws(() => parseSupplierPaymentStatus({ ...status, ...changed }, expected));
  }
  assert.throws(() => parseSupplierPaymentSummary({ ...summary, deployment_id: operation }, expected));
  assert.throws(() => parseSupplierPaymentSummary({ ...summary, summary: { ...summary.summary, operation_id: invoice } }, expected));
});

test('financial status and summary strictly reject protected or unknown fields', () => {
  for (const extra of [{ amount: '1.00' }, { canonical_entities: [] }, { actor_id: operation }, { current_balance: '0.00' }]) {
    assert.equal(supplierPaymentStatus.safeParse({ ...status, ...extra }).success, false);
  }
  for (const extra of [{ notes: 'Private note' }, { funding_source: '1' }, { journal: {} }, { owner: operation }]) {
    assert.equal(supplierPaymentSummary.safeParse({ ...summary, summary: { ...summary.summary, ...extra } }).success, false);
  }
});

test('summary preserves exact historical money date units and evidence semantics', () => {
  const cents = { ...summary, summary: { ...summary.summary, amount: '0.30', invoices: [{ ...summary.summary.invoices[0],
    amount: '0.30', lines: [{ line_index: 0, amount: '0.10' }, { line_index: 1, amount: '0.20' }] }] } };
  assert.equal(parseSupplierPaymentSummary(cents, expected).summary.amount, '0.30');
  for (const amount of [0.3, '0.3', '0.300', 'NaN', '1e2', '0.00']) {
    assert.equal(supplierPaymentSummary.safeParse({ ...summary, summary: { ...summary.summary, amount } }).success, false);
  }
  assert.equal(supplierPaymentSummary.safeParse({ ...summary, summary: { ...summary.summary, payment_date: '2026-02-30' } }).success, false);
  assert.equal(supplierPaymentStatus.safeParse({ ...status, balance_semantics: 'current_balance' }).success, false);
});

test('summary refuses duplicate membership and inconsistent line or invoice totals', () => {
  const original = summary.summary.invoices[0]!;
  for (const invoices of [[original, original], [{ ...original, amount: '149.00' }],
      [{ ...original, lines: [original.lines[0], original.lines[0]] }]]) {
    assert.equal(supplierPaymentSummary.safeParse({ ...summary, summary: { ...summary.summary, invoices } }).success, false);
  }
});

test('summary refuses aggregate line overflow and preserves maximum bounded Unicode fields', () => {
  const rows = Array.from({ length: 26 }, (_, line_index) => ({ line_index, amount: '1.00' }));
  const invoices = [invoice, operation].map(invoice_id => ({ invoice_id, invoice_version: version, amount: '26.00', lines: rows }));
  assert.equal(supplierPaymentSummary.safeParse({ ...summary, summary: { ...summary.summary, amount: '52.00', invoices } }).success, false);
  const large = Array.from({ length: 10 }, (_, index) => ({ invoice_id: `dddddddd-dddd-4ddd-8ddd-dddddddddd${index.toString().padStart(2, '0')}`,
    invoice_version: version, amount: '5.00', lines: Array.from({ length: 5 }, (_, line_index) => ({ line_index, amount: '1.00' })) }));
  // A valid maximum-shaped response remains bounded and is never shortened.
  const valid = { ...summary, summary: { ...summary.summary, amount: '50.00', payee: '🧑'.repeat(160), external_reference: '財'.repeat(120), invoices: large } };
  assert.equal(supplierPaymentSummary.safeParse(valid).success, true);
  assert.equal(valid.summary.invoices.length, 10);
});

test('empty expected digests cannot bypass an explicitly requested receipt or scope comparison', () => {
  assert.throws(() => parseSupplierPaymentStatus(status, { ...expected, financialReceiptHash: '' }));
  assert.throws(() => parseSupplierPaymentStatus(status, { ...expected, scopeRevision: '' }));
  assert.throws(() => parseSupplierPaymentSummary(summary, { ...expected, paymentVersion: '' }));
});

test('financial read routes accept only canonical UUID and read action without query injection', () => {
  assert.equal(supplierPaymentReadPath(operation, 'status'), `/mobile-sync/finance/supplier-payments/${operation}/status`);
  for (const value of [operation.toUpperCase(), `${operation}?actor=other`, '../payments', 'not-a-uuid']) {
    assert.throws(() => supplierPaymentReadPath(value, 'summary'));
  }
});

test('operational AuthClient still cannot invoke financial routes or any financial mutation', async () => {
  let calls = 0;
  const client = new AuthClient(async () => { calls++; return status; },
    { async read() { return null; }, async write() {} }, async () => {});
  client.setAccess('Synthetic-access');
  await assert.rejects(client.request(supplierPaymentReadPath(operation, 'status')), /route_unavailable/);
  await assert.rejects(client.request('/mobile-sync/finance/push', { amount: '1.00' }), /route_unavailable/);
  assert.equal(calls, 0);
});
