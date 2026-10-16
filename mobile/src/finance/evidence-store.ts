/** Private, separate-database evidence store. No native opener, API or UI uses it yet.
 * The eventual caller MUST supply a keyed SQLCipher Database, authenticated grant
 * and current session context. This host-testable layer alone is NOT encryption.
 */
import { z } from 'zod';
import type { Database, SqlConnection } from '../db/sql';
import { canonical } from '../db/repository';
import { uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';
import { financialUUIDOperation } from './uuid-commands';
import { checkFinancialEvidenceClock, financialStorageContext, financialStorageGrant, parseFinancialStorageGrant,
  type FinancialEvidenceClock, type FinancialStorageContext, type FinancialStorageGrant } from './storage-policy';

const identitySchema = z.strictObject({ actorId: uuid, deviceId: uuid, deploymentId: uuid });
const digestSchema = z.string().regex(/^[a-f0-9]{64}(?![\s\S])/);
const PROFILE = 'financial-supplier-payment-uuid-private-v1';
const MARKER = 'financial-evidence-private-v1';
const MAX_ROWS = 1000, MAX_BYTES = 16 * 1024 * 1024;
const DDL = `
CREATE TABLE financial_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE financial_commands(operation_id TEXT PRIMARY KEY, operation_json TEXT NOT NULL, command_hash TEXT NOT NULL, byte_count INTEGER NOT NULL CHECK(byte_count>0));
CREATE TABLE financial_delivery(operation_id TEXT PRIMARY KEY REFERENCES financial_commands(operation_id), state TEXT NOT NULL CHECK(state='pending_local_evidence'));
CREATE TRIGGER financial_command_immutable BEFORE UPDATE ON financial_commands BEGIN SELECT RAISE(ABORT,'immutable_financial_evidence'); END;
CREATE TRIGGER financial_command_retained BEFORE DELETE ON financial_commands BEGIN SELECT RAISE(ABORT,'retained_financial_evidence'); END;
CREATE TRIGGER financial_delivery_retained BEFORE DELETE ON financial_delivery BEGIN SELECT RAISE(ABORT,'retained_financial_evidence'); END;
CREATE TRIGGER financial_identity_immutable BEFORE UPDATE ON financial_meta WHEN OLD.key IN ('identity','profile') BEGIN SELECT RAISE(ABORT,'immutable_financial_identity'); END;
CREATE TRIGGER financial_meta_retained BEFORE DELETE ON financial_meta BEGIN SELECT RAISE(ABORT,'retained_financial_metadata'); END;`;

interface Authorization { grant: FinancialStorageGrant; clock: FinancialEvidenceClock; blocked: boolean }
const savedAuthorization = z.strictObject({ grant: financialStorageGrant, blocked: z.boolean(),
  clock: z.strictObject({ requestStartedMs: z.number().int().nonnegative(), receivedMs: z.number().int().nonnegative(), highWaterMs: z.number().int().nonnegative() }),
});
interface Stored { operation_id: string; operation_json: string; command_hash: string; byte_count: number }
export interface FinancialEvidence {
  operation: z.infer<typeof financialUUIDOperation>; commandHash: string; status: 'pending_local_evidence';
}

export function financialEvidenceHashInput(identity: StoreIdentity, operation: z.infer<typeof financialUUIDOperation>) {
  // EXACT Django UUID-v2 basis. Do not normalize dates, order, microseconds or decimal strings.
  return canonical({ basis: PROFILE, deployment_id: identity.deploymentId,
    actor_id: identity.actorId, device_id: identity.deviceId, operation });
}

export class FinancialEvidenceStore {
  private generation = 0;
  private context: FinancialStorageContext | null = null;
  readonly identity: Readonly<StoreIdentity>;
  private constructor(private db: Database, identity: StoreIdentity, private hash: (input: string) => Promise<string>,
    private now: () => number) { this.identity = Object.freeze(identitySchema.parse(identity)); }

  static async open(db: Database, identity: StoreIdentity, hash: (input: string) => Promise<string>, now: () => number = Date.now) {
    const store = new FinancialEvidenceStore(db, identity, hash, now);
    await db.exec('PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;');
    if ((await db.first<{ foreign_keys: number }>('PRAGMA foreign_keys'))?.foreign_keys !== 1) throw new Error('foreign_keys_unavailable');
    await db.transaction(async tx => {
      const version = (await tx.first<{ user_version: number }>('PRAGMA user_version'))?.user_version ?? 0;
      const tables = await tx.all<{ name: string }>("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'");
      if (version === 0) {
        if (tables.length) throw new Error('financial_storage_separate_database_required');
        await tx.exec(DDL);
        await tx.run('INSERT INTO financial_meta VALUES(?,?)', ['profile', MARKER]);
        await tx.run('INSERT INTO financial_meta VALUES(?,?)', ['identity', canonical(store.identity)]);
        await tx.exec('PRAGMA user_version=1');
      } else if (version !== 1 || tables.map(row => row.name).sort().join(',') !== 'financial_commands,financial_delivery,financial_meta' ||
        (await tx.first<{ value: string }>("SELECT value FROM financial_meta WHERE key='profile'"))?.value !== MARKER) {
        throw new Error('financial_storage_upgrade_or_review_required');
      }
      if ((await tx.first<{ value: string }>("SELECT value FROM financial_meta WHERE key='identity'"))?.value !== canonical(store.identity)) {
        throw new Error('financial_storage_identity_mismatch_retain_original');
      }
    });
    return store; // ALWAYS locked, including after process restart.
  }

  /** Only a FRESH successful authenticated response may call this; not a cached capability. */
  async authorize(value: unknown, expected: FinancialStorageContext, observation: { requestStartedMs: number; receivedMs: number }) {
    this.lock();
    const generation = this.generation;
    // Disable any old grant BEFORE parsing/replacing it. A failed fresh server
    // check must never leave an older authorization available after restart.
    await this.blockSavedAuthorization();
    this.sameGeneration(generation);
    const context = financialStorageContext.parse(expected);
    const grant = parseFinancialStorageGrant(value, context, this.identity);
    const clock = checkFinancialEvidenceClock(grant, { ...observation, highWaterMs: observation.receivedMs }, this.now());
    await this.db.transaction(async tx => {
      this.sameGeneration(generation);
      await this.saveAuthorization(tx, { grant, clock, blocked: false });
      checkFinancialEvidenceClock(grant, clock, this.now());
      this.sameGeneration(generation);
    });
    this.sameGeneration(generation);
    this.context = context;
  }

  /** Called ONLY after the enclosing auth lifecycle has allowed cached access and private unlock. */
  async unlock(expected: FinancialStorageContext) {
    this.lock();
    const generation = this.generation;
    const context = financialStorageContext.parse(expected);
    await this.protected(generation, () => this.db.transaction(async tx => {
      const saved = await this.authorization(tx, generation, context);
      await this.finish(tx, saved, generation);
    }));
    this.sameGeneration(generation);
    this.context = context;
  }

  /** Synchronous generation fence: a pending hash/read/transaction cannot reopen this instance. */
  lock() { this.generation++; this.context = null; }

  /** Caller must first durably deny its enclosing auth pointer. Failure is NOT successful revocation. */
  async deny() {
    this.lock();
    await this.blockSavedAuthorization();
  }
  private async blockSavedAuthorization() {
    await this.db.transaction(async tx => {
      // Authorization is replaceable policy metadata, not original business
      // evidence. This also blocks malformed old policy without parsing it.
      await tx.run("UPDATE financial_meta SET value=? WHERE key='authorization'", ['{"blocked":true}']);
    });
  }

  async close() { this.lock(); await this.db.close(); }

  private sameGeneration(generation: number) {
    if (generation !== this.generation) throw new Error('financial_storage_locked_retain_original');
  }
  private active() {
    if (!this.context) throw new Error('financial_storage_locked_retain_original');
    return { generation: this.generation, context: this.context };
  }
  private async saveAuthorization(tx: SqlConnection, value: Authorization) {
    await tx.run('INSERT INTO financial_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ['authorization', canonical(value)]);
  }
  private async authorization(tx: SqlConnection, generation: number, context: FinancialStorageContext) {
    this.sameGeneration(generation);
    const row = await tx.first<{ value: string }>("SELECT value FROM financial_meta WHERE key='authorization'");
    if (!row) throw new Error('financial_storage_authorization_required');
    let decoded: unknown;
    try { decoded = JSON.parse(row.value); } catch { throw new Error('financial_storage_review_required'); }
    if (!decoded || typeof decoded !== 'object' || !('blocked' in decoded) || decoded.blocked !== false) {
      throw new Error('financial_storage_reauthentication_required');
    }
    const parsed = savedAuthorization.safeParse(decoded);
    if (!parsed.success) throw new Error('financial_storage_review_required');
    const saved = parsed.data;
    const grant = parseFinancialStorageGrant(saved.grant, context, this.identity);
    const clock = checkFinancialEvidenceClock(grant, saved.clock, this.now());
    await this.saveAuthorization(tx, { grant, clock, blocked: false });
    this.sameGeneration(generation);
    return { grant, clock };
  }

  private async finish(tx: SqlConnection, authorization: Omit<Authorization, 'blocked'>, generation: number) {
    const clock = checkFinancialEvidenceClock(authorization.grant, authorization.clock, this.now());
    await this.saveAuthorization(tx, { ...authorization, clock, blocked: false });
    this.sameGeneration(generation);
    checkFinancialEvidenceClock(authorization.grant, clock, this.now());
  }
  private async protected<T>(generation: number, work: () => Promise<T>) {
    try { return await work(); }
    catch (error) {
      if (generation === this.generation && error instanceof Error && /^financial_storage_(?:context_mismatch|invalid_clock|clock_rollback|window_expired|reauthentication_required|authorization_required|review_required)/.test(error.message)) {
        // Outside the failed/rolled-back transaction. If persistence fails,
        // propagate failure; never advertise a durable denial as successful.
        await this.deny();
      }
      throw error;
    }
  }

  async capture(value: unknown): Promise<FinancialEvidence> {
    const { generation, context } = this.active();
    const operation = financialUUIDOperation.parse(value); // Deep copy; caller edits cannot race hashing.
    const serialized = canonical(operation);
    const commandHash = digestSchema.parse(await this.hash(financialEvidenceHashInput(this.identity, operation)));
    this.sameGeneration(generation);
    await this.protected(generation, () => this.db.transaction(async tx => {
      const authorization = await this.authorization(tx, generation, context);
      const saved = await tx.first<Stored>('SELECT * FROM financial_commands WHERE operation_id=?', [operation.operation_id]);
      if (saved) {
        if (saved.operation_json !== serialized || saved.command_hash !== commandHash || saved.byte_count !== byteLength(serialized)) {
          throw new Error('financial_evidence_idempotency_mismatch_retain_original');
        }
        const delivery = await tx.first<{ state: string }>('SELECT state FROM financial_delivery WHERE operation_id=?', [operation.operation_id]);
        if (delivery?.state !== 'pending_local_evidence') throw new Error('financial_evidence_review_required');
      } else {
        const budget = await tx.first<{ count: number; bytes: number }>('SELECT COUNT(*) AS count, COALESCE(SUM(byte_count),0) AS bytes FROM financial_commands');
        if (!budget || budget.count >= MAX_ROWS || budget.bytes + byteLength(serialized) > MAX_BYTES) throw new Error('financial_evidence_storage_limit_retain_original');
        await tx.run('INSERT INTO financial_commands VALUES(?,?,?,?)', [operation.operation_id, serialized, commandHash, byteLength(serialized)]);
        await tx.run("INSERT INTO financial_delivery VALUES(?,'pending_local_evidence')", [operation.operation_id]);
      }
      await this.finish(tx, authorization, generation); // Roll back BOTH rows if locked during SQL.
    }));
    this.sameGeneration(generation);
    return { operation, commandHash, status: 'pending_local_evidence' };
  }

  /** Bounded local page, never a confirmed cash total or an upload queue API. */
  async page(after: string | null = null): Promise<{ evidence: FinancialEvidence[]; next: string | null }> {
    const { generation, context } = this.active();
    if (after !== null) uuid.parse(after);
    const result = await this.protected(generation, () => this.db.transaction(async tx => {
      const authorization = await this.authorization(tx, generation, context);
      const headers = await tx.all<{ operation_id: string; byte_count: number; actual_bytes: number }>(`SELECT operation_id,byte_count,
        length(CAST(operation_json AS BLOB)) AS actual_bytes FROM financial_commands
        WHERE (? IS NULL OR operation_id>?) ORDER BY operation_id LIMIT 26`, [after, after]);
      const evidence: FinancialEvidence[] = [];
      let bytes = 0;
      for (const header of headers.slice(0, 25)) {
        if (!Number.isSafeInteger(header.byte_count) || header.byte_count < 1 || header.actual_bytes !== header.byte_count || header.actual_bytes > 1048576) {
          throw new Error('financial_evidence_review_required');
        }
        if (bytes + header.actual_bytes > 1048576 && evidence.length) break;
        bytes += header.actual_bytes;
        const row = await tx.first<Stored & { state: string }>(`SELECT c.*,d.state FROM financial_commands c
          LEFT JOIN financial_delivery d USING(operation_id) WHERE c.operation_id=?`, [header.operation_id]);
        if (!row) throw new Error('financial_evidence_review_required');
        const operation = financialUUIDOperation.parse(JSON.parse(row.operation_json));
        const hash = digestSchema.parse(await this.hash(financialEvidenceHashInput(this.identity, operation)));
        this.sameGeneration(generation);
        if (row.operation_id !== operation.operation_id || row.operation_json !== canonical(operation) ||
            row.command_hash !== hash || row.byte_count !== byteLength(row.operation_json) || row.state !== 'pending_local_evidence') {
          throw new Error('financial_evidence_review_required');
        }
        evidence.push({ operation, commandHash: hash, status: 'pending_local_evidence' });
      }
      await this.finish(tx, authorization, generation);
      const last = evidence.at(-1)?.operation.operation_id;
      return { evidence, next: headers.length > evidence.length && last ? last : null };
    }));
    this.sameGeneration(generation);
    return result;
  }
}
