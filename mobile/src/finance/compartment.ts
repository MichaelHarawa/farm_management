/** Session-owned sensitive compartment. Host-testable orchestration, not encryption. */
import { z } from 'zod';
import { financialStorageContext, financialStorageGrant, checkFinancialEvidenceClock,
  type FinancialEvidenceClock, type FinancialStorageContext, type FinancialStorageGrant } from './storage-policy';
import type { FinancialEvidenceStore } from './evidence-store';
import type { FinancialStorageGrantReader } from './storage-client';
import { uuid, type StoreIdentity } from '../protocol';

const expectedSchema = z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid, streamEpoch: uuid });
const readySchema = z.strictObject({ version: z.literal(1), status: z.literal('ready'), grant: financialStorageGrant,
  context: financialStorageContext, clock: z.strictObject({ requestStartedMs: z.number().int().nonnegative(),
    receivedMs: z.number().int().nonnegative(), highWaterMs: z.number().int().nonnegative() }) });
const deniedSchema = z.strictObject({ version: z.literal(1), status: z.literal('denied') });
export type FinancialAccessRecord = z.infer<typeof readySchema> | { version: 1; status: 'denied' };
export interface FinancialCompartmentPorts {
  access: { read(): Promise<unknown>; write(value: FinancialAccessRecord): Promise<void> };
  open(): Promise<FinancialEvidenceStore>;
  reader(): Pick<FinancialStorageGrantReader, 'read' | 'close'>;
  isCurrent(): boolean;
  now(): number;
}
const denied: FinancialAccessRecord = { version: 1, status: 'denied' };

export class FinancialCompartment {
  private generation = 0;
  private store: FinancialEvidenceStore | null = null;
  private reader: Pick<FinancialStorageGrantReader, 'read' | 'close'> | null = null;
  private policy: z.infer<typeof readySchema> | null = null;
  private flight: Promise<unknown> | null = null;
  private closing: Promise<void> | null = null;
  private denying: Promise<void> | null = null;
  private activeGeneration: number | null = null;
  private requiresDenial = false;
  private readonly expected: Readonly<StoreIdentity & { streamEpoch: string }>;
  constructor(expected: StoreIdentity & { streamEpoch: string }, private ports: FinancialCompartmentPorts) {
    this.expected = Object.freeze(expectedSchema.parse(expected));
  }
  get isOpen() { return this.activeGeneration === this.generation && this.store !== null && this.policy !== null && this.ports.isCurrent(); }
  get isBusy() { return this.flight !== null || this.closing !== null || this.denying !== null; }
  private current(generation: number) {
    if (generation !== this.generation || !this.ports.isCurrent() || this.closing) throw new Error('financial_compartment_locked');
  }
  private binding(context: FinancialStorageContext, grant: FinancialStorageGrant) {
    if (context.actorId !== this.expected.actorId || context.deploymentId !== this.expected.deploymentId ||
        context.deviceId !== this.expected.deviceId || context.streamEpoch !== this.expected.streamEpoch ||
        grant.actor_id !== context.actorId || grant.device_id !== context.deviceId || grant.deployment_id !== context.deploymentId ||
        grant.session_id !== context.sessionId || grant.stream_epoch !== context.streamEpoch || grant.scope_revision !== context.scopeRevision) {
      throw new Error('financial_compartment_identity_mismatch');
    }
  }
  private begin<T>(work: (generation: number) => Promise<T>): Promise<T> {
    if (this.flight || this.closing || this.denying) return Promise.reject(new Error('financial_compartment_busy'));
    const generation = this.generation;
    const task = (async () => {
      this.current(generation);
      try { return await work(generation); }
      catch (error) {
        this.invalidate();
        // Never pretend a failed secure write established durable revocation.
        try { await this.ports.access.write(denied); }
        finally { const previous = this.store; this.store = null; await previous?.close(); }
        throw error;
      }
    })();
    this.flight = task;
    void task.finally(() => { if (this.flight === task) this.flight = null; }).catch(() => {});
    return task;
  }
  /** Write-ahead denial: crash/network/PIN/schema failure cannot reuse an old grant. */
  authorizeOnline() {
    return this.begin(async generation => {
      await this.ports.access.write(denied);
      this.current(generation);
      await this.detach();
      const reader = this.ports.reader(); this.reader = reader;
      let opened: FinancialEvidenceStore | null = null;
      try {
        const result = await reader.read();
        this.current(generation);
        this.binding(result.context, result.grant);
        opened = await this.ports.open(); // Private native unlock; no unkeyed fallback.
        this.current(generation);
        await opened.authorize(result.grant, result.context, result.observation);
        const clock = checkFinancialEvidenceClock(result.grant, { ...result.observation, highWaterMs: result.observation.receivedMs }, this.ports.now());
        const policy = readySchema.parse({ version: 1, status: 'ready', grant: result.grant, context: result.context, clock });
        await this.publishPointer(policy, generation);
        this.store = opened; this.policy = policy; this.activeGeneration = generation; this.requiresDenial = false; opened = null;
      } finally { reader.close(); if (this.reader === reader) this.reader = null; await opened?.close(); }
    });
  }
  /** Outer auth must already allow cached access; secure marker is an additional independent gate. */
  unlockCached() {
    return this.begin(async generation => {
      const raw = await this.ports.access.read();
      // Give a closed, actionable reason for an actual DENIED marker, before
      // any native key/PIN/SQL open. Corrupt or unknown records still fail strict
      // validation; none may become an authorization or a replacement grant.
      if (deniedSchema.safeParse(raw).success) throw new Error('financial_storage_reauthentication_required');
      const saved = readySchema.parse(raw);
      this.binding(saved.context, saved.grant);
      const clock = checkFinancialEvidenceClock(saved.grant, saved.clock, this.ports.now());
      await this.ports.access.write(denied); // Before PIN/open. Crash here requires fresh authorization.
      this.current(generation);
      await this.detach();
      let opened: FinancialEvidenceStore | null = null;
      try {
        opened = await this.ports.open();
        this.current(generation);
        await opened.unlock(saved.context);
        const policy = { ...saved, clock: checkFinancialEvidenceClock(saved.grant, clock, this.ports.now()) };
        await this.publishPointer(policy, generation);
        this.store = opened; this.policy = policy; this.activeGeneration = generation; this.requiresDenial = false; opened = null;
      } finally { await opened?.close(); }
    });
  }
  private async publishPointer(policy: z.infer<typeof readySchema>, generation: number) {
    this.current(generation);
    await this.ports.access.write(policy);
    try { this.current(generation); }
    catch (error) { await this.ports.access.write(denied); throw error; }
  }
  private async detach() {
    const previous = this.store; this.store = null; this.policy = null; this.activeGeneration = null;
    previous?.lock(); await previous?.close();
  }
  private access<T>(work: (store: FinancialEvidenceStore) => Promise<T>): Promise<T> {
    return this.begin(async generation => {
      const store = this.store, policy = this.policy;
      if (!store || !policy || this.activeGeneration !== generation) throw new Error('financial_compartment_locked');
      const clock = checkFinancialEvidenceClock(policy.grant, policy.clock, this.ports.now());
      await this.ports.access.write(denied); // Also protects process death during a read/save/checkpoint.
      this.current(generation);
      const result = await work(store);
      const next = { ...policy, clock: checkFinancialEvidenceClock(policy.grant, clock, this.ports.now()) };
      await this.publishPointer(next, generation);
      this.policy = next;
      return result;
    });
  }
  capture(value: unknown) { return this.access(store => store.capture(value)); }
  page(after: string | null = null) { return this.access(store => store.page(after)); }
  checkpoint() { return this.access(async () => {}); }

  lock() {
    this.generation++;
    this.reader?.close(); this.store?.lock(); this.activeGeneration = null;
  }
  /** Discard cached-restart eligibility before durable denial. */
  invalidate() { this.lock(); this.policy = null; this.requiresDenial = true; }
  deny(): Promise<void> {
    if (this.denying) return this.denying;
    this.invalidate();
    // Wait for older work BEFORE the final durable denial. Its allow/write is
    // generation-fenced and cannot race over a newer account's access marker.
    const task = (async () => {
      await this.flight?.catch(() => {});
      try { await this.ports.access.write(denied); }
      finally { await this.detach(); }
    })();
    this.denying = task;
    void task.finally(() => { if (this.denying === task) this.denying = null; }).catch(() => {});
    return task;
  }
  close(): Promise<void> {
    if (this.closing) return this.closing;
    const policy = this.flight || this.denying ? null : this.policy;
    this.lock();
    const generation = this.generation;
    this.closing = (async () => {
      await this.flight?.catch(() => {});
      await this.denying?.catch(() => {});
      try {
        // Ordinary background lock retains an authorized cached restart, but
        // advances an INDEPENDENT secure high-water mark before closing SQL.
        if (this.requiresDenial) await this.ports.access.write(denied);
        else if (policy && generation === this.generation) {
          const clock: FinancialEvidenceClock = checkFinancialEvidenceClock(policy.grant, policy.clock, this.ports.now());
          await this.ports.access.write({ ...policy, clock });
          if (generation !== this.generation) await this.ports.access.write(denied);
        }
      } catch (error) { await this.ports.access.write(denied); throw error; }
      finally { await this.detach(); }
    })();
    return this.closing;
  }
}
