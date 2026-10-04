import { migrations } from './schema';
import type { Database, SqlConnection } from './sql';
import { type StoreIdentity } from '../protocol';
import { poultryCommand, onlineOnly, normalizedPayload, type PoultryCommand } from '../poultry/commands';

export async function migrate(db: Database, steps = migrations): Promise<void> {
  await db.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
  const fk = await db.first<{ foreign_keys: number }>('PRAGMA foreign_keys');
  if (fk?.foreign_keys !== 1) throw new Error('foreign_keys_unavailable');
  const current = (await db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version ?? 0;
  if (current > steps.length) throw new Error('database_upgrade_required');
  // Transactional DDL: failure rolls back every new migration, retaining prior version/outbox.
  await db.transaction(async (tx) => {
    for (let i = current; i < steps.length; i++) {
      await tx.exec(steps[i]!);
      await tx.exec(`PRAGMA user_version=${i + 1}`);
    }
  });
}

export class Repository {
  private bound = false;
  constructor(readonly db: Database, readonly identity: StoreIdentity) {}
  private requireBound() { if (!this.bound) throw new Error('original_identity_mismatch'); }

  async bindIdentity() {
    await this.db.transaction(async (tx) => {
      const saved = await tx.first<{ value: string }>('SELECT value FROM metadata WHERE key=?', ['identity']);
      const identity = JSON.stringify(this.identity);
      if (saved && saved.value !== identity) throw new Error('original_identity_mismatch');
      if (!saved) await tx.run('INSERT INTO metadata(key,value) VALUES(?,?)', ['identity', identity]);
    });
    this.bound = true;
  }

  async saveDraftAndEnqueue(input: PoultryCommand, hash: (canonical: string) => Promise<string>, mode: 'queued'|'online' = 'queued', draftKey?: string) {
    this.requireBound();
    const operation = poultryCommand.parse(input);
    if (onlineOnly(operation) !== (mode === 'online')) throw new Error('online_confirmation_required');
    const serialized = canonical(operation);
    const digest = await hash(commandHashInput(this.identity,operation));
    await this.db.transaction(async (tx) => {
      const count = await tx.first<{ count: number }>("SELECT COUNT(*) AS count FROM outbox WHERE state NOT IN ('accepted','rejected')");
      if ((count?.count ?? 0) >= 5000) throw new Error('queue_limit');
      if (mode === 'online' && await tx.first(`SELECT o.operation_id FROM outbox o JOIN online_intents i USING(operation_id)
        JOIN deliveries d USING(operation_id) WHERE o.entity_type=? AND o.entity_uuid=?
        AND d.status NOT IN ('confirmed','rejected','conflict','discarded') LIMIT 1`, [operation.entity_type,operation.entity_uuid]))
        throw new Error('original_online_intent_requires_recovery');
      if ('batch_uuid' in operation.payload) {
        const parent = await tx.first<{ tombstone: number }>('SELECT tombstone FROM confirmed_entities WHERE entity_type=? AND entity_uuid=?', ['poultry.batch', operation.payload.batch_uuid]);
        if (!parent || parent.tombstone) {
          const local = await tx.first<{operation_id:string}>(`SELECT o.operation_id FROM outbox o JOIN deliveries d USING(operation_id)
            WHERE o.entity_type='poultry.batch' AND o.entity_uuid=? AND json_extract(o.command_json,'$.action')='book'
            AND d.status IN ('queued','sending','retry_wait','dependency_blocked') LIMIT 1`, [operation.payload.batch_uuid]);
          // Child intent names a retained booking/delivery chain; no guessed FK.
          if (!local || !operation.depends_on.length) throw new Error('download_parent_first');
          const linked = await tx.first(`WITH RECURSIVE ancestors(id) AS (
            SELECT value FROM json_each(?) UNION SELECT p.depends_on FROM operation_dependencies p JOIN ancestors a ON p.operation_id=a.id)
            SELECT id FROM ancestors WHERE id=?`, [canonical(operation.depends_on), local.operation_id]);
          if (!linked) throw new Error('required_parent_dependency');
        }
      }
      if (operation.supersedes_operation_id) {
        const prior = await tx.first<{ result_json: string }>('SELECT result_json FROM receipts WHERE operation_id=?', [operation.supersedes_operation_id]);
        if (!prior || !['conflict','validation_failed','period_locked','permission_denied'].includes(JSON.parse(prior.result_json).outcome)) throw new Error('terminal_receipt_required');
        const next = await tx.first(`SELECT o.operation_id FROM outbox o JOIN deliveries d USING(operation_id)
          WHERE o.supersedes_operation_id=? AND d.status<>'discarded' LIMIT 1`,[operation.supersedes_operation_id]);
        if (next) throw new Error('correction_already_retained');
      }
      await tx.run(`INSERT INTO outbox(operation_id,entity_uuid,entity_type,actor_id,device_id,deployment_id,command_json,command_hash,captured_at,supersedes_operation_id)
        VALUES(?,?,?,?,?,?,?,?,?,?)`, [operation.operation_id, operation.entity_uuid, operation.entity_type, this.identity.actorId,
        this.identity.deviceId, this.identity.deploymentId, serialized, digest, operation.captured_at,operation.supersedes_operation_id ?? null]);
      await tx.run('INSERT INTO pending_overlays(operation_id,entity_uuid,entity_type,payload_json) VALUES(?,?,?,?)',
        [operation.operation_id, operation.entity_uuid, operation.entity_type, canonical(operation.payload)]);
      await tx.run("INSERT INTO deliveries(operation_id,status) VALUES(?,'queued')", [operation.operation_id]);
      if (mode === 'online') await tx.run('INSERT INTO online_intents(operation_id) VALUES(?)', [operation.operation_id]);
      for (const dependency of operation.depends_on) {
        if (dependency === operation.operation_id) throw new Error('dependency_cycle');
        await tx.run('INSERT INTO operation_dependencies(operation_id,depends_on) VALUES(?,?)', [operation.operation_id, dependency]);
      }
      if (draftKey) await tx.run('DELETE FROM form_drafts WHERE draft_key=?', [draftKey]);
    });
  }

  async saveForm(key: string, values: unknown) {
    this.requireBound();
    const json = canonical(values);
    if (!key || key.length > 120 || json.length > 32768) throw new Error('form_draft_budget');
    await this.db.run('INSERT INTO form_drafts VALUES(?,?,?) ON CONFLICT(draft_key) DO UPDATE SET values_json=excluded.values_json,updated_at=excluded.updated_at',
      [key,json,new Date().toISOString()]);
  }
  async form<T>(key: string): Promise<T|null> {
    this.requireBound();
    const row = await this.db.first<{values_json:string}>('SELECT values_json FROM form_drafts WHERE draft_key=?', [key]);
    return row ? JSON.parse(row.values_json) as T : null;
  }
  async clearForm(key: string) { this.requireBound(); await this.db.run('DELETE FROM form_drafts WHERE draft_key=?', [key]); }

  async setMetadata(key: string, value: unknown, tx: SqlConnection = this.db) {
    this.requireBound();
    if (key === 'identity') throw new Error('original_identity_mismatch');
    await tx.run('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', [key, JSON.stringify(value)]);
  }
  async metadata<T>(key: string): Promise<T | null> {
    this.requireBound();
    const row = await this.db.first<{ value: string }>('SELECT value FROM metadata WHERE key=?', [key]);
    return row ? JSON.parse(row.value) as T : null;
  }
  async queueCount() {
    this.requireBound();
    return (await this.db.first<{ count: number }>("SELECT COUNT(*) AS count FROM outbox o LEFT JOIN deliveries d USING(operation_id) WHERE o.state <> 'accepted' AND COALESCE(d.status,'quarantined')<>'discarded'"))?.count ?? 0;
  }
  async batches(after = '', limit = 25) {
    this.requireBound();
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('invalid_page_size');
    return this.db.all<{ entity_uuid: string; payload_json: string }>(
      'SELECT entity_uuid,payload_json FROM confirmed_entities WHERE entity_type=? AND tombstone=0 AND visible=1 AND entity_uuid>? ORDER BY entity_uuid LIMIT ?', ['poultry.batch', after, limit]);
  }
  async poultryBatches(after = '', search = '', status = '', limit = 25) {
    this.requireBound();
    if (!Number.isInteger(limit) || limit < 1 || limit > 100 || search.length > 120) throw new Error('invalid_page_size');
    const term = `%${search.replace(/[\\%_]/g, value => `\\${value}`)}%`;
    return this.db.all<{entity_uuid:string;payload_json:string;local_only:number}>(`SELECT * FROM (
      SELECT entity_uuid,payload_json,0 local_only FROM confirmed_entities WHERE entity_type='poultry.batch' AND visible=1 AND tombstone=0
      UNION ALL SELECT o.entity_uuid,json_set(p.payload_json,'$.status','booked','$.batch_id','Pending booking · ' || substr(o.entity_uuid,1,8)),1
      FROM pending_overlays p JOIN outbox o USING(operation_id) JOIN deliveries d USING(operation_id)
      WHERE o.entity_type='poultry.batch' AND json_extract(o.command_json,'$.action')='book' AND d.status IN ('queued','sending','retry_wait','dependency_blocked')
      AND NOT EXISTS(SELECT 1 FROM confirmed_entities c WHERE c.entity_type='poultry.batch' AND c.entity_uuid=o.entity_uuid))
      WHERE entity_uuid>? AND (json_extract(payload_json,'$.batch_id') LIKE ? ESCAPE '\\' OR entity_uuid LIKE ? ESCAPE '\\')
      AND (?='' OR json_extract(payload_json,'$.status')=?) ORDER BY entity_uuid LIMIT ?`, [after,term,term,status,status,limit]);
  }
  async batchDependency(batchUuid: string) {
    this.requireBound();
    const row = await this.db.first<{command_json:string}>(`SELECT o.command_json FROM outbox o JOIN deliveries d USING(operation_id)
      WHERE o.entity_type='poultry.batch' AND o.entity_uuid=? AND d.status IN ('queued','sending','retry_wait','dependency_blocked')
      AND json_extract(o.command_json,'$.action') IN ('book','mark_delivered','confirm_delivery') ORDER BY o.rowid DESC LIMIT 1`, [batchUuid]);
    return row ? poultryCommand.parse(JSON.parse(row.command_json)) : null;
  }
  async invalidateScope(lease?: {owner:string;now:number}) {
    this.requireBound();
    await this.db.transaction(async (tx) => {
      if(lease){const current=await tx.first<{owner:string;expires_ms:number}>('SELECT owner,expires_ms FROM sync_lease WHERE id=1');
        if(!current||current.owner!==lease.owner||current.expires_ms<=lease.now)throw new Error('sync_lease_lost');}
      await tx.run('DELETE FROM pack_membership');
      await tx.run('DELETE FROM pack_manifests');
      await tx.run('DELETE FROM confirmed_entities');
      await tx.run('DELETE FROM sync_state');
      await tx.run('DELETE FROM bootstrap_entities'); await tx.run('DELETE FROM bootstrap_pages'); await tx.run('DELETE FROM delta_fragments');
      await tx.run("UPDATE outbox SET state='quarantined' WHERE state <> 'accepted'");
      await tx.run("UPDATE deliveries SET status='quarantined' WHERE status NOT IN ('confirmed','discarded')");
      // Retain overlays, original immutable commands, mappings/receipts and attachments for original-user review.
    });
  }
  async acquireLease(owner: string, now: number, ttlMs = 30_000) {
    this.requireBound();
    if (!owner || !Number.isSafeInteger(now) || ttlMs < 1 || ttlMs > 60_000) throw new Error('invalid_lease');
    return this.db.transaction(async (tx) => {
      const lease = await tx.first<{ owner: string; expires_ms: number }>('SELECT owner,expires_ms FROM sync_lease WHERE id=1');
      if (lease && lease.expires_ms > now) return false;
      await tx.run('INSERT INTO sync_lease(id,owner,expires_ms) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires_ms=excluded.expires_ms', [owner, now + ttlMs]);
      return true;
    });
  }
  async releaseLease(owner: string) { this.requireBound(); await this.db.run('DELETE FROM sync_lease WHERE id=1 AND owner=?', [owner]); }
  async renewLease(owner: string, now: number, ttlMs = 60_000) {
    this.requireBound();
    if (!Number.isSafeInteger(now) || ttlMs < 1 || ttlMs > 60_000) throw new Error('invalid_lease');
    return (await this.db.run('UPDATE sync_lease SET expires_ms=? WHERE id=1 AND owner=? AND expires_ms>?', [now + ttlMs, owner, now])).changes === 1;
  }
}

export function normalizedInstant(value: string): string {
  return value.replace(/(?:\.(\d{1,6}))?Z$/, (_match, fraction: string | undefined) =>
    fraction && /[1-9]/.test(fraction) ? `.${fraction.padEnd(6, '0')}Z` : 'Z');
}

export function commandHashInput(identity: StoreIdentity, operation: PoultryCommand): string {
  // Match Django UTC precision and dependency normalization, not JS Date truncation.
  const normalized = { ...operation, captured_at: normalizedInstant(operation.captured_at),
    depends_on: [...operation.depends_on].sort(),
    payload: normalizedPayload(operation.payload) };
  return canonical({deployment_id:identity.deploymentId,actor_id:identity.actorId,device_id:identity.deviceId,operation:normalized});
}

export function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    const json = JSON.stringify(value);
    if (json === undefined) throw new Error('unsupported_canonical_value');
    return json;
  }
  if (Array.isArray(value)) return `[${value.map((item) => item === undefined ? 'null' : canonical(item)).join(',')}]`;
  const object = value as Record<string, unknown>;
  // Match JSON wire semantics for optional fields; valid existing command hashes
  // are unchanged. Never persist the invalid JSON token "undefined".
  return `{${Object.keys(object).filter((key) => object[key] !== undefined).sort().map((key) => `${JSON.stringify(key)}:${canonical(object[key])}`).join(',')}}`;
}
