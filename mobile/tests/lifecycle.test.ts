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
