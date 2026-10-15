import assert from 'node:assert/strict';
import { test } from 'node:test';
import { invoiceReferencePage, invoiceReferenceDetail, parseInvoiceReferencePage,
  parseInvoiceReferenceDetail, verifyInvoiceReferencePages } from '../src/finance/invoice-references';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const group = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const second = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const scope = 'a'.repeat(64), version = 'b'.repeat(64);
const context = { invoice_reference_version: 1, deployment_id: deployment, device_id: device, scope_revision: scope,
  server_time: '2026-10-15T12:00:00.000001Z', access: 'online_only_original_actor_finance_writer',
  offline_cache_seconds: 0, financial_uploads: false };
const invoice = { invoice_group_id: group, invoice_version: version, supplier: 'Synthetic supplier',
  invoice_reference: 'SYNTHETIC-001', purchase_date: '2026-01-01', currency: 'MWK',
  original_total_purchase_cost: '150.00', line_count: 2, recorded_at: context.server_time,
  evidence: 'immutable_original_invoice', balance_semantics: 'original_purchase_not_current_outstanding' };
const line = { invoice_line_index: 0, original_item_name: 'Original stock', original_location_name: 'Original store',
  captured_quantity: '2.0000', captured_unit: 'bag', base_quantity: '100.0000', base_unit: 'kg',
  original_line_cost: '100.00', expiry_date: null };
const detail = { ...context, detail_version: version, invoice, lines: [line, { ...line, invoice_line_index: 1, original_line_cost: '50.00' }],
  proof: 'original_invoice_sources_and_purchase_journals', label_semantics: 'original_purchase_names_and_values',
  payment_authority: 'none_revalidate_payables_and_cash_on_posting' };
const page = { ...context, catalog_version: version, total_authorized_rows: 1, rows: [invoice], next_cursor: null };
const expected = { identity: { deploymentId: deployment, deviceId: device, actorId: group }, scopeRevision: scope,
  invoiceId: group, invoiceVersion: version, catalogVersion: version };

test('original invoice pages and detail retain exact values without claiming payable authority', () => {
  const original = structuredClone([page, detail]);
  assert.deepEqual(parseInvoiceReferencePage(page, expected), page);
  assert.deepEqual(parseInvoiceReferenceDetail(detail, expected), detail);
  assert.deepEqual(verifyInvoiceReferencePages([page], expected), [invoice]);
  assert.deepEqual([page, detail], original);
});

test('financial invoice contracts refuse extra private fields money claims and offline grants', () => {
  for (const extra of [{ offline_cache_seconds: 86400 }, { financial_uploads: true }, { actor_id: group }, { notes: 'Private' }]) {
    assert.equal(invoiceReferencePage.safeParse({ ...page, ...extra }).success, false);
    assert.equal(invoiceReferenceDetail.safeParse({ ...detail, ...extra }).success, false);
  }
  for (const extra of [{ amount_due: '10.00' }, { payment_status: 'unpaid' }, { notes: 'Private' }, { server_id: '7' }]) {
    assert.equal(invoiceReferencePage.safeParse({ ...page, rows: [{ ...invoice, ...extra }] }).success, false);
  }
  for (const extra of [{ item_id: '7' }, { lot_id: group }, { quantity_available: '10.0000' }, { current_item_name: 'Changed' }]) {
    assert.equal(invoiceReferenceDetail.safeParse({ ...detail, lines: [{ ...line, ...extra }, detail.lines[1]] }).success, false);
  }
});

test('invoice selection is scoped to current deployment device revision and exact parent version', () => {
  for (const extra of [{ deployment_id: group }, { device_id: group }, { scope_revision: version }]) {
    assert.throws(() => parseInvoiceReferencePage({ ...page, ...extra }, expected));
    assert.throws(() => parseInvoiceReferenceDetail({ ...detail, ...extra }, expected));
  }
  assert.throws(() => parseInvoiceReferencePage({ ...page, catalog_version: scope }, expected));
  assert.throws(() => parseInvoiceReferenceDetail({ ...detail, invoice: { ...invoice, invoice_version: scope } }, expected));
  assert.throws(() => parseInvoiceReferenceDetail(detail, { ...expected, invoiceId: second }));
});

test('exact invoice money quantities dates and identifiers refuse numeric rounded or normalized evidence', () => {
  for (const value of [150, '150', '150.001', '1.5e2', '0150.00', '150.00\n', '150.00\r\n', '0.00']) {
    assert.equal(invoiceReferencePage.safeParse({ ...page, rows: [{ ...invoice, original_total_purchase_cost: value }] }).success, false);
  }
  for (const value of [2, '2', '2.00001', '02.0000', '2.0000\n', '0.0000']) {
    assert.equal(invoiceReferenceDetail.safeParse({ ...detail, lines: [{ ...line, captured_quantity: value }, detail.lines[1]] }).success, false);
  }
  for (const extra of [{ invoice_group_id: '7' }, { invoice_group_id: group.toUpperCase() }, { invoice_version: version + '\n' },
    { purchase_date: '2026-02-30' }, { recorded_at: context.server_time + '\n' }, { recorded_at: '2026-10-15T12:00:00.1234567Z' }]) {
    assert.equal(invoiceReferencePage.safeParse({ ...page, rows: [{ ...invoice, ...extra }] }).success, false);
  }
});

test('detail refuses missing duplicate reordered or guessed lines and changed original totals', () => {
  for (const lines of [[line], [line, line], [...detail.lines].reverse(), [line, { ...line, invoice_line_index: 2 }],
    [line, { ...detail.lines[1], original_line_cost: '49.99' }]]) {
    assert.equal(invoiceReferenceDetail.safeParse({ ...detail, lines }).success, false);
  }
  assert.equal(invoiceReferenceDetail.safeParse({ ...detail, invoice: { ...invoice, line_count: 3 } }).success, false);
});

test('completeness checks reject interrupted overlapping stale and reordered catalog pages', () => {
  const first = { ...page, total_authorized_rows: 2, next_cursor: 'opaque-cursor' };
  const last = { ...first, rows: [{ ...invoice, invoice_group_id: second }], next_cursor: null };
  assert.equal(verifyInvoiceReferencePages([first, last], expected).length, 2);
  for (const pages of [[], [first], [last, first], [first, { ...last, rows: [invoice] }],
    [first, { ...last, catalog_version: scope }], [first, { ...last, total_authorized_rows: 3 }]]) {
    assert.throws(() => verifyInvoiceReferencePages(pages, expected));
  }
  assert.equal(invoiceReferencePage.safeParse({ ...first, rows: [] }).success, false);
  assert.equal(invoiceReferencePage.safeParse({ ...page, rows: [invoice, invoice] }).success, false);
});

test('large exact totals use decimal arithmetic and never binary floating point', () => {
  const large = { ...detail, invoice: { ...invoice, original_total_purchase_cost: '999999999999.99' },
    lines: [{ ...line, original_line_cost: '999999999999.98' }, { ...detail.lines[1], original_line_cost: '0.01' }] };
  assert.equal(invoiceReferenceDetail.safeParse(large).success, true);
  assert.equal(invoiceReferenceDetail.safeParse({ ...large, invoice: { ...large.invoice, original_total_purchase_cost: '999999999999.98' } }).success, false);
});
