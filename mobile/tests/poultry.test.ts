import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash,randomUUID } from 'node:crypto';
import { canonical,commandHashInput,migrate,Repository } from '../src/db/repository';
import { migrations } from '../src/db/schema';
import { SyncStore } from '../src/sync/store';
import { entity,type Entity } from '../src/sync/protocol';
import { capabilitiesSchema,type Capabilities } from '../src/protocol';
import { poultryCommand,normalizedPayload,type PoultryCommand } from '../src/poultry/commands';
import { buildFormCommand,formDefaults,formFromCommand } from '../src/poultry/forms';
import { submitOnlinePoultry } from '../src/poultry/online';
import { phase5PilotEnabled } from '../src/build-mode-policy';
import { ApiError } from '../src/auth/client';
import { hostDatabase,identity,command } from './helpers';
const at='2026-10-04T10:00:00Z',now=Date.parse(at),epoch=randomUUID(),scope='synthetic-poultry-v2';
const pack='operational-current-v2',batchUuid=command.payload.batch_uuid;
const hash=async(s:string)=>createHash('sha256').update(s).digest('hex');
const caps:Capabilities=capabilitiesSchema.parse({protocol_version:1,schema_version:2,policy_version:1,projection_version:2,
  deployment_id:identity.deploymentId,device_id:identity.deviceId,stream_epoch:epoch,scope_revision:scope,server_time:at,
  entities:['poultry.batch','poultry.mortality','poultry.feed_usage','poultry.treatment','poultry.weight_sample','poultry.flock_adjustment','poultry.adjustment_proposal'],
  commands:{'poultry.feed_usage.record':{available:true,mode:'queued'},'poultry.adjustment_proposal.approve':{available:true,mode:'online'}},
  lookups:{version:1,choices:{feed_type:[{value:'starter',label:'Starter'}],feed_source:[{value:'cp_feed',label:'CP'}],unit_of_measurement:[{value:'g',label:'Grams'},{value:'kg',label:'Kilograms'}]},
    treatment_quantity_unit:'recorded unit',stock_linked_capture:false,mortality_threshold_percent:'8'},offline:{operational_days:7,sensitive_hours:24}});
const batch=entity.parse({entity_type:'poultry.batch',entity_uuid:batchUuid,revision:'1',payload:{server_id:'1',created_at:at,updated_at:at,
  batch_id:'Synthetic-poultry',bird_type:'broilers',broiler_strain:'ross308',source:'central_poultry',source_other:'',booking_date:null,
  estimated_chick_arrival_date:null,expected_quantity:120,actual_quantity_received:100,entry_date:'2026-10-01T00:00:00Z',expected_maturity_date:'2026-11-16T00:00:00Z',
  delivery_confirmed_at:at,quantity:100,closed_at:null,status:'active',initial_birds:100,sold_bird_count:0,total_mortality:0,remaining_birds:100,approved_adjustment_count:0}});
function operation(kind:string,action:string,payload:object,extra:object={}):PoultryCommand {
  return poultryCommand.parse({operation_id:randomUUID(),entity_uuid:randomUUID(),entity_type:kind,action,payload_version:1,base_version:null,captured_at:at,depends_on:[],payload,...extra});
}
const feed=()=>operation('poultry.feed_usage','record',{batch_uuid:batchUuid,feeding_start_date:at,feeding_end_date:at,feed_type:'starter',feed_source:'cp_feed',
  quantity_given:1500,unit_of_measurement:'g',notes:'Weighed feed',reported_by_name:'Observed worker'});
const approval=()=>operation('poultry.adjustment_proposal','approve',{reason:'Verified count'},{base_version:'1'});
async function setup(){const db=hostDatabase();await migrate(db);const repo=new Repository(db,identity);await repo.bindIdentity();return{repo,store:new SyncStore(repo,hash)};}
async function activate(store:SyncStore,rows:Entity[]=[batch],packs=[pack]) {
  const id=randomUUID(),digest=await hash(canonical(rows));
  await store.beginSnapshot({snapshot_id:id,deployment_id:identity.deploymentId,stream_epoch:epoch,scope_revision:scope,watermark:'1',expires_at:'2026-10-05T10:00:00Z',
    packs: [...packs].sort(),row_count:rows.length,manifest:[{page:0,row_count:rows.length,sha256:digest}],next_page_cursor:'page'},epoch,scope);
  await store.stageSnapshotPage({snapshot_id:id,page:0,entities:rows,sha256:digest,page_complete:true,next_page_cursor:null,delta_cursor:'delta'},'page',at);
}
function approved(op:PoultryCommand) {
  const proposed=entity.parse({entity_type:op.entity_type,entity_uuid:op.entity_uuid,revision:'2',payload:{server_id:'2',created_at:at,updated_at:at,
    batch_uuid:batchUuid,effective_at:at,quantity_change:-2,reason:'Original count evidence',status:'approved',review_reason:'Verified count',adjustment_server_id:'3'}});
  return {operation_id:op.operation_id,outcome:'accepted',code:'accepted',message:'Recorded once',field_errors:{},recovery_action:'reconcile_and_pull',
    canonical_entities:[batch,proposed],entity_mappings:[{entity_type:op.entity_type,entity_uuid:op.entity_uuid,server_id:'2',revision:'2'}],transaction_id:randomUUID(),committed_at:at};
}

test('Phase5 gate requires exact native package, local build and separate backend',()=>{
  const native={applicationId:'com.farmmanagement.mobile.dev.acceptance.phase5',buildType:'localAcceptance'};
  assert.equal(phase5PilotEnabled('development','http://10.0.2.2:7074/api/v1',true,native),true);
  for(const url of ['http://10.0.2.2:7070/api/v1','http://10.0.2.2:7073/api/v1','https://farm.invalid/api/v1'])assert.equal(phase5PilotEnabled('development',url,true,native),false);
  assert.equal(phase5PilotEnabled('production','http://10.0.2.2:7074/api/v1',true,native),false);
  assert.equal(phase5PilotEnabled('development','http://10.0.2.2:7074/api/v1',true,{...native,buildType:'release'}),false);
});
test('strict poultry types preserve units and UTC microseconds without rewriting evidence text',()=>{
  const op=feed();assert.equal((op.payload as Record<string,unknown>).unit_of_measurement,'g');
  assert.equal(poultryCommand.safeParse({...op,payload:{...op.payload,quantity_given:'1500'}}).success,false);
  assert.equal(poultryCommand.safeParse({...op,payload:{...op.payload,unit_of_measurement:'tonnes'}}).success,false);
  assert.equal(poultryCommand.safeParse({...op,payload:{...op.payload,stock_issue:{}}}).success,false);
  assert.deepEqual(normalizedPayload({sampled_at:'2026-10-04T10:00:00.123Z',notes:'2026-10-04T10:00:00.123Z'}),
    {sampled_at:'2026-10-04T10:00:00.123000Z',notes:'2026-10-04T10:00:00.123Z'});
  const legacy=JSON.parse(commandHashInput(identity,command));assert.deepEqual(legacy.operation.payload,command.payload);
});
test('native form builder reports field errors, reference coverage and exact kg/g units; correction retains date intent',()=>{
  const values={...formDefaults('feed',at),batch_uuid:batchUuid,feed_type:'starter',feed_source:'cp_feed',quantity_given:'1500',unit_of_measurement:'g',notes:'Weighed',reported_by_name:'Worker'};
  const envelope={operation_id:randomUUID(),entity_uuid:randomUUID(),captured_at:at,base_version:null,depends_on:[]};
  const built=buildFormCommand('feed',values,caps,envelope);assert.ok(built.command);assert.equal((built.command.payload as Record<string,unknown>).quantity_given,1500);
  assert.equal((built.command.payload as Record<string,unknown>).unit_of_measurement,'g');
  assert.ok(buildFormCommand('feed',{...values,quantity_given:'1.5'},caps,envelope).errors.quantity_given);
  assert.ok(buildFormCommand('feed',{...values,unit_of_measurement:'tonnes'},caps,envelope).errors.unit_of_measurement);
  assert.ok(buildFormCommand('feed',values,{...caps,lookups:undefined},envelope).errors.feed_type);
  assert.deepEqual(formFromCommand('feed',built.command),values);
});
test('schema2 to schema3 retains original UUID/payload/hash/quarantine and adds durable per-user forms',async()=>{
  const db=hostDatabase();await migrate(db,migrations.slice(0,2));const repo=new Repository(db,identity);await repo.bindIdentity();
  try{
    await db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)',[batch.entity_type,batchUuid,'1',canonical(batch.payload)]);
    // Old save paths never refer to the new online/form tables for mortality.
    await repo.saveDraftAndEnqueue(command,hash);await repo.invalidateScope();
    const before=await db.first('SELECT * FROM outbox');await migrate(db);
    assert.deepEqual(await db.first('SELECT * FROM outbox'),before);
    assert.equal((await db.first<{status:string}>('SELECT status FROM deliveries'))?.status,'quarantined');
    await repo.saveForm('poultry:feed:new',{batch_uuid:batchUuid,quantity_given:'1500'});
    assert.deepEqual(await repo.form('poultry:feed:new'),{batch_uuid:batchUuid,quantity_given:'1500'});
    const foreign=new Repository(db,{...identity,actorId:randomUUID()});await assert.rejects(foreign.bindIdentity(),/identity_mismatch/);
  }finally{await db.close();}
});
test('offline booking and delivery prerequisites are durable; wrong parent chain cannot enqueue a child',async()=>{
  const {repo,store}=await setup();
  try{
    const book=operation('poultry.batch','book',{bird_type:'broilers',source:'central_poultry',booking_date:'2026-10-04',estimated_chick_arrival_date:'2026-10-04',
      expected_quantity:120,entry_date:at,expected_maturity_date:'2026-11-19T10:00:00Z'});
    await repo.saveDraftAndEnqueue(book,hash);
    const delivered=operation('poultry.batch','mark_delivered',{batch_uuid:book.entity_uuid},{entity_uuid:book.entity_uuid,depends_on:[book.operation_id]});
    await repo.saveDraftAndEnqueue(delivered,hash);
    const arrived=operation('poultry.batch','confirm_delivery',{batch_uuid:book.entity_uuid,entry_date:at,quantity:100},{entity_uuid:book.entity_uuid,depends_on:[delivered.operation_id]});
    await repo.saveDraftAndEnqueue(arrived,hash);
    const child=poultryCommand.parse({...feed(),depends_on:[arrived.operation_id],payload:{...feed().payload,batch_uuid:book.entity_uuid}});
    await repo.saveDraftAndEnqueue(child,hash);
    await assert.rejects(repo.saveDraftAndEnqueue({...child,operation_id:randomUUID(),entity_uuid:randomUUID(),depends_on:[]},hash),/download_parent_first/);
    assert.equal((await repo.poultryBatches())[0]?.local_only,1);
    assert.equal((await repo.batchDependency(book.entity_uuid))?.operation_id,arrived.operation_id);
    await repo.acquireLease('test',now,60000);assert.deepEqual((await store.claim(now,'test')).map(r=>r.operation_id),[book.operation_id]);
    assert.equal((await store.queue()).find(r=>r.operation_id===child.operation_id)?.status,'dependency_blocked');
    assert.equal((await store.operationDetails(child.operation_id)).hash,await hash(commandHashInput(identity,child)));
  }finally{await repo.db.close();}
});
test('online intents are never automatically claimed; a second unresolved review cannot replace its ID',async()=>{
  const {repo,store}=await setup();
  try{
    const op=approval();await repo.saveDraftAndEnqueue(op,hash,'online');await repo.acquireLease('auto',now,60000);
    assert.deepEqual(await store.claim(now,'auto',20,caps),[]);
    assert.equal((await store.queue())[0]?.ever_sent,0);
    await assert.rejects(repo.saveDraftAndEnqueue(poultryCommand.parse({...op,operation_id:randomUUID(),action:'reject'}),hash,'online'),/original_online_intent/);
    assert.equal((await store.originalOnlineIntent(op.entity_uuid))?.command.operation_id,op.operation_id);
    await assert.rejects(repo.saveDraftAndEnqueue({...op,operation_id:randomUUID()},hash),/online_confirmation/);
  }finally{await repo.db.close();}
});
test('lost online approval response recovers the same exact receipt without another POST or replacement',async()=>{
  const {repo,store}=await setup();const op=approval(),receipt=approved(op);let posts=0,lookups=0;
  try{
    await repo.saveDraftAndEnqueue(op,hash,'online');const before=await store.operationDetails(op.operation_id);
    const api={async request(path:string){if(path.endsWith(op.operation_id)){lookups++;if(!posts)throw new ApiError(404,'operation_not_found');return receipt;}
      assert.equal(path,'/mobile-sync/poultry-online');posts++;throw new Error('Lost response after commit');}};
    await assert.rejects(submitOnlinePoultry({store,api,authorize:async()=>caps,owner:'first',operationId:op.operation_id,confirmed:true,now:()=>now}));
    assert.equal((await store.queue())[0]?.status,'retry_wait');assert.deepEqual(await store.operationDetails(op.operation_id),before);
    const recovered=await submitOnlinePoultry({store,api,authorize:async()=>caps,owner:'second',operationId:op.operation_id,confirmed:false,now:()=>now+31000});
    assert.equal(recovered.outcome,'accepted');assert.equal(posts,1);assert.equal(lookups,2);
    assert.equal((await store.operationDetails(op.operation_id)).hash,before.hash);assert.equal(await repo.queueCount(),0);
  }finally{await repo.db.close();}
});
test('missing online receipt requires fresh confirmation and revalidated authority; foreign receipt never confirms',async()=>{
  const {repo,store}=await setup();const op=approval();let posts=0,auths=0;
  try{
    await repo.saveDraftAndEnqueue(op,hash,'online');
    const api={async request(path:string){if(path.endsWith(op.operation_id))throw new ApiError(404,'operation_not_found');posts++;return approved({...op,operation_id:randomUUID()});}};
    await assert.rejects(submitOnlinePoultry({store,api,authorize:async()=>caps,owner:'no',operationId:op.operation_id,confirmed:false,now:()=>now}),/confirmation_required/);
    await assert.rejects(submitOnlinePoultry({store,api,authorize:async()=>{auths++;return auths===1?caps:{...caps,commands:{}};},owner:'denied',operationId:op.operation_id,confirmed:true,now:()=>now}),/authority_changed/);
    assert.equal(posts,0);
    await assert.rejects(submitOnlinePoultry({store,api,authorize:async()=>caps,owner:'foreign',operationId:op.operation_id,confirmed:true,now:()=>now}),/foreign_receipt/);
    assert.equal((await store.operationDetails(op.operation_id)).receipt,null);assert.equal((await store.queue())[0]?.status,'retry_wait');
  }finally{await repo.db.close();}
});
test('removal refuses pending forms/events, prevents automatic resurrection and restores only explicit verified pack',async()=>{
  const {repo,store}=await setup();
  try{
    await activate(store);await repo.saveForm('poultry:feed:new',{batch_uuid:batchUuid});
    await assert.rejects(store.removeBatch(batchUuid,'remove',now),/requires_parent/);await repo.clearForm('poultry:feed:new');
    const op=feed();await repo.saveDraftAndEnqueue(op,hash);const before=await store.operationDetails(op.operation_id);
    await assert.rejects(store.removeBatch(batchUuid,'remove',now),/requires_parent/);await store.discardUnsent(op.operation_id,true);
    await store.removeBatch(batchUuid,'remove',now);assert.equal(await store.batch(batchUuid),null);assert.equal(await store.cursor(),null);
    // More than one page of excluded rows used to leave an unadvanced SQL cursor.
    await activate(store);assert.equal(await store.batch(batchUuid),null);
    await activate(store,[batch],[pack,`batch-v2:${batchUuid}`]);assert.ok(await store.batch(batchUuid));
    assert.deepEqual(await store.excludedBatches(),[]);assert.deepEqual(await store.operationDetails(op.operation_id),before);
  }finally{await repo.db.close();}
});
test('feed accepted receipt requires matching immutable payload and leaves mismatches unresolved',async()=>{
  const {repo,store}=await setup();const op=feed();
  try{
    await activate(store);await repo.saveDraftAndEnqueue(op,hash);
    const f=entity.parse({entity_type:'poultry.feed_usage',entity_uuid:op.entity_uuid,revision:'2',payload:{...op.payload,server_id:'2',created_at:at,updated_at:at,
      initial_age:3,current_number_of_birds:100,population_calculation_version:'v2',population_calculated_at:at,quantity_kg:'1.500'}});
    const receipt={operation_id:op.operation_id,outcome:'accepted',code:'accepted',message:'Recorded',field_errors:{},recovery_action:'reconcile_and_pull',
      canonical_entities:[batch,f],entity_mappings:[{entity_type:op.entity_type,entity_uuid:op.entity_uuid,server_id:'2',revision:'2'}],transaction_id:randomUUID(),committed_at:at};
    await assert.rejects(store.reconcile({...receipt,canonical_entities:[batch,{...f,payload:{...f.payload,quantity_given:15}}]},at),/payload_mismatch/);
    assert.equal((await store.operationDetails(op.operation_id)).receipt,null);
    await store.reconcile(receipt,at);assert.equal(await repo.queueCount(),0);assert.equal((await store.history(batchUuid,'poultry.feed_usage')).length,1);
  }finally{await repo.db.close();}
});

test('pending online proposal review keeps both its downloaded proposal and batch parent',async()=>{
  const {repo,store}=await setup(),op=approval();
  try {
    const proposal=entity.parse({entity_type:'poultry.adjustment_proposal',entity_uuid:op.entity_uuid,revision:'1',payload:{server_id:'2',created_at:at,updated_at:at,
      batch_uuid:batchUuid,effective_at:at,quantity_change:-2,reason:'Evidence',status:'pending',review_reason:'',adjustment_server_id:null}});
    await activate(store,[batch,proposal]);await repo.saveDraftAndEnqueue(op,hash,'online');
    await assert.rejects(store.removeBatch(batchUuid,'remove',now),/requires_parent/);
    assert.ok(await store.batch(batchUuid));assert.equal((await store.history(batchUuid,'poultry.adjustment_proposal')).length,1);
    assert.equal((await store.operationDetails(op.operation_id)).command.operation_id,op.operation_id);
  }finally{await repo.db.close();}
});

test('known terminal online failure creates one linked correction without replacing unknown evidence',async()=>{
  const {repo,store}=await setup(),op=approval();
  try {
    await repo.saveDraftAndEnqueue(op,hash,'online');
    assert.equal(await store.terminalOnlineIntent(op.entity_uuid,'approve'),null);
    const failed={operation_id:op.operation_id,outcome:'conflict',code:'revision_conflict',message:'Review current evidence',field_errors:{},recovery_action:'review'};
    await store.reconcile(failed,at);const original=await store.operationDetails(op.operation_id);
    assert.equal(await store.originalOnlineIntent(op.entity_uuid),null);
    assert.equal((await store.terminalOnlineIntent(op.entity_uuid,'approve'))?.command.operation_id,op.operation_id);
    assert.equal(await store.terminalOnlineIntent(op.entity_uuid,'reject'),null);
    const correction=poultryCommand.parse({...op,operation_id:randomUUID(),base_version:'2',supersedes_operation_id:op.operation_id});
    await repo.saveDraftAndEnqueue(correction,hash,'online');
    assert.equal((await store.originalOnlineIntent(op.entity_uuid))?.command.operation_id,correction.operation_id);
    assert.equal(await store.terminalOnlineIntent(op.entity_uuid,'approve'),null);
    await assert.rejects(repo.saveDraftAndEnqueue({...correction,operation_id:randomUUID()},hash,'online'),/original_online_intent/);
    assert.deepEqual(await store.operationDetails(op.operation_id),original);
  }finally{await repo.db.close();}
});
