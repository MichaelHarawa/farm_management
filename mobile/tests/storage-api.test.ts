import assert from 'node:assert/strict';
import { randomUUID, createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { ApiError, AuthClient, httpTransport, type Credentials, type TransportOptions } from '../src/auth/client';
import { FinancialStorageGrantReader } from '../src/finance/storage-client';
import { financialStorageGrantPath, mobileAccessBinding, financialStorageOptions } from '../src/finance/storage-transport';
import { FinancialEvidenceStore } from '../src/finance/evidence-store';
import { hostDatabase, identity } from './helpers';

const epoch = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', session = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const requestId = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const now = Date.parse('2026-10-15T16:30:00Z');
const binding = { ...identity, sessionId: session };
const expected = { ...identity, streamEpoch: epoch };
const grant = { financial_storage_version: 1, profile: 'financial-evidence-private-v1', deployment_id: identity.deploymentId,
  actor_id: identity.actorId, device_id: identity.deviceId, session_id: session, stream_epoch: epoch, scope_revision: 'a'.repeat(64),
  server_time: new Date(now).toISOString(), expires_at: new Date(now + 86400000).toISOString(), maximum_offline_seconds: 86400,
  access: 'local_evidence_only_not_posting_authority', commands: ['inventory.supplier_payment.record'], reference_cache_seconds: 0, financial_uploads: false };
const response = (request = requestId, changes = {}) => ({ financial_storage_api_version: 1, request_id: request, grant, ...changes });
const token = (changes = {}) => [Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url'),
  Buffer.from(JSON.stringify({ token_type: 'access', user_id: identity.actorId, deployment_id: identity.deploymentId,
    mobile_device_id: identity.deviceId, mobile_session_id: session, exp: 2000000000, ...changes })).toString('base64url'), 'synthetic-signature'].join('.');
const credentials = { async read(): Promise<Credentials> { return { refresh: 'synthetic-refresh', rotation: 'ready' }; }, async write() {} };
const sha = async (value: string) => createHash('sha256').update(value).digest('hex');

test('local token binding handles UTF8 without browser or Node decoding dependencies, never authenticates signatures', () => {
  assert.deepEqual(mobileAccessBinding(token({ ignored_text: 'Synthetic café 🐔' })), binding);
  for (const invalid of ['private-invalid-token', token({ token_type: 'refresh' }), token({ mobile_session_id: undefined }),
    token({ user_id: 10 }), token({ mobile_device_id: identity.deviceId.toUpperCase() }), token({ exp: 1.5 }),
    'a.____.b', token() + '\n', 'a.a.b', 'a.' + 'a'.repeat(17000) + '.b']) {
    assert.throws(() => mobileAccessBinding(invalid), error => error instanceof Error && error.message === 'financial_storage_bound_access_required');
  }
});

test('storage GET is explicit; generic and reference methods cannot reach it or financial posts', async () => {
  let sent = 0;
  const auth = new AuthClient(async (path, body, access, options) => {
    sent++; assert.equal(path, financialStorageGrantPath); assert.equal(body, undefined);
    assert.equal(access, token()); assert.deepEqual(options, { financialStorage: 1, requestId }); return response();
  }, credentials, async () => {});
  auth.setAccess(token());
  for (const path of [financialStorageGrantPath, '/mobile-sync/finance/push']) {
    await assert.rejects(auth.request(path), /route_unavailable/);
    await assert.rejects(auth.readFinancialReference(path), /route_unavailable/);
  }
  assert.deepEqual(await auth.readFinancialStorageGrant(requestId), { response: response(), binding });
  assert.equal(sent, 1);
});

test('grant response binds fresh challenge, actual access session, original identity and independently expected epoch', async () => {
  const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant(id) {
    assert.equal(id, requestId); return { response: response(id), binding };
  } }, expected, () => requestId, () => now);
  const result = await reader.read();
  assert.deepEqual(result.grant, grant);
  assert.deepEqual(result.context, { ...expected, sessionId: session, scopeRevision: grant.scope_revision });
  assert.deepEqual(result.observation, { requestStartedMs: now, receivedMs: now });
});

test('old cached response cannot restart the clock for a different fresh request', async () => {
  const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant() { return { response: response(), binding }; } },
    expected, randomUUID, () => now);
  await assert.rejects(reader.read(), /response_binding_mismatch/);
});

test('grant validation rejects foreign identities, session, epoch, scope extras, upload and reference-cache authority', async () => {
  for (const change of [{ actor_id: randomUUID() }, { device_id: randomUUID() }, { deployment_id: randomUUID() },
    { session_id: randomUUID() }, { stream_epoch: randomUUID() }, { scope_revision: 'a'.repeat(64) + '\n' },
    { reference_cache_seconds: 86400 }, { financial_uploads: true }, { payroll: [] }]) {
    const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant() {
      return { response: response(requestId, { grant: { ...grant, ...change } }), binding };
    } }, expected, () => requestId, () => now);
    await assert.rejects(reader.read());
  }
  for (const key of ['actorId', 'deploymentId', 'deviceId'] as const) {
    const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant() {
      return { response: response(), binding: { ...binding, [key]: randomUUID() } };
    } }, expected, () => requestId, () => now);
    await assert.rejects(reader.read(), /binding_mismatch/);
  }
});

test('invalid or previously used challenge refuses before HTTP, including after a lost response', async () => {
  let sent = 0;
  const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant() { sent++; throw new Error('synthetic_response_lost'); } },
    expected, () => requestId, () => now);
  await assert.rejects(reader.read(), /response_lost/);
  await assert.rejects(reader.read(), /fresh_request_required/);
  assert.equal(sent, 1);
  for (const invalid of [requestId.toUpperCase(), requestId + '\n', epoch.replace('-4aaa-', '-5aaa-'), 'invalid']) {
    assert.equal(financialStorageOptions.safeParse({ financialStorage: 1, requestId: invalid }).success, false);
  }
});

test('reader close fences late response and concurrent reads cannot share a challenge', async () => {
  let finish!: (value: { response: unknown; binding: typeof binding }) => void;
  const reader = new FinancialStorageGrantReader({ readFinancialStorageGrant: () => new Promise(resolve => { finish = resolve; }) },
    expected, () => requestId, () => now);
  const first = reader.read();
  const rejected = assert.rejects(first, /reader_closed/);
  await assert.rejects(reader.read(), /already_in_flight/);
  reader.close(); finish({ response: response(), binding });
  await rejected;
  await assert.rejects(reader.read(), /reader_closed/);
});

test('request-start latency, rollback and a short session expiry are checked before returning a grant', async () => {
  for (const [received, expiry] of [[now + 60001, now + 86400000], [now - 1, now + 86400000], [now + 1000, now + 1000]]) {
    let calls = 0;
    const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant() {
      return { response: response(requestId, { grant: { ...grant, expires_at: new Date(expiry!).toISOString() } }), binding };
    } }, expected, () => requestId, () => calls++ ? received! : now);
    await assert.rejects(reader.read(), /invalid_clock|clock_rollback|window_expired/);
  }
});

test('concurrent grant 401s use one durable rotation and bind the ACTUAL replacement token session', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' }, rotations = 0;
  const nextSession = randomUUID();
  const auth = new AuthClient(async (path, body, access, options) => {
    if (path === '/auth/refresh') {
      rotations++; assert.equal(stored.rotation, 'in_flight'); assert.equal(options, undefined);
      await new Promise(resolve => setTimeout(resolve, 10));
      return { access: token({ mobile_session_id: nextSession }), refresh: 'rotated' };
    }
    if (access === token()) throw new ApiError(401, 'expired');
    assert.equal(stored.refresh, 'rotated'); assert.equal(body, undefined);
    assert.ok(options && 'financialStorage' in options);
    return response(options.requestId, { grant: { ...grant, session_id: nextSession } });
  }, { async read() { return stored; }, async write(value) { stored = value; } }, async () => assert.fail('Unexpected denial'));
  auth.setAccess(token());
  const results = await Promise.all(Array.from({ length: 10 }, () => auth.readFinancialStorageGrant(randomUUID())));
  assert.equal(rotations, 1);
  assert.ok(results.every(value => value.binding.sessionId === nextSession));
});

test('lost refresh cannot retry a consumed token or return a grant after restart', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' }, sent = 0, denied = 0;
  const auth = new AuthClient(async path => {
    sent++;
    if (path === '/auth/refresh') throw new Error('synthetic_lost_rotation');
    throw new ApiError(401, 'expired');
  }, { async read() { return stored; }, async write(value) { stored = value; } }, async () => { denied++; });
  auth.setAccess(token());
  await assert.rejects(auth.readFinancialStorageGrant(requestId), /sign_in_required/);
  assert.equal(stored.rotation, 'reauthenticate'); assert.equal(sent, 2); assert.equal(denied, 1);
  const restarted = new AuthClient(async () => assert.fail('Consumed refresh cannot be retried'), { async read() { return stored; }, async write() {} }, async () => {});
  await assert.rejects(restarted.readFinancialStorageGrant(randomUUID()), /sign_in_required/);
});

test('403 locks without refresh; a late successful response after lock cannot escape', async () => {
  let denied = 0, sent = 0;
  const auth = new AuthClient(async () => { sent++; throw new ApiError(403, 'device_revoked'); }, credentials, async () => { denied++; });
  auth.setAccess(token());
  await assert.rejects(auth.readFinancialStorageGrant(requestId), /device_revoked/);
  await assert.rejects(auth.readFinancialStorageGrant(randomUUID()), /session_locked/);
  assert.equal(sent, 1); assert.equal(denied, 1);
  let finish!: (value: unknown) => void;
  const late = new AuthClient(() => new Promise(resolve => { finish = resolve; }), credentials, async () => {});
  late.setAccess(token());
  const pending = late.readFinancialStorageGrant(requestId);
  const rejected = assert.rejects(pending, /session_locked/);
  late.lock(); finish(response()); await rejected;
});

test('HTTP storage GET sends only exact storage headers/options and refuses routes, body and mixed flags before fetch', async () => {
  const original = globalThis.fetch;
  const seen: RequestInit[] = [];
  globalThis.fetch = async (_input, init) => { seen.push(init!); return new Response(JSON.stringify(response()), { headers: { 'Cache-Control': 'private, no-store, max-age=0' } }); };
  try {
    const transport = httpTransport('https://synthetic.example.invalid/api/v1', 2);
    await transport(financialStorageGrantPath, undefined, token(), { financialStorage: 1, requestId });
    assert.equal(seen[0]?.method, 'GET'); assert.equal(seen[0]?.body, undefined); assert.equal(seen[0]?.cache, 'no-store');
    assert.equal(seen[0]?.redirect, 'error');
    const headers = new Headers(seen[0]?.headers);
    assert.equal(headers.get('X-Mobile-Finance-Storage-Request'), requestId);
    assert.equal(headers.get('X-Mobile-Finance-Version'), '1');
    assert.equal(headers.get('X-Mobile-Finance-Storage-Version'), '1');
    assert.equal(headers.get('X-Mobile-Finance-References-Version'), null);
    assert.equal(headers.get('X-Mobile-Poultry-Version'), null);
    for (const [path, body, options] of [
      ['/mobile-sync/push', undefined, { financialStorage: 1, requestId }],
      [financialStorageGrantPath + '?actor_id=x', undefined, { financialStorage: 1, requestId }],
      [financialStorageGrantPath, { amount: '1.00' }, { financialStorage: 1, requestId }],
      [financialStorageGrantPath, undefined, { financialStorage: 1, requestId, financialReferences: 1 }],
      [financialStorageGrantPath, undefined, { financialStorage: 2, requestId }],
      [financialStorageGrantPath, undefined, { financialReferences: 1 }],
    ] as const) await assert.rejects(transport(path, body, token(), options as TransportOptions), /route_unavailable/);
    assert.equal(seen.length, 1);
  } finally { globalThis.fetch = original; }
});

test('HTTP storage refuses cached policy, excessive actual bytes and content length, with safe fixed errors', async () => {
  const original = globalThis.fetch;
  const transport = httpTransport('https://synthetic.example.invalid/api/v1');
  const read = () => transport(financialStorageGrantPath, undefined, token(), { financialStorage: 1, requestId });
  try {
    globalThis.fetch = async () => new Response(JSON.stringify(response()));
    await assert.rejects(read(), /cache_policy_required/);
    globalThis.fetch = async () => new Response('x'.repeat(8193), { headers: { 'Cache-Control': 'no-store' } });
    await assert.rejects(read(), /response_too_large/);
    globalThis.fetch = async () => new Response('{}', { headers: { 'Cache-Control': 'no-store', 'Content-Length': '8193' } });
    await assert.rejects(read(), /response_too_large/);
    globalThis.fetch = async () => new Response(JSON.stringify({ code: 'financial_bridge_disabled', message: 'PRIVATE' }), { status: 503 });
    await assert.rejects(read(), /financial_bridge_disabled/);
    globalThis.fetch = async () => new Response(JSON.stringify({ code: 'PRIVATE-CONTENT', message: 'PRIVATE' }), { status: 503 });
    await assert.rejects(read(), error => error instanceof ApiError && error.code === 'mobile_backend_not_ready');
  } finally { globalThis.fetch = original; }
});

test('fresh reader result can authorize the independent store without expanding uploads or references', async t => {
  const auth = new AuthClient(async (_path, _body, _access, options) => {
    assert.ok(options && 'financialStorage' in options); return response(options.requestId);
  }, credentials, async () => {});
  auth.setAccess(token());
  const reader = new FinancialStorageGrantReader(auth, expected, randomUUID, () => now);
  const acquired = await reader.read();
  const db = hostDatabase();
  const store = await FinancialEvidenceStore.open(db, identity, sha, () => now);
  t.after(() => store.close());
  await store.authorize(acquired.grant, acquired.context, acquired.observation);
  assert.deepEqual(await store.page(), { evidence: [], next: null });
  assert.equal((await db.all("SELECT name FROM sqlite_master WHERE type='table'")).length, 3);
});

test('actual owned Django HTTP grant envelope passes strict challenge/session parsing and local authorization', async t => {
  const fixture = JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-storage-api-http-fixture-20261015.json', import.meta.url), 'utf8'));
  assert.equal(fixture.actual_http, true); assert.equal(fixture.native, false); assert.equal(fixture.financial_effects_unchanged, true);
  const body = fixture.response;
  const actualIdentity = { actorId: body.grant.actor_id, deviceId: body.grant.device_id, deploymentId: body.grant.deployment_id };
  const start = Date.parse(body.grant.server_time);
  const reader = new FinancialStorageGrantReader({ async readFinancialStorageGrant(request) {
    assert.equal(request, body.request_id);
    return { response: body, binding: fixture.binding };
  } }, { ...actualIdentity, streamEpoch: body.grant.stream_epoch }, () => body.request_id, () => start + 100);
  const acquired = await reader.read();
  const store = await FinancialEvidenceStore.open(hostDatabase(), actualIdentity, sha, () => start + 100);
  t.after(() => store.close());
  await store.authorize(acquired.grant, acquired.context, acquired.observation);
  assert.deepEqual(await store.page(), { evidence: [], next: null });
  assert.match(fixture.cache_control, /no-store/);
  assert.match(fixture.vary, /X-Mobile-Finance-Storage-Request/);
});
