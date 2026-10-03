import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, AuthClient, type Credentials } from '../src/auth/client';
import { offlineAccess } from '../src/auth/offline';
import { validateSettings } from '../src/config';
import { sessionErrorMessage } from '../src/auth/errors';
import { serializedCredentials } from '../src/auth/credential-store';
test('session diagnostics use only safe codes/statuses and fixed development stages', () => {
  const secret = 'private-token-and-key-do-not-display';
  assert.doesNotMatch(sessionErrorMessage(new Error(secret), 'encrypted_store'), new RegExp(secret));
  assert.match(sessionErrorMessage(new Error(secret), 'encrypted_store'), /Step: encrypted local storage/);
  assert.match(sessionErrorMessage(new ApiError(401, secret), 'sign_in_request'), /HTTP 401/);
  assert.doesNotMatch(sessionErrorMessage(new ApiError(401, secret)), /private-token|Step:/);
  assert.equal(sessionErrorMessage(new Error('device_unlock_cancelled')), 'device_unlock_cancelled');
});
test('concurrent 401s share one rotation; refresh persisted before resumed reads', async () => {
  let stored: Credentials = { refresh: 'old-refresh', rotation: 'ready' }; let rotations = 0; let reads = 0;
  const client = new AuthClient(async (path, body, access) => {
    if (path === '/auth/refresh') { rotations++; assert.equal(stored.rotation, 'in_flight'); assert.deepEqual(body, { refresh: 'old-refresh' }); await new Promise((resolve) => setTimeout(resolve, 20)); return { access: 'new-access', refresh: 'new-refresh' }; }
    if (access !== 'new-access') throw new ApiError(401, 'expired');
    assert.equal(stored.refresh, 'new-refresh'); reads++; return {};
  }, { async read() { return stored; }, async write(value) { stored = value; } }, async () => { assert.fail('must not deny'); });
  client.setAccess('expired'); await Promise.all(Array.from({ length: 20 }, () => client.read('/auth/me')));
  assert.equal(rotations, 1); assert.equal(reads, 20);
});
test('lost refresh and restart intent require sign-in without replaying refresh', async () => {
  let stored: Credentials = { refresh: 'secret', rotation: 'ready' }; let requests = 0; let denied = 0;
  const store = { async read() { return stored; }, async write(value: Credentials) { stored = value; } };
  const client = new AuthClient(async () => { requests++; throw new Error('transport timeout'); }, store, async () => { denied++; });
  await assert.rejects(client.refresh(), /sign_in_required/); assert.equal(stored.rotation, 'reauthenticate'); assert.equal(denied, 1);
  await assert.rejects(client.refresh(), /session_locked/); assert.equal(requests, 1);
  stored = { refresh: 'old', rotation: 'in_flight' };
  await assert.rejects(new AuthClient(async () => { assert.fail('must not retry uncertain credential'); }, store, async () => {}).refresh(), /sign_in_required/);
});
test('403 never rotates and lock during refresh cannot resume requests', async () => {
  let denied = 0; let calls = 0;
  const store = { async read() { return { refresh: 'test', rotation: 'ready' as const }; }, async write() {} };
  const client = new AuthClient(async () => { calls++; throw new ApiError(403, 'revoked'); }, store, async () => { denied++; });
  client.setAccess('access'); await assert.rejects(client.read('/auth/me')); assert.equal(calls, 1); assert.equal(denied, 1);
  let finish: ((value: unknown) => void) | undefined;
  const racing = new AuthClient(() => new Promise((resolve) => { finish = resolve; }), store, async () => {});
  const flight = racing.refresh(); await new Promise((resolve) => setTimeout(resolve, 0)); racing.lock(); finish!({ access: 'new', refresh: 'new' });
  await assert.rejects(flight, /session_locked/);
});
test('late refresh and denial after lock cannot replace a new login or call old denial', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' };
  let finish!: (value: unknown) => void;
  let denied = 0;
  const store = serializedCredentials({ async read() { return stored; }, async write(value) { stored = value; } });
  const client = new AuthClient(() => new Promise((resolve) => { finish = resolve; }), store, async () => { denied++; });
  const refresh = client.refresh();
  const rejected = assert.rejects(refresh, /session_locked/);
  await new Promise((resolve) => setTimeout(resolve, 0));
  client.lock();
  await store.write({ refresh: 'new-login', rotation: 'ready' });
  finish({ refresh: 'old-rotated', access: 'old-access' });
  await rejected;
  assert.equal(stored.refresh, 'new-login');
  assert.equal(denied, 0);
  await assert.rejects(client.read('/auth/me'), /session_locked/);

  let reject!: (reason: unknown) => void;
  const staleRead = new AuthClient(() => new Promise((_ok, fail) => { reject = fail; }), store, async () => { denied++; });
  staleRead.setAccess('old-access');
  const read = staleRead.read('/auth/me');
  const readRejected = assert.rejects(read, /session_locked/);
  staleRead.lock();
  reject(new ApiError(403, 'revoked'));
  await readRejected;
  assert.equal(denied, 0);
});
test('native credential writes finish in order and stale queued writes are skipped', async () => {
  let stored: Credentials = { refresh: 'original', rotation: 'ready' };
  let release!: () => void;
  let started!: () => void;
  const blocked = new Promise<void>((resolve) => { release = resolve; });
  const writing = new Promise<void>((resolve) => { started = resolve; });
  const writes: string[] = [];
  const store = serializedCredentials({
    async read() { return stored; },
    async write(value) {
      writes.push(value.refresh);
      if (value.refresh === 'old-rotated') { started(); await blocked; }
      stored = value;
    },
  });
  let denied = 0;
  const oldClient = new AuthClient(async () => ({ access: 'old-access', refresh: 'old-rotated' }), store, async () => { denied++; });
  const refresh = oldClient.refresh();
  const rejected = assert.rejects(refresh, /session_locked/);
  await writing;
  oldClient.lock();
  const newLogin = store.write({ refresh: 'new-login', rotation: 'ready' });
  const stale = store.write({ refresh: 'must-not-write', rotation: 'reauthenticate' }, () => false);
  const staleRejected = assert.rejects(stale, /session_locked/);
  assert.deepEqual(writes, ['original', 'old-rotated']);
  release();
  await Promise.all([rejected, newLogin, staleRejected]);
  assert.equal(stored.refresh, 'new-login');
  assert.equal(denied, 0);
  assert.deepEqual(writes, ['original', 'old-rotated', 'new-login']);
});
test('offline windows use validated server time, expire and reject clock rollback', () => {
  const clock = { validatedLocalMs: 100000, validatedServerMs: 200000, highWaterMs: 110000, operationalDays: 7, sensitiveHours: 24 };
  assert.equal(offlineAccess(clock, 110000).allowed, true);
  assert.equal(offlineAccess(clock, 100000).reason, 'clock_rollback');
  assert.equal(offlineAccess(clock, 100000 + 7 * 86400_000).reason, 'offline_window_expired');
  assert.equal(offlineAccess(clock, 100000 + 86400_000, true).allowed, false);
  assert.equal(offlineAccess({ ...clock, operationalDays: 99 }, 100000 + 8 * 86400_000).allowed, false);
});
test('environment validation rejects cleartext release, credentials and unexpected API paths', () => {
  assert.equal(validateSettings('development', 'http://10.0.2.2:7070/api/v1').environment, 'development');
  assert.equal(validateSettings('staging', 'https://staging.example.test/api/v1', true).environment, 'staging');
  for (const [env, url, release] of [['production', 'http://example.test/api/v1', true], ['development', 'http://example.test/api/v1', false], ['development', 'http://10.0.2.2:7070/api/v1', true], ['staging', 'https://user:secret@example.test/api/v1', false], ['staging', 'https://example.test/api/v1/', false], ['staging', 'https://example.test/api/v1?token=secret', false]] as const) {
    assert.throws(() => validateSettings(env, url, release));
  }
});
