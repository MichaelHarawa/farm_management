import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { test } from 'node:test';
import { canonical } from '../src/db/repository';
import { entity as operationalEntity, pack as operationalPack } from '../src/sync/protocol';
import { referencePackId, referencePackEntity, referencePackManifest, referencePackPage, referencePackDelta,
  parseReferencePackManifest, parseReferencePackDelta, verifyReferencePackPages } from '../src/finance/reference-pack';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const actor = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', epoch = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const entityId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', snapshotId = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
const scope = 'a'.repeat(64), hash = async (value: string) => createHash('sha256').update(value).digest('hex');
const expected = { identity: { deploymentId: deployment, deviceId: device, actorId: actor }, epoch, scopeRevision: scope };
const context = { financial_reference_pack_version: 1, pack_id: referencePackId, deployment_id: deployment,
  stream_epoch: epoch, device_id: device, actor_id: actor, scope_revision: scope, server_time: '2026-10-15T15:00:00Z',
  access: 'online_only_current_finance_writer', offline_cache_seconds: 0, financial_uploads: false };
const reference = { reference_id: actor, reference_version: scope, source_type: 'loan', label: 'Synthetic source', currency: 'MWK',
  cash_pool_id: actor, cash_pool_semantics: 'source_specific', balance_semantics: 'not_a_cash_balance_or_reservation' };
const funding = { entity_type: 'finance.funding_selection', entity_uuid: entityId, revision: '9007199254740993',
  payload: { financial_projection_version: 1, reference, available: true, source_version: scope } };
const invoice = { entity_type: 'finance.invoice_reference', entity_uuid: snapshotId, revision: '1',
  payload: { financial_projection_version: 1, invoice: { invoice_group_id: device, invoice_version: scope, supplier: 'Synthetic supplier',
    invoice_reference: 'SYNTHETIC-PACK-001', purchase_date: '2026-01-01', currency: 'MWK', original_total_purchase_cost: '150.00',
    line_count: 2, recorded_at: context.server_time, evidence: 'immutable_original_invoice', balance_semantics: 'original_purchase_not_current_outstanding' } } };

async function fixture(groups: unknown[][] = [[funding], [invoice]]) {
  const rows = groups.flat();
  const shared = { ...context, snapshot_id: snapshotId, watermark: '9007199254740995', expires_at: '2026-10-15T15:15:00Z',
    catalog_version: await hash(canonical({ basis: 'financial-reference-pack-private-v1', scope, rows })) };
  const pages = await Promise.all(groups.map(async (entities, page) => ({ ...shared, entities, page, sha256: await hash(canonical(entities)),
    next_page_cursor: page < groups.length - 1 ? `signed-page-${page + 1}` : null,
    delta_cursor: page === groups.length - 1 ? 'signed-delta' : null })));
  const manifest = { ...shared, row_count: rows.length, manifest: pages.map(page => ({ page: page.page,
    row_count: page.entities.length, sha256: page.sha256 })), next_page_cursor: 'signed-page-0' };
  return { manifest, pages, rows };
}
const fragment = { transaction_id: snapshotId, fragment_index: 0, fragment_final: true };
const upsert = { ...funding, ...fragment, sequence: '9007199254740994', kind: 'upsert' };
const delta = { ...context, run_watermark: '9007199254740995', changes: [upsert], fragments: [fragment], next_cursor: 'signed-next', run_complete: true };

test('complete private reference pack preserves exact original values without cache or posting authority', async () => {
  const data = await fixture(), original = structuredClone(data);
  const verified = await verifyReferencePackPages(data.manifest, data.pages, expected, hash);
  assert.deepEqual(verified.rows, data.rows);
  assert.equal(verified.deltaCursor, 'signed-delta');
  assert.equal(verified.rows[0]?.revision, '9007199254740993');
  assert.deepEqual(data, original);
});

test('empty complete reference scope has a genuine hashed empty page', async () => {
  const data = await fixture([[]]);
  const result = await verifyReferencePackPages(data.manifest, data.pages, expected, hash);
  assert.deepEqual(result.rows, []);
  assert.equal(result.manifest.row_count, 0);
});

test('positive financial references cannot expand operational profiles or accepted pack names', () => {
  assert.equal(referencePackEntity.safeParse(funding).success, true);
  assert.equal(operationalEntity.safeParse(funding).success, false);
  assert.equal(operationalPack.safeParse(referencePackId).success, false);
  assert.equal(referencePackEntity.safeParse({ ...funding, entity_type: 'poultry.batch' }).success, false);
});

test('reference entities refuse private fields fake balances unsupported versions and unsafe revision counters', () => {
  for (const extra of [{ source_pk: '7' }, { owner_id: actor }, { available_balance: '100.00' }, { notes: 'Private' }]) {
    assert.equal(referencePackEntity.safeParse({ ...funding, ...extra }).success, false);
    assert.equal(referencePackEntity.safeParse({ ...funding, payload: { ...funding.payload, ...extra } }).success, false);
  }
  for (const value of [0, 1, '0', '01', '1\n', '1.0', '9223372036854775808']) {
    assert.equal(referencePackEntity.safeParse({ ...funding, revision: value }).success, false);
  }
  assert.equal(referencePackEntity.safeParse({ ...funding, payload: { ...funding.payload, financial_projection_version: 2 } }).success, false);
  assert.equal(referencePackEntity.safeParse({ ...invoice, payload: { ...invoice.payload,
    invoice: { ...invoice.payload.invoice, original_total_purchase_cost: 150 } } }).success, false);
});

test('every envelope binds exact deployment actor device epoch scope and forbids an offline grant', async () => {
  const data = await fixture();
  for (const extra of [{ deployment_id: actor }, { device_id: actor }, { actor_id: device }, { stream_epoch: actor }, { scope_revision: 'b'.repeat(64) }]) {
    assert.throws(() => parseReferencePackManifest({ ...data.manifest, ...extra }, expected));
    assert.throws(() => parseReferencePackDelta({ ...delta, ...extra }, expected));
    await assert.rejects(verifyReferencePackPages(data.manifest, data.pages.map(page => ({ ...page, ...extra })), expected, hash));
  }
  for (const extra of [{ offline_cache_seconds: 86400 }, { financial_uploads: true }, { policy_version: 1 }, { pack_id: 'operational-current-v1' }]) {
    assert.equal(referencePackManifest.safeParse({ ...data.manifest, ...extra }).success, false);
    assert.equal(referencePackDelta.safeParse({ ...delta, ...extra }).success, false);
  }
});

test('manifest refuses incomplete counts repeated pages empty intermediate pages and expired or extended lifetime', async () => {
  const { manifest } = await fixture();
  for (const extra of [{ row_count: 3 }, { manifest: [] }, { manifest: [manifest.manifest[0], manifest.manifest[0]] },
    { expires_at: context.server_time }, { expires_at: '2026-10-15T15:15:01Z' }, { watermark: '1\n' }, { watermark: '9223372036854775808' }]) {
    assert.equal(referencePackManifest.safeParse({ ...manifest, ...extra }).success, false);
  }
  const empty = await fixture([[], [funding]]);
  assert.equal(referencePackManifest.safeParse(empty.manifest).success, false);
});

test('all pages and exact content checksums are required before a delta cursor is usable', async () => {
  const data = await fixture();
  for (const pages of [[], [data.pages[0]], [...data.pages].reverse(), [data.pages[0], data.pages[0]]]) {
    await assert.rejects(verifyReferencePackPages(data.manifest, pages, expected, hash));
  }
  for (const extra of [{ watermark: '1' }, { snapshot_id: actor }, { expires_at: '2026-10-15T15:14:59Z' },
    { catalog_version: 'b'.repeat(64) }, { sha256: 'b'.repeat(64) }, { delta_cursor: 'premature-delta' }]) {
    const pages = data.pages.map((page, index) => index === 0 ? { ...page, ...extra } : page);
    await assert.rejects(verifyReferencePackPages(data.manifest, pages, expected, hash));
  }
  const changed = data.pages.map((page, index) => index === 0 ? { ...page, entities: [{ ...funding, revision: '2' }] } : page);
  await assert.rejects(verifyReferencePackPages(data.manifest, changed, expected, hash));
});

test('page ending and original catalog hash cannot be forged with individually valid pages', async () => {
  const data = await fixture();
  await assert.rejects(verifyReferencePackPages({ ...data.manifest, catalog_version: 'b'.repeat(64) },
    data.pages.map(page => ({ ...page, catalog_version: 'b'.repeat(64) })), expected, hash));
  const final = data.pages.map(page => ({ ...page, delta_cursor: null, next_page_cursor: 'not-final' }));
  await assert.rejects(verifyReferencePackPages(data.manifest, final, expected, hash));
  assert.equal(referencePackPage.safeParse({ ...data.pages[0], next_page_cursor: null, delta_cursor: null }).success, false);
});

test('repeated or reordered UUIDs refuse even when the catalog and all page hashes match', async () => {
  for (const groups of [[[funding], [funding]], [[invoice], [funding]], [[funding], [{ ...invoice, entity_uuid: entityId }]]]) {
    const data = await fixture(groups);
    await assert.rejects(verifyReferencePackPages(data.manifest, data.pages, expected, hash));
  }
});

test('delta uses exact bigint sequence bounds and never accepts earlier visible work', () => {
  assert.deepEqual(parseReferencePackDelta(delta, expected, '9007199254740993'), delta);
  assert.throws(() => parseReferencePackDelta(delta, expected, '9007199254740994'));
  assert.throws(() => parseReferencePackDelta(delta, expected, '9007199254740996'));
  for (const value of [9007199254740994, '01', '1.0', '1\n', '9223372036854775808']) {
    assert.equal(referencePackDelta.safeParse({ ...delta, changes: [{ ...upsert, sequence: value }] }).success, false);
  }
  assert.equal(referencePackDelta.safeParse({ ...delta, run_watermark: '9007199254740993' }).success, false);
});

test('hidden-only final fragments are valid but incomplete runs cannot claim completion', () => {
  assert.equal(referencePackDelta.safeParse({ ...delta, changes: [] }).success, true);
  assert.equal(referencePackDelta.safeParse({ ...delta, changes: [], run_complete: false,
    fragments: [{ ...fragment, fragment_final: false }] }).success, true);
  assert.equal(referencePackDelta.safeParse({ ...delta, fragments: [{ ...fragment, fragment_final: false }] }).success, false);
  assert.equal(referencePackDelta.safeParse({ ...delta, fragments: [] }).success, false);
  assert.equal(referencePackDelta.safeParse({ ...delta, fragments: [fragment, fragment] }).success, false);
});

test('delta fragment membership flags order and tombstone identity are strict', () => {
  for (const changes of [[{ ...upsert, transaction_id: actor }], [{ ...upsert, fragment_index: 1 }],
    [{ ...upsert, fragment_final: false }], [upsert, upsert]]) {
    assert.equal(referencePackDelta.safeParse({ ...delta, changes }).success, false);
  }
  const tombstone = { entity_type: 'finance.funding_selection', entity_uuid: entityId, revision: '2',
    ...fragment, sequence: '9007199254740994', kind: 'tombstone' };
  assert.equal(referencePackDelta.safeParse({ ...delta, changes: [tombstone] }).success, true);
  for (const extra of [{ payload: {} }, { entity_type: 'finance.invoice_reference' }, { revision: '1' }, { kind: 'evict_from_pack' }]) {
    assert.equal(referencePackDelta.safeParse({ ...delta, changes: [{ ...tombstone, ...extra }] }).success, false);
  }
});

test('UTF-8 byte budgets fail explicitly and schema does not silently trim original labels', async () => {
  const data = await fixture();
  assert.equal(referencePackManifest.safeParse({ ...data.manifest, next_page_cursor: 'x'.repeat(4097) }).success, false);
  assert.equal(referencePackEntity.safeParse({ ...funding, payload: { ...funding.payload,
    reference: { ...reference, label: ' Synthetic source ' } } }).success, false);
  const oversized = { ...data.pages[0], entities: Array.from({ length: 51 }, () => funding) };
  assert.equal(referencePackPage.safeParse(oversized).success, false);
});
