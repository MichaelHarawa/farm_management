import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fundingReferencePage, fundingReferenceRows, parseFundingReferencePage,
  verifyFundingReferencePages } from '../src/finance/funding-references';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const source = 'cccccccc-cccc-5ccc-8ccc-cccccccccccc';
const second = 'dddddddd-dddd-5ddd-8ddd-dddddddddddd';
const scope = 'a'.repeat(64), version = 'b'.repeat(64);
const row = { reference_id: source, reference_version: version, source_type: 'loan', label: 'Synthetic loan',
  currency: 'MWK', cash_pool_id: source, cash_pool_semantics: 'source_specific', balance_semantics: 'not_a_cash_balance_or_reservation' };
const page = { financial_reference_version: 1, deployment_id: deployment, device_id: device, scope_revision: scope,
  catalog_version: version, server_time: '2026-10-14T12:00:00Z', access: 'online_only_current_finance_writer',
  offline_cache_seconds: 0, financial_uploads: false, total_authorized_rows: 1, rows: [row], next_cursor: null };
const expected = { identity: { deploymentId: deployment, deviceId: device, actorId: source }, scopeRevision: scope, catalogVersion: version };
const selection = [{ funding_source: source, funding_version: version, amount: '50.00', classification: 'reinvestment' }];

test('funding pages and exact selections are separate nonmutating no-balance contracts', () => {
  const before = structuredClone([page, selection]);
  assert.deepEqual(parseFundingReferencePage(page, expected), page);
  assert.deepEqual(fundingReferenceRows.parse(selection), selection);
  assert.deepEqual([page, selection], before);
  assert.deepEqual(verifyFundingReferencePages([page], expected), [row]);
});

test('funding catalog refuses foreign device deployment scope and version', () => {
  for (const change of [{ deployment_id: source }, { device_id: source }, { scope_revision: version }, { catalog_version: scope }]) {
    assert.throws(() => parseFundingReferencePage({ ...page, ...change }, expected));
  }
});

test('positive funding pages reject owner/source PK notes balances future fields and offline grants', () => {
  for (const change of [{ current_balance: '200.00' }, { offline_cache_seconds: 86400 }, { financial_uploads: true }, { actor_id: source }]) {
    assert.equal(fundingReferencePage.safeParse({ ...page, ...change }).success, false);
  }
  for (const change of [{ owner_id: source }, { server_id: '9007199254740993' }, { notes: 'Private' },
    { current_balance: '200.00' }, { source_type: 'future-financial-source' }, { label: '  untrimmed  ' }]) {
    assert.equal(fundingReferencePage.safeParse({ ...page, rows: [{ ...row, ...change }] }).success, false);
  }
});

test('funding identity inputs refuse raw PK numeric or rounded money and extras', () => {
  for (const change of [{ funding_source: '9007199254740993' }, { funding_source: 7 }, { amount: 50 }, { amount: 50.01 },
    { amount: '1e2' }, { amount: '50.001' }, { amount: '0.00' }, { amount: '050.00' }, { owner_id: source },
    { classification: 'loan' }, { funding_version: 'invalid' }, { funding_source: source.toUpperCase() },
    { amount: '50.00\n' }, { amount: '50.00\r\n' }, { funding_version: `${version}\n` }]) {
    assert.equal(fundingReferenceRows.safeParse([{ ...selection[0], ...change }]).success, false);
  }
  assert.equal(fundingReferenceRows.safeParse([...selection, ...selection]).success, false);
  assert.equal(fundingReferenceRows.safeParse([]).success, false);
  assert.equal(fundingReferenceRows.safeParse(Array(101).fill(selection[0])).success, false);
  assert.equal(fundingReferenceRows.parse([{ ...selection[0], amount: '999999999999.99' }])[0]?.amount, '999999999999.99');
});

test('shared batch aliases identify one cash pool without granting amounts or a cost bearer', () => {
  const alias = { ...row, source_type: 'batch_collection', cash_pool_id: second, cash_pool_semantics: 'shared_batch_collection' };
  assert.equal(fundingReferencePage.safeParse({ ...page, rows: [alias] }).success, true);
  for (const change of [{ source_type: 'loan' }, { cash_pool_semantics: 'source_specific' }]) {
    assert.equal(fundingReferencePage.safeParse({ ...page, rows: [{ ...alias, ...change }] }).success, false);
  }
  assert.equal(fundingReferencePage.safeParse({ ...page, rows: [{ ...row, cash_pool_id: second }] }).success, false);
});

test('catalog completeness checks reject interrupted reordered overlapping or changed pages', () => {
  const first = { ...page, total_authorized_rows: 2, next_cursor: 'opaque-signed-cursor' };
  const last = { ...first, rows: [{ ...row, reference_id: second, cash_pool_id: second }], next_cursor: null };
  assert.equal(verifyFundingReferencePages([first, last], expected).length, 2);
  for (const pages of [[], [first], [last, first], [first, { ...last, catalog_version: scope }],
    [first, { ...last, scope_revision: version }], [first, { ...last, rows: [row] }], [first, { ...last, total_authorized_rows: 3 }]]) {
    assert.throws(() => verifyFundingReferencePages(pages, expected));
  }
  assert.equal(fundingReferencePage.safeParse({ ...first, rows: [] }).success, false);
  assert.equal(fundingReferencePage.safeParse({ ...page, rows: [row, row] }).success, false);
});
