import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import * as Network from 'expo-network';
import { phase4Pilot } from '../build-mode.native';
import type { AppSettings } from '../config';
import { Repository,canonical,commandHashInput } from '../db/repository';
import type { Database,SqlConnection,SqlValue } from '../db/sql';
import { mortalityCommand,type MortalityCommand,type Capabilities } from '../protocol';
import { SyncStore } from '../sync/store';
import { SyncEngine,type SyncApi } from '../sync/engine';

interface Expected { command:MortalityCommand; hash:string }
interface Checkpoint { identity:string; drafts:Expected[]; interruption?:{ kind:string; command?:MortalityCommand; cursor?:string|null; replicaHash?:string; operationIds?:string[]; reached?:boolean } }
type Report=(value:string)=>void;
export class NativeSyncProbe {
  constructor(private settings:AppSettings,private username:string,private store:SyncStore,
    private api:SyncApi,private authorize:()=>Promise<Capabilities>) {}
  private async guard() {
    if (!phase4Pilot || this.settings.environment!=='development' || this.settings.apiBaseUrl!=='http://10.0.2.2:7073/api/v1' || this.username!=='mobile-test-worker') throw new Error('synthetic_phase4_build_required');
    const batches=await this.store.repository.batches('',2);
    if (batches.length!==1 || JSON.parse(batches[0]!.payload_json).batch_id!=='SYNTHETIC-PHASE4') throw new Error('owned_phase4_download_required');
    return batches[0]!.entity_uuid;
  }
  private identity() { return canonical(this.store.repository.identity); }
  private key() { return `phase4-native-${this.store.repository.identity.deploymentId}`; }
  private async read():Promise<Checkpoint> {
    const value=await SecureStore.getItemAsync(this.key());
    if (!value) return {identity:this.identity(),drafts:[]};
    const parsed=JSON.parse(value) as Checkpoint;
    if(parsed.identity!==this.identity())throw new Error('original_identity_mismatch');
    return parsed;
  }
  private async write(value:Checkpoint) { await SecureStore.setItemAsync(this.key(),canonical(value)); }
  private async offline() {
    const state=await Network.getNetworkStateAsync();
    if(state.isConnected!==false)throw new Error('enable_airplane_mode_before_capture');
  }
  private command(batch:string,quantity=1):MortalityCommand {
    return mortalityCommand.parse({operation_id:Crypto.randomUUID(),entity_uuid:Crypto.randomUUID(),entity_type:'poultry.mortality',action:'record',payload_version:1,base_version:null,
      captured_at:new Date().toISOString(),depends_on:[],payload:{batch_uuid:batch,mortality_date:new Date().toISOString(),quantity_dead:quantity,
        suspected_cause:'Unknown',description:'Synthetic Phase4 native acceptance',action_taken:'Recorded and reviewed',reported_by_name:'Synthetic worker'}});
  }
  async manual(enabled:boolean) {
    await this.guard();await this.store.repository.setMetadata('native-phase4-manual',enabled);
    return enabled?'Automatic sync held for native interruption checks. Manual Sync still uses real Django.':'Automatic startup/resume/reconnect sync restored.';
  }
  async captureThree() {
    const batch=await this.guard();await this.offline();
    const checkpoint=await this.read();
    if(checkpoint.drafts.length)throw new Error('original_native_drafts_already_prepared');
    for(let i=0;i<3;i++) {
      const command=this.command(batch);const hash=await this.store.hash(commandHashInput(this.store.repository.identity,command));
      // Checkpoint first: failed save is detectable, never silently replaced.
      checkpoint.drafts.push({command,hash});await this.write(checkpoint);
      await this.store.repository.saveDraftAndEnqueue(command,this.store.hash);
    }
    return this.verifyDrafts();
  }
  async verifyDrafts() {
    await this.guard();const checkpoint=await this.read();
    if(!checkpoint.drafts.length)throw new Error('no_original_native_checkpoint');
    let confirmed=0,overlays=0;
    for(const expected of checkpoint.drafts) {
      const details=await this.store.operationDetails(expected.command.operation_id);
      const hash=await this.store.hash(commandHashInput(this.store.repository.identity,details.command));
      if(canonical(details.command)!==canonical(expected.command) || details.hash!==expected.hash || hash!==expected.hash)throw new Error('original_operation_changed');
      const overlay=await this.store.repository.db.first<{payload_json:string}>('SELECT payload_json FROM pending_overlays WHERE operation_id=?',[expected.command.operation_id]);
      if(details.receipt&&['accepted','replayed'].includes(details.receipt.outcome)) {
        if(overlay)throw new Error('confirmed_overlay_not_retired');confirmed++;
      }else{
        if(!overlay || overlay.payload_json!==canonical(expected.command.payload))throw new Error('original_overlay_missing');overlays++;
      }
    }
    return `PASS: ${checkpoint.drafts.length} exact original operation IDs, payloads and recomputed identity-bound hashes; ${confirmed} confirmed receipts, ${overlays} original pending overlays. No replacement IDs.`;
  }
  // Real keyed native transactions. Hold AFTER a write but BEFORE COMMIT;
  // external Android force-stop exercises SQLCipher/WAL rollback, not JS throws.
  private pausedDatabase(match:(sql:string,values:SqlValue[])=>boolean,reached:()=>Promise<void>):Database {
    const db=this.store.repository.db;let held=false;
    return {...db,transaction:<T>(work:(tx:SqlConnection)=>Promise<T>)=>db.transaction(tx=>work({...tx,run:async(sql,values=[])=>{
      const output=await tx.run(sql,values);
      if(!held&&match(sql,values)){held=true;await reached();await new Promise<never>(()=>{});}
      return output;
    }}))};
  }
  async pauseSave(report:Report) {
    const batch=await this.guard();await this.offline();
    const checkpoint=await this.read();const command=this.command(batch);
    checkpoint.interruption={kind:'save',command,reached:false};await this.write(checkpoint);
    const db=this.pausedDatabase((sql,values)=>sql.includes('INSERT INTO pending_overlays')&&values[0]===command.operation_id,async()=>{
      checkpoint.interruption!.reached=true;await this.write(checkpoint);report('PAUSED: real outbox and overlay writes are uncommitted. Force-stop this Phase4 app now.');
    });
    const repository=new Repository(db,this.store.repository.identity);await repository.bindIdentity();
    await repository.saveDraftAndEnqueue(command,this.store.hash);
    throw new Error('save_interruption_not_reached');
  }
  private async replicaHash() {
    const rows=await this.store.repository.db.all('SELECT * FROM confirmed_entities ORDER BY entity_type,entity_uuid LIMIT 101');
    if(rows.length>100)throw new Error('native_probe_row_bound');return this.store.hash(canonical(rows));
  }
  async pausePull(report:Report) {
    await this.guard();const checkpoint=await this.read();
    checkpoint.interruption={kind:'pull',cursor:await this.store.cursor(),replicaHash:await this.replicaHash(),reached:false};await this.write(checkpoint);
    const db=this.pausedDatabase((_sql,values)=>values[0]==='phase4:download_cursor',async()=>{
      checkpoint.interruption!.reached=true;await this.write(checkpoint);report('PAUSED: real pull-page writes and cursor are uncommitted. Force-stop this Phase4 app now.');
    });
    const repository=new Repository(db,this.store.repository.identity);await repository.bindIdentity();
    await this.engine(new SyncStore(repository,this.store.hash),this.api).run();
    throw new Error('pull_interruption_not_reached');
  }
  async pausePush(afterResponse:boolean,report:Report) {
    await this.guard();const checkpoint=await this.read();
    checkpoint.interruption={kind:afterResponse?'committed_push':'sending',reached:false};await this.write(checkpoint);
    const api:SyncApi={request:async(path,body)=>{
      if(path!=='/mobile-sync/push')return this.api.request(path,body);
      checkpoint.interruption!.operationIds=(body as {operations:MortalityCommand[]}).operations.map(op=>mortalityCommand.parse(op).operation_id);
      const hold=async()=>{checkpoint.interruption!.reached=true;await this.write(checkpoint);report(afterResponse?
        'PAUSED: Django returned its committed receipt; local sending intent is still unreconciled. Force-stop this Phase4 app now.':
        'PAUSED: native sending intent is durable; no push HTTP request has been sent. Force-stop this Phase4 app now.');await new Promise<never>(()=>{});};
      if(!afterResponse)await hold();
      const value=await this.api.request(path,body);if(afterResponse)await hold();return value;
    }};
    await this.engine(this.store,api).run();throw new Error('push_interruption_not_reached');
  }
  private engine(store:SyncStore,api:SyncApi) {return new SyncEngine({store,api,authorize:this.authorize,owner:Crypto.randomUUID(),uploadsEnabled:true});}
  async verifyInterruption() {
    await this.guard();const checkpoint=await this.read();const point=checkpoint.interruption;
    if(!point?.reached)throw new Error('native_interruption_not_reached');
    if(point.kind==='save') {
      const id=point.command!.operation_id;
      for(const table of ['outbox','pending_overlays','deliveries'])if(await this.store.repository.db.first(`SELECT operation_id FROM ${table} WHERE operation_id=?`,[id]))throw new Error('partial_local_save');
    }else if(point.kind==='pull') {
      if(await this.store.cursor()!==point.cursor || await this.replicaHash()!==point.replicaHash)throw new Error('partial_pull_commit');
    }else {
      if(!point.operationIds?.length)throw new Error('no_durable_sending_ids');
      for(const id of point.operationIds) {
        const row=await this.store.repository.db.first<{status:string;state:string;ever_sent:number;attempts:number}>(
          'SELECT d.status,d.ever_sent,o.state,o.attempts FROM deliveries d JOIN outbox o USING(operation_id) WHERE operation_id=?',[id]);
        if(!row || row.status!=='sending' || row.state!=='unknown' || row.ever_sent!==1 || row.attempts<1)throw new Error('durable_unknown_intent_missing');
      }
    }
    const drafts=await this.verifyDrafts();
    return `PASS: ${point.kind} interruption recovered. ${drafts}`;
  }
  async addOne(quantity=1) {
    const batch=await this.guard();await this.offline();const checkpoint=await this.read();
    if(!checkpoint.drafts.length)throw new Error('original_three_required');
    const command=this.command(batch,quantity);const hash=await this.store.hash(commandHashInput(this.store.repository.identity,command));
    checkpoint.drafts.push({command,hash});await this.write(checkpoint);
    await this.store.repository.saveDraftAndEnqueue(command,this.store.hash);return this.verifyDrafts();
  }
  async summary() {
    const batch=await this.guard();const db=this.store.repository.db;
    const states=await db.all('SELECT d.status,COUNT(*) n FROM deliveries d GROUP BY d.status ORDER BY d.status');
    const version=await db.first<{user_version:number}>('PRAGMA user_version');
    const fragments=await db.first<{n:number}>('SELECT COUNT(*) n FROM delta_fragments');
    const flock=await this.store.batch(batch);
    return `Native SQLCipher schema ${version?.user_version}. Confirmed flock ${flock?.payload.remaining_birds}; provisional pending ${flock?.pendingMortality}. Fragments ${fragments?.n}. Deliveries ${canonical(states)}.`;
  }
}
