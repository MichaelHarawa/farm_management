import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import { test, type TestContext } from 'node:test';
import { FinancialEvidenceStore, financialEvidenceHashInput } from '../src/finance/evidence-store';
import { financialUUIDOperation } from '../src/finance/uuid-commands';
import { financialStorageGrant, parseFinancialStorageGrant, checkFinancialEvidenceClock,
  type FinancialStorageContext } from '../src/finance/storage-policy';
import { hostDatabase, identity } from './helpers';
import { canonical, migrate } from '../src/db/repository';
import type { Database, SqlConnection } from '../src/db/sql';

const now = Date.parse('2026-10-15T16:00:00.000Z');
const sha = async (text: string) => createHash('sha256').update(text).digest('hex');
const context: FinancialStorageContext = { ...identity, sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  streamEpoch: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', scopeRevision: 'a'.repeat(64) };
const grant = { financial_storage_version: 1, profile: 'financial-evidence-private-v1', deployment_id: identity.deploymentId,
  actor_id: identity.actorId, device_id: identity.deviceId, session_id: context.sessionId, stream_epoch: context.streamEpoch,
  scope_revision: context.scopeRevision, server_time: new Date(now).toISOString(), expires_at: new Date(now + 86400000).toISOString(),
  maximum_offline_seconds: 86400, access: 'local_evidence_only_not_posting_authority',
  commands: ['inventory.supplier_payment.record'], reference_cache_seconds: 0, financial_uploads: false };
const command = { financial_command_version: 2, operation_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  command: 'inventory.supplier_payment.record', captured_at: '2026-10-15T15:59:59.123456Z', depends_on: [],
  payload: { currency: 'MWK', payee: 'Synthetic café 🐔 supplier', payment_method: 'bank_transfer',
    external_reference: 'SYNTHETIC-EVIDENCE-ONLY', payment_date: '2026-01-12', total_payment_amount: '50.00',
    invoices: [{ invoice_group_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', invoice_version: 'b'.repeat(64), total_payment_amount: '50.00',
      lines: [{ invoice_line_index: 0, amount: '50.00', funding_allocations: [{ funding_source: 'eeeeeeee-eeee-5eee-8eee-eeeeeeeeeeee',
        funding_version: 'c'.repeat(64), amount: '50.00' }] }] }], notes: 'Original physical evidence, not an official receipt' } };
const observation = { requestStartedMs: now, receivedMs: now + 100 };

async function setup(t: TestContext, options: { db?: Database; clock?: () => number; hash?: typeof sha } = {}) {
  const db = options.db ?? hostDatabase();
  const store = await FinancialEvidenceStore.open(db, identity, options.hash ?? sha, options.clock ?? (() => now + 100));
  t.after(() => store.close());
  await store.authorize(grant, context, observation);
  return { db, store };
}
async function raw(db: Database) {
  return { commands: await db.all('SELECT * FROM financial_commands ORDER BY operation_id'),
    delivery: await db.all('SELECT * FROM financial_delivery ORDER BY operation_id') };
}

test('evidence grant is separate, strict, bounded and never permits uploads/reference cache', () => {
  assert.deepEqual(parseFinancialStorageGrant(grant, context, identity), grant);
  for (const change of [{ financial_uploads: true }, { reference_cache_seconds: 86400 }, { balance: '100.00' },
    { commands: [...grant.commands, 'poultry.sale.record'] }, { maximum_offline_seconds: 604800 },
    { expires_at: grant.server_time }, { expires_at: new Date(now + 86400001).toISOString() },
    { scope_revision: context.scopeRevision + '\n' }, { financial_storage_version: true }]) {
    assert.equal(financialStorageGrant.safeParse({ ...grant, ...change }).success, false);
  }
  assert.equal(financialStorageGrant.safeParse({ offline: { sensitive_hours: 24 } }).success, false);
  assert.equal(financialStorageGrant.safeParse({ offline_cache_seconds: 0 }).success, false);
  for (const key of ['actorId', 'deviceId', 'deploymentId', 'sessionId', 'streamEpoch', 'scopeRevision'] as const) {
    assert.throws(() => parseFinancialStorageGrant(grant, { ...context, [key]: key === 'scopeRevision' ? 'f'.repeat(64) : randomUUID() }, identity));
  }
});

test('latency cannot extend expiry; short sessions, rollback and malformed clocks refuse', () => {
  const parsed = financialStorageGrant.parse(grant);
  const clock = { ...observation, highWaterMs: now + 1000 };
  assert.equal(checkFinancialEvidenceClock(parsed, clock, now + 86400000 - 1).highWaterMs, now + 86400000 - 1);
  assert.throws(() => checkFinancialEvidenceClock(parsed, clock, now + 86400000), /window_expired/);
  assert.throws(() => checkFinancialEvidenceClock(parsed, clock, now - 1), /clock_rollback/);
  assert.throws(() => checkFinancialEvidenceClock(parsed, { ...clock, highWaterMs: now + 10000 }, now + 1000), /clock_rollback/);
  for (const changes of [{ receivedMs: now - 1 }, { requestStartedMs: NaN }, { highWaterMs: Infinity },
    { receivedMs: now + 60001, highWaterMs: now + 60001 }, { highWaterMs: now - 1 }]) {
    assert.throws(() => checkFinancialEvidenceClock(parsed, { ...clock, ...changes }, now + 100), /invalid_clock/);
  }
  const short = financialStorageGrant.parse({ ...grant, expires_at: new Date(now + 500).toISOString() });
  assert.throws(() => checkFinancialEvidenceClock(short, { ...clock, receivedMs: now + 500 }, now + 500), /window_expired/);
});

test('twenty exact local retries retain one immutable command and one pending delivery', async t => {
  const { store, db } = await setup(t);
  const original = structuredClone(command);
  for (let index = 0; index < 20; index++) assert.equal((await store.capture(command)).status, 'pending_local_evidence');
  const saved = await raw(db);
  assert.equal(saved.commands.length, 1);
  assert.equal(saved.delivery.length, 1);
  const page = await store.page();
  assert.deepEqual(page.evidence[0]?.operation, original);
  assert.deepEqual(command, original);
  assert.equal(page.next, null);
  assert.equal(page.evidence[0]?.commandHash, await sha(financialEvidenceHashInput(identity, financialUUIDOperation.parse(command))));
  const tables = await db.all<{ name: string }>("SELECT name FROM sqlite_master WHERE type='table'");
  assert.deepEqual(tables.map(row => row.name).sort(), ['financial_commands', 'financial_delivery', 'financial_meta']);
});

test('changed date amount source or capture cannot reuse a saved operation ID', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  const variants = [ { ...command, captured_at: '2026-10-15T15:59:59.123457Z' },
    { ...command, payload: { ...command.payload, total_payment_amount: '51.00' } },
    { ...command, payload: { ...command.payload, payment_date: '2026-01-13' } } ];
  const source = structuredClone(command);
  source.payload.invoices[0]!.lines[0]!.funding_allocations[0]!.funding_source = randomUUID();
  variants.push(source);
  for (const changed of variants) await assert.rejects(store.capture(changed), /idempotency_mismatch/);
  assert.deepEqual(await raw(db), before);
});

test('actual SQLite trigger failure rolls back BOTH command and delivery, retaining earlier work', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  await db.exec("CREATE TRIGGER test_fail_delivery BEFORE INSERT ON financial_delivery BEGIN SELECT RAISE(ABORT,'synthetic_disk_failure'); END;");
  await assert.rejects(store.capture({ ...command, operation_id: randomUUID() }), /synthetic_disk_failure/);
  assert.deepEqual(await raw(db), before);
});

test('immutable SQLite guards prevent editing/deleting original evidence, metadata and delivery', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  for (const sql of ["UPDATE financial_commands SET command_hash='changed'", 'DELETE FROM financial_commands',
    'DELETE FROM financial_delivery', "UPDATE financial_meta SET value='changed' WHERE key='identity'", 'DELETE FROM financial_meta']) {
    await assert.rejects(db.exec(sql), /immutable_financial|retained_financial/);
  }
  assert.deepEqual(await raw(db), before);
});

test('separate on-disk database restarts locked, recovers exact work only after matching private unlock', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'farm-finance-evidence-'));
  const path = join(dir, 'evidence.db');
  const db = hostDatabase(path);
  const first = await FinancialEvidenceStore.open(db, identity, sha, () => now + 100);
  let close = () => first.close();
  t.after(async () => {
    await close(); // Close BEFORE cleanup on Windows; hooks run in registration order.
    await rm(dir, { recursive: true, force: true }); // Only this newly owned test directory.
  });
  await first.authorize(grant, context, observation);
  await first.capture(command);
  const before = await raw(db);
  await first.close();
  close = async () => {};
  const reopenedDB = hostDatabase(path);
  const reopened = await FinancialEvidenceStore.open(reopenedDB, identity, sha, () => now + 200);
  close = () => reopened.close();
  await assert.rejects(reopened.page(), /locked/);
  await reopened.unlock(context);
  assert.deepEqual(await raw(reopenedDB), before);
  assert.deepEqual((await reopened.page()).evidence[0]?.operation, command);
});

test('another actor, deployment or device cannot bind the original database; returning preserves it', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  for (const key of ['actorId', 'deviceId', 'deploymentId'] as const) {
    await assert.rejects(FinancialEvidenceStore.open(db, { ...identity, [key]: randomUUID() }, sha), /identity_mismatch/);
  }
  store.lock();
  await store.unlock(context);
  assert.deepEqual(await raw(db), before);
});

test('operational schema and unknown future financial schema are refused without mutation', async t => {
  const db = hostDatabase();
  t.after(() => db.close());
  await migrate(db);
  const before = await db.all('SELECT * FROM sqlite_master ORDER BY name');
  await assert.rejects(FinancialEvidenceStore.open(db, identity, sha));
  assert.deepEqual(await db.all('SELECT * FROM sqlite_master ORDER BY name'), before);
  const other = await setup(t);
  await other.store.capture(command);
  const saved = await raw(other.db);
  await other.db.exec('PRAGMA user_version=2');
  await assert.rejects(FinancialEvidenceStore.open(other.db, identity, sha), /upgrade_or_review/);
  assert.deepEqual(await raw(other.db), saved);
});

test('persisted authorization denial retains exact work and refuses reopen until fresh online authorization', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  await store.deny();
  await assert.rejects(store.page(), /locked/);
  const reopened = await FinancialEvidenceStore.open(db, identity, sha, () => now + 200);
  await assert.rejects(reopened.unlock(context), /reauthentication_required/);
  assert.deepEqual(await raw(db), before);
  const replacement = { ...context, sessionId: randomUUID(), scopeRevision: 'f'.repeat(64) };
  await reopened.authorize({ ...grant, session_id: replacement.sessionId, scope_revision: replacement.scopeRevision }, replacement, observation);
  assert.deepEqual((await reopened.page()).evidence[0]?.operation, command);
});

test('failed replacement grant cannot restore an older grant after restarting', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  await assert.rejects(store.authorize({ ...grant, financial_uploads: true }, context, observation));
  const reopened = await FinancialEvidenceStore.open(db, identity, sha, () => now + 200);
  await assert.rejects(reopened.unlock(context), /reauthentication_required/);
  assert.deepEqual(await raw(db), before);
});

test('expiry and rollback are durably denied; corrected clock alone cannot restore access', async t => {
  for (const failureTime of [now + 86400000, now - 3000]) {
    let time = now + 100;
    const { store, db } = await setup(t, { clock: () => time });
    await store.capture(command);
    const before = await raw(db);
    time = failureTime;
    await assert.rejects(store.page(), /window_expired|clock_rollback/);
    time = now + 500;
    const reopened = await FinancialEvidenceStore.open(db, identity, sha, () => time);
    await assert.rejects(reopened.unlock(context), /reauthentication_required/);
    assert.deepEqual(await raw(db), before);
  }
});

test('locking while hashing fences the result and never creates a command', async t => {
  let release!: () => void, entered!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { entered = resolve; });
  const { store, db } = await setup(t, { hash: async text => { entered(); await waiting; return sha(text); } });
  const pending = store.capture(command);
  await started;
  store.lock();
  release();
  await assert.rejects(pending, /locked/);
  assert.deepEqual(await raw(db), { commands: [], delivery: [] });
});

test('locking between command and delivery rolls back the actual SQLite transaction', async t => {
  const db = hostDatabase();
  let store!: FinancialEvidenceStore;
  const wrapped: Database = { ...db, transaction: work => db.transaction(tx => work({ ...tx,
    run: async (sql, values) => { const result = await tx.run(sql, values); if (sql.startsWith('INSERT INTO financial_commands')) store.lock(); return result; },
  })) };
  ({ store } = await setup(t, { db: wrapped }));
  await assert.rejects(store.capture(command), /locked/);
  assert.deepEqual(await raw(db), { commands: [], delivery: [] });
});

test('input edits during hashing cannot mutate original operation or hash', async t => {
  let release!: () => void, entered!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { entered = resolve; });
  const { store } = await setup(t, { hash: async text => { entered(); await waiting; return sha(text); } });
  const value = structuredClone(command);
  const pending = store.capture(value);
  await started;
  value.payload.total_payment_amount = '999.00';
  release();
  assert.deepEqual((await pending).operation, command);
});

test('local evidence pages paginate 25 at a time without changing pending work', async t => {
  const { store, db } = await setup(t);
  for (let index = 0; index < 27; index++) await store.capture({ ...command, operation_id: randomUUID() });
  const before = await raw(db);
  const first = await store.page();
  assert.equal(first.evidence.length, 25);
  assert.ok(first.next);
  const second = await store.page(first.next);
  assert.equal(second.evidence.length, 2);
  assert.equal(second.next, null);
  assert.equal(new Set([...first.evidence, ...second.evidence].map(row => row.operation.operation_id)).size, 27);
  assert.deepEqual(await raw(db), before);
});

test('missing delivery and oversized corrupted bodies fail review without materializing payload', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  await db.exec('DROP TRIGGER financial_delivery_retained; DELETE FROM financial_delivery;');
  await assert.rejects(store.page(), /review_required/);
  let fetchedPayload = false;
  const wrapped: Database = { ...db, transaction: work => db.transaction(tx => work({ ...tx,
    first: <T>(sql: string, values?: Parameters<SqlConnection['run']>[1]) => { if (sql.includes('SELECT c.*')) fetchedPayload = true; return tx.first<T>(sql, values); },
  })) };
  await db.exec("DROP TRIGGER financial_command_immutable; UPDATE financial_commands SET operation_json=replace(hex(zeroblob(600000)),'0','a'),byte_count=1200000;");
  const other = await FinancialEvidenceStore.open(wrapped, identity, sha, () => now + 100);
  await other.unlock(context);
  await assert.rejects(other.page(), /review_required/);
  assert.equal(fetchedPayload, false);
});

test('schema initialization failure rolls back DDL, identity and version', async t => {
  const db = hostDatabase();
  t.after(() => db.close());
  const wrapped: Database = { ...db, transaction: work => db.transaction(tx => work({ ...tx,
    run: async (sql, values) => { if (values?.[0] === 'identity') throw new Error('synthetic_initialization_failure'); return tx.run(sql, values); },
  })) };
  await assert.rejects(FinancialEvidenceStore.open(wrapped, identity, sha), /initialization_failure/);
  assert.deepEqual(await db.all("SELECT name FROM sqlite_master WHERE type='table'"), []);
  assert.equal((await db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version, 0);
});

test('returned values cannot edit persisted originals or frozen partition identity', async t => {
  const { store, db } = await setup(t);
  const originalIdentity = canonical(store.identity);
  const saved = await store.capture(command);
  const before = await raw(db);
  saved.operation.payload.notes = 'Edited outside store';
  assert.throws(() => Object.assign(store.identity, { actorId: randomUUID() }));
  assert.equal(canonical(store.identity), originalIdentity);
  assert.deepEqual(await raw(db), before);
});

test('actual Django grant and Unicode/microsecond UUID-v2 hash survive a durable local capture', async t => {
  // Required, real owned PostgreSQL output; missing fixture is a failure, never a skipped test.
  const fixture = JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-financial-storage-cross-language-20261015.json', import.meta.url), 'utf8'));
  assert.equal(fixture.provenance, 'owned_postgresql_private_grant_and_pure_uuid_hash_no_upload');
  const actualGrant = financialStorageGrant.parse(fixture.grant);
  const actualIdentity = { actorId: actualGrant.actor_id, deploymentId: actualGrant.deployment_id, deviceId: actualGrant.device_id };
  const actualContext = { ...actualIdentity, sessionId: actualGrant.session_id, streamEpoch: actualGrant.stream_epoch, scopeRevision: actualGrant.scope_revision };
  const serverMs = Date.parse(actualGrant.server_time);
  const store = await FinancialEvidenceStore.open(hostDatabase(), actualIdentity, sha, () => serverMs + 100);
  t.after(() => store.close());
  await store.authorize(actualGrant, actualContext, { requestStartedMs: serverMs, receivedMs: serverMs + 100 });
  const saved = await store.capture(fixture.operation);
  assert.equal(saved.commandHash, fixture.command_hash);
  assert.deepEqual(saved.operation, fixture.operation);
  assert.equal(saved.operation.captured_at, '2026-10-15T15:59:59.123456Z');
  assert.equal(saved.operation.payload.payee, 'Synthetic café 🐔 supplier');
  assert.deepEqual((await store.page()).evidence, [saved]);
});

test('locking during a slow read exposes no stale financial data and rolls back its clock update', async t => {
  let wait = false, release!: () => void, entered!: () => void;
  const waiting = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { entered = resolve; });
  const { store, db } = await setup(t, { hash: async text => { if (wait) { entered(); await waiting; } return sha(text); } });
  await store.capture(command);
  const before = await raw(db);
  wait = true;
  const pending = store.page();
  await started;
  store.lock();
  release();
  await assert.rejects(pending, /locked/);
  assert.deepEqual(await raw(db), before);
});

test('corrupt policy is durably refused and never destroys the original operation', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  const before = await raw(db);
  await db.run("UPDATE financial_meta SET value=? WHERE key='authorization'", ['{bad-json']);
  await assert.rejects(store.page(), /review_required/);
  await assert.rejects(store.unlock(context), /reauthentication_required/);
  assert.deepEqual(await raw(db), before);
});

test('local evidence row budget refuses another capture but exact retries and original pages remain available', async t => {
  const { store, db } = await setup(t);
  await store.capture(command);
  // Fill only the count-boundary fixture in this owned in-memory database.
  const row = await db.first<{ operation_json: string; command_hash: string; byte_count: number }>('SELECT * FROM financial_commands');
  assert.ok(row);
  await db.transaction(async tx => {
    for (let index = 1; index < 1000; index++) {
      const id = randomUUID();
      const operation = financialUUIDOperation.parse({ ...command, operation_id: id });
      const json = canonical(operation);
      await tx.run('INSERT INTO financial_commands VALUES(?,?,?,?)', [id, json, await sha(financialEvidenceHashInput(identity, operation)), Buffer.byteLength(json)]);
      await tx.run("INSERT INTO financial_delivery VALUES(?,'pending_local_evidence')", [id]);
    }
  });
  const before = await raw(db);
  await assert.rejects(store.capture({ ...command, operation_id: randomUUID() }), /storage_limit/);
  assert.equal((await store.capture(command)).status, 'pending_local_evidence');
  assert.equal((await store.page()).evidence.length, 25);
  assert.deepEqual(await raw(db), before);
});

test('an expiry reached during asynchronous read is durably denied without returning financial evidence', async t => {
  let time = now + 100, expireDuringHash = false;
  const { store, db } = await setup(t, { clock: () => time, hash: async text => {
    if (expireDuringHash) time = now + 86400000;
    return sha(text);
  } });
  await store.capture(command);
  const before = await raw(db);
  expireDuringHash = true;
  await assert.rejects(store.page(), /window_expired/);
  time = now + 200;
  await assert.rejects(store.unlock(context), /reauthentication_required/);
  assert.deepEqual(await raw(db), before);
});

test('denial persistence failure is reported, not misrepresented as durable revocation', async t => {
  const db = hostDatabase();
  let rejectDenial = false;
  const wrapped: Database = { ...db, transaction: work => db.transaction(tx => work({ ...tx,
    run: async (sql, values) => {
      if (rejectDenial && sql.startsWith('UPDATE financial_meta SET value=')) throw new Error('synthetic_denial_disk_failure');
      return tx.run(sql, values);
    },
  })) };
  const { store } = await setup(t, { db: wrapped });
  await store.capture(command);
  const before = await raw(db);
  rejectDenial = true;
  await assert.rejects(store.deny(), /denial_disk_failure/);
  await assert.rejects(store.page(), /locked/);
  assert.deepEqual(await raw(db), before);
  // The outer native auth lifecycle MUST deny its independent secure pointer
  // before calling deny(). This standalone store cannot claim disk-full-safe
  // cross-restart revocation until that native integration is implemented.
});
