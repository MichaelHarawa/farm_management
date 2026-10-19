/** Real host SQLite recovery; synthetic grant/SecureStore ports, NOT Android encryption or HTTP proof. */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { test, type TestContext } from 'node:test';
import type { AppSettings } from '../src/config';
import type { StoreIdentity } from '../src/protocol';
import { FinancialCompartment, type FinancialAccessRecord } from '../src/finance/compartment';
import { FinancialEvidenceStore } from '../src/finance/evidence-store';
import { financialNamespace } from '../src/finance/key-database';
import { financialStorageGrant } from '../src/finance/storage-policy';
import { hostDatabase, identity } from './helpers';

const fixture = JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-financial-storage-cross-language-20261015.json', import.meta.url), 'utf8'));
const now = Date.parse('2026-10-18T08:00:00Z');
const settings: AppSettings = { environment: 'development', apiBaseUrl: 'http://10.0.2.2:7075/api/v1' };
const sha = async (value: string) => createHash('sha256').update(value).digest('hex');

async function setup(t: TestContext) {
  const directory = await mkdtemp(join(tmpdir(), 'farm-boundary-recovery-'));
  const secure = new Map<string, FinancialAccessRecord>();
  const handles = new Set<FinancialEvidenceStore>();
  const compartments = new Set<FinancialCompartment>();
  const state = { time: now, selected: '', opens: 0, reads: 0 };
  async function scope(config: AppSettings, owner: StoreIdentity, epoch = randomUUID()) {
    const namespace = await financialNamespace(config, owner, sha);
    function create() {
      const compartment = new FinancialCompartment({ ...owner, streamEpoch: epoch }, {
        now: () => state.time, isCurrent: () => state.selected === namespace.partition,
        access: {
          async read() { return structuredClone(secure.get(namespace.access) ?? null); },
          async write(record) { secure.set(namespace.access, structuredClone(record)); },
        },
        async open() {
          state.opens++;
          const db = hostDatabase(join(directory, namespace.database));
          let store: FinancialEvidenceStore;
          try { store = await FinancialEvidenceStore.open(db, owner, sha, () => state.time); }
          catch (error) { await db.close(); throw error; }
          handles.add(store);
          const close = store.close.bind(store);
          store.close = async () => { if (handles.delete(store)) await close(); };
          return store;
        },
        reader: () => ({
          async read() {
            state.reads++;
            const context = { ...owner, streamEpoch: epoch, sessionId: randomUUID(), scopeRevision: 'a'.repeat(64) };
            // Shape-correct synthetic response only. Actual Django grant authority
            // is separately verified in PostgreSQL/TCP tests, never claimed here.
            const grant = financialStorageGrant.parse({ ...fixture.grant,
              actor_id: owner.actorId, deployment_id: owner.deploymentId, device_id: owner.deviceId,
              stream_epoch: epoch, session_id: context.sessionId, scope_revision: context.scopeRevision,
              server_time: new Date(state.time).toISOString(), expires_at: new Date(state.time + 86400000).toISOString() });
            return { grant, context, observation: { requestStartedMs: state.time, receivedMs: state.time } };
          }, close() {},
        }),
      });
      compartments.add(compartment);
      return compartment;
    }
    return { namespace, create, select() { state.selected = namespace.partition; } };
  }
  t.after(async () => {
    for (const compartment of compartments) await compartment.close().catch(() => {});
    for (const handle of handles) await handle.close();
    // Only this newly created, validated temporary directory is removed.
    assert.equal(dirname(resolve(directory)), resolve(tmpdir()));
    assert.match(basename(directory), /^farm-boundary-recovery-/);
    await rm(directory, { recursive: true, force: true });
  });
  return { scope, state, secure };
}

for (const changed of ['backend', 'deployment', 'actor', 'device'] as const) {
  test(`host ${changed} switch cannot expose another store; returning retains exact original evidence`, async t => {
    const f = await setup(t);
    const a = await f.scope(settings, identity);
    const b = await f.scope(changed === 'backend' ? { ...settings, apiBaseUrl: 'http://10.0.2.2:7076/api/v1' } : settings,
      changed === 'backend' ? identity : { ...identity, [changed === 'deployment' ? 'deploymentId' : changed === 'actor' ? 'actorId' : 'deviceId']: randomUUID() });
    assert.notEqual(a.namespace.partition, b.namespace.partition);
    a.select();
    const original = a.create();
    await original.authorizeOnline();
    const savedA = await original.capture(fixture.operation);
    await original.close();
    const markerA = structuredClone(f.secure.get(a.namespace.access));
    b.select();
    const other = b.create(), opens = f.state.opens, reads = f.state.reads;
    await assert.rejects(other.unlockCached());
    assert.equal(f.state.opens, opens); assert.equal(f.state.reads, reads);
    assert.deepEqual(f.secure.get(a.namespace.access), markerA);
    // A disposed instance remains closing/busy, or generation-locked. Neither
    // state may execute IO or expose either account's evidence.
    await assert.rejects(original.page(), /^Error: financial_compartment_(?:busy|locked)$/);
    assert.equal(f.state.opens, opens); assert.equal(f.state.reads, reads);
    await other.authorizeOnline();
    assert.deepEqual((await other.page()).evidence, []);
    const otherOperation = structuredClone(fixture.operation);
    otherOperation.payload.notes = 'Different synthetic evidence; identical operation ID in a separate partition.';
    const savedB = await other.capture(otherOperation);
    assert.equal(savedB.operation.operation_id, savedA.operation.operation_id);
    assert.notEqual(savedB.commandHash, savedA.commandHash);
    await other.close();
    a.select();
    const returned = a.create(), beforeRead = f.state.reads;
    await returned.unlockCached();
    assert.deepEqual((await returned.page()).evidence, [savedA]);
    assert.equal(f.state.reads, beforeRead); // No server port or recapture on return.
    await returned.close();
    b.select();
    const returnedB = b.create();
    await returnedB.unlockCached();
    assert.deepEqual((await returnedB.page()).evidence, [savedB]);
    await returnedB.close();
  });
}

for (const failure of ['expiry', 'rollback'] as const) {
  test(`host ${failure} denial survives reopen; fresh authorization recovers exact original without recapture`, async t => {
    const f = await setup(t), a = await f.scope(settings, identity);
    a.select();
    const original = a.create();
    await original.authorizeOnline();
    const saved = await original.capture(fixture.operation);
    f.state.time += 10000;
    await original.close(); // Independent secure high-water advances while SQL is closed.
    f.state.time = failure === 'expiry' ? now + 86400000 : now + 5000;
    const reopened = a.create(), opens = f.state.opens, reads = f.state.reads;
    await assert.rejects(reopened.unlockCached(), failure === 'expiry' ? /window_expired/ : /clock_rollback/);
    assert.equal(f.state.opens, opens); assert.equal(f.state.reads, reads);
    assert.deepEqual(f.secure.get(a.namespace.access), { version: 1, status: 'denied' });
    f.state.time = now + 20000; // Correcting time alone must NOT restore access.
    const deniedAgain = a.create();
    await assert.rejects(deniedAgain.unlockCached(), /reauthentication_required/);
    assert.equal(f.state.opens, opens); assert.equal(f.state.reads, reads);
    await deniedAgain.authorizeOnline();
    const recovered = (await deniedAgain.page()).evidence;
    assert.deepEqual(recovered, [saved]);
    const first = recovered[0];
    assert.ok(first);
    assert.equal(first.operation.operation_id, fixture.operation.operation_id);
    await deniedAgain.close();
  });
}
