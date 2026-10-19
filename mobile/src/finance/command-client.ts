/** Explicit financial HTTP use only. NO scheduler, outbox mutation or posting UI.
 * Caller must persist original command/hash and sending intent BEFORE submit.
 * HTTP loss/404/status review never authorizes a replacement ID or physical payment.
 */
import { z } from 'zod';
import type { AuthClient, FinancialBoundHTTPRead } from '../auth/client';
import { uuid, type StoreIdentity } from '../protocol';
import { financialEvidenceHashInput } from './evidence-store';
import { financialCommandIdentity } from './command-transport';
import { parseFinancialUUIDEnvelope, parseFinancialUUIDResponse } from './uuid-commands';

const digest = z.string().length(64).regex(/^[a-f0-9]{64}$/);
const hashMap = z.record(uuid, digest);
type CommandAuth = Pick<AuthClient, 'submitFinancialCommands' | 'recoverFinancialCommand'>;

export class FinancialCommandClient {
  private closed = false;
  private busy = false;
  private readonly identity: Readonly<StoreIdentity>;
  constructor(private auth: CommandAuth, identity: StoreIdentity, private hash: (text: string) => Promise<string>) {
    this.identity = Object.freeze(financialCommandIdentity.parse(identity));
  }
  close() { this.closed = true; }
  private current() { if (this.closed) throw new Error('financial_command_client_closed'); }
  private async work<T>(action: () => Promise<T>): Promise<T> {
    this.current();
    if (this.busy) throw new Error('financial_command_request_in_flight');
    this.busy = true;
    try { return await action(); }
    finally { this.busy = false; }
  }
  private response(value: FinancialBoundHTTPRead, hashes: Record<string, string>) {
    this.current();
    if (value.binding.actorId !== this.identity.actorId || value.binding.deviceId !== this.identity.deviceId ||
        value.binding.deploymentId !== this.identity.deploymentId) throw new Error('financial_command_identity_mismatch');
    return parseFinancialUUIDResponse(value.response, { identity: this.identity, commandHashes: hashes });
  }
  submit(value: unknown, originalCommandHashes: Record<string, string>) {
    return this.work(async () => {
      const envelope = parseFinancialUUIDEnvelope(value, this.identity);
      const hashes = hashMap.parse(originalCommandHashes);
      if (envelope.operations.length !== Object.keys(hashes).length) throw new Error('financial_command_original_hash_required');
      for (const operation of envelope.operations) {
        const computed = digest.parse(await this.hash(financialEvidenceHashInput(this.identity, operation)));
        this.current();
        if (hashes[operation.operation_id] !== computed) throw new Error('financial_command_original_hash_required');
      }
      this.current();
      return this.response(await this.auth.submitFinancialCommands(envelope, this.identity), hashes);
    });
  }
  recover(operationId: string, originalCommandHash: string) {
    return this.work(async () => {
      const id = uuid.parse(operationId), hash = digest.parse(originalCommandHash);
      return this.response(await this.auth.recoverFinancialCommand(id, this.identity), { [id]: hash });
    });
  }
}
