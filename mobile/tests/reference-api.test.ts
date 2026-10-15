import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ApiError, AuthClient, httpTransport, type Credentials, type TransportOptions } from '../src/auth/client';
import { FinancialReferenceReader, referenceCapabilities } from '../src/finance/reference-client';
import { isFinancialReferencePath, referenceCatalogPath, referenceInvoicePath, referenceRoot } from '../src/finance/reference-paths';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const actor = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', invoiceId = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const identity = { deploymentId: deployment, deviceId: device, actorId: actor };
const fundingScope = 'a'.repeat(64), invoiceScope = 'b'.repeat(64), version = 'c'.repeat(64);
const time = '2026-10-15T14:00:00.123456Z';
const capabilities = { financial_reference_api_version: 1, deployment_id: deployment, device_id: device, actor_id: actor,
  server_time: time, access: 'online_only_current_finance_writer', offline_cache_seconds: 0, financial_uploads: false,
  packs: [], profiles: { funding: 1, original_invoices: 1 }, scopes: { funding: fundingScope, original_invoices: invoiceScope },
  limits: { funding_rows: 1000, funding_page_rows: 50, funding_catalog_bytes: 524288, invoice_rows: 100,
    invoice_page_rows: 25, invoice_catalog_bytes: 524288, invoice_detail_bytes: 65536, invoice_lines: 50, cursor_seconds: 900 } };
const funding = { financial_reference_version: 1, deployment_id: deployment, device_id: device, scope_revision: fundingScope,
  catalog_version: version, server_time: time, access: 'online_only_current_finance_writer', offline_cache_seconds: 0,
  financial_uploads: false, total_authorized_rows: 0, rows: [], next_cursor: null };
const invoice = { invoice_group_id: invoiceId, invoice_version: version, supplier: 'Synthetic supplier', invoice_reference: 'SYNTHETIC-001',
  purchase_date: '2026-01-01', currency: 'MWK', original_total_purchase_cost: '150.00', line_count: 2,
  recorded_at: time, evidence: 'immutable_original_invoice', balance_semantics: 'original_purchase_not_current_outstanding' };
const invoices = { invoice_reference_version: 1, deployment_id: deployment, device_id: device, scope_revision: invoiceScope,
  catalog_version: version, server_time: time, access: 'online_only_original_actor_finance_writer', offline_cache_seconds: 0,
  financial_uploads: false, total_authorized_rows: 1, rows: [invoice], next_cursor: null };
const line = { invoice_line_index: 0, original_item_name: 'Original stock', original_location_name: 'Original store',
  captured_quantity: '10.0000', captured_unit: 'kg', base_quantity: '10.0000', base_unit: 'kg', original_line_cost: '100.00', expiry_date: null };
const detail = { invoice_reference_version: 1, deployment_id: deployment, device_id: device, scope_revision: invoiceScope,
  server_time: time, access: 'online_only_original_actor_finance_writer', offline_cache_seconds: 0, financial_uploads: false,
  detail_version: version, invoice, lines: [line, { ...line, invoice_line_index: 1, original_line_cost: '50.00' }],
  proof: 'original_invoice_sources_and_purchase_journals', label_semantics: 'original_purchase_names_and_values',
  payment_authority: 'none_revalidate_payables_and_cash_on_posting' };
const store = { async read(): Promise<Credentials> { return { refresh: 'synthetic-refresh', rotation: 'ready' }; }, async write() {} };

test('reference paths are exact bounded canonical GET locations, not financial dispatch', () => {
  for (const path of [`${referenceRoot}/capabilities`, referenceCatalogPath('funding'), referenceCatalogPath('invoices', 'signed:opaque.cursor-_~'),
    referenceInvoicePath(invoiceId, version)]) assert.equal(isFinancialReferencePath(path), true);
  for (const path of ['/auth/me', '/mobile-sync/finance/push', '/mobile-sync/push', `${referenceRoot}/funding/prepare`,
    `${referenceRoot}/funding?cursor=`, `${referenceRoot}/funding?cursor=a&actor_id=${actor}`, `${referenceRoot}/funding?cursor=a&cursor=b`,
    `${referenceRoot}/capabilities?fields=notes`, `${referenceRoot}/invoices/../funding`, `${referenceRoot}/funding?cursor=%ZZ`,
    `${referenceRoot}/funding?cursor=%61`, `${referenceRoot}/invoices/${invoiceId}?invoice_version=${version}&amount=1`,
    `${referenceRoot}/invoices/${invoiceId}?invoice_version=${version}\n`]) assert.equal(isFinancialReferencePath(path), false, path);
  assert.throws(() => referenceCatalogPath('funding', 'x'.repeat(2049)));
  assert.throws(() => referenceInvoicePath(invoiceId.toUpperCase(), version));
  assert.throws(() => referenceInvoicePath(invoiceId, version + '\n'));
});

test('ordinary auth requests still refuse every financial route before sending', async () => {
  let sent = 0;
  const auth = new AuthClient(async () => { sent++; return {}; }, store, async () => {});
  auth.setAccess('synthetic-access');
  for (const path of [`${referenceRoot}/capabilities`, `${referenceRoot}/funding`, '/mobile-sync/finance/push']) {
    await assert.rejects(auth.request(path), /route_unavailable/);
  }
  await assert.rejects(auth.readFinancialReference('/mobile-sync/push'), /route_unavailable/);
  assert.equal(sent, 0);
});

test('new read method carries only explicit reference options and no body', async () => {
  const auth = new AuthClient(async (path, body, access, options) => {
    assert.equal(path, referenceCatalogPath('funding', 'signed:cursor'));
    assert.equal(body, undefined);
    assert.equal(access, 'synthetic-access');
    assert.deepEqual(options, { financialReferences: 1 });
    return funding;
  }, store, async () => {});
  auth.setAccess('synthetic-access');
  assert.deepEqual(await auth.readFinancialReference(referenceCatalogPath('funding', 'signed:cursor')), funding);
});

test('reference 401s use one durable rotation then retry safe GETs without losing options', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' };
  let rotations = 0, reads = 0;
  const auth = new AuthClient(async (path, body, access, options) => {
    if (path === '/auth/refresh') {
      rotations++; assert.equal(stored.rotation, 'in_flight'); assert.equal(options, undefined);
      await new Promise(resolve => setTimeout(resolve, 10));
      return { access: 'new-access', refresh: 'new-refresh' };
    }
    assert.equal(body, undefined); assert.deepEqual(options, { financialReferences: 1 });
    if (access !== 'new-access') throw new ApiError(401, 'expired');
    assert.equal(stored.refresh, 'new-refresh'); reads++; return funding;
  }, { async read() { return stored; }, async write(value) { stored = value; } }, async () => assert.fail('Unexpected denial'));
  auth.setAccess('expired');
  await Promise.all(Array.from({ length: 12 }, () => auth.readFinancialReference(referenceCatalogPath('funding'))));
  assert.equal(rotations, 1); assert.equal(reads, 12);
});

test('reference 403 locks and does not rotate; late locked results cannot escape', async () => {
  let sent = 0, denied = 0;
  const auth = new AuthClient(async () => { sent++; throw new ApiError(403, 'device_revoked'); }, store, async () => { denied++; });
  auth.setAccess('synthetic-access');
  await assert.rejects(auth.readFinancialReference(`${referenceRoot}/capabilities`));
  await assert.rejects(auth.readFinancialReference(`${referenceRoot}/capabilities`), /session_locked/);
  assert.equal(sent, 1); assert.equal(denied, 1);
  let finish!: (value: unknown) => void;
  const racing = new AuthClient(() => new Promise(resolve => { finish = resolve; }), store, async () => {});
  racing.setAccess('synthetic-access');
  const request = racing.readFinancialReference(referenceCatalogPath('funding'));
  const rejected = assert.rejects(request, /session_locked/);
  racing.lock(); finish(funding); await rejected;
});

test('reader obtains actor-bound scopes before accepting positive pages and exact detail', async () => {
  const paths: string[] = [];
  const reader = await FinancialReferenceReader.open({ async readFinancialReference(path) {
    paths.push(path);
    if (path.endsWith('/capabilities')) return capabilities;
    if (path.endsWith('/funding')) return funding;
    if (path.endsWith('/invoices')) return invoices;
    return detail;
  } }, identity);
  assert.deepEqual(await reader.fundingPage(), funding);
  assert.deepEqual(await reader.invoicePage(), invoices);
  assert.deepEqual(await reader.invoiceDetail(invoiceId, version), detail);
  assert.equal(paths.length, 4);
  assert.equal(paths[3], referenceInvoicePath(invoiceId, version));
});

test('capability identity profile or offline grants cannot be silently adopted', async () => {
  for (const change of [{ actor_id: invoiceId }, { deployment_id: invoiceId }, { device_id: invoiceId }, { financial_uploads: true },
    { offline_cache_seconds: 86400 }, { packs: ['financial-current'] }, { profiles: { funding: 2, original_invoices: 1 } },
    { source_balance: '100.00' }, { server_time: time + '\n' }]) {
    await assert.rejects(FinancialReferenceReader.open({ async readFinancialReference() { return { ...capabilities, ...change }; } }, identity));
  }
  assert.deepEqual(referenceCapabilities.parse(capabilities), capabilities);
});

test('reader refuses scope changes without refreshing parents or mutating input', async () => {
  const original = structuredClone([capabilities, funding, invoices, detail]);
  const reader = await FinancialReferenceReader.open({ async readFinancialReference(path) {
    if (path.endsWith('/capabilities')) return capabilities;
    if (path.endsWith('/funding')) return { ...funding, scope_revision: invoiceScope };
    if (path.endsWith('/invoices')) return { ...invoices, scope_revision: fundingScope };
    return { ...detail, invoice: { ...invoice, invoice_version: fundingScope } };
  } }, identity);
  await assert.rejects(reader.fundingPage(), /scope_changed/);
  await assert.rejects(reader.invoicePage(), /scope_changed/);
  await assert.rejects(reader.invoiceDetail(invoiceId, version), /parent_changed/);
  assert.deepEqual([capabilities, funding, invoices, detail], original);
});

test('reader copies identity/scopes and close fences a result still in flight', async () => {
  const mutable = structuredClone(identity), supplied = structuredClone(capabilities);
  let finish!: (value: unknown) => void;
  const reader = await FinancialReferenceReader.open({ async readFinancialReference(path) {
    if (path.endsWith('/capabilities')) return supplied;
    return new Promise(resolve => { finish = resolve; });
  } }, mutable);
  mutable.actorId = invoiceId; supplied.scopes.funding = invoiceScope;
  const flight = reader.fundingPage();
  const rejected = assert.rejects(flight, /session_closed/);
  reader.close(); finish(funding); await rejected;
  await assert.rejects(reader.invoicePage(), /session_closed/);
});

test('HTTP reference GET sends both opt-in headers and no cache, not poultry or write headers', async () => {
  const original = globalThis.fetch;
  const seen: RequestInit[] = [];
  globalThis.fetch = async (_input, init) => { seen.push(init!); return new Response(JSON.stringify(funding), { status: 200 }); };
  try {
    const transport = httpTransport('https://synthetic.example.invalid/api/v1', 2);
    await transport(referenceCatalogPath('funding'), undefined, 'synthetic-access', { financialReferences: 1 });
    assert.equal(seen[0]?.method, 'GET'); assert.equal(seen[0]?.body, undefined); assert.equal(seen[0]?.cache, 'no-store');
    const headers = new Headers(seen[0]?.headers);
    assert.equal(headers.get('X-Mobile-Finance-Version'), '1');
    assert.equal(headers.get('X-Mobile-Finance-References-Version'), '1');
    assert.equal(headers.get('X-Mobile-Poultry-Version'), null);
    assert.equal(headers.get('Authorization'), 'Bearer synthetic-access');
    await transport('/mobile-sync/capabilities', undefined, 'synthetic-access');
    const ordinary = new Headers(seen[1]?.headers);
    assert.equal(ordinary.get('X-Mobile-Finance-Version'), null);
    assert.equal(ordinary.get('X-Mobile-Poultry-Version'), '2');
    for (const [path, body, options] of [
      ['/mobile-sync/push', undefined, { financialReferences: 1 }],
      [referenceCatalogPath('funding'), { amount: '1.00' }, { financialReferences: 1 }],
      [referenceCatalogPath('funding'), undefined, { financialReferences: 2 }],
    ] as const) await assert.rejects(transport(path, body, 'synthetic-access', options as TransportOptions), /route_unavailable/);
    assert.equal(seen.length, 2);
  } finally { globalThis.fetch = original; }
});

test('HTTP reference errors expose fixed codes only and do not change ordinary transport codes', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ code: 'invoice_catalog_changed', message: 'PRIVATE-DO-NOT-ECHO' }), { status: 409 });
  const transport = httpTransport('https://synthetic.example.invalid/api/v1');
  try {
    await assert.rejects(transport(referenceCatalogPath('invoices'), undefined, 'synthetic', { financialReferences: 1 }), /invoice_catalog_changed/);
    await assert.rejects(transport('/mobile-sync/capabilities', undefined, 'synthetic'), /request_409/);
    globalThis.fetch = async () => new Response(JSON.stringify({ code: 'PRIVATE-DO-NOT-ECHO', message: 'secret' }), { status: 503 });
    await assert.rejects(transport(referenceCatalogPath('invoices'), undefined, 'synthetic', { financialReferences: 1 }), error => {
      assert.ok(error instanceof ApiError); assert.equal(error.code, 'mobile_backend_not_ready');
      assert.doesNotMatch(error.message, /PRIVATE|secret/); return true;
    });
  } finally { globalThis.fetch = original; }
});
