import { ApiError } from '../auth/client';
import type { Capabilities } from '../protocol';
import { canonical } from '../db/repository';
import { bootstrap, bootstrapPage, changesPage, pushResponse, result } from './protocol';
import { SyncStore, type Delivery } from './store';
import { ZodError } from 'zod';

export interface SyncApi { request(path: string, body?: unknown): Promise<unknown> }
export interface EngineOptions {
  api: SyncApi; store: SyncStore; authorize(): Promise<Capabilities>; owner: string;
  uploadsEnabled: boolean; now?: () => number; random?: () => number;
  maxPages?: number; maxCommands?: number; maxRunMs?: number;
}
export interface SyncOutcome { status: 'complete'|'paused'|'busy'; requests: number; pages: number; commands: number }
export function backoff(attempt: number, random: number, retryAfter = 0) {
  return Math.max(retryAfter,Math.min(300000,1000*2**Math.min(Math.max(attempt,1),8))*(0.5+Math.min(1,Math.max(0,random))*0.5));
}
function unsafeResponse(error: unknown) {
  return error instanceof ZodError || error instanceof SyntaxError || error instanceof ApiError &&
    error.status>=400 && error.status<500 && ![401,403,429].includes(error.status) || error instanceof Error &&
    ['foreign_receipt','push_receipt_set_mismatch','receipt_changed','receipt_entity_mismatch','receipt_payload_mismatch','mapping_rebound','query_original_operation','response_too_large'].includes(error.message);
}
// Same bounded coordinator for startup/manual/reconnect. Phase9 adds background scheduling.
export class SyncEngine {
  private flight: Promise<SyncOutcome> | null = null;
  private canceled = false;
  constructor(private options: EngineOptions) {}
  cancel() { this.canceled = true; }
  run(packs = ['operational-current-v1']): Promise<SyncOutcome> {
    if (this.flight) return this.flight;
    this.canceled = false;
    this.flight = this.execute(packs).finally(() => { this.flight = null; });
    return this.flight;
  }
  private async execute(packs: string[]): Promise<SyncOutcome> {
    const {store,api,owner} = this.options;
    const now = this.options.now ?? Date.now;
    const started = now(); let requests=0,pages=0,commands=0;
    const outcome = (status: SyncOutcome['status']): SyncOutcome => ({status,requests,pages,commands});
    if (!await store.repository.acquireLease(owner,now(),60000)) return outcome('busy');
    const active = async () => {
      if (this.canceled) throw new Error('sync_canceled');
      if (now()-started > (this.options.maxRunMs ?? 120000)) throw new Error('sync_run_budget');
      if (!await store.repository.renewLease(owner,now())) throw new Error('sync_lease_lost');
    };
    const call = async (path: string, body?: unknown) => {
      await active(); requests++;
      const value = await api.request(path,body);
      await active(); return value;
    };
    const maxPages = this.options.maxPages ?? 50;
    const fence = () => ({owner,now:now()});
    try {
      if (await store.notBefore()>now()) return outcome('paused');
      await active(); const capabilities = await this.options.authorize(); await active();
      if (capabilities.deployment_id !== store.repository.identity.deploymentId || capabilities.device_id !== store.repository.identity.deviceId) throw new Error('server_identity_mismatch');
      const pageRows = capabilities.limits?.page_rows ?? 500;
      await store.recoverSending(fence());
      let coverage = await store.coverage();
      if (coverage && (coverage.scope !== capabilities.scope_revision || coverage.epoch !== capabilities.stream_epoch)) {
        await store.repository.invalidateScope(fence()); coverage=null;
      }
      const selected = [...new Set([...(coverage?.packs ?? []),...packs])].sort();
      const download = async () => {
        let staged = await store.snapshot();
        if (staged && (Date.parse(staged.manifest.expires_at)<=now() || canonical(staged.manifest.packs)!==canonical(selected))) {
          await store.restartStaging(fence()); staged=null;
        }
        const m = bootstrap.parse(await call('/mobile-sync/bootstrap',{protocol_version:1,packs:selected,
          ...(staged?{resume_snapshot_id:staged.manifest.snapshot_id}:{})}));
        if (canonical(m.packs)!==canonical(selected)) throw new Error('snapshot_pack_mismatch');
        await store.beginSnapshot(m,capabilities.stream_epoch,capabilities.scope_revision,fence());
        for (;;) {
          const s = await store.snapshot(); if (!s) break;
          if (pages>=maxPages) return false;
          const p = bootstrapPage.parse(await call(`/mobile-sync/bootstrap/${s.manifest.snapshot_id}/pages?cursor=${encodeURIComponent(s.cursor)}`));
          await store.stageSnapshotPage(p,s.cursor,new Date(now()).toISOString(),fence()); pages++;
        }
        return true;
      };
      const pull = async () => {
        for (;;) {
          if (pages>=maxPages) return false;
          const cursor = await store.cursor(); if (!cursor) throw new Error('bootstrap_required');
          const p = changesPage.parse(await call(`/mobile-sync/changes?cursor=${encodeURIComponent(cursor)}&limit=${pageRows}`));
          await store.applyPage(p,cursor,fence()); pages++;
          if (p.run_complete) return true; // Empty visible page is not a completion signal.
        }
      };
      try {
        if (!coverage || await store.snapshot() || canonical(coverage.packs)!==canonical(selected)) if (!await download()) return outcome('paused');
        if (!await pull()) return outcome('paused');
      } catch (error) {
        const missingSnapshot=error instanceof ApiError&&error.status===404&&error.code==='snapshot_not_found';
        if (!(error instanceof ApiError) || !missingSnapshot&&(![409,410].includes(error.status)||!['resync_required','scope_reset_required'].includes(error.code))) throw error;
        // At most one recovery per run. History expiry preserves the last good replica.
        if (error.code==='scope_reset_required') { await store.repository.invalidateScope(fence()); throw new ApiError(401,'sign_in_required'); }
        await store.restartStaging(fence()); if (!await download() || !await pull()) return outcome('paused');
      }
      if (this.options.uploadsEnabled && capabilities.commands['poultry.mortality.record']?.available) {
        while (commands < (this.options.maxCommands ?? 50)) {
          await active();
          const rows = await store.claim(now(),owner,Math.min(20,(this.options.maxCommands??50)-commands));
          if (!rows.length) break;
          const resend: Delivery[] = [];
          try {
            for (const row of rows) {
              if (!row.ever_sent) { resend.push(row); continue; }
              try {
                const receipt = result.parse(await call(`/mobile-sync/operations/${row.operation_id}`));
                if (receipt.operation_id !== row.operation_id) throw new Error('foreign_receipt');
                await store.reconcile(receipt,new Date(now()).toISOString(),fence());
              } catch (error) {
                if (error instanceof ApiError && error.status===404 && error.code==='operation_not_found') resend.push(row);
                else throw error;
              }
            }
            if (resend.length) {
              const response = pushResponse.parse(await call('/mobile-sync/push',{protocol_version:1,device_id:store.repository.identity.deviceId,
                operations:resend.map((r)=>JSON.parse(r.command_json))}));
              if (response.deployment_id!==store.repository.identity.deploymentId || response.device_id!==store.repository.identity.deviceId ||
                response.results.length!==resend.length || new Set(response.results.map((r)=>r.operation_id)).size!==resend.length ||
                response.results.some((r)=>!resend.some((s)=>s.operation_id===r.operation_id))) throw new Error('push_receipt_set_mismatch');
              for (const receipt of response.results) {
                let owned=receipt;
                if(receipt.code==='idempotency_mismatch'){
                  owned=result.parse(await call(`/mobile-sync/operations/${receipt.operation_id}`));
                  if(owned.operation_id!==receipt.operation_id)throw new Error('foreign_receipt');
                  // Status has no request hash: a rejection for different content
                  // cannot be relabelled as a known failure of this local intent.
                  if(!['accepted','replayed'].includes(owned.outcome))throw new Error('query_original_operation');
                }
                await store.reconcile(owned,new Date(now()).toISOString(),fence());
              }
            }
            commands+=rows.length;
          } catch (error) {
            const retry = backoff(Math.max(...rows.map((r)=>r.attempts)),(this.options.random??Math.random)(),error instanceof ApiError?error.retryAfterMs:0);
            // A canceled/lost response remains unknown; never generate a new command UUID.
            try {
              if (unsafeResponse(error)) await store.quarantineSending(rows.map((r)=>r.operation_id),'protocol_review_unknown_outcome',fence());
              else await store.wait(rows.map((r)=>r.operation_id),error instanceof ApiError&&[401,403].includes(error.status)?'sign_in_required':'unknown_outcome',now()+retry,fence());
            } catch { /* Original encrypted sending intent survives close. */ }
            throw error;
          }
        }
        if (!await pull()) return outcome('paused');
      }
      await active();await store.finishRun(new Date(now()).toISOString(),fence());
      return outcome('complete'); // Transport completed, not a claim that every retained operation was accepted.
    } catch(error) {
      if (!(error instanceof ApiError && [401,403].includes(error.status)) &&
        !(error instanceof Error && ['sync_canceled','sync_lease_lost'].includes(error.message))) {
        try { await store.pauseUntil(now()+backoff(1,(this.options.random??Math.random)(),error instanceof ApiError?error.retryAfterMs:0),fence()); } catch { /* Retain durable request state when locked. */ }
      }
      throw error;
    } finally { try { await store.repository.releaseLease(owner); } catch { /* Expiring lease survives process/session death. */ } }
  }
}
