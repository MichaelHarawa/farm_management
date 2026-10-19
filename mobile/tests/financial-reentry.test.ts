import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { publishPrivateFinancialSession, requireFinancialSessionOwner, sameFinancialOrigin } from '../src/auth/financial-reentry';
import { SessionLifecycle } from '../src/auth/lifecycle';
import { FinancialCompartment } from '../src/finance/compartment';
import { FinancialEvidenceStore } from '../src/finance/evidence-store';
import { hostDatabase, identity } from './helpers';

const origin = { base: 'http://10.0.2.2:7075/api/v1', partition: 'a'.repeat(64), identity };
test('financial work binds the exact session object before asynchronous work, not matching account IDs', () => {
  const original = { pointer: structuredClone(origin) }, replacement = structuredClone(original);
  assert.equal(requireFinancialSessionOwner(original, original), original);
  assert.throws(() => requireFinancialSessionOwner(null, original), /session_locked/);
  assert.throws(() => requireFinancialSessionOwner(replacement, original), /session_locked/);
  assert.throws(() => requireFinancialSessionOwner(original, replacement), /session_locked/);
});
function scenario() {
  const state = { allowed: true, opens: 0, prepares: 0, publishes: 0, disposals: 0 };
  const pending = { pointer: structuredClone(origin) };
  const ports = { current: () => state.allowed, async reopen() { state.opens++; return pending; },
    async prepare() { state.prepares++; }, async publish() { state.publishes++; }, async dispose() { state.disposals++; } };
  return { state, pending, ports };
}
test('financial reentry publishes only after private preparation, never before it', async () => {
  const f = scenario(), events: string[] = [];
  await publishPrivateFinancialSession(origin, { ...f.ports,
    async reopen() { events.push('reopen'); return f.ports.reopen(); },
    async prepare() { assert.equal(f.state.publishes, 0); events.push('private-prepare'); await f.ports.prepare(); },
    async publish() { events.push('publish'); await f.ports.publish(); } });
  assert.deepEqual(events, ['reopen', 'private-prepare', 'publish']);
  assert.equal(f.state.disposals, 0);
});
test('invalid foreground/generation before opening performs no PIN, SQL or publication', async () => {
  const f = scenario(); f.state.allowed = false;
  await assert.rejects(publishPrivateFinancialSession(origin, f.ports), /session_locked/);
  assert.deepEqual(f.state, { allowed: false, opens: 0, prepares: 0, publishes: 0, disposals: 0 });
});
test('late invalidation after reopen or private preparation disposes once without publishing', async () => {
  for (const when of ['reopen', 'prepare'] as const) {
    const f = scenario(), original = f.ports[when];
    const ports = { ...f.ports, [when]: async () => { const value = await original(); f.state.allowed = false; return value; } };
    await assert.rejects(publishPrivateFinancialSession(origin, ports), /session_locked/);
    assert.equal(f.state.publishes, 0); assert.equal(f.state.disposals, 1);
  }
});
test('private preparation or publication failure releases owned resources, not their retained data', async () => {
  for (const when of ['prepare', 'publish'] as const) {
    const f = scenario();
    await assert.rejects(publishPrivateFinancialSession(origin, { ...f.ports,
      [when]: async () => { throw new Error('synthetic_cancel_or_denial'); } }), /synthetic_cancel_or_denial/);
    assert.equal(f.state.disposals, 1);
  }
  const f = scenario();
  await assert.rejects(publishPrivateFinancialSession(origin, { ...f.ports,
    async reopen() { throw new Error('reopen_owns_its_own_failure_cleanup'); } }));
  assert.equal(f.state.disposals, 0); // No handle was handed to this coordinator.
});
test('every original backend/account/deployment/device/partition field is checked before preparation', async () => {
  const changes = [{ base: 'http://10.0.2.2:7074/api/v1' }, { partition: 'b'.repeat(64) },
    ...(['actorId', 'deploymentId', 'deviceId'] as const).map(key => ({ identity: { ...identity, [key]: randomUUID() } }))];
  for (const change of changes) {
    const f = scenario(); Object.assign(f.pending.pointer, change);
    assert.equal(sameFinancialOrigin(origin, f.pending.pointer), false);
    await assert.rejects(publishPrivateFinancialSession(origin, f.ports), /original_identity_mismatch/);
    assert.equal(f.state.prepares, 0); assert.equal(f.state.publishes, 0); assert.equal(f.state.disposals, 1);
  }
});
test('identity changes during private work cannot publish, even if the caller changes its expected object too', async () => {
  const f = scenario(), supplied = structuredClone(origin);
  await assert.rejects(publishPrivateFinancialSession(supplied, { ...f.ports, async prepare() {
    f.pending.pointer.identity.deviceId = randomUUID();
    supplied.identity.deviceId = f.pending.pointer.identity.deviceId;
  } }), /original_identity_mismatch/);
  assert.equal(f.state.publishes, 0); assert.equal(f.state.disposals, 1);
});
test('real host financial store authorizes while main session stays unpublished through a simulated private activity pause', async () => {
  const fixture = JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-financial-storage-cross-language-20261015.json', import.meta.url), 'utf8'));
  const now = Date.parse('2026-10-16T09:00:00Z'), epoch = randomUUID(), sessionId = randomUUID();
  let foreground = true, securePointer: unknown = null;
  const sha = async (text: string) => createHash('sha256').update(text).digest('hex');
  const context = { ...identity, sessionId, streamEpoch: epoch, scopeRevision: 'a'.repeat(64) };
  const grant = { ...fixture.grant, actor_id: identity.actorId, device_id: identity.deviceId, deployment_id: identity.deploymentId,
    session_id: sessionId, stream_epoch: epoch, scope_revision: context.scopeRevision,
    server_time: new Date(now).toISOString(), expires_at: new Date(now + 86400000).toISOString() };
  const lifecycle = new SessionLifecycle<{ pointer: typeof origin; client: { lock(): void };
    repository: { db: { close(): Promise<void> } }; sensitive?: FinancialCompartment }>(() => {});
  let closedMain = 0;
  const pending = { pointer: structuredClone(origin), client: { lock() {} }, repository: { db: { async close() { closedMain++; } } },
    sensitive: undefined as FinancialCompartment | undefined };
  await publishPrivateFinancialSession(origin, {
    current: () => foreground && lifecycle.current === null && lifecycle.isCurrent(0),
    async reopen() { return pending; },
    async prepare(opened) {
      opened.sensitive = new FinancialCompartment({ ...identity, streamEpoch: epoch }, {
        now: () => now, isCurrent: () => foreground && lifecycle.isCurrent(0) && (lifecycle.current === null || lifecycle.current === opened),
        access: { async read() { return securePointer; }, async write(value) { securePointer = value; } },
        reader: () => ({ async read() { return { grant, context, observation: { requestStartedMs: now, receivedMs: now } }; }, close() {} }),
        async open() {
          foreground = false;
          assert.equal(lifecycle.current, null); // No published data while Android pauses for private credentials.
          await Promise.resolve(); foreground = true;
          return FinancialEvidenceStore.open(hostDatabase(), identity, sha, () => now);
        },
      });
      await opened.sensitive.authorizeOnline(); assert.equal(lifecycle.current, null);
    },
    async publish(opened) { lifecycle.publish(opened, 0); },
    async dispose(opened) { await opened.sensitive?.deny(); await opened.sensitive?.close(); await opened.repository.db.close(); },
  });
  assert.equal(lifecycle.current, pending); assert.equal(pending.sensitive?.isOpen, true);
  const saved = await pending.sensitive!.capture(fixture.operation);
  assert.deepEqual((await pending.sensitive!.page()).evidence, [saved]);
  await lifecycle.retire(0); assert.equal(lifecycle.current, null); assert.equal(closedMain, 1);
});
