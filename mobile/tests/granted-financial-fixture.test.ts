import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, type TestContext } from 'node:test';
import { canonical } from '../src/db/repository';
import { FinancialEvidenceStore, financialEvidenceHashInput, type FinancialEvidence } from '../src/finance/evidence-store';
import { type FinancialStorageContext } from '../src/finance/storage-policy';
import { captureGrantedFinancialFixture, requireGrantedFinancialFixtureScope, verifyGrantedFinancialFixture,
  type GrantedFinancialFixtureDescriptor, type GrantedFinancialFixturePorts, type GrantedFinancialFixtureScope } from '../src/test/granted-financial-fixture';
import { hostDatabase, identity } from './helpers';

const sha = async (text: string) => createHash('sha256').update(text).digest('hex');
const now = Date.parse('2026-10-17T06:00:01Z');
const context: FinancialStorageContext = { ...identity, sessionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  streamEpoch: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', scopeRevision: 'a'.repeat(64) };
// Host policy fixture only. No HTTP/native authentication or encryption is simulated as a passing native result.
const grant = { financial_storage_version: 1, profile: 'financial-evidence-private-v1', deployment_id: identity.deploymentId,
  actor_id: identity.actorId, device_id: identity.deviceId, session_id: context.sessionId, stream_epoch: context.streamEpoch,
  scope_revision: context.scopeRevision, server_time: new Date(now).toISOString(), expires_at: new Date(now + 86400000).toISOString(),
  maximum_offline_seconds: 86400, access: 'local_evidence_only_not_posting_authority',
  commands: ['inventory.supplier_payment.record'], reference_cache_seconds: 0, financial_uploads: false };
const observation = { requestStartedMs: now, receivedMs: now };
const scope = (): GrantedFinancialFixtureScope => ({ enabled: true, environment: 'development',
  apiBaseUrl: 'http://10.0.2.2:7075/api/v1', username: 'mobile-finance-manager', identity: { ...identity } });

async function setup(t: TestContext, path?: string) {
  const db = hostDatabase(path), store = await FinancialEvidenceStore.open(db, identity, sha, () => now);
  await store.authorize(grant, context, observation);
  const state = { raw: null as string | null, current: true, reads: 0, creates: 0, randoms: 0, hashes: 0, captures: 0, pages: 0 };
  const calls: string[] = [];
  const ports: GrantedFinancialFixturePorts = {
    current: () => state.current,
    descriptor: {
      async read() { calls.push('read'); state.reads++; return state.raw; },
      async createExclusive(text) {
        calls.push('create'); state.creates++;
        assert.equal(state.raw, null, 'exclusive descriptor creation cannot replace original');
        state.raw = text;
      },
    },
    randomUUID() { calls.push('random'); state.randoms++; return randomUUID(); },
    async hash(text) { calls.push('hash'); state.hashes++; return sha(text); },
    async capture(operation) { calls.push('capture'); state.captures++; return store.capture(operation); },
    async page() { calls.push('page'); state.pages++; return store.page(); },
  };
  let closed = false;
  const close = async () => { if (!closed) { closed = true; await store.close(); } };
  t.after(close);
  const originals = () => db.all('SELECT c.*,d.state FROM financial_commands c JOIN financial_delivery d USING(operation_id) ORDER BY c.operation_id');
  return { state, calls, ports, db, store, close, originals };
}

test('all scope gates reject before even current(), descriptor, hashing, randomness or protected IO', async () => {
  let calls = 0;
  const refuse = () => { calls++; throw new Error('unexpected IO'); };
  const ports: GrantedFinancialFixturePorts = { current: refuse, descriptor: { read: refuse, createExclusive: refuse },
    randomUUID: refuse, hash: refuse, capture: refuse, page: refuse };
  const invalid: unknown[] = [
    { ...scope(), enabled: false }, { ...scope(), environment: 'production' }, { ...scope(), environment: 'staging' },
    { ...scope(), apiBaseUrl: 'http://10.0.2.2:7074/api/v1' }, { ...scope(), apiBaseUrl: 'http://10.0.2.2:7075/api/v1/' },
    { ...scope(), username: 'mobile-finance-worker' }, { ...scope(), username: 'mobile-finance-viewer' },
    { ...scope(), identity: { ...identity, actorId: 'not-a-uuid' } },
    { ...scope(), identity: { ...identity, deviceId: identity.deviceId.toUpperCase() } },
    { ...scope(), identity: { ...identity, other: 'unsupported' } }, { ...scope(), enabled: 'true' },
  ];
  for (const value of invalid) {
    const unsafe = value as GrantedFinancialFixtureScope;
    assert.throws(() => requireGrantedFinancialFixtureScope(unsafe), /^Error: granted_financial_fixture_unavailable$/);
    await assert.rejects(captureGrantedFinancialFixture(unsafe, ports), /^Error: granted_financial_fixture_unavailable$/);
    await assert.rejects(verifyGrantedFinancialFixture(unsafe, ports), /^Error: granted_financial_fixture_unavailable$/);
  }
  assert.equal(calls, 0);
  const input = scope(), parsed = requireGrantedFinancialFixtureScope(input);
  assert.notEqual(parsed.identity, input.identity);
  assert.equal(Object.isFrozen(parsed.identity), true);
});

test('first protected capture persists and rereads one immutable bounded synthetic descriptor before capture', async t => {
  const f = await setup(t), result = await captureGrantedFinancialFixture(scope(), f.ports);
  assert.equal(result.outcome, 'captured');
  assert.equal(result.evidence.status, 'pending_local_evidence');
  assert.equal(result.evidence.commandHash, await sha(financialEvidenceHashInput(identity, result.descriptor.operation)));
  assert.equal(f.state.raw, canonical(result.descriptor));
  assert.ok(Buffer.byteLength(f.state.raw!) <= 16 * 1024);
  assert.deepEqual(Object.keys(result.descriptor).sort(), ['commandHash', 'kind', 'operation', 'scope', 'version']);
  assert.deepEqual(Object.keys(result.descriptor.scope).sort(), ['apiBaseUrl', 'identity']);
  assert.equal(result.descriptor.operation.payload.total_payment_amount, '12.34');
  assert.match(result.descriptor.operation.payload.payee, /FICTITIOUS café 🐔/);
  assert.equal(result.descriptor.operation.captured_at, '2026-10-17T06:00:00.123456Z');
  assert.equal(result.descriptor.operation.payload.payment_date, '2026-10-17');
  assert.match(result.descriptor.operation.payload.notes, /No observed payment/);
  assert.equal(Object.isFrozen(result.descriptor.operation.payload.invoices[0]!.lines), true);
  assert.equal(f.state.randoms, 1); assert.equal(f.state.creates, 1); assert.equal(f.state.captures, 1);
  const createdAt = f.calls.indexOf('create'), capturedAt = f.calls.indexOf('capture');
  assert.ok(f.calls.indexOf('page') < f.calls.indexOf('random'), 'existing evidence is checked before generating a candidate');
  assert.ok(createdAt < capturedAt && f.calls.slice(createdAt + 1, capturedAt).includes('read'),
    'the persisted descriptor is reread before any protected capture');
  assert.equal((await f.originals()).length, 1);
});

test('exact repeated capture exercises store idempotency without new UUID, descriptor or evidence', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  const text = f.state.raw, second = await captureGrantedFinancialFixture(scope(), f.ports);
  assert.equal(second.outcome, 'retained');
  assert.deepEqual(second.evidence, first.evidence);
  assert.equal(f.state.raw, text); assert.equal(f.state.randoms, 1); assert.equal(f.state.creates, 1); assert.equal(f.state.captures, 2);
  assert.deepEqual(await f.originals(), before);
});

test('verification never captures, generates randomness or creates a descriptor', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  const refuse = () => { throw new Error('verification mutated'); };
  const result = await verifyGrantedFinancialFixture(scope(), { ...f.ports, randomUUID: refuse, capture: refuse,
    descriptor: { ...f.ports.descriptor, createExclusive: refuse } });
  assert.equal(result.outcome, 'verified'); assert.deepEqual(result.evidence, first.evidence);
  assert.deepEqual(await f.originals(), before);
});

test('descriptor committed but write response lost retains the exact operation for an explicit retry', async t => {
  const f = await setup(t);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports, descriptor: { ...f.ports.descriptor,
    async createExclusive(text) { await f.ports.descriptor.createExclusive(text); throw new Error('native secret write error'); },
  } }), /^Error: granted_financial_fixture_failed$/);
  const original = f.state.raw;
  assert.ok(original); assert.equal(f.state.captures, 0); assert.equal((await f.originals()).length, 0);
  const result = await captureGrantedFinancialFixture(scope(), f.ports);
  assert.equal(canonical(result.descriptor), original); assert.equal(f.state.randoms, 1); assert.equal(f.state.creates, 1);
  assert.equal(result.outcome, 'captured');
});

test('descriptor creation failure or nonexact reread cannot start capture', async t => {
  for (const mode of ['before-write', 'changed-reread'] as const) await t.test(mode, async child => {
    const f = await setup(child);
    await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports, descriptor: { ...f.ports.descriptor,
      async createExclusive(text) {
        if (mode === 'before-write') throw new Error('private error');
        await f.ports.descriptor.createExclusive(text + ' ');
      },
    } }), mode === 'before-write' ? /granted_financial_fixture_failed/ : /granted_financial_fixture_descriptor_changed/);
    assert.equal(f.state.captures, 0); assert.equal((await f.originals()).length, 0);
    if (mode === 'changed-reread') assert.ok(f.state.raw?.endsWith(' '));
  });
});

test('committed capture with a lost response is recovered with the same original ID payload hash and pending row', async t => {
  const f = await setup(t);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports,
    async capture(operation) { await f.ports.capture(operation); throw new Error('untrusted native error'); },
  }), /^Error: granted_financial_fixture_failed$/);
  const originalText = f.state.raw, before = await f.originals();
  assert.equal(before.length, 1);
  const result = await captureGrantedFinancialFixture(scope(), f.ports);
  assert.equal(result.outcome, 'retained'); assert.equal(f.state.raw, originalText); assert.equal(f.state.randoms, 1);
  assert.deepEqual(await f.originals(), before);
});

test('a missing descriptor cannot adopt existing rows or cursor and verification cannot create it', async t => {
  const f = await setup(t);
  await captureGrantedFinancialFixture(scope(), f.ports);
  const before = await f.originals(), counts = { randoms: f.state.randoms, creates: f.state.creates, captures: f.state.captures };
  f.state.raw = null;
  await assert.rejects(captureGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_evidence_mismatch/);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_descriptor_required/);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports,
    async page() { return { evidence: [], next: randomUUID() }; },
  }), /granted_financial_fixture_evidence_mismatch/);
  assert.deepEqual({ randoms: f.state.randoms, creates: f.state.creates, captures: f.state.captures }, counts);
  assert.equal(f.state.raw, null); assert.deepEqual(await f.originals(), before);
});

test('corrupt oversized extended or changed fixed-payload descriptors refuse without replacement', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  const changes = [
    '{not-json', 'x'.repeat(16 * 1024 + 1), '🐔'.repeat(5000),
    JSON.stringify({ ...first.descriptor, sessionId: context.sessionId }),
    JSON.stringify({ ...first.descriptor, commandHash: '0'.repeat(64) }),
    JSON.stringify({ ...first.descriptor, operation: { ...first.descriptor.operation, payload: {
      ...first.descriptor.operation.payload, total_payment_amount: '12.35' } } }),
    JSON.stringify({ ...first.descriptor, operation: { ...first.descriptor.operation, depends_on: [randomUUID()] } }),
  ];
  const captures = f.state.captures;
  for (const text of changes) {
    f.state.raw = text;
    await assert.rejects(captureGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_descriptor_invalid/);
    await assert.rejects(verifyGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_descriptor_invalid/);
    assert.equal(f.state.raw, text);
  }
  assert.equal(f.state.captures, captures); assert.deepEqual(await f.originals(), before);
});

test('valid descriptor of a changed operation cannot replace an original protected row', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  const changed: GrantedFinancialFixtureDescriptor = structuredClone(first.descriptor);
  changed.operation.operation_id = randomUUID();
  changed.commandHash = await sha(financialEvidenceHashInput(identity, changed.operation));
  f.state.raw = canonical(changed);
  await assert.rejects(captureGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_evidence_mismatch/);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_evidence_mismatch/);
  assert.equal(f.state.captures, 1); assert.deepEqual(await f.originals(), before);
});

test('descriptor identity cannot cross actor device or deployment scopes', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  for (const key of ['actorId', 'deviceId', 'deploymentId'] as const) {
    const foreignScope = scope(); foreignScope.identity[key] = randomUUID();
    await assert.rejects(captureGrantedFinancialFixture(foreignScope, f.ports), /granted_financial_fixture_scope_mismatch/);
    await assert.rejects(verifyGrantedFinancialFixture(foreignScope, f.ports), /granted_financial_fixture_scope_mismatch/);
  }
  assert.equal(f.state.raw, canonical(first.descriptor)); assert.equal(f.state.captures, 1);
  assert.deepEqual(await f.originals(), before);
});

test('descriptor changes during protected preflight are caught by an exact reread before capture', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports, async page() {
    const result = await f.ports.page(); f.state.raw = canonical(first.descriptor) + '\n'; return result;
  } }), /granted_financial_fixture_descriptor_changed/);
  assert.equal(f.state.captures, 1); assert.deepEqual(await f.originals(), before);
});

test('extra protected rows and any cursor refuse rather than claiming a sole original fixture', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports);
  await f.store.capture({ ...first.descriptor.operation, operation_id: randomUUID() });
  const before = await f.originals();
  await assert.rejects(captureGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_evidence_mismatch/);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_evidence_mismatch/);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), { ...f.ports,
    async page() { return { evidence: [first.evidence], next: first.evidence.operation.operation_id }; },
  }), /granted_financial_fixture_evidence_mismatch/);
  assert.equal(f.state.captures, 1); assert.deepEqual(await f.originals(), before);
});

test('descriptor changed during capture or final page cannot yield a successful result', async t => {
  for (const stage of ['capture', 'final-page'] as const) await t.test(stage, async child => {
    const f = await setup(child);
    const ports = { ...f.ports,
      async capture(operation: FinancialEvidence['operation']) {
        const result = await f.ports.capture(operation);
        if (stage === 'capture') f.state.raw += '\n';
        return result;
      },
      async page() {
        const result = await f.ports.page();
        if (stage === 'final-page' && f.state.captures) f.state.raw += '\n';
        return result;
      },
    };
    await assert.rejects(captureGrantedFinancialFixture(scope(), ports), /granted_financial_fixture_descriptor_changed/);
    assert.equal((await f.originals()).length, 1, 'committed original remains intact after descriptor fault');
    assert.equal(f.state.captures, 1);
  });
});

test('verification refuses empty or altered full payload hash status and extended evidence responses', async t => {
  const f = await setup(t), first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals();
  const altered = structuredClone(first.evidence);
  altered.operation.payload.invoices[0]!.lines[0]!.funding_allocations[0]!.funding_version = 'd'.repeat(64);
  const rows: unknown[][] = [[], [altered], [{ ...first.evidence, commandHash: '0'.repeat(64) }],
    [{ ...first.evidence, status: 'accepted' }], [{ ...first.evidence, unexpected: 'not allowed' }]];
  for (const evidence of rows) await assert.rejects(verifyGrantedFinancialFixture(scope(), { ...f.ports,
    async page() { return { evidence: evidence as FinancialEvidence[], next: null }; },
  }), /granted_financial_fixture_evidence_mismatch/);
  assert.deepEqual(await f.originals(), before);
});

test('stale ownership before an action or after every awaited port stops subsequent IO', async t => {
  const stages = ['read', 'page', 'hash', 'create', 'capture'] as const;
  for (const stage of stages) await t.test(stage, async child => {
    const f = await setup(child);
    const finish = async <T>(name: string, work: () => Promise<T>) => {
      const result = await work(); if (name === stage) f.state.current = false; return result;
    };
    const ports: GrantedFinancialFixturePorts = { ...f.ports,
      descriptor: { read: () => finish('read', f.ports.descriptor.read),
        createExclusive: text => finish('create', () => f.ports.descriptor.createExclusive(text)) },
      hash: text => finish('hash', () => f.ports.hash(text)),
      capture: operation => finish('capture', () => f.ports.capture(operation)),
      page: () => finish('page', f.ports.page),
    };
    await assert.rejects(captureGrantedFinancialFixture(scope(), ports), /^Error: granted_financial_fixture_stale$/);
    assert.equal(f.calls.at(-1), stage);
    assert.equal(f.state.captures, stage === 'capture' ? 1 : 0);
    if (stage === 'capture') assert.equal((await f.originals()).length, 1, 'committed original is preserved after late ownership loss');
  });
  const f = await setup(t); f.state.current = false;
  await assert.rejects(captureGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_stale/);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), f.ports), /granted_financial_fixture_stale/);
  assert.deepEqual(f.calls, []);
});

test('verification fences after protected page and descriptor IO without exposing a stale success', async t => {
  const f = await setup(t); await captureGrantedFinancialFixture(scope(), f.ports);
  await assert.rejects(verifyGrantedFinancialFixture(scope(), { ...f.ports, async page() {
    const result = await f.ports.page(); f.state.current = false; return result;
  } }), /granted_financial_fixture_stale/);
  assert.equal(f.state.captures, 1);
});

test('mutating caller scope during an await cannot reattribute a descriptor or its hash', async t => {
  const f = await setup(t), input = scope();
  const result = await captureGrantedFinancialFixture(input, { ...f.ports, async hash(text) {
    input.identity.actorId = randomUUID(); input.apiBaseUrl = 'http://10.0.2.2:7074/api/v1'; return f.ports.hash(text);
  } });
  assert.deepEqual(result.descriptor.scope.identity, identity);
  assert.equal(result.descriptor.scope.apiBaseUrl, scope().apiBaseUrl);
});

test('arbitrary port failures are replaced with fixed safe error text', async t => {
  const f = await setup(t);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports, current() { throw new Error('private current error'); } }),
    /^Error: granted_financial_fixture_failed$/);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports,
    descriptor: { ...f.ports.descriptor, async read() { throw new Error('private SQL/key/server contents'); } },
  }), /^Error: granted_financial_fixture_failed$/);
  await assert.rejects(captureGrantedFinancialFixture(scope(), { ...f.ports,
    async hash() { throw new Error('private hash error'); },
  }), /^Error: granted_financial_fixture_failed$/);
  assert.equal((await f.originals()).length, 0);
});

test('on-disk reopen and explicit denial retain the exact descriptor and original protected evidence', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'farm-granted-financial-fixture-'));
  t.after(() => rm(directory, { recursive: true, force: true })); // Only this newly owned host-test directory.
  const path = join(directory, 'evidence.db'), f = await setup(t, path);
  const first = await captureGrantedFinancialFixture(scope(), f.ports), before = await f.originals(), descriptor = f.state.raw;
  await f.close();
  const db = hostDatabase(path), reopened = await FinancialEvidenceStore.open(db, identity, sha, () => now);
  let closed = false;
  t.after(async () => { if (!closed) await reopened.close(); });
  const ports = { ...f.ports, capture: (operation: FinancialEvidence['operation']) => reopened.capture(operation), page: () => reopened.page() };
  await assert.rejects(verifyGrantedFinancialFixture(scope(), ports), /granted_financial_fixture_failed/);
  await reopened.unlock(context);
  assert.deepEqual((await verifyGrantedFinancialFixture(scope(), ports)).evidence, first.evidence);
  await reopened.deny();
  await assert.rejects(reopened.unlock(context), /reauthentication_required/);
  await assert.rejects(captureGrantedFinancialFixture(scope(), ports), /granted_financial_fixture_failed/);
  await reopened.authorize(grant, context, observation);
  assert.deepEqual((await verifyGrantedFinancialFixture(scope(), ports)).evidence, first.evidence);
  assert.equal(f.state.raw, descriptor);
  assert.deepEqual(await db.all('SELECT c.*,d.state FROM financial_commands c JOIN financial_delivery d USING(operation_id) ORDER BY c.operation_id'), before);
  await reopened.close(); closed = true;
});
