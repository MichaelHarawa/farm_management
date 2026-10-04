import { ApiError } from '../auth/client';
import type { Capabilities } from '../protocol';
import type { SyncApi } from '../sync/engine';
import { result } from '../sync/protocol';
import { SyncStore } from '../sync/store';
import { commandName, onlineOnly } from './commands';

// Explicit foreground confirmation only. The automatic sync engine excludes
// these rows before marking any sending intent, including after process death.
export async function submitOnlinePoultry(options:{store:SyncStore;api:SyncApi;authorize():Promise<Capabilities>;
  operationId:string;owner:string;confirmed:boolean;now?:()=>number}) {
  const {store,api,operationId,owner}=options,now=options.now??Date.now;
  if(!await store.repository.acquireLease(owner,now(),60000))throw new Error('sync_busy');
  const fence=()=>({owner,now:now()});
  try {
    const caps=await options.authorize(),owned=await store.operationDetails(operationId);
    if(caps.deployment_id!==store.repository.identity.deploymentId||caps.device_id!==store.repository.identity.deviceId||
      !onlineOnly(owned.command)||!caps.commands[commandName(owned.command)]?.available||caps.commands[commandName(owned.command)]?.mode!=='online')
      throw new Error('online_authority_required');
    // A prior unknown outcome must be queried first. Never replace its UUID.
    let receipt:unknown;
    try {receipt=await api.request(`/mobile-sync/operations/${operationId}`);}
    catch(error){if(!(error instanceof ApiError&&error.status===404&&error.code==='operation_not_found'))throw error;}
    if(receipt){const parsed=result.parse(receipt);if(parsed.operation_id!==operationId)throw new Error('foreign_receipt');
      await store.reconcile(parsed,new Date(now()).toISOString(),fence());return parsed;}
    if(!options.confirmed)throw new Error('fresh_foreground_confirmation_required');
    // Check authority again after recovery lookup. Confirmation is not
    // persisted or carried into a background run or subsequent restart.
    const current=await options.authorize();
    if(current.deployment_id!==caps.deployment_id||current.device_id!==caps.device_id||current.scope_revision!==caps.scope_revision||
      !current.commands[commandName(owned.command)]?.available||current.commands[commandName(owned.command)]?.mode!=='online')
      throw new Error('online_authority_changed');
    if(!await store.repository.renewLease(owner,now()))throw new Error('sync_lease_lost');
    const command=await store.claimOnline(operationId,fence());
    try {
      const accepted=result.parse(await api.request('/mobile-sync/poultry-online',command));
      if(accepted.operation_id!==operationId)throw new Error('foreign_receipt');
      await store.reconcile(accepted,new Date(now()).toISOString(),fence());return accepted;
    } catch(error){
      await store.wait([operationId],'online_outcome_unknown',now()+30000,fence());throw error;
    }
  } finally { try { await store.repository.releaseLease(owner); } catch { /* A retired session retains the original intent. */ } }
}
