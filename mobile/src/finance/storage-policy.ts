/** Private evidence policy. Operational capability/online references are NOT grants. */
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';

export const financialStorageGrant = z.strictObject({
  financial_storage_version: z.literal(1), profile: z.literal('financial-evidence-private-v1'),
  deployment_id: uuid, actor_id: uuid, device_id: uuid, session_id: uuid, stream_epoch: uuid,
  scope_revision: z.string().regex(/^[a-f0-9]{64}(?![\s\S])/), server_time: instant, expires_at: instant,
  maximum_offline_seconds: z.literal(86400), access: z.literal('local_evidence_only_not_posting_authority'),
  commands: z.tuple([z.literal('inventory.supplier_payment.record')]), reference_cache_seconds: z.literal(0),
  financial_uploads: z.literal(false),
}).refine(value => {
  const duration = Date.parse(value.expires_at) - Date.parse(value.server_time);
  return duration > 0 && duration <= 86400000;
}, 'Financial evidence authorization must expire within 24 hours.');

export const financialStorageContext = z.strictObject({
  deploymentId: uuid, actorId: uuid, deviceId: uuid, sessionId: uuid, streamEpoch: uuid,
  scopeRevision: z.string().regex(/^[a-f0-9]{64}(?![\s\S])/),
});
export type FinancialStorageContext = z.infer<typeof financialStorageContext>;
export type FinancialStorageGrant = z.infer<typeof financialStorageGrant>;
export interface FinancialEvidenceClock { requestStartedMs: number; receivedMs: number; highWaterMs: number }

export function parseFinancialStorageGrant(value: unknown, context: FinancialStorageContext, identity: StoreIdentity) {
  const grant = financialStorageGrant.parse(value);
  const expected = financialStorageContext.parse(context);
  if (expected.actorId !== identity.actorId || expected.deviceId !== identity.deviceId || expected.deploymentId !== identity.deploymentId ||
      grant.actor_id !== expected.actorId || grant.device_id !== expected.deviceId || grant.deployment_id !== expected.deploymentId ||
      grant.session_id !== expected.sessionId || grant.stream_epoch !== expected.streamEpoch || grant.scope_revision !== expected.scopeRevision) {
    throw new Error('financial_storage_context_mismatch_retain_original');
  }
  return grant;
}

/** Request START makes latency conservative; a delayed response cannot extend access. */
export function checkFinancialEvidenceClock(grant: FinancialStorageGrant, clock: FinancialEvidenceClock, now: number) {
  const values = [now, clock.requestStartedMs, clock.receivedMs, clock.highWaterMs];
  if (values.some(value => !Number.isSafeInteger(value) || value < 0) || clock.receivedMs < clock.requestStartedMs ||
      clock.receivedMs - clock.requestStartedMs > 60000 || clock.highWaterMs < clock.receivedMs) {
    throw new Error('financial_storage_invalid_clock');
  }
  if (now < clock.receivedMs || now < clock.highWaterMs - 2000) throw new Error('financial_storage_clock_rollback');
  if (Date.parse(grant.server_time) + now - clock.requestStartedMs >= Date.parse(grant.expires_at)) {
    throw new Error('financial_storage_window_expired_reauthenticate');
  }
  return { ...clock, highWaterMs: Math.max(now, clock.highWaterMs) };
}
