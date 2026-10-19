import { test } from 'node:test';
import assert from 'node:assert/strict';
import { SessionLifecycle } from '../src/auth/lifecycle';

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
function resource(name: string) {
  const events: string[] = [];
  return { name, events, client: { lock() { events.push('locked'); } }, repository: { db: { async close() { events.push('closed'); } } } };
}

test('background/signout retirement detaches before persistence and closes after a failed write', async () => {
  const visible: (string | null)[] = [];
  const lifecycle = new SessionLifecycle<ReturnType<typeof resource>>((session) => visible.push(session?.name ?? null));
  const session = resource('worker');
  lifecycle.publish(session, lifecycle.generation);
  const write = deferred<void>();
  const retirement = lifecycle.retire(lifecycle.generation, () => write.promise);
  const failure = assert.rejects(retirement, /secure_store_unavailable/);
  assert.equal(lifecycle.current, null);
  assert.deepEqual(visible, ['worker', null]);
  assert.deepEqual(session.events, ['locked']);
  let nextActionStarted = false;
  const next = lifecycle.settled().then(() => { nextActionStarted = true; });
  await Promise.resolve();
  assert.equal(nextActionStarted, false);
  write.reject(new Error('secure_store_unavailable'));
  await failure;
  await next;
  assert.deepEqual(session.events, ['locked', 'closed']);
});

test('failed current authorization hides and closes the session', async () => {
  const lifecycle = new SessionLifecycle<ReturnType<typeof resource>>(() => {});
  const session = resource('worker');
  lifecycle.publish(session, lifecycle.generation);
  await assert.rejects(lifecycle.failClosed(lifecycle.generation, async () => {
    throw new Error('capability_transport_failed');
  }), /capability_transport_failed/);
  assert.equal(lifecycle.current, null);
  assert.deepEqual(session.events, ['locked', 'closed']);
});

test('stale failure and denial callbacks cannot close or overwrite a newer account', async () => {
  const lifecycle = new SessionLifecycle<ReturnType<typeof resource>>(() => {});
  const first = resource('worker');
  const oldGeneration = lifecycle.generation;
  lifecycle.publish(first, oldGeneration);
  const response = deferred<void>();
  const oldFailure = lifecycle.failClosed(oldGeneration, () => response.promise);
  const rejected = assert.rejects(oldFailure, /late_failure/);
  await lifecycle.retire(oldGeneration);
  const second = resource('viewer');
  lifecycle.publish(second, lifecycle.generation);
  let oldPointerWritten = false;
  await lifecycle.retire(oldGeneration, async () => { oldPointerWritten = true; });
  response.reject(new Error('late_failure'));
  await rejected;
  assert.equal(oldPointerWritten, false);
  assert.equal(lifecycle.current, second);
  assert.deepEqual(second.events, []);
  assert.throws(() => lifecycle.publish(first, oldGeneration), /session_locked/);
});

test('sensitive resource locks synchronously and operational SQL closes even if sensitive close fails', async () => {
  const events: string[] = [];
  const session = { ...resource('supervisor'), sensitive: {
    lock() { events.push('sensitive_locked'); }, async close() { events.push('sensitive_closed'); throw new Error('sensitive_close_failed'); },
  } };
  const lifecycle = new SessionLifecycle<typeof session>(() => {});
  lifecycle.publish(session, 0);
  const retired = lifecycle.retire(0, async () => { events.push('persisted'); });
  assert.deepEqual(events, ['sensitive_locked']);
  await assert.rejects(retired, /sensitive_close_failed/);
  assert.deepEqual(events, ['sensitive_locked', 'persisted', 'sensitive_closed']);
  assert.deepEqual(session.events, ['locked', 'closed']);
});

test('persisted denial resolves before an in-flight resource can close, while next account waits for full retirement', async () => {
  const closing = deferred<void>();
  const session = { ...resource('supervisor'), sensitive: { lock() {}, async close() { await closing.promise; } } };
  const lifecycle = new SessionLifecycle<typeof session>(() => {});
  lifecycle.publish(session, 0);
  let persisted = false;
  await lifecycle.retireAfterPersistence(0, async () => { persisted = true; });
  assert.equal(persisted, true); assert.equal(lifecycle.current, null);
  let settled = false;
  const waiter = lifecycle.settled().then(() => { settled = true; });
  await Promise.resolve(); assert.equal(settled, false);
  closing.resolve(); await waiter;
  assert.deepEqual(session.events, ['locked', 'closed']);
});

test('failed or stale persistence denial cannot hang or act on a new account', async () => {
  const lifecycle = new SessionLifecycle<ReturnType<typeof resource>>(() => {});
  const first = resource('first'); lifecycle.publish(first, 0);
  await assert.rejects(lifecycle.retireAfterPersistence(0, async () => { throw new Error('secure_pointer_failed'); }), /secure_pointer_failed/);
  await lifecycle.settled();
  const second = resource('second'); lifecycle.publish(second, lifecycle.generation);
  await lifecycle.retireAfterPersistence(0, async () => assert.fail('Stale callback must not persist'));
  assert.equal(lifecycle.current, second); assert.deepEqual(second.events, []);
});
