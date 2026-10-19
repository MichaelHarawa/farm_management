import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { ApiError, AuthClient, httpTransport, type Credentials, type TransportOptions } from '../src/auth/client';
import { FinancialCommandClient } from '../src/finance/command-client';
import { financialCommandRoot, financialCommandStatusPath, isFinancialCommandRequest } from '../src/finance/command-transport';
import { financialEvidenceHashInput } from '../src/finance/evidence-store';
import { financialUUIDOperation } from '../src/finance/uuid-commands';

const identity = { actorId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', deploymentId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  deviceId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' };
const id = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', session = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const binding = { ...identity, sessionId: session };
const operation = financialUUIDOperation.parse({ financial_command_version: 2, operation_id: id,
  command: 'inventory.supplier_payment.record', captured_at: '2026-10-18T12:00:00.123456Z', depends_on: [],
  payload: { currency: 'MWK', payee: 'Synthetic café 🐔', payment_method: 'cash', external_reference: 'SYNTHETIC-API',
    payment_date: '2026-01-12', total_payment_amount: '12.34', invoices: [{ invoice_group_id: session,
      invoice_version: 'a'.repeat(64), total_payment_amount: '12.34', lines: [{ invoice_line_index: 0, amount: '12.34',
        funding_allocations: [{ funding_source: session, funding_version: 'b'.repeat(64), amount: '12.34' }] }] }], notes: 'Original evidence' } });
const envelope = { financial_protocol_version: 1, deployment_id: identity.deploymentId, device_id: identity.deviceId, operations: [operation] };
const sha = async (value: string) => createHash('sha256').update(value).digest('hex');
const hash = createHash('sha256').update(financialEvidenceHashInput(identity, operation)).digest('hex');
const hashes = { [id]: hash };
const accepted = { financial_command_version: 2, operation_id: id, command: operation.command, command_hash: hash,
  outcome: 'accepted', code: 'accepted', message: 'Observed supplier payment recorded once; original evidence retained.',
  field_errors: {}, recovery_action: 'retain_receipt_never_resubmit', transaction_id: session, committed_at: operation.captured_at,
  financial_evidence: { submission_id: session, receipt_hash: 'c'.repeat(64), payment_version: 'd'.repeat(64), recorded_at: operation.captured_at,
    basis: 'immutable_completed_financial_receipt_not_current_balance' } };
const response = { financial_protocol_version: 1, deployment_id: identity.deploymentId, device_id: identity.deviceId,
  server_time: operation.captured_at, results: [accepted] };
const wrapped = { response, binding };
const token = (changes = {}) => [Buffer.from('{"alg":"HS256"}').toString('base64url'), Buffer.from(JSON.stringify({
  token_type: 'access', user_id: identity.actorId, deployment_id: identity.deploymentId, mobile_device_id: identity.deviceId,
  mobile_session_id: session, exp: 2000000000, ...changes })).toString('base64url'), 'synthetic-signature'].join('.');
const credentials = { async read(): Promise<Credentials> { return { refresh: 'synthetic-refresh', rotation: 'ready' }; }, async write() {} };
const ports = () => ({ async submitFinancialCommands() { return wrapped; }, async recoverFinancialCommand() { return wrapped; } });

test('command POST and status are explicit, bounded allowlists; generic and reference finance remain blocked', async () => {
  let sends = 0;
  const auth = new AuthClient(async (path, body, access, options) => {
    sends++; assert.equal(access, token()); assert.deepEqual(options, { financialCommands: 1 });
    if (path === financialCommandRoot) assert.deepEqual(body, envelope);
    else { assert.equal(path, financialCommandStatusPath(id)); assert.equal(body, undefined); }
    return response;
  }, credentials, async () => {});
  auth.setAccess(token());
  await assert.rejects(auth.request(financialCommandRoot, envelope), /route_unavailable/);
  await assert.rejects(auth.readFinancialReference(financialCommandRoot), /route_unavailable/);
  assert.deepEqual(await auth.submitFinancialCommands(envelope, identity), wrapped);
  assert.deepEqual(await auth.recoverFinancialCommand(id, identity), wrapped);
  assert.equal(sends, 2);
  for (const path of [financialCommandRoot + '?actor=x', financialCommandRoot + '/../../push', financialCommandStatusPath(id) + '?x=1',
    financialCommandStatusPath(id) + '\n', financialCommandRoot + '/' + id.toUpperCase()]) {
    assert.equal(isFinancialCommandRequest(path, undefined), false);
  }
});

test('sent JWT actor deployment and device must match original evidence BEFORE any POST', async () => {
  for (const claim of ['user_id', 'deployment_id', 'mobile_device_id']) {
    let sent = 0, denied = 0;
    const auth = new AuthClient(async () => { sent++; return response; }, credentials, async () => { denied++; });
    auth.setAccess(token({ [claim]: randomUUID() }));
    await assert.rejects(auth.submitFinancialCommands(envelope, identity), /financial_command_identity_mismatch/);
    assert.equal(sent, 0); assert.equal(denied, 1);
  }
});

test('caller mutation while refreshing cannot change exact original request sent', async () => {
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const copy = structuredClone(envelope);
  const auth = new AuthClient(async (path, body) => {
    if (path === '/auth/refresh') { await gate; return { access: token(), refresh: 'rotated' }; }
    assert.deepEqual(body, envelope); return response;
  }, credentials, async () => {});
  const sending = auth.submitFinancialCommands(copy, identity);
  copy.operations[0]!.payload.notes = 'MUTATED AFTER CALL';
  release(); await sending;
});

test('exact original command hashes are required before submit and immutable results are checked', async () => {
  let sent = 0;
  const client = new FinancialCommandClient({ ...ports(), async submitFinancialCommands(value, expected) {
    sent++; assert.deepEqual(value, envelope); assert.deepEqual(expected, identity); return wrapped;
  } }, identity, sha);
  const invalidHashes: Record<string, string>[] = [{}, { [id]: 'a'.repeat(64) }, { ...hashes, [session]: hash }];
  for (const invalid of invalidHashes) {
    await assert.rejects(client.submit(envelope, invalid), /original_hash_required/);
  }
  assert.equal(sent, 0);
  assert.deepEqual(await client.submit(envelope, hashes), response);
  assert.deepEqual(await client.recover(id, hash), response);
  assert.equal(sent, 1);
});

test('foreign partial contradictory or wrong-hash responses cannot retire original work', async () => {
  for (const result of [{ ...wrapped, binding: { ...binding, actorId: session } },
    { ...wrapped, response: { ...response, device_id: session } },
    { ...wrapped, response: { ...response, results: [] } },
    { ...wrapped, response: { ...response, results: [{ ...accepted, command_hash: '0'.repeat(64) }] } },
    { ...wrapped, response: { ...response, results: [{ ...accepted, financial_evidence: undefined }] } }]) {
    const client = new FinancialCommandClient({ ...ports(), async submitFinancialCommands() { return result; } }, identity, sha);
    await assert.rejects(client.submit(envelope, hashes));
  }
});

test('lost response and unknown status never trigger replacement POST or implicit resubmission', async () => {
  let submits = 0, reads = 0;
  const original = structuredClone(envelope);
  const client = new FinancialCommandClient({ async submitFinancialCommands(value) {
    submits++; assert.deepEqual(value, original); throw new Error('synthetic_lost_after_commit');
  }, async recoverFinancialCommand(operationId) { reads++; assert.equal(operationId, id); throw new ApiError(404, 'operation_not_found'); } }, identity, sha);
  await assert.rejects(client.submit(original, hashes), /lost_after_commit/);
  await assert.rejects(client.recover(id, hash), /operation_not_found/);
  assert.equal(submits, 1); assert.equal(reads, 1); assert.deepEqual(original, envelope);
});

test('close and concurrency fences reject stale results and stop before dispatch during hashing', async () => {
  let finish!: (value: typeof wrapped) => void;
  const client = new FinancialCommandClient({ ...ports(), submitFinancialCommands: () => new Promise(resolve => { finish = resolve; }) }, identity, sha);
  const sending = client.submit(envelope, hashes);
  await new Promise(resolve => setImmediate(resolve));
  const rejected = assert.rejects(sending, /client_closed/);
  await assert.rejects(client.recover(id, hash), /request_in_flight/);
  client.close(); finish(wrapped); await rejected;
  let hashDone!: (value: string) => void, dispatched = 0;
  const hashing = new FinancialCommandClient({ ...ports(), async submitFinancialCommands() { dispatched++; return wrapped; } }, identity,
    () => new Promise(resolve => { hashDone = resolve; }));
  const pending = hashing.submit(envelope, hashes), stopped = assert.rejects(pending, /client_closed/);
  hashing.close(); hashDone(hash); await stopped;
  assert.equal(dispatched, 0);
});

test('401 retries only original financial request after one durable rotation; 403 denies without refresh', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' }, rotations = 0, sent = 0;
  const auth = new AuthClient(async (path, body, access) => {
    if (path === '/auth/refresh') { rotations++; assert.equal(stored.rotation, 'in_flight'); return { access: token({ exp: 2000000100 }), refresh: 'rotated' }; }
    sent++; assert.deepEqual(body, envelope);
    if (access === token()) throw new ApiError(401, 'expired');
    return response;
  }, { async read() { return stored; }, async write(value) { stored = value; } }, async () => assert.fail('No denial expected'));
  auth.setAccess(token());
  await auth.submitFinancialCommands(envelope, identity);
  assert.equal(rotations, 1); assert.equal(sent, 2);
  let denied = 0, count = 0;
  const forbidden = new AuthClient(async () => { count++; throw new ApiError(403, 'permission_denied'); }, credentials, async () => { denied++; });
  forbidden.setAccess(token());
  await assert.rejects(forbidden.submitFinancialCommands(envelope, identity), /permission_denied/);
  assert.equal(count, 1); assert.equal(denied, 1);
});

test('HTTP financial submit/status use exact headers no redirects/cache and refuse mixed options before fetch', async () => {
  const saved = globalThis.fetch, seen: RequestInit[] = [];
  globalThis.fetch = async (_url, init) => { seen.push(init!); return new Response(JSON.stringify(response), { headers: { 'Cache-Control': 'no-store' } }); };
  try {
    const transport = httpTransport('https://synthetic.example.invalid/api/v1', 2);
    await transport(financialCommandRoot, envelope, token(), { financialCommands: 1 });
    await transport(financialCommandStatusPath(id), undefined, token(), { financialCommands: 1 });
    assert.equal(seen[0]?.method, 'POST'); assert.deepEqual(JSON.parse(String(seen[0]?.body)), envelope);
    assert.equal(seen[1]?.method, 'GET'); assert.equal(seen[1]?.body, undefined);
    assert.equal(seen[0]?.redirect, 'error'); assert.equal(seen[0]?.cache, 'no-store');
    const headers = new Headers(seen[0]?.headers);
    assert.equal(headers.get('X-Mobile-Finance-Version'), '1'); assert.equal(headers.get('X-Mobile-Finance-Command-Version'), '2');
    assert.equal(headers.get('X-Mobile-Poultry-Version'), null); assert.equal(headers.get('X-Mobile-Finance-Storage-Version'), null);
    for (const [path, body, options] of [[financialCommandRoot, envelope, { financialCommands: 1, financialReferences: 1 }],
      ['/mobile-sync/push', envelope, { financialCommands: 1 }], [financialCommandRoot, undefined, { financialCommands: 1 }],
      [financialCommandStatusPath(id), envelope, { financialCommands: 1 }]] as const) {
      await assert.rejects(transport(path, body, token(), options as TransportOptions), /route_unavailable/);
    }
    assert.equal(seen.length, 2);
  } finally { globalThis.fetch = saved; }
});

test('HTTP financial response bounds and no-store are mandatory; errors contain only allowlisted codes', async () => {
  const saved = globalThis.fetch, transport = httpTransport('https://synthetic.example.invalid/api/v1');
  const read = () => transport(financialCommandStatusPath(id), undefined, token(), { financialCommands: 1 });
  try {
    globalThis.fetch = async () => new Response('{}');
    await assert.rejects(read(), /cache_policy_required/);
    globalThis.fetch = async () => new Response('x'.repeat(131073), { headers: { 'Cache-Control': 'no-store' } });
    await assert.rejects(read(), /response_too_large/);
    globalThis.fetch = async () => new Response('{}', { headers: { 'Cache-Control': 'no-store', 'Content-Length': '131073' } });
    await assert.rejects(read(), /response_too_large/);
    globalThis.fetch = async () => new Response('{"code":"PRIVATE-RAW-NOT-TO-ECHO"}', { status: 503 });
    await assert.rejects(read(), error => error instanceof ApiError && error.code === 'mobile_backend_not_ready');
  } finally { globalThis.fetch = saved; }
});
