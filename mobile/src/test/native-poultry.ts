import * as Crypto from 'expo-crypto';
import * as Network from 'expo-network';
import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';
import { phase5Pilot } from '../build-mode.native';
import { canonical,commandHashInput } from '../db/repository';
import { openEncrypted,sha256,storePartition } from '../db/native';
import type { AppSettings } from '../config';
import type { AccountProbeSession } from './native-account';
import type { StoreIdentity,MortalityCommand } from '../protocol';
import { poultryCommand,type PoultryCommand } from '../poultry/commands';
import type { SyncStore } from '../sync/store';

const deployment='0db9df4d-9387-49a2-a630-8d9ea934af32';
const nativeBatch='c895573b-f2f2-4c94-88c6-8b8ae48d133f';
const base='http://10.0.2.2:7074/api/v1';
interface Expected {command:PoultryCommand;hash:string}
interface Checkpoint {version:1;identity:string;operations:Expected[]}
function ensure(value:unknown,message:string):asserts value{if(!value)throw new Error(message);}
const secureOptions={keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY};

// Adopts existing UI-captured work only. Never generates a shift, sends a request,
// changes a role, modifies a command, or accesses another account/deployment.
export class NativePoultryProbe {
  constructor(private settings:AppSettings,private session:AccountProbeSession,private store:SyncStore){}
  private async guard(){
    const {pointer,user,repository,capabilities}=this.session;
    ensure(phase5Pilot&&this.settings.environment==='development'&&this.settings.apiBaseUrl===base&&pointer.base===base,
      'exact_phase5_test_build_required');
    ensure(['mobile-test-worker','mobile-test-supervisor','mobile-test-native-supervisor','mobile-test-viewer'].includes(user.username)&&
      pointer.identity.deploymentId===deployment&&user.id===pointer.identity.actorId&&
      capabilities.deployment_id===deployment&&capabilities.device_id===pointer.identity.deviceId&&
      canonical(repository.identity)===canonical(pointer.identity)&&this.store.repository===repository,
      'original_synthetic_identity_required');
    ensure(pointer.partition===await storePartition(base,pointer.identity)&&
      canonical(await repository.metadata('identity'))===canonical(pointer.identity),'original_partition_required');
    const batch=await this.store.batch(nativeBatch);
    ensure(batch?.payload?.batch_id==='SYNTHETIC-PHASE5','owned_original_download_required');
  }
  private identity(){return canonical(this.session.pointer.identity);}
  private key(){return `phase5-native-${deployment}-${this.session.user.id}`;}
  private async read():Promise<Checkpoint>{
    const raw=await SecureStore.getItemAsync(this.key(),secureOptions);
    if(!raw)return {version:1,identity:this.identity(),operations:[]};
    const checkpoint=JSON.parse(raw) as Checkpoint;
    ensure(checkpoint.version===1&&checkpoint.identity===this.identity()&&Array.isArray(checkpoint.operations)&&
      checkpoint.operations.length<=100,'original_checkpoint_required');
    checkpoint.operations.forEach(item=>{poultryCommand.parse(item.command);ensure(/^[0-9a-f]{64}$/.test(item.hash),'original_hash_required');});
    return checkpoint;
  }
  async manual(held:boolean){
    await this.guard();const owner=Crypto.randomUUID();
    ensure(await this.store.repository.acquireLease(owner,Date.now(),60000),'wait_for_active_worker');
    try{await this.store.repository.setMetadata('native-phase5-manual',held);}
    finally{await this.store.repository.releaseLease(owner);}
    return held?'Automatic Phase5 sync held for owned native recovery checks. Explicit Sync still uses real Django.':
      'Automatic Phase5 startup/resume/reconnect sync restored.';
  }
  async checkpoint(){
    await this.guard();ensure(await this.store.repository.metadata('native-phase5-manual')===true,'hold_automatic_sync_first');
    ensure((await Network.getNetworkStateAsync()).isConnected===false,'capture_checkpoint_offline');
    const checkpoint=await this.read();
    const rows=await this.store.repository.db.all<{command_json:string;command_hash:string;actor_id:string;device_id:string;deployment_id:string}>(
      'SELECT command_json,command_hash,actor_id,device_id,deployment_id FROM outbox ORDER BY operation_id LIMIT 101');
    ensure(rows.length>0&&rows.length<=100,'existing_bounded_native_work_required');
    for(const row of rows){
      const command=poultryCommand.parse(JSON.parse(row.command_json));
      ensure(row.actor_id===this.session.user.id&&row.device_id===this.session.pointer.identity.deviceId&&row.deployment_id===deployment&&
        row.command_hash===await this.store.hash(commandHashInput(this.store.repository.identity,command)),'original_command_hash_mismatch');
      const prior=checkpoint.operations.find(item=>item.command.operation_id===command.operation_id);
      if(prior)ensure(prior.hash===row.command_hash&&canonical(prior.command)===canonical(command),'original_command_changed');
      else checkpoint.operations.push({command,hash:row.command_hash});
    }
    const serialized=canonical(checkpoint);ensure(serialized.length<=100000,'checkpoint_size_bound');
    await SecureStore.setItemAsync(this.key(),serialized,secureOptions);
    return this.verify();
  }
  async verify(){
    await this.guard();const checkpoint=await this.read();ensure(checkpoint.operations.length>0,'checkpoint_existing_work_first');
    let confirmed=0,pending=0,discarded=0;
    for(const expected of checkpoint.operations){
      const details=await this.store.operationDetails(expected.command.operation_id);
      ensure(details.hash===expected.hash&&canonical(details.command)===canonical(expected.command)&&
        expected.hash===await this.store.hash(commandHashInput(this.store.repository.identity,details.command)),'original_command_changed');
      const dependencies=await this.store.repository.db.all<{depends_on:string}>(
        'SELECT depends_on FROM operation_dependencies WHERE operation_id=? ORDER BY depends_on',[expected.command.operation_id]);
      ensure(canonical(dependencies.map(row=>row.depends_on))===canonical([...expected.command.depends_on].sort()),'original_dependencies_changed');
      const overlay=await this.store.repository.db.first<{payload_json:string}>(
        'SELECT payload_json FROM pending_overlays WHERE operation_id=?',[expected.command.operation_id]);
      const delivery=await this.store.repository.db.first<{status:string;ever_sent:number}>(
        'SELECT status,ever_sent FROM deliveries WHERE operation_id=?',[expected.command.operation_id]);
      ensure(delivery,'original_delivery_missing');
      if(details.receipt&&['accepted','replayed'].includes(details.receipt.outcome)){
        ensure(!overlay&&delivery.status==='confirmed','accepted_overlay_not_retired');confirmed++;
      }else if(delivery.status==='discarded'){
        ensure(!overlay&&!details.receipt&&!delivery.ever_sent,'discarded_evidence_changed');discarded++;
      }else{ensure(overlay?.payload_json===canonical(expected.command.payload),'original_overlay_missing');pending++;}
    }
    return `PASS: ${checkpoint.operations.length} original typed Phase5 operation IDs, canonical payloads, recomputed identity-bound hashes and dependency links. ${confirmed} confirmed, ${pending} retained overlays, ${discarded} explicit unsent discards. No operation or upload created by this check.`;
  }
}

export async function runNativePoultryUpgradeProbe(){
  ensure(phase5Pilot,'exact_phase5_test_build_required');
  const identity:StoreIdentity={actorId:Crypto.randomUUID(),deviceId:Crypto.randomUUID(),deploymentId:Crypto.randomUUID()};
  const partition=await sha256(`synthetic-phase5-schema2-upgrade\n${Crypto.randomUUID()}`);
  let repository=await openEncrypted(partition,identity);
  try{
    await repository.setMetadata('owned-phase5-upgrade-probe',true);
    ensure((await repository.db.first<{n:number}>('SELECT COUNT(*) n FROM outbox'))?.n===0,'fresh_scratch_required');
    // Create a legacy-v2 fixture only in this freshly owned, empty scratch DB.
    // No retained user tables/keys or real Phase4 package are touched.
    await repository.db.transaction(async tx=>{
      await tx.exec('DROP INDEX batch_history; DROP TABLE form_drafts; DROP TABLE online_intents; DROP TABLE offline_batch_exclusions; PRAGMA user_version=2;');
    });
    const batch=Crypto.randomUUID(),at=new Date().toISOString();
    await repository.db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)',
      ['poultry.batch',batch,'1','{"batch_id":"SYNTHETIC-PHASE5-UPGRADE"}']);
    const command:MortalityCommand={operation_id:Crypto.randomUUID(),entity_uuid:Crypto.randomUUID(),entity_type:'poultry.mortality',action:'record',
      payload_version:1,base_version:null,captured_at:at,depends_on:[],payload:{batch_uuid:batch,mortality_date:at,quantity_dead:1,
        suspected_cause:'Synthetic',description:'Native schema2 upgrade evidence',action_taken:'Never upload',reported_by_name:'Synthetic'}};
    await repository.saveDraftAndEnqueue(command,sha256);await repository.invalidateScope();
    const before=canonical({outbox:await repository.db.all('SELECT * FROM outbox'),overlays:await repository.db.all('SELECT * FROM pending_overlays'),
      deliveries:await repository.db.all('SELECT * FROM deliveries')});
    await repository.db.close();repository=await openEncrypted(partition,identity);
    ensure(await repository.metadata('owned-phase5-upgrade-probe')===true,'owned_scratch_required');
    ensure((await repository.db.first<{user_version:number}>('PRAGMA user_version'))?.user_version===3,'native_upgrade_not_applied');
    ensure(before===canonical({outbox:await repository.db.all('SELECT * FROM outbox'),overlays:await repository.db.all('SELECT * FROM pending_overlays'),
      deliveries:await repository.db.all('SELECT * FROM deliveries')}),'legacy_evidence_changed');
    const row=await repository.db.first<{command_json:string;command_hash:string}>('SELECT command_json,command_hash FROM outbox');
    ensure(row?.command_json===canonical(command)&&row.command_hash===await sha256(commandHashInput(identity,command)),'legacy_hash_changed');
    await repository.saveForm('synthetic-upgrade-form',{quantity_given:'1500',unit_of_measurement:'g'});
    ensure(canonical(await repository.form('synthetic-upgrade-form'))===canonical({quantity_given:'1500',unit_of_measurement:'g'}),'new_form_unavailable');
    await repository.db.close();
    await SQLite.deleteDatabaseAsync(`farm-${partition}.db`);
    await SecureStore.deleteItemAsync(`db-key-${partition}`);await SecureStore.deleteItemAsync(`db-key-policy-${partition}`);
    return 'PASS: owned SQLCipher schema2→3 upgrade retained the exact original synthetic UUID/payload/recomputed hash/quarantined delivery/overlay and enabled durable forms. Only its scratch database/key removed. Existing-package upgrade and physical-phone checks are separate.';
  }catch(error){try{await repository.db.close();}catch{/* Preserve failed owned scratch evidence. */}throw error;}
}
