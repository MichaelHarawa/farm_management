import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ApiError, AuthClient, httpTransport, type Credentials } from '../src/auth/client';
import { parseFinancialCommandCapabilities } from '../src/finance/command-capabilities';
import { financialCommandCapabilitiesPath, isFinancialCommandRequest } from '../src/finance/command-transport';

const identity = { actorId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', deploymentId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  deviceId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' };
const binding = { ...identity, sessionId: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' };
const capabilities = { financial_protocol_version: 1, financial_command_version: 2, deployment_id: identity.deploymentId,
  device_id: identity.deviceId, actor_id: identity.actorId, server_time: '2026-10-18T16:00:00.123456Z',
  access: 'online_only_current_authority', offline_cache_seconds: 0, packs: [], requires_separate_native_storage_grant: true,
  submission_enabled: true, status_recovery_enabled: true, commands: ['inventory.supplier_payment.record'],
  limits: { request_bytes: 1048576, response_bytes: 131072, operations: 20, dependencies_per_operation: 20,
    invoices_per_operation: 10, lines_per_operation: 50, funding_rows_per_operation: 100 } };
const token = (changes = {}) => [Buffer.from('{"alg":"HS256"}').toString('base64url'), Buffer.from(JSON.stringify({
  token_type: 'access', user_id: identity.actorId, deployment_id: identity.deploymentId, mobile_device_id: identity.deviceId,
  mobile_session_id: binding.sessionId, exp: 2000000000, ...changes })).toString('base64url'), 'synthetic-signature'].join('.');
const credentials = { async read(): Promise<Credentials> { return { refresh: 'synthetic-refresh', rotation: 'ready' }; }, async write() {} };

test('command discovery is explicit fresh identity-bound GET only, never generic or reference upload permission', async () => {
  let sends = 0;
  const auth = new AuthClient(async (path, body, access, options) => {
    sends++; assert.equal(path, financialCommandCapabilitiesPath); assert.equal(body, undefined); assert.equal(access, token());
    assert.deepEqual(options, { financialCommands: 1 }); return capabilities;
  }, credentials, async () => {});
  auth.setAccess(token());
  await assert.rejects(auth.request(financialCommandCapabilitiesPath), /route_unavailable/);
  await assert.rejects(auth.readFinancialReference(financialCommandCapabilitiesPath), /route_unavailable/);
  const parsed = await auth.readFinancialCommandCapabilities(identity);
  assert.deepEqual(parsed, capabilities);
  parsed.commands.pop();
  assert.deepEqual(await auth.readFinancialCommandCapabilities(identity), capabilities);
  assert.equal(sends, 2);
});

test('read-only discovery keeps recovery with empty command list and grants no cached storage', () => {
  const value = { ...capabilities, submission_enabled: false, commands: [] };
  assert.deepEqual(parseFinancialCommandCapabilities(value, binding, identity), value);
  for (const invalid of [{ ...value, commands: capabilities.commands }, { ...capabilities, commands: [] },
    { ...capabilities, status_recovery_enabled: false }, { ...capabilities, commands: ['finance.arbitrary'] },
    { ...capabilities, offline_cache_seconds: 3600 }, { ...capabilities, packs: ['finance'] },
    { ...capabilities, requires_separate_native_storage_grant: false }, { ...capabilities, unknown: true },
    { ...capabilities, limits: { ...capabilities.limits, operations: 100 } }]) {
    assert.throws(() => parseFinancialCommandCapabilities(invalid, binding, identity));
  }
});

test('foreign JWT refuses discovery before fetch and foreign response identities cannot authorize delivery', async () => {
  let sends = 0;
  const auth = new AuthClient(async () => { sends++; return capabilities; }, credentials, async () => {});
  auth.setAccess(token({ deployment_id: binding.sessionId }));
  await assert.rejects(auth.readFinancialCommandCapabilities(identity), /identity_mismatch/);
  assert.equal(sends, 0);
  for (const field of ['actor_id', 'device_id', 'deployment_id']) {
    assert.throws(() => parseFinancialCommandCapabilities({ ...capabilities, [field]: binding.sessionId }, binding, identity), /identity_mismatch/);
  }
  assert.throws(() => parseFinancialCommandCapabilities(capabilities, { ...binding, actorId: binding.sessionId }, identity), /identity_mismatch/);
  assert.throws(() => parseFinancialCommandCapabilities({ ...capabilities, unknown: 'x'.repeat(9000) }, binding, identity), /too_large/);
});

test('capabilities paths cannot accept bodies policy queries traversal or fallback headers', async () => {
  const saved = globalThis.fetch, seen: RequestInit[] = [];
  globalThis.fetch = async (_url, init) => { seen.push(init!); return new Response(JSON.stringify(capabilities), { headers: { 'Cache-Control': 'no-store' } }); };
  try {
    const transport = httpTransport('https://synthetic.example.invalid/api/v1', 2);
    await transport(financialCommandCapabilitiesPath, undefined, token(), { financialCommands: 1 });
    assert.equal(seen[0]?.method, 'GET'); assert.equal(seen[0]?.body, undefined); assert.equal(seen[0]?.cache, 'no-store');
    const headers = new Headers(seen[0]?.headers);
    assert.equal(headers.get('X-Mobile-Finance-Command-Version'), '2'); assert.equal(headers.get('X-Mobile-Poultry-Version'), null);
    assert.equal(isFinancialCommandRequest(financialCommandCapabilitiesPath, {}), false);
    for (const path of [financialCommandCapabilitiesPath + '?policy=all', financialCommandCapabilitiesPath + '/',
      financialCommandCapabilitiesPath + '\n', financialCommandCapabilitiesPath + '/../push']) {
      await assert.rejects(transport(path, undefined, token(), { financialCommands: 1 }), /route_unavailable/);
    }
    await assert.rejects(transport(financialCommandCapabilitiesPath, {}, token(), { financialCommands: 1 }), /route_unavailable/);
    assert.equal(seen.length, 1);
  } finally { globalThis.fetch = saved; }
});

test('denial and lock during discovery cannot publish late capability or implicitly submit', async () => {
  let release!: (value: unknown) => void, denied = 0, calls = 0;
  const auth = new AuthClient(() => { calls++; return new Promise(resolve => { release = resolve; }); }, credentials, async () => { denied++; });
  auth.setAccess(token());
  const pending = auth.readFinancialCommandCapabilities(identity), rejected = assert.rejects(pending, /session_locked/);
  auth.lock(); release(capabilities); await rejected;
  assert.equal(calls, 1); assert.equal(denied, 0);
  const forbidden = new AuthClient(async () => { throw new ApiError(403, 'permission_denied'); }, credentials, async () => { denied++; });
  forbidden.setAccess(token());
  await assert.rejects(forbidden.readFinancialCommandCapabilities(identity), /permission_denied/);
  assert.equal(denied, 1);
});
