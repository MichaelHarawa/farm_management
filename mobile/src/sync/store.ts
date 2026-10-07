import { canonical, commandHashInput, type Repository } from '../db/repository';
import type { SqlConnection } from '../db/sql';
import { mortalityCommand, type MortalityCommand, type Capabilities } from '../protocol';
import { poultryCommand, commandName, onlineOnly, normalizedPayload, type PoultryCommand } from '../poultry/commands';
import { bootstrap, bootstrapPage, changesPage, result, newer, byteLength, type Bootstrap, type Change, type Entity } from './protocol';

interface SnapshotState { manifest: Bootstrap; cursor: string; nextPage: number; bytes: number }
function frozenSnapshot(manifest: Bootstrap) {
  // Django re-signs this opaque page-zero token on resume. It is transport,
  // not frozen content. Compare every other validated field, and keep the
  // original durable page cursor/progress rather than rewinding to page zero.
  return canonical({...manifest,next_page_cursor:null});
}
export interface Coverage { deployment: string; epoch: string; scope: string; packs: string[]; watermark: string; completedAt: string }
export interface Delivery { operation_id: string; command_json: string; command_hash: string; status: string; reason: string | null; ever_sent: number; attempts: number; next_ms: number }
type Digest = (text: string) => Promise<string>;
export interface WriteLease { owner: string; now: number }
const KEY = 'phase4';
export class SyncStore {
  constructor(readonly repository: Repository, readonly hash: Digest) {}
  private get db() { return this.repository.db; }
  private async bound() { await this.repository.metadata('identity-check'); }
  private async fence(tx: SqlConnection, lease?: WriteLease) {
    if (!lease) return;
    const current = await tx.first<{owner:string;expires_ms:number}>('SELECT owner,expires_ms FROM sync_lease WHERE id=1');
    if (!current || current.owner!==lease.owner || current.expires_ms<=lease.now) throw new Error('sync_lease_lost');
  }
  private async get<T>(key: string, tx: SqlConnection = this.db): Promise<T | null> {
    const row = await tx.first<{ value: string }>('SELECT value FROM sync_state WHERE key=?', [`${KEY}:${key}`]);
    return row ? JSON.parse(row.value) as T : null;
  }
  private async put(key: string, value: unknown, tx: SqlConnection) {
    await tx.run('INSERT INTO sync_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', [`${KEY}:${key}`,canonical(value)]);
  }
  async coverage() { await this.bound(); return this.get<Coverage>('coverage'); }
  async cursor() { await this.bound(); return this.get<string>('download_cursor'); }
  async snapshot() { await this.bound(); return this.get<SnapshotState>('snapshot'); }
  async lastSuccess() { await this.bound(); return this.get<string>('last_success'); }
  async notBefore() { await this.bound(); return await this.get<number>('not_before') ?? 0; }
  async pauseUntil(at: number, lease?: WriteLease) { await this.bound(); await this.db.transaction(async(tx) => {await this.fence(tx,lease);await this.put('not_before',at,tx);}); }
  async finishRun(at: string, lease?: WriteLease) { await this.bound(); await this.db.transaction(async(tx) => {await this.fence(tx,lease);await this.put('last_success',at,tx);}); }
  async restartStaging(lease?: WriteLease) {
    await this.bound(); await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      await tx.run('DELETE FROM bootstrap_entities'); await tx.run('DELETE FROM bootstrap_pages');
      await tx.run('DELETE FROM sync_state WHERE key=?',[`${KEY}:snapshot`]);
    }); // Last good replica/cursors/outbox are deliberately retained.
  }
  async beginSnapshot(raw: unknown, epoch: string, scope: string, lease?: WriteLease) {
    await this.bound(); const m = bootstrap.parse(raw);
    if (m.deployment_id !== this.repository.identity.deploymentId || m.stream_epoch !== epoch || m.scope_revision !== scope ||
      m.manifest.some((p,i) => p.page !== i) || m.manifest.reduce((n,p) => n+p.row_count,0) !== m.row_count) throw new Error('snapshot_identity_or_manifest');
    await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      const old = await this.get<SnapshotState>('snapshot',tx);
      if (old?.manifest.snapshot_id === m.snapshot_id) {
        if (frozenSnapshot(old.manifest) !== frozenSnapshot(m)) throw new Error('snapshot_changed');
        return;
      }
      await tx.run('DELETE FROM bootstrap_entities'); await tx.run('DELETE FROM bootstrap_pages');
      await this.put('snapshot',{manifest:m,cursor:m.next_page_cursor,nextPage:0,bytes:0},tx);
    });
  }
  async stageSnapshotPage(raw: unknown, requestedCursor: string, now: string, lease?: WriteLease) {
    await this.bound(); const p = bootstrapPage.parse(raw);
    const digest = await this.hash(canonical(p.entities));
    await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      const s = await this.get<SnapshotState>('snapshot',tx);
      if (!s || s.cursor !== requestedCursor || p.snapshot_id !== s.manifest.snapshot_id || p.page !== s.nextPage) throw new Error('snapshot_page_order');
      if (Date.parse(now) >= Date.parse(s.manifest.expires_at)) throw new Error('snapshot_expired');
      const descriptor = s.manifest.manifest[p.page];
      const final = p.page === s.manifest.manifest.length-1;
      if (!descriptor || descriptor.sha256 !== digest || p.sha256 !== digest || descriptor.row_count !== p.entities.length ||
        p.page_complete !== final || final !== (p.next_page_cursor === null) || final !== !!p.delta_cursor || (!final && p.next_page_cursor === requestedCursor)) throw new Error('snapshot_checksum_or_completion');
      s.bytes += byteLength(canonical(p.entities));
      if (s.bytes > 32*1024*1024) throw new Error('snapshot_budget');
      for (const e of p.entities) await tx.run('INSERT INTO bootstrap_entities VALUES(?,?,?,?)',[e.entity_type,e.entity_uuid,e.revision,canonical(e.payload)]);
      await tx.run('INSERT INTO bootstrap_pages VALUES(?,?,?)',[p.page,digest,p.entities.length]);
      s.nextPage++;
      if (!final) { s.cursor = p.next_page_cursor!; await this.put('snapshot',s,tx); return; }
      const count = await tx.first<{n:number}>('SELECT COUNT(*) n FROM bootstrap_entities');
      if (count?.n !== s.manifest.row_count) throw new Error('snapshot_row_count');
      const orphan = await tx.first(`SELECT c.entity_uuid FROM bootstrap_entities c WHERE c.entity_type<>'poultry.batch'
        AND NOT EXISTS(SELECT 1 FROM bootstrap_entities b WHERE b.entity_type='poultry.batch' AND b.entity_uuid=json_extract(c.payload_json,'$.batch_uuid')) LIMIT 1`);
      if (orphan) throw new Error('snapshot_missing_parent');
      for (const pack of s.manifest.packs) {
        if (pack.startsWith('batch-v2:')) await tx.run('DELETE FROM offline_batch_exclusions WHERE batch_uuid=?', [pack.slice(9)]);
        await tx.run('DELETE FROM pack_membership WHERE pack_id=?',[pack]);
        await tx.run('INSERT INTO pack_manifests VALUES(?,?,?,?,1) ON CONFLICT(pack_id) DO UPDATE SET manifest_json=excluded.manifest_json,scope_revision=excluded.scope_revision,as_of=excluded.as_of,complete=1',
          [pack,canonical(s.manifest),s.manifest.scope_revision,now]);
      }
      // Bounded SQL iteration avoids loading 100k entities into JS at once.
      let after = '';
      for (;;) {
        const rows = await tx.all<{entity_type:Entity['entity_type'];entity_uuid:string;revision:string;payload_json:string}>(
          "SELECT * FROM bootstrap_entities WHERE entity_type || ':' || entity_uuid>? ORDER BY entity_type,entity_uuid LIMIT 100",[after]);
        if (!rows.length) break;
        for (const row of rows) {
          after = `${row.entity_type}:${row.entity_uuid}`;
          const e: Entity = { ...row, payload: JSON.parse(row.payload_json) };
          await this.upsert(e,tx);
          const batchUuid = e.entity_type === 'poultry.batch' ? e.entity_uuid : (e.payload as {batch_uuid:string}).batch_uuid;
          if (await tx.first('SELECT batch_uuid FROM offline_batch_exclusions WHERE batch_uuid=?', [batchUuid])) continue;
          const batch = await tx.first<{payload_json:string}>("SELECT payload_json FROM bootstrap_entities WHERE entity_type='poultry.batch' AND entity_uuid=?",[batchUuid]);
          for (const pack of s.manifest.packs) if (pack === `batch:${batchUuid}` || pack === `batch-v2:${batchUuid}` ||
              ['operational-current-v1','operational-current-v2'].includes(pack) && JSON.parse(batch!.payload_json).status !== 'closed')
            await tx.run('INSERT OR IGNORE INTO pack_membership VALUES(?,?,?)',[pack,e.entity_type,e.entity_uuid]);
        }
      }
      await this.visibility(tx);
      await tx.run('DELETE FROM delta_fragments');
      await this.put('coverage',{deployment:s.manifest.deployment_id,epoch:s.manifest.stream_epoch,scope:s.manifest.scope_revision,packs:s.manifest.packs,watermark:s.manifest.watermark,completedAt:now},tx);
      await this.put('download_cursor',p.delta_cursor,tx); await this.put('applied_cursor',p.delta_cursor,tx);
      await this.put('visible_sequence',s.manifest.watermark,tx);await this.put('last_page',null,tx);
      await tx.run('DELETE FROM sync_state WHERE key IN (?,?)',[`${KEY}:snapshot`,`${KEY}:run_watermark`]);
      await tx.run('DELETE FROM bootstrap_entities'); await tx.run('DELETE FROM bootstrap_pages');
    });
  }
  private async upsert(e: Entity, tx: SqlConnection) {
    const batchUuid = e.entity_type === 'poultry.batch' ? e.entity_uuid : (e.payload as {batch_uuid:string}).batch_uuid;
    if (await tx.first('SELECT batch_uuid FROM offline_batch_exclusions WHERE batch_uuid=?', [batchUuid])) return;
    const old = await tx.first<{revision:string;tombstone:number}>('SELECT revision,tombstone FROM confirmed_entities WHERE entity_type=? AND entity_uuid=?',[e.entity_type,e.entity_uuid]);
    if (old && !newer(e.revision,old.revision)) return;
    await tx.run(`INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json,tombstone,visible) VALUES(?,?,?,?,0,1)
      ON CONFLICT(entity_type,entity_uuid) DO UPDATE SET revision=excluded.revision,payload_json=excluded.payload_json,tombstone=0,visible=1`,[e.entity_type,e.entity_uuid,e.revision,canonical(e.payload)]);
  }
  private async visibility(tx: SqlConnection) {
    await tx.run(`UPDATE confirmed_entities SET visible=CASE WHEN tombstone=1 THEN 0
      WHEN EXISTS(SELECT 1 FROM pack_membership m WHERE m.entity_type=confirmed_entities.entity_type AND m.entity_uuid=confirmed_entities.entity_uuid)
      OR EXISTS(SELECT 1 FROM pending_overlays p WHERE p.entity_type=confirmed_entities.entity_type AND p.entity_uuid=confirmed_entities.entity_uuid)
      OR (entity_type='poultry.batch' AND EXISTS(SELECT 1 FROM pending_overlays p WHERE json_extract(p.payload_json,'$.batch_uuid')=confirmed_entities.entity_uuid)) THEN 1 ELSE 0 END`);
  }
  private async apply(change: Change, tx: SqlConnection) {
    if (change.kind === 'upsert') {
      const batchUuid = change.entity_type === 'poultry.batch' ? change.entity_uuid : (change.payload as {batch_uuid:string}).batch_uuid;
      if (await tx.first('SELECT batch_uuid FROM offline_batch_exclusions WHERE batch_uuid=?', [batchUuid])) return;
    }
    const old = await tx.first<{revision:string}>('SELECT revision FROM confirmed_entities WHERE entity_type=? AND entity_uuid=?',[change.entity_type,change.entity_uuid]);
    if (old && newer(old.revision,change.revision)) return;
    if (change.kind === 'upsert') {
      await this.upsert(change as Entity,tx);
      for (const pack of change.pack_ids) await tx.run('INSERT OR IGNORE INTO pack_membership VALUES(?,?,?)',[pack,change.entity_type,change.entity_uuid]);
    } else if (change.kind === 'evict_from_pack') {
      if (old && newer(change.revision,old.revision)) await tx.run('UPDATE confirmed_entities SET revision=? WHERE entity_type=? AND entity_uuid=?',[change.revision,change.entity_type,change.entity_uuid]);
      for (const pack of change.pack_ids) await tx.run('DELETE FROM pack_membership WHERE pack_id=? AND entity_type=? AND entity_uuid=?',[pack,change.entity_type,change.entity_uuid]);
    } else {
      await tx.run(`INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json,tombstone,visible) VALUES(?,?,?,'{}',1,0)
        ON CONFLICT(entity_type,entity_uuid) DO UPDATE SET revision=excluded.revision,payload_json='{}',tombstone=1,visible=0`,[change.entity_type,change.entity_uuid,change.revision]);
      await tx.run('DELETE FROM pack_membership WHERE entity_type=? AND entity_uuid=?',[change.entity_type,change.entity_uuid]);
    }
  }
  async applyPage(raw: unknown, requestedCursor: string, lease?: WriteLease) {
    await this.bound(); const page = changesPage.parse(raw);
    if (byteLength(canonical(page)) > 1024*1024 || !page.run_complete && requestedCursor === page.next_cursor) throw new Error('pull_budget_or_no_progress');
    const digest=await this.hash(canonical(page));
    await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      const coverage = await this.get<Coverage>('coverage',tx);
      if (!coverage || page.deployment_id !== coverage.deployment || page.stream_epoch !== coverage.epoch || page.scope_revision !== coverage.scope) throw new Error('pull_identity_or_cursor');
      const current=await this.get<string>('download_cursor',tx);
      if(requestedCursor!==current){
        const last=await this.get<{from:string;digest:string}>('last_page',tx);
        if(last?.from===requestedCursor&&last.digest===digest&&current===page.next_cursor)return; // Exact last-page replay is a no-op.
        throw new Error('pull_identity_or_cursor');
      }
      const watermark = await this.get<string>('run_watermark',tx);
      if (watermark && watermark !== page.run_watermark || newer(coverage.watermark,page.run_watermark)) throw new Error('pull_watermark_changed');
      const seen = new Set<string>();const previous=await this.get<string>('visible_sequence',tx)??coverage.watermark;
      let sequence = newer(coverage.watermark,previous)?coverage.watermark:previous;
      for (const c of page.changes) {
        if (!newer(c.sequence,sequence) || newer(c.sequence,page.run_watermark) || c.pack_ids.some((p) => !coverage.packs.includes(p))) throw new Error('pull_order_or_pack');
        sequence = c.sequence;
        if (!page.fragments.some((f) => f.transaction_id === c.transaction_id && f.fragment_index === c.fragment_index && f.fragment_final === c.fragment_final)) throw new Error('fragment_descriptor_missing');
      }
      for (const f of page.fragments) {
        if (seen.has(f.transaction_id)) throw new Error('duplicate_fragment'); seen.add(f.transaction_id);
        const unfinished = await tx.first<{transaction_id:string}>('SELECT transaction_id FROM delta_fragments LIMIT 1');
        if (unfinished && unfinished.transaction_id !== f.transaction_id) throw new Error('transaction_group_order');
        const changes = page.changes.filter((c) => c.transaction_id === f.transaction_id);
        const json = canonical(changes);
        const old = await tx.first<{changes_json:string;final:number}>('SELECT changes_json,final FROM delta_fragments WHERE transaction_id=? AND fragment_index=?',[f.transaction_id,f.fragment_index]);
        if (old && (old.changes_json !== json || old.final !== Number(f.fragment_final))) throw new Error('fragment_changed');
        await tx.run('INSERT OR IGNORE INTO delta_fragments VALUES(?,?,?,?,?,?)',[f.transaction_id,f.fragment_index,Number(f.fragment_final),json,byteLength(json)+changes.length*1024,changes.length]);
        const size = await tx.first<{bytes:number;rows:number}>('SELECT SUM(byte_count) bytes,SUM(row_count) rows FROM delta_fragments WHERE transaction_id=?',[f.transaction_id]);
        if ((size?.bytes ?? 0)>16*1024*1024 || (size?.rows ?? 0)>10000) throw new Error('transaction_budget');
        const parts = await tx.all<{fragment_index:number;final:number;changes_json:string}>('SELECT fragment_index,final,changes_json FROM delta_fragments WHERE transaction_id=? ORDER BY fragment_index',[f.transaction_id]);
        if (parts.some((p,i) => p.fragment_index !== i || p.final && i !== parts.length-1)) throw new Error('fragment_gap');
        if (f.fragment_final) {
          for (const part of parts) for (const c of JSON.parse(part.changes_json) as Change[]) await this.apply(c,tx);
          await tx.run('DELETE FROM delta_fragments WHERE transaction_id=?',[f.transaction_id]);
        }
      }
      await this.visibility(tx);
      await this.put('download_cursor',page.next_cursor,tx);
      await this.put('last_page',{from:requestedCursor,digest},tx);await this.put('visible_sequence',sequence,tx);
      const pending = await tx.first<{n:number}>('SELECT COUNT(*) n FROM delta_fragments');
      if (!pending?.n) await this.put('applied_cursor',page.next_cursor,tx);
      if (page.run_complete && pending?.n) throw new Error('unfinished_transaction_at_watermark');
      if(page.run_complete)await this.put('coverage',{...coverage,watermark:page.run_watermark,completedAt:page.server_time},tx);
      await this.put('run_watermark',page.run_complete ? null : page.run_watermark,tx);
    });
  }
  async recoverSending(lease?: WriteLease) {
    await this.bound(); await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      await tx.run("UPDATE outbox SET state='unknown' WHERE operation_id IN (SELECT operation_id FROM deliveries WHERE status='sending') AND state IN ('pending','unknown')");
      await tx.run("UPDATE deliveries SET status='retry_wait',reason='interrupted_sending',next_ms=0 WHERE status='sending'");
    });
  }
  async queue(after = '', limit = 25): Promise<Delivery[]> {
    await this.bound(); if (!Number.isInteger(limit) || limit<1 || limit>100) throw new Error('invalid_page_size');
    return this.db.all(`SELECT o.*,CASE WHEN o.state='quarantined' AND d.status<>'discarded' THEN 'quarantined' ELSE d.status END status,
      d.reason,MAX(d.ever_sent,CASE WHEN o.attempts>0 OR o.state IN ('unknown','accepted','rejected','conflict') THEN 1 ELSE 0 END) ever_sent,d.next_ms FROM outbox o JOIN deliveries d USING(operation_id)
      WHERE o.operation_id>? AND d.status<>'confirmed' ORDER BY o.operation_id LIMIT ?`,[after,limit]);
  }
  async operationDetails(id: string) {
    await this.bound();
    const row = await this.db.first<{command_json:string;command_hash:string;result_json:string|null}>(
      'SELECT o.command_json,o.command_hash,r.result_json FROM outbox o LEFT JOIN receipts r USING(operation_id) WHERE operation_id=?',[id]);
    if (!row) throw new Error('owned_operation_not_found');
    return {command:poultryCommand.parse(JSON.parse(row.command_json)),hash:row.command_hash,
      receipt:row.result_json?result.parse(JSON.parse(row.result_json)):null};
  }
  async claim(now: number, leaseOwner: string, limit = 20, capabilities?: Capabilities) {
    await this.bound(); return this.db.transaction(async (tx) => {
      const lease = await tx.first<{owner:string;expires_ms:number}>('SELECT * FROM sync_lease WHERE id=1');
      if (!lease || lease.owner !== leaseOwner || lease.expires_ms <= now) throw new Error('sync_lease_lost');
      await tx.run(`UPDATE deliveries SET status='dependency_blocked',reason='parent_not_confirmed'
        WHERE status IN ('queued','retry_wait') AND EXISTS(SELECT 1 FROM operation_dependencies p JOIN deliveries parent ON parent.operation_id=p.depends_on
          WHERE p.operation_id=deliveries.operation_id AND parent.status<>'confirmed')`);
      const rows = await tx.all<Delivery & {actor_id:string;device_id:string;deployment_id:string}>(`SELECT o.*,d.status,d.reason,d.ever_sent,d.next_ms FROM outbox o JOIN deliveries d USING(operation_id)
        WHERE d.status IN ('queued','retry_wait','dependency_blocked') AND d.next_ms<=? AND o.state IN ('pending','unknown')
        AND NOT EXISTS(SELECT 1 FROM online_intents i WHERE i.operation_id=o.operation_id)
        AND NOT EXISTS(SELECT 1 FROM operation_dependencies p JOIN deliveries parent ON parent.operation_id=p.depends_on WHERE p.operation_id=o.operation_id AND parent.status<>'confirmed')
        ORDER BY o.captured_at,o.operation_id LIMIT ?`,[now,limit]);
      const ready: Delivery[] = []; let bytes = 200;
      for (const row of rows) {
        const identity = this.repository.identity;
        if (row.actor_id!==identity.actorId || row.device_id!==identity.deviceId || row.deployment_id!==identity.deploymentId) throw new Error('foreign_operation');
        const deps = await tx.all<{status:string}>(`SELECT d.status FROM operation_dependencies p JOIN deliveries d ON d.operation_id=p.depends_on WHERE p.operation_id=?`,[row.operation_id]);
        if (deps.some((d) => d.status !== 'confirmed')) {
          await tx.run("UPDATE deliveries SET status='dependency_blocked',reason='parent_not_confirmed' WHERE operation_id=?",[row.operation_id]); continue;
        }
        const command = poultryCommand.parse(JSON.parse(row.command_json));
        if (onlineOnly(command) || capabilities && !capabilities.commands[commandName(command)]?.available) continue;
        if (row.operation_id !== command.operation_id || await this.hash(commandHashInput(identity,command)) !== row.command_hash) throw new Error('immutable_command_identity_or_hash');
        if (bytes+byteLength(row.command_json)>1024*1024) break;
        bytes += byteLength(row.command_json);
        await tx.run("UPDATE deliveries SET status='sending',ever_sent=1,reason=NULL WHERE operation_id=?",[row.operation_id]);
        await tx.run("UPDATE outbox SET state='unknown',attempts=attempts+1 WHERE operation_id=?",[row.operation_id]);
        ready.push({...row,attempts:row.attempts+1});
      }
      return ready;
    });
  }
  async wait(ids: string[], reason: string, until: number, lease?: WriteLease) {
    await this.bound(); await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      for (const id of ids) await tx.run("UPDATE deliveries SET status='retry_wait',reason=?,next_ms=? WHERE operation_id=? AND status='sending'",[reason,until,id]);
    });
  }
  async quarantineSending(ids: string[], reason: string, lease?: WriteLease) {
    await this.bound(); await this.db.transaction(async(tx)=>{
      await this.fence(tx,lease);
      for (const id of ids) await tx.run("UPDATE deliveries SET status='quarantined',reason=? WHERE operation_id=? AND status='sending'",[reason,id]);
    }); // Not a business rejection; original unknown evidence and overlay remain.
  }
  async retry(id: string, now: number) {
    await this.bound(); await this.db.transaction(async(tx)=>{
      const row = await tx.first<{status:string;next_ms:number;state:string}>(`SELECT d.status,d.next_ms,o.state FROM deliveries d JOIN outbox o USING(operation_id) WHERE operation_id=?`,[id]);
      if (!row || row.status !== 'retry_wait' || !['pending','unknown'].includes(row.state) || row.next_ms>now || (await this.get<number>('not_before',tx)??0)>now) throw new Error('retry_not_due');
      await tx.run("UPDATE deliveries SET next_ms=0 WHERE operation_id=?",[id]);
    }); // The next engine run checks the original operation's status before replay.
  }
  async correction(id: string): Promise<MortalityCommand> {
    return mortalityCommand.parse(await this.queuedCorrection(id));
  }
  async queuedCorrection(id:string):Promise<PoultryCommand> {
    await this.bound();
    const row = await this.db.first<{command_json:string;result_json:string;status:string}>(`SELECT o.command_json,r.result_json,d.status FROM outbox o JOIN receipts r USING(operation_id) JOIN deliveries d USING(operation_id) WHERE operation_id=?`,[id]);
    if (!row || !['rejected','conflict'].includes(row.status) || !['conflict','validation_failed','period_locked','permission_denied'].includes(result.parse(JSON.parse(row.result_json)).outcome)) throw new Error('terminal_receipt_required');
    const command=poultryCommand.parse(JSON.parse(row.command_json));
    if(onlineOnly(command))throw new Error('online_original_review_required');
    return command;
  }
  async reconcile(raw: unknown, now: string, lease?: WriteLease) {
    await this.bound(); const receipt = result.parse(raw);
    await this.db.transaction(async (tx) => {
      await this.fence(tx,lease);
      const row = await tx.first<{command_json:string;state:string}>('SELECT command_json,state FROM outbox WHERE operation_id=?',[receipt.operation_id]);
      if (!row) throw new Error('foreign_receipt');
      const command = poultryCommand.parse(JSON.parse(row.command_json));
      if (receipt.code === 'idempotency_mismatch') throw new Error('query_original_operation');
      const accepted = ['accepted','replayed'].includes(receipt.outcome);
      if (accepted && (!receipt.canonical_entities!.some((e) => e.entity_type === command.entity_type && e.entity_uuid === command.entity_uuid) ||
        !receipt.entity_mappings!.some((m) => m.entity_type === command.entity_type && m.entity_uuid === command.entity_uuid))) throw new Error('receipt_entity_mismatch');
      if(accepted){
        const target=receipt.canonical_entities!.find(e=>e.entity_type===command.entity_type&&e.entity_uuid===command.entity_uuid)!.payload as Record<string,unknown>;
        const expected = { ...command.payload } as Record<string,unknown>;
        const actual = Object.fromEntries(Object.keys(expected).map(key=>[key,target[key]]));
        if (command.entity_type === 'poultry.batch') { delete expected.batch_uuid; delete actual.batch_uuid; }
        if (command.action === 'mark_delivered' && target.status !== 'delivered') throw new Error('receipt_payload_mismatch');
        if (['approve','reject'].includes(command.action)) {
          if (target.review_reason !== expected.reason || target.status !== (command.action === 'approve'?'approved':'rejected')) throw new Error('receipt_payload_mismatch');
        } else if (command.action !== 'recalculate_feed' && canonical(normalizedPayload(actual))!==canonical(normalizedPayload(expected))) throw new Error('receipt_payload_mismatch');
      }
      const existing = await tx.first<{result_json:string}>('SELECT result_json FROM receipts WHERE operation_id=?',[receipt.operation_id]);
      if (existing) {
        const before = result.parse(JSON.parse(existing.result_json));
        if (canonical({...before,outcome:before.outcome==='replayed'?'accepted':before.outcome}) !== canonical({...receipt,outcome:receipt.outcome==='replayed'?'accepted':receipt.outcome})) throw new Error('receipt_changed');
        if(row.state==='quarantined'&&!accepted) {
          const status=receipt.outcome==='conflict'?'conflict':'rejected';
          await tx.run('UPDATE outbox SET state=? WHERE operation_id=?',[status,receipt.operation_id]);
          await tx.run('UPDATE deliveries SET status=?,reason=? WHERE operation_id=?',[status,receipt.code,receipt.operation_id]);
        }
        return;
      }
      if (['dependency_blocked','retry_later'].includes(receipt.outcome)) {
        await tx.run('UPDATE deliveries SET status=?,reason=?,next_ms=? WHERE operation_id=?',[
          receipt.outcome==='dependency_blocked'?'dependency_blocked':'retry_wait',receipt.code,Date.parse(now)+30000,receipt.operation_id]); return;
      }
      await tx.run('INSERT INTO receipts VALUES(?,?,?)',[receipt.operation_id,canonical(receipt),now]);
      if (accepted) {
        for (const e of receipt.canonical_entities!) await this.upsert(e,tx);
        for (const m of receipt.entity_mappings!) {
          const old = await tx.first<{revision:string;server_id:string}>('SELECT revision,server_id FROM entity_mappings WHERE entity_type=? AND entity_uuid=?',[m.entity_type,m.entity_uuid]);
          if (old && old.server_id !== m.server_id) throw new Error('mapping_rebound');
          if (!old || newer(m.revision,old.revision)) await tx.run('INSERT INTO entity_mappings VALUES(?,?,?,?) ON CONFLICT(entity_type,entity_uuid) DO UPDATE SET revision=excluded.revision',[m.entity_type,m.entity_uuid,m.server_id,m.revision]);
        }
        await tx.run('DELETE FROM pending_overlays WHERE operation_id=?',[receipt.operation_id]);
        await tx.run("UPDATE outbox SET state='accepted' WHERE operation_id=?",[receipt.operation_id]);
        await tx.run("UPDATE deliveries SET status='confirmed',reason=NULL WHERE operation_id=?",[receipt.operation_id]);
      } else {
        await tx.run('INSERT INTO conflicts VALUES(?,?,?)',[receipt.operation_id,receipt.code,canonical(receipt)]);
        await tx.run('UPDATE outbox SET state=? WHERE operation_id=?',[receipt.outcome==='conflict'?'conflict':'rejected',receipt.operation_id]);
        await tx.run('UPDATE deliveries SET status=?,reason=? WHERE operation_id=?',[receipt.outcome==='conflict'?'conflict':'rejected',receipt.code,receipt.operation_id]);
      }
    });
  }
  async allowReviewedRetry(id:string,capabilities:Capabilities,acknowledgeOriginalIntent:boolean,lease:WriteLease) {
    await this.bound();
    if(!acknowledgeOriginalIntent || capabilities.deployment_id!==this.repository.identity.deploymentId ||
      capabilities.device_id!==this.repository.identity.deviceId)throw new Error('current_permission_and_owner_review_required');
    await this.db.transaction(async(tx)=>{
      await this.fence(tx,lease);
      const coverage=await this.get<Coverage>('coverage',tx);
      if(!coverage || coverage.scope!==capabilities.scope_revision || coverage.epoch!==capabilities.stream_epoch)throw new Error('download_current_scope_first');
      const row=await tx.first<Delivery&{state:string;actor_id:string;device_id:string;deployment_id:string}>(
        'SELECT o.*,d.status,d.ever_sent,d.reason,d.next_ms FROM outbox o JOIN deliveries d USING(operation_id) WHERE operation_id=?',[id]);
      if(!row || row.state!=='quarantined' || row.status==='discarded' || row.actor_id!==this.repository.identity.actorId ||
        row.device_id!==this.repository.identity.deviceId || row.deployment_id!==this.repository.identity.deploymentId)throw new Error('owned_quarantined_operation_required');
      if(await tx.first('SELECT operation_id FROM receipts WHERE operation_id=?',[id]))throw new Error('reconcile_original_terminal_receipt');
      const command=poultryCommand.parse(JSON.parse(row.command_json));
      if(!capabilities.commands[commandName(command)]?.available)throw new Error('current_permission_and_owner_review_required');
      if(command.operation_id!==id || await this.hash(commandHashInput(this.repository.identity,command))!==row.command_hash)throw new Error('immutable_command_identity_or_hash');
      if('batch_uuid' in command.payload){
        const parent=await tx.first<{payload_json:string}>("SELECT payload_json FROM confirmed_entities WHERE entity_type='poultry.batch' AND entity_uuid=? AND visible=1 AND tombstone=0",[command.payload.batch_uuid]);
        const required=command.action==='mark_delivered'?['booked']:command.action==='confirm_delivery'?['delivered']:['active','mature','selling'];
        if(!parent || !required.includes(JSON.parse(parent.payload_json).status))throw new Error('current_production_parent_required');
      }else if(onlineOnly(command)&&!await tx.first('SELECT entity_uuid FROM confirmed_entities WHERE entity_type=? AND entity_uuid=? AND visible=1 AND tombstone=0',[command.entity_type,command.entity_uuid]))throw new Error('current_review_target_required');
      const submitted=!!row.ever_sent||row.attempts>0;
      await tx.run('UPDATE outbox SET state=? WHERE operation_id=?',[submitted?'unknown':'pending',id]);
      await tx.run('UPDATE deliveries SET status=?,reason=?,next_ms=MAX(next_ms,?) WHERE operation_id=?',[
        submitted?'retry_wait':'queued','original_owner_reviewed',lease.now,id]);
    }); // Called ONLY after current online auth and exact owned operation_not_found.
  }
  async discardUnsent(id: string, acknowledgeBlockedChildren: boolean) {
    await this.bound(); await this.db.transaction(async (tx) => {
      const delivery = await tx.first<{ever_sent:number;status:string;state:string;attempts:number}>('SELECT d.*,o.state,o.attempts FROM deliveries d JOIN outbox o USING(operation_id) WHERE operation_id=?',[id]);
      if (!delivery || delivery.state!=='pending' || delivery.attempts>0 || delivery.ever_sent || !['queued','dependency_blocked'].includes(delivery.status)) throw new Error('cannot_discard_submitted');
      const children = await tx.first<{n:number}>('SELECT COUNT(*) n FROM operation_dependencies WHERE depends_on=?',[id]);
      if (children?.n && !acknowledgeBlockedChildren) throw new Error('confirm_blocked_children');
      await tx.run("UPDATE deliveries SET status='discarded',reason='explicit_unsent_discard' WHERE operation_id=?",[id]);
      await tx.run("UPDATE outbox SET state='quarantined' WHERE operation_id=?",[id]);
      await tx.run('DELETE FROM pending_overlays WHERE operation_id=?',[id]);
      await tx.run("UPDATE deliveries SET status='dependency_blocked',reason='parent_discarded' WHERE operation_id IN (SELECT operation_id FROM operation_dependencies WHERE depends_on=?) AND status IN ('queued','dependency_blocked','retry_wait')",[id]);
    });
  }
  async correctTerminal(id: string, next: MortalityCommand) {
    if (next.operation_id === id || next.supersedes_operation_id !== id) throw new Error('new_linked_operation_required');
    await this.repository.saveDraftAndEnqueue(next,this.hash); // Repository verifies durable terminal receipt atomically.
  }
  async batch(uuid: string) {
    await this.bound();
    const row = await this.db.first<{payload_json:string;revision:string}>("SELECT payload_json,revision FROM confirmed_entities WHERE entity_type='poultry.batch' AND entity_uuid=? AND tombstone=0 AND visible=1",[uuid]);
    const pending = await this.db.first<{quantity:number;unresolved:number}>(`SELECT COUNT(*) unresolved,
      COALESCE(SUM(CASE WHEN EXISTS(SELECT 1 FROM confirmed_entities c WHERE c.entity_type=p.entity_type AND c.entity_uuid=p.entity_uuid)
        THEN 0 ELSE json_extract(p.payload_json,'$.quantity_dead') END),0) quantity FROM pending_overlays p
      JOIN deliveries d USING(operation_id) WHERE json_extract(p.payload_json,'$.batch_uuid')=? AND d.status IN ('queued','sending','retry_wait','dependency_blocked')`,[uuid]);
    return row ? {payload:JSON.parse(row.payload_json),revision:row.revision,pendingMortality:pending?.quantity??0,unresolvedOperations:pending?.unresolved??0} : null;
  }

  async history(batchUuid: string, type: Entity['entity_type'], after = '', limit = 25) {
    await this.bound();
    if (!Number.isInteger(limit) || limit < 1 || limit > 100 || type === 'poultry.batch') throw new Error('invalid_history_page');
    return this.db.all<{entity_uuid:string;revision:string;payload_json:string}>(`SELECT entity_uuid,revision,payload_json FROM confirmed_entities
      WHERE entity_type=? AND json_extract(payload_json,'$.batch_uuid')=? AND entity_uuid>? AND visible=1 AND tombstone=0 ORDER BY entity_uuid LIMIT ?`,
      [type,batchUuid,after,limit]);
  }

  async removeBatch(batchUuid: string, owner: string, now: number) {
    await this.bound();
    if (!await this.repository.acquireLease(owner,now,60000)) throw new Error('sync_busy');
    try {
      await this.db.transaction(async tx => {
        await this.fence(tx,{owner,now});
        if (await this.get('snapshot',tx) || await tx.first('SELECT transaction_id FROM delta_fragments LIMIT 1')) throw new Error('finish_download_first');
        const pending = await tx.first(`SELECT p.operation_id FROM pending_overlays p WHERE p.entity_uuid=? OR json_extract(p.payload_json,'$.batch_uuid')=?
          OR EXISTS(SELECT 1 FROM confirmed_entities e WHERE e.entity_type=p.entity_type AND e.entity_uuid=p.entity_uuid
            AND json_extract(e.payload_json,'$.batch_uuid')=?) LIMIT 1`, [batchUuid,batchUuid,batchUuid]);
        const form = await tx.first(`SELECT draft_key FROM form_drafts WHERE json_extract(values_json,'$.batch_uuid')=? LIMIT 1`, [batchUuid]);
        const attachments = await tx.first(`SELECT attachment_id FROM attachment_jobs a WHERE a.state<>'complete' AND (a.source_uuid=? OR EXISTS(
          SELECT 1 FROM confirmed_entities e WHERE e.entity_uuid=a.source_uuid AND json_extract(e.payload_json,'$.batch_uuid')=?)) LIMIT 1`, [batchUuid,batchUuid]);
        if (pending || form || attachments) throw new Error('pending_work_requires_parent');
        await tx.run('INSERT OR IGNORE INTO offline_batch_exclusions VALUES(?)', [batchUuid]);
        await tx.run(`DELETE FROM pack_membership WHERE entity_uuid=? OR entity_uuid IN (
          SELECT entity_uuid FROM confirmed_entities WHERE json_extract(payload_json,'$.batch_uuid')=?)`, [batchUuid,batchUuid]);
        await tx.run(`DELETE FROM confirmed_entities WHERE (entity_type='poultry.batch' AND entity_uuid=?) OR json_extract(payload_json,'$.batch_uuid')=?`, [batchUuid,batchUuid]);
        for (const pack of [`batch:${batchUuid}`,`batch-v2:${batchUuid}`]) await tx.run('DELETE FROM pack_manifests WHERE pack_id=?', [pack]);
        const coverage = await this.get<Coverage>('coverage',tx);
        if (coverage) await this.put('coverage',{...coverage,packs:coverage.packs.filter(p => ![ `batch:${batchUuid}`,`batch-v2:${batchUuid}`].includes(p))},tx);
        await this.put('download_cursor',null,tx); await this.put('applied_cursor',null,tx);
      });
    } finally { await this.repository.releaseLease(owner); }
  }

  async excludedBatches() { await this.bound(); return this.db.all<{batch_uuid:string}>('SELECT batch_uuid FROM offline_batch_exclusions ORDER BY batch_uuid LIMIT 100'); }

  async downloadState() {
    await this.bound();
    return {staging:!!await this.snapshot(),incompleteTransaction:!!await this.db.first('SELECT transaction_id FROM delta_fragments LIMIT 1'),
      requiresBootstrap:!await this.cursor(),excluded:await this.excludedBatches()};
  }

  async originalOnlineIntent(entityUuid:string, action?:string) {
    await this.bound();
    const row = await this.db.first<{operation_id:string}>(`SELECT o.operation_id FROM outbox o JOIN online_intents i USING(operation_id)
      JOIN deliveries d USING(operation_id) WHERE o.entity_uuid=? AND (? IS NULL OR json_extract(o.command_json,'$.action')=?)
      AND d.status NOT IN ('confirmed','rejected','conflict','discarded') ORDER BY o.rowid LIMIT 1`, [entityUuid,action??null,action??null]);
    return row ? this.operationDetails(row.operation_id) : null;
  }
  async terminalOnlineIntent(entityUuid:string, action:string) {
    await this.bound();
    // A fresh attempt after a known failure keeps the audit link. Unknown or
    // quarantined intents are recovered by originalOnlineIntent, never replaced.
    const row=await this.db.first<{operation_id:string}>(`SELECT o.operation_id FROM outbox o JOIN online_intents i USING(operation_id)
      JOIN deliveries d USING(operation_id) JOIN receipts r USING(operation_id)
      WHERE o.entity_uuid=? AND json_extract(o.command_json,'$.action')=? AND d.status IN ('conflict','rejected')
      AND NOT EXISTS(SELECT 1 FROM outbox c JOIN deliveries cd USING(operation_id)
        WHERE c.supersedes_operation_id=o.operation_id AND cd.status<>'discarded') ORDER BY o.rowid DESC LIMIT 1`,[entityUuid,action]);
    return row?this.operationDetails(row.operation_id):null;
  }
  async claimOnline(id:string,lease:WriteLease) {
    await this.bound();
    return this.db.transaction(async tx => {
      await this.fence(tx,lease);
      const row = await tx.first<Delivery>(`SELECT o.*,d.status,d.ever_sent,d.reason,d.next_ms FROM outbox o JOIN deliveries d USING(operation_id)
        JOIN online_intents i USING(operation_id) WHERE o.operation_id=?`, [id]);
      if (!row || !['queued','retry_wait','sending'].includes(row.status)) throw new Error('online_intent_requires_review');
      const command=poultryCommand.parse(JSON.parse(row.command_json));
      if (!onlineOnly(command) || command.operation_id!==id || await this.hash(commandHashInput(this.repository.identity,command))!==row.command_hash)
        throw new Error('immutable_command_identity_or_hash');
      await tx.run('UPDATE online_intents SET submitted=1 WHERE operation_id=?', [id]);
      await tx.run("UPDATE deliveries SET status='sending',ever_sent=1,reason=NULL WHERE operation_id=?", [id]);
      await tx.run("UPDATE outbox SET state='unknown',attempts=attempts+1 WHERE operation_id=?", [id]);
      return command;
    });
  }
}
