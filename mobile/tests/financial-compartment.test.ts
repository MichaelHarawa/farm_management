import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, type TestContext } from 'node:test';
import { FinancialCompartment, type FinancialAccessRecord } from '../src/finance/compartment';
import { FinancialEvidenceStore } from '../src/finance/evidence-store';
import { SessionLifecycle } from '../src/auth/lifecycle';
import { AuthClient, ApiError, type Credentials } from '../src/auth/client';
import { FinancialStorageGrantReader } from '../src/finance/storage-client';
import { hostDatabase, identity } from './helpers';
import { readFileSync } from 'node:fs';

const fixture = JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-financial-storage-cross-language-20261015.json', import.meta.url), 'utf8'));
const command = fixture.operation;
const now = Date.parse('2026-10-16T07:00:00Z');
const epoch = randomUUID(), session = randomUUID(), scope = 'a'.repeat(64);
const context = { ...identity, streamEpoch: epoch, sessionId: session, scopeRevision: scope };
const grant = { ...fixture.grant, actor_id: identity.actorId, device_id: identity.deviceId, deployment_id: identity.deploymentId,
  stream_epoch: epoch, session_id: session, scope_revision: scope, server_time: new Date(now).toISOString(), expires_at: new Date(now + 86400000).toISOString() };
const acquired = { grant, context, observation: { requestStartedMs: now, receivedMs: now + 100 } };
const sha = async (value: string) => createHash('sha256').update(value).digest('hex');
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(ok => { resolve = ok; }); return { promise, resolve }; }
async function setup(t: TestContext) {
  const directory = await mkdtemp(join(tmpdir(), 'farm-finance-compartment-'));
  const path = join(directory, 'private-evidence.db');
  const state = { pointer: null as unknown, time: now + 100, current: true, opens: 0, reads: 0, readerClosed: 0,
    failWrite: false, failOpen: false, delayRead: null as Promise<typeof acquired> | null, afterWrite: null as (() => Promise<void>) | null };
  const events: string[] = [];
  const openHandles = new Set<FinancialEvidenceStore>();
  const ports = {
    now: () => state.time, isCurrent: () => state.current,
    access: {
      async read() { return structuredClone(state.pointer); },
      async write(value: FinancialAccessRecord) {
        events.push(value.status);
        if (state.failWrite) throw new Error('synthetic_secure_store_failure');
        state.pointer = structuredClone(value);
        await state.afterWrite?.();
      },
    },
    async open() {
      state.opens++; events.push('open');
      if (state.failOpen) throw new Error('synthetic_pin_or_key_failure');
      const store = await FinancialEvidenceStore.open(hostDatabase(path), identity, sha, () => state.time);
      openHandles.add(store);
      const original = store.close.bind(store);
      let closed = false;
      store.close = async () => { if (!closed) { closed = true; openHandles.delete(store); await original(); } };
      return store;
    },
    reader() { return { async read() { state.reads++; events.push('read'); return state.delayRead ?? structuredClone(acquired); }, close() { state.readerClosed++; } }; },
  };
  const create = (overrides = {}) => new FinancialCompartment({ ...identity, streamEpoch: epoch, ...overrides }, ports);
  const compartment = create();
  t.after(async () => {
    await compartment.close().catch(() => {});
    for (const handle of openHandles) await handle.close();
    await rm(directory, { recursive: true, force: true }); // This newly owned test directory ONLY.
  });
  return { state, events, ports, compartment, create, path };
}

test('financial opener is lazy; write-ahead independent denial precedes network, PIN, grant and final enable', async t => {
  const f = await setup(t);
  assert.equal(f.state.opens, 0); assert.equal(f.state.reads, 0);
  await f.compartment.authorizeOnline();
  assert.deepEqual(f.events, ['denied', 'read', 'open', 'ready']);
  assert.equal(f.compartment.isOpen, true);
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'ready');
});

test('on-disk financial operation survives ordinary lock/close/reopen with exact ID payload and hash', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const saved = await f.compartment.capture(command);
  f.state.time += 5000;
  f.compartment.lock();
  assert.equal(f.compartment.isOpen, false);
  await f.compartment.close();
  const next = f.create();
  await next.unlockCached();
  assert.deepEqual((await next.page()).evidence, [saved]);
  await next.close();
});

test('explicit denial refuses cached restart but fresh current authorization recovers the original', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const saved = await f.compartment.capture(command);
  await f.compartment.deny();
  await f.compartment.close();
  const next = f.create();
  const opens = f.state.opens, reads = f.state.reads;
  await assert.rejects(next.unlockCached(), /^Error: financial_storage_reauthentication_required$/);
  assert.equal(f.state.opens, opens); assert.equal(f.state.reads, reads);
  assert.equal(next.isOpen, false);
  await next.authorizeOnline();
  assert.deepEqual((await next.page()).evidence, [saved]);
  await next.close();
});

test('host strict DENIED marker has an explicit reason before any financial key opener or server read', async t => {
  const f = await setup(t);
  f.state.pointer = { version: 1, status: 'denied' };
  await assert.rejects(f.compartment.unlockCached(), /^Error: financial_storage_reauthentication_required$/);
  assert.equal(f.state.opens, 0); assert.equal(f.state.reads, 0);
  assert.equal(f.compartment.isOpen, false);
  assert.deepEqual(f.state.pointer, { version: 1, status: 'denied' });
});

test('unknown or malformed policy is not mislabeled as a valid DENIED record and never opens a key', async t => {
  for (const pointer of [null, { version: 2, status: 'denied' }, { version: 1, status: 'DENIED' },
    { version: 1, status: 'denied', grant: 'unexpected' }]) {
    const f = await setup(t); f.state.pointer = pointer;
    await assert.rejects(f.compartment.unlockCached(), error => {
      assert(error instanceof Error);
      assert.notEqual(error.message, 'financial_storage_reauthentication_required');
      return true;
    });
    assert.equal(f.state.opens, 0); assert.equal(f.state.reads, 0);
    assert.equal(f.compartment.isOpen, false);
    assert.deepEqual(f.state.pointer, { version: 1, status: 'denied' });
  }
});

test('failed fresh check cannot fall back to a previously ready secure grant', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  await f.compartment.capture(command);
  f.state.failOpen = true;
  await assert.rejects(f.compartment.authorizeOnline(), /pin_or_key_failure/);
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
  const next = f.create();
  await assert.rejects(next.unlockCached());
  assert.equal(f.state.opens, 2);
});

test('expiry and rollback deny before key open; corrected time alone cannot restore access', async t => {
  for (const failureTime of [now - 3000, now + 86400000]) {
    const f = await setup(t);
    await f.compartment.authorizeOnline();
    await f.compartment.capture(command);
    await f.compartment.close();
    const count = f.state.opens;
    f.state.time = failureTime;
    const next = f.create();
    await assert.rejects(next.unlockCached(), /clock_rollback|window_expired/);
    assert.equal(f.state.opens, count);
    f.state.time = now + 5000;
    await assert.rejects(f.create().unlockCached());
    assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
  }
});

test('different deployment actor device or epoch cannot use the original secure marker', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const ready = structuredClone(f.state.pointer);
  await f.compartment.close();
  const count = f.state.opens;
  for (const key of ['deploymentId', 'actorId', 'deviceId', 'streamEpoch']) {
    f.state.pointer = structuredClone(ready);
    await assert.rejects(f.create({ [key]: randomUUID() }).unlockCached(), /identity_mismatch/);
  }
  assert.equal(f.state.opens, count);
});

test('lock while grant is in flight cannot open a key or re-enable the old secure pointer', async t => {
  const f = await setup(t), response = deferred<typeof acquired>();
  f.state.delayRead = response.promise;
  const pending = f.compartment.authorizeOnline();
  const rejected = assert.rejects(pending, /compartment_locked/);
  while (!f.state.reads) await new Promise(resolve => setTimeout(resolve, 1));
  f.compartment.lock();
  const closing = f.compartment.close();
  response.resolve(acquired);
  await rejected; await closing;
  assert.equal(f.state.opens, 0);
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
});

test('lock during final secure allow write compensates denial and closes SQL before restart', async t => {
  const f = await setup(t), written = deferred<void>(), finish = deferred<void>();
  f.state.afterWrite = async () => { if ((f.state.pointer as FinancialAccessRecord).status === 'ready') { written.resolve(); await finish.promise; } };
  const pending = f.compartment.authorizeOnline();
  const rejected = assert.rejects(pending, /compartment_locked/);
  await written.promise;
  f.compartment.lock(); finish.resolve();
  await rejected;
  assert.equal(f.compartment.isOpen, false);
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
});

test('secure high-water survives closing independently of older SQL metadata', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  await f.compartment.capture(command);
  f.state.time += 10000;
  f.compartment.lock(); await f.compartment.close();
  f.state.time -= 5000;
  const before = f.state.opens;
  await assert.rejects(f.create().unlockCached(), /clock_rollback/);
  assert.equal(f.state.opens, before);
});

test('failed secure checkpoint is explicit, hides data and does not claim durable denial', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const original = await f.compartment.capture(command);
  f.state.failWrite = true;
  await assert.rejects(f.compartment.page(), /secure_store_failure/);
  assert.equal(f.compartment.isOpen, false);
  f.state.failWrite = false;
  // If the OS refuses EVERY write, durable revocation cannot be manufactured.
  // Restore an independent denial before recovery, never silently report success.
  await f.compartment.deny();
  await f.compartment.authorizeOnline();
  assert.deepEqual((await f.compartment.page()).evidence, [original]);
});

test('actual 403 originating inside a financial request persists denial and retirement does not self-deadlock', async t => {
  const f = await setup(t);
  const lifecycle = new SessionLifecycle<{ client: AuthClient; repository: { db: { close(): Promise<void> } }; sensitive: FinancialCompartment }>(() => {});
  let persisted = false;
  const auth = new AuthClient(async () => { throw new ApiError(403, 'device_revoked'); }, {
    async read(): Promise<Credentials> { return { refresh: 'synthetic', rotation: 'ready' }; }, async write() {},
  }, async () => lifecycle.retireAfterPersistence(0, async previous => {
    previous?.sensitive.invalidate();
    await f.ports.access.write({ version: 1, status: 'denied' });
    persisted = true;
  }));
  // Valid shape for local consistency check only. Server authentication is not mocked as success.
  const access = ['eyJhbGciOiJIUzI1NiJ9', Buffer.from(JSON.stringify({ token_type: 'access', user_id: identity.actorId,
    deployment_id: identity.deploymentId, mobile_device_id: identity.deviceId, mobile_session_id: session, exp: 2000000000 })).toString('base64url'), 'signature'].join('.');
  auth.setAccess(access);
  const compartment = new FinancialCompartment({ ...identity, streamEpoch: epoch }, { ...f.ports,
    reader: () => new FinancialStorageGrantReader(auth, { ...identity, streamEpoch: epoch }, randomUUID, () => f.state.time),
  });
  lifecycle.publish({ client: auth, repository: { db: { async close() {} } }, sensitive: compartment }, 0);
  await assert.rejects(compartment.authorizeOnline(), /device_revoked/);
  await lifecycle.settled();
  assert.equal(lifecycle.current, null); assert.equal(persisted, true);
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
});

test('a pending denial excludes reauthorization and close cannot resurrect its old cached grant', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const entered = deferred<void>(), finish = deferred<void>();
  f.state.afterWrite = async () => { entered.resolve(); await finish.promise; };
  const denial = f.compartment.deny();
  await entered.promise;
  await assert.rejects(f.compartment.authorizeOnline(), /compartment_busy/);
  const closing = f.compartment.close();
  finish.resolve(); await denial; await closing;
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
});

test('denial during an ordinary close allow-write is compensated before close finishes', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  const entered = deferred<void>(), finish = deferred<void>();
  f.state.afterWrite = async () => {
    if ((f.state.pointer as FinancialAccessRecord).status === 'ready') { entered.resolve(); await finish.promise; }
  };
  const closing = f.compartment.close();
  await entered.promise;
  const denial = f.compartment.deny();
  finish.resolve(); await closing; await denial;
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
});

test('invalidated idle financial state cannot be re-enabled by ordinary close after another persistence failure', async t => {
  const f = await setup(t);
  await f.compartment.authorizeOnline();
  f.compartment.invalidate(); // E.g. main auth-pointer write then fails; the financial marker must still deny.
  await f.compartment.close();
  assert.equal((f.state.pointer as FinancialAccessRecord).status, 'denied');
  await assert.rejects(f.create().unlockCached());
});
