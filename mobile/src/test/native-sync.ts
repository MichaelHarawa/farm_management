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
import { ApiError } from '../auth/client';
import { changesPage,bootstrap } from '../sync/protocol';
import { checkSyncCoordination } from './sync-coordination';

interface Expected { command:MortalityCommand; hash:string }
interface Checkpoint { identity:string; drafts:Expected[]; dependencyPair?:{parent:string;child:string}; recovery?:{snapshotId:string;replicaHash:string;cursor:string|null}; interruption?:{
  kind:string; command?:MortalityCommand; cursor?:string|null; appliedCursor?:string|null; replicaHash?:string;
  fragmentHash?:string; operationIds?:string[]; reached?:boolean } }
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
    let confirmed=0,overlays=0,discarded=0;
    for(const expected of checkpoint.drafts) {
      const details=await this.store.operationDetails(expected.command.operation_id);
      const hash=await this.store.hash(commandHashInput(this.store.repository.identity,details.command));
      if(canonical(details.command)!==canonical(expected.command) || details.hash!==expected.hash || hash!==expected.hash)throw new Error('original_operation_changed');
      const overlay=await this.store.repository.db.first<{payload_json:string}>('SELECT payload_json FROM pending_overlays WHERE operation_id=?',[expected.command.operation_id]);
      const delivery=await this.store.repository.db.first<{status:string}>('SELECT status FROM deliveries WHERE operation_id=?',[expected.command.operation_id]);
      if(details.receipt&&['accepted','replayed'].includes(details.receipt.outcome)) {
        if(overlay)throw new Error('confirmed_overlay_not_retired');confirmed++;
      }else if(delivery?.status==='discarded'){
        if(overlay||details.receipt)throw new Error('discarded_unsent_evidence_changed');discarded++;
      }else{
        if(!overlay || overlay.payload_json!==canonical(expected.command.payload))throw new Error('original_overlay_missing');overlays++;
      }
    }
    return `PASS: ${checkpoint.drafts.length} exact original operation IDs, payloads and recomputed identity-bound hashes; ${confirmed} confirmed receipts, ${overlays} original pending overlays, ${discarded} explicitly discarded unsent records. No replacement IDs.`;
  }
  async checkpointCurrentCommands() {
    await this.guard();const checkpoint=await this.read();
    const rows=await this.store.repository.db.all<{command_json:string;command_hash:string}>('SELECT command_json,command_hash FROM outbox ORDER BY operation_id LIMIT 101');
    if(rows.length>100)throw new Error('native_probe_row_bound');
    for(const row of rows){
      const command=mortalityCommand.parse(JSON.parse(row.command_json));
      if(await this.store.hash(commandHashInput(this.store.repository.identity,command))!==row.command_hash)throw new Error('original_operation_changed');
      const old=checkpoint.drafts.find(d=>d.command.operation_id===command.operation_id);
      if(old&&(canonical(old.command)!==canonical(command)||old.hash!==row.command_hash))throw new Error('original_operation_changed');
      if(!old)checkpoint.drafts.push({command,hash:row.command_hash});
    }
    await this.write(checkpoint);return this.verifyDrafts(); // Adopt existing immutable evidence, never recreate it.
  }
  async captureDependencyPair() {
    const batch=await this.guard();await this.offline();const checkpoint=await this.read();
    if(checkpoint.dependencyPair)throw new Error('original_dependency_pair_already_prepared');
    const parent=this.command(batch),child=mortalityCommand.parse({...this.command(batch),depends_on:[parent.operation_id]});
    checkpoint.dependencyPair={parent:parent.operation_id,child:child.operation_id};
    for(const command of [parent,child]){
      checkpoint.drafts.push({command,hash:await this.store.hash(commandHashInput(this.store.repository.identity,command))});
      await this.write(checkpoint);await this.store.repository.saveDraftAndEnqueue(command,this.store.hash);
    }
    return `Prepared original parent ${parent.operation_id} and dependent ${child.operation_id}. Discard only through the normal Sync confirmation. ${await this.verifyDrafts()}`;
  }
  async verifyDiscardedDependency() {
    await this.guard();const pair=(await this.read()).dependencyPair;
    if(!pair)throw new Error('original_dependency_pair_required');
    const parent=await this.store.repository.db.first<{status:string;ever_sent:number}>('SELECT status,ever_sent FROM deliveries WHERE operation_id=?',[pair.parent]);
    const child=await this.store.repository.db.first<{status:string;reason:string;ever_sent:number}>('SELECT status,reason,ever_sent FROM deliveries WHERE operation_id=?',[pair.child]);
    const link=await this.store.repository.db.first('SELECT operation_id FROM operation_dependencies WHERE operation_id=? AND depends_on=?',[pair.child,pair.parent]);
    if(parent?.status!=='discarded'||parent.ever_sent||child?.status!=='dependency_blocked'||child.reason!=='parent_discarded'||child.ever_sent||!link)throw new Error('explicit_discard_dependency_not_retained');
    return `PASS: explicit unsent parent discard; original child remains blocked and linked, neither submitted or reparented. ${await this.verifyDrafts()}`;
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
  private async appliedCursor() {
    const row=await this.store.repository.db.first<{value:string}>('SELECT value FROM sync_state WHERE key=?',['phase4:applied_cursor']);
    return row?JSON.parse(row.value) as string:null;
  }
  private async fragmentState() {
    const rows=await this.store.repository.db.all('SELECT * FROM delta_fragments ORDER BY transaction_id,fragment_index LIMIT 101');
    if(rows.length>100)throw new Error('native_probe_row_bound');
    return {count:rows.length,hash:await this.store.hash(canonical(rows))};
  }
  async pauseCommittedFragment(report:Report) {
    await this.guard();const checkpoint=await this.read();
    if((await this.fragmentState()).count)throw new Error('complete_existing_fragments_first');
    checkpoint.interruption={kind:'committed_fragment',cursor:await this.store.cursor(),appliedCursor:await this.appliedCursor(),replicaHash:await this.replicaHash(),reached:false};
    await this.write(checkpoint);const original=this.store.repository.db;let held=false;
    const db:Database={...original,transaction:async<T>(work:(tx:SqlConnection)=>Promise<T>):Promise<T>=>{
      const value=await original.transaction(work); // COMMIT has completed, unlike pausePull.
      const fragments=await this.fragmentState();
      if(!held&&fragments.count){
        held=true;const cursor=await this.store.cursor();
        if(cursor===checkpoint.interruption!.cursor||await this.appliedCursor()!==checkpoint.interruption!.appliedCursor||await this.replicaHash()!==checkpoint.interruption!.replicaHash)throw new Error('partial_fragment_became_visible');
        checkpoint.interruption!.cursor=cursor;checkpoint.interruption!.fragmentHash=fragments.hash;
        checkpoint.interruption!.reached=true;await this.write(checkpoint);
        report('PAUSED: incomplete fragment and download cursor are committed; applied cursor and visible replica are unchanged. Force-stop this Phase4 app now.');
        await new Promise<never>(()=>{});
      }
      return value;
    }};
    const repository=new Repository(db,this.store.repository.identity);await repository.bindIdentity();
    await this.engine(new SyncStore(repository,this.store.hash),this.api,false).run();
    throw new Error('committed_fragment_interruption_not_reached');
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
  private engine(store:SyncStore,api:SyncApi,uploadsEnabled=true) {return new SyncEngine({store,api,authorize:this.authorize,owner:Crypto.randomUUID(),uploadsEnabled});}
  async downloadOnly(archive=false) {
    const batch=await this.guard();const packs=archive?['operational-current-v1',`batch:${batch}`]:['operational-current-v1'];
    const outcome=await this.engine(this.store,this.api,false).run(packs);
    const membership=await this.store.repository.db.all<{pack_id:string}>('SELECT pack_id FROM pack_membership WHERE entity_type=? AND entity_uuid=? ORDER BY pack_id',['poultry.batch',batch]);
    return `Read-only real download ${canonical(outcome)}. Batch memberships ${canonical(membership)}. ${await this.summary()}`;
  }
  async coordinatorOverlap() {
    await this.guard();
    if (!await this.store.repository.metadata('native-phase4-manual')) throw new Error('hold_automatic_sync_before_overlap_probe');
    const evidence = async () => {
      const rows:Record<string,unknown[]> = {};
      for (const table of ['outbox','pending_overlays','deliveries','receipts','operation_dependencies']) {
        rows[table] = await this.store.repository.db.all(`SELECT * FROM ${table} ORDER BY operation_id LIMIT 101`);
        if (rows[table]!.length > 100) throw new Error('native_probe_row_bound');
      }
      return this.store.hash(canonical(rows));
    };
    const before = await evidence();
    const outcome = await checkSyncCoordination({ store:this.store,api:this.api,authorize:this.authorize },
      [Crypto.randomUUID(),Crypto.randomUUID()]);
    if (await evidence() !== before) throw new Error('coordination_original_evidence_changed');
    const checkpoint = await this.read();
    const retained = checkpoint.drafts.length ? await this.verifyDrafts() : 'No original draft checkpoint exists in this separate device partition.';
    return `PASS: native persisted lease excludes the independent worker before auth/HTTP; simultaneous same-engine trigger shares one flight. Real Django read-only run ${canonical(outcome)}. Original command/dependency/receipt/delivery bytes unchanged. ${retained}`;
  }
  async startCursorRecovery() {
    await this.guard();const checkpoint=await this.read();
    if(await this.store.snapshot())throw new Error('complete_existing_snapshot_first');
    const replicaHash=await this.replicaHash(),cursor=await this.store.cursor();let expired=false;
    const api:SyncApi={request:async(path,body)=>{try{return await this.api.request(path,body);}catch(e){
      if(path.startsWith('/mobile-sync/changes?')&&e instanceof ApiError&&e.status===410&&e.code==='resync_required')expired=true;
      throw e;
    }}};
    const outcome=await new SyncEngine({store:this.store,api,authorize:this.authorize,owner:Crypto.randomUUID(),uploadsEnabled:false,maxPages:1}).run();
    const staged=await this.store.snapshot();
    if(!expired||outcome.status!=='paused'||!staged||staged.nextPage!==1||await this.replicaHash()!==replicaHash||await this.store.cursor()!==cursor)throw new Error('real_cursor_recovery_not_retained');
    checkpoint.recovery={snapshotId:staged.manifest.snapshot_id,replicaHash,cursor};await this.write(checkpoint);
    return `PASS: real cursor 410 stages one verified page without replacing the last good replica/cursor. Snapshot ${staged.manifest.snapshot_id}. ${await this.verifyDrafts()}`;
  }
  async completeExpiredSnapshot() {
    await this.guard();const checkpoint=await this.read(),point=checkpoint.recovery;
    if(!point||(await this.store.snapshot())?.manifest.snapshot_id!==point.snapshotId||await this.replicaHash()!==point.replicaHash||await this.store.cursor()!==point.cursor)throw new Error('original_staging_checkpoint_changed');
    let expired=false,replacement=false;
    const api:SyncApi={request:async(path,body)=>{try{
      const value=await this.api.request(path,body);
      if(path==='/mobile-sync/bootstrap'&&bootstrap.parse(value).snapshot_id!==point.snapshotId)replacement=true;
      return value;
    }catch(e){if(path==='/mobile-sync/bootstrap'&&e instanceof ApiError&&e.status===410&&e.code==='resync_required')expired=true;throw e;}}};
    const outcome=await this.engine(this.store,api,false).run();
    if(!expired||!replacement||outcome.status!=='complete'||await this.store.snapshot())throw new Error('real_snapshot_expiry_recovery_not_complete');
    return `PASS: real server snapshot expiry replaced staging only and completed verified download. ${canonical(outcome)}. ${await this.verifyDrafts()} ${await this.summary()}`;
  }
  async hiddenContinuation() {
    const batch=await this.guard();let empty=0,visibleAfterEmpty=false;
    const api:SyncApi={request:async(path,body)=>{
      const value=await this.api.request(path,body);
      if(path.startsWith('/mobile-sync/changes?')){
        const page=changesPage.parse(value);
        if(!page.changes.length&&!page.run_complete)empty++;
        for(const change of page.changes){
          if(change.kind==='upsert'){
            const payload=change.payload as Record<string,unknown>;
            if(change.entity_type==='poultry.batch'?change.entity_uuid!==batch:payload.batch_uuid!==batch)throw new Error('hidden_entity_leaked');
            if(empty&&change.entity_type==='poultry.feed_usage'&&payload.notes==='Synthetic visible update after hidden-only history')visibleAfterEmpty=true;
          }
        }
      }
      return value;
    }};
    const outcome=await this.engine(this.store,api,false).run();
    const foreign=await this.store.repository.db.first("SELECT entity_uuid FROM confirmed_entities WHERE entity_type='poultry.batch' AND entity_uuid<>?",[batch]);
    if(!empty||!visibleAfterEmpty||foreign||outcome.status!=='complete')throw new Error('hidden_continuation_not_proven');
    return `PASS: ${empty} real empty/nonfinal pages continued to the later visible feed change; no hidden batch replica or payload. ${canonical(outcome)}. ${await this.verifyDrafts()}`;
  }
  async replayOldReceipt() {
    await this.guard();const checkpoint=await this.read();
    const first=checkpoint.drafts.find(d=>d.command.operation_id==='5929a03c-d9a3-4370-9807-55222ad72950');
    if(!first)throw new Error('original_first_operation_required');
    await this.authorize();const replica=await this.replicaHash();
    const overlays=()=>this.store.repository.db.all('SELECT * FROM pending_overlays ORDER BY operation_id');
    const before=await this.store.hash(canonical(await overlays()));
    const receipt=await this.api.request(`/mobile-sync/operations/${first.command.operation_id}`);
    await this.store.reconcile(receipt,new Date().toISOString());
    if(await this.replicaHash()!==replica||await this.store.hash(canonical(await overlays()))!==before)throw new Error('old_receipt_changed_newer_state');
    const target=await this.store.repository.db.first<{revision:string;tombstone:number}>('SELECT revision,tombstone FROM confirmed_entities WHERE entity_type=? AND entity_uuid=?',[first.command.entity_type,first.command.entity_uuid]);
    return `PASS: actual original server receipt cannot overwrite the newer replica or other overlays. Target ${canonical(target)}. ${await this.verifyDrafts()}`;
  }
  async verifyInterruption() {
    await this.guard();const checkpoint=await this.read();const point=checkpoint.interruption;
    if(!point?.reached)throw new Error('native_interruption_not_reached');
    if(point.kind==='save') {
      const id=point.command!.operation_id;
      for(const table of ['outbox','pending_overlays','deliveries'])if(await this.store.repository.db.first(`SELECT operation_id FROM ${table} WHERE operation_id=?`,[id]))throw new Error('partial_local_save');
    }else if(point.kind==='pull') {
      if(await this.store.cursor()!==point.cursor || await this.replicaHash()!==point.replicaHash)throw new Error('partial_pull_commit');
    }else if(point.kind==='committed_fragment') {
      const fragments=await this.fragmentState();
      if(!fragments.count||fragments.hash!==point.fragmentHash||await this.store.cursor()!==point.cursor||await this.appliedCursor()!==point.appliedCursor||await this.replicaHash()!==point.replicaHash)throw new Error('committed_fragment_recovery_changed');
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
