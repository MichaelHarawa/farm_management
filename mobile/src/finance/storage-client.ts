/** Fresh authenticated grant acquisition only. No DB/key/native-screen side effect. */
import { z } from 'zod';
import type { AuthClient } from '../auth/client';
import { uuid, type StoreIdentity } from '../protocol';
import { checkFinancialEvidenceClock, financialStorageGrant, parseFinancialStorageGrant } from './storage-policy';
import { financialStorageRequestId } from './storage-transport';

export const financialStorageResponse = z.strictObject({ financial_storage_api_version: z.literal(1), request_id: financialStorageRequestId,
  grant: financialStorageGrant });
const identitySchema = z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid, streamEpoch: uuid });

export class FinancialStorageGrantReader {
  private closed = false;
  private busy = false;
  private used = new Set<string>();
  private readonly expected: Readonly<StoreIdentity & { streamEpoch: string }>;
  constructor(private auth: Pick<AuthClient, 'readFinancialStorageGrant'>, expected: StoreIdentity & { streamEpoch: string },
    private newRequestId: () => string, private now: () => number = Date.now) {
    this.expected = Object.freeze(identitySchema.parse(expected));
  }
  close() { this.closed = true; }
  private requireOpen() { if (this.closed) throw new Error('financial_storage_reader_closed'); }

  async read() {
    this.requireOpen();
    if (this.busy) throw new Error('financial_storage_grant_already_in_flight');
    this.busy = true;
    try {
      const requestId = financialStorageRequestId.parse(this.newRequestId());
      if (this.used.has(requestId) || this.used.size >= 1000) throw new Error('financial_storage_fresh_request_required');
      this.used.add(requestId); // A failed/lost response also consumes this local challenge.
      const requestStartedMs = this.now();
      const result = await this.auth.readFinancialStorageGrant(requestId);
      const receivedMs = this.now();
      this.requireOpen();
      const body = financialStorageResponse.parse(result.response);
      const expected = this.expected, binding = result.binding;
      if (body.request_id !== requestId || binding.actorId !== expected.actorId || binding.deviceId !== expected.deviceId ||
          binding.deploymentId !== expected.deploymentId || body.grant.stream_epoch !== expected.streamEpoch) {
        throw new Error('financial_storage_response_binding_mismatch');
      }
      const context = { ...expected, sessionId: uuid.parse(binding.sessionId), scopeRevision: body.grant.scope_revision };
      const grant = parseFinancialStorageGrant(body.grant, context, expected);
      checkFinancialEvidenceClock(grant, { requestStartedMs, receivedMs, highWaterMs: receivedMs }, receivedMs);
      return { grant, context, observation: { requestStartedMs, receivedMs } };
    } finally { this.busy = false; }
  }
}
