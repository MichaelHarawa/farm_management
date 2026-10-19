/** Financial private unlock owns an UNPUBLISHED main session until all gates pass. */
import type { StoreIdentity } from '../protocol';

export interface FinancialReentryOrigin { base: string; partition: string; identity: StoreIdentity }
/** Reference identity is intentional: a replacement login for the same actor is NOT the old owner. */
export function requireFinancialSessionOwner<T extends object>(current: T | null, owner: object): T {
  if (current === null || current !== owner) throw new Error('session_locked');
  return current;
}
export function sameFinancialOrigin(left: FinancialReentryOrigin, right: FinancialReentryOrigin) {
  return left.base === right.base && left.partition === right.partition &&
    left.identity.actorId === right.identity.actorId && left.identity.deviceId === right.identity.deviceId &&
    left.identity.deploymentId === right.identity.deploymentId;
}

export async function publishPrivateFinancialSession<T extends { pointer: FinancialReentryOrigin }>(origin: FinancialReentryOrigin,
  ports: { current(): boolean; reopen(): Promise<T>; prepare(session: T): Promise<void>;
    publish(session: T): Promise<void>; dispose(session: T): Promise<void> }) {
  const expected = { base: origin.base, partition: origin.partition, identity: { ...origin.identity } };
  function requireCurrent() { if (!ports.current()) throw new Error('session_locked'); }
  requireCurrent();
  let pending: T | null = null, published = false;
  try {
    pending = await ports.reopen();
    requireCurrent();
    if (!sameFinancialOrigin(expected, pending.pointer)) throw new Error('original_identity_mismatch');
    await ports.prepare(pending); // Main data is still unpublished during HTTP and private OS prompts.
    requireCurrent();
    if (!sameFinancialOrigin(expected, pending.pointer)) throw new Error('original_identity_mismatch');
    await ports.publish(pending);
    published = true;
  } finally {
    // Includes cancellation, late denial, time/identity changes and publication failure.
    // No repository, key or original evidence is deleted or replaced.
    if (pending && !published) await ports.dispose(pending);
  }
}
