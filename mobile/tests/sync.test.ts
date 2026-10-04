import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash,randomUUID } from 'node:crypto';
import { mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { migrate,Repository,canonical,commandHashInput } from '../src/db/repository';
import { migrations } from '../src/db/schema';
import { SyncStore } from '../src/sync/store';
import { SyncEngine,backoff } from '../src/sync/engine';
import { checkSyncCoordination } from '../src/test/sync-coordination';
import { entity,changesPage,type Entity } from '../src/sync/protocol';
import { ApiError } from '../src/auth/client';
import { capabilitiesSchema } from '../src/protocol';
import { hostDatabase,command,identity } from './helpers';
const hash = async (s:string) => createHash('sha256').update(s).digest('hex');
const at='2026-10-02T10:00:00Z',epoch=randomUUID(),scope='synthetic-scope',pack='operational-current-v1';
const batch: Entity = entity.parse({entity_type:'poultry.batch',entity_uuid:command.payload.batch_uuid,revision:'1',payload:{
 server_id:'9007199254740993',created_at:at,updated_at:at,batch_id:'Synthetic',bird_type:'broiler',broiler_strain:'other',source:'other',source_other:'Synthetic',
 booking_date:null,estimated_chick_arrival_date:null,expected_quantity:100,actual_quantity_received:100,entry_date:'2026-09-01T00:00:00Z',
 expected_maturity_date:'2026-12-01T00:00:00Z',delivery_confirmed_at:at,quantity:100,closed_at:null,status:'active',initial_birds:100,sold_bird_count:0,
 total_mortality:0,remaining_birds:100,approved_adjustment_count:0}});
const caps=capabilitiesSchema.parse({protocol_version:1,schema_version:1,policy_version:1,projection_version:1,deployment_id:identity.deploymentId,
 device_id:identity.deviceId,stream_epoch:epoch,server_time:at,scope_revision:scope,entities:['poultry.batch','poultry.mortality','poultry.feed_usage'],
 commands:{'poultry.mortality.record':{available:true}},offline:{operational_days:7,sensitive_hours:24}});

test('pull requests honor the validated server row budget and continue bounded pages',async()=>{
 const {repo,store}=await setup();
 try{
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  const limited=capabilitiesSchema.parse({...caps,limits:{page_rows:1,page_bytes:1048576}});
  assert.equal(limited.limits?.page_rows,1);
  assert.equal(capabilitiesSchema.safeParse({...caps,limits:{page_rows:0}}).success,false);
  let calls=0;
  const engine=new SyncEngine({store,owner:'budget',uploadsEnabled:false,authorize:async()=>limited,now:()=>Date.parse(at),api:{async request(path){
   assert.equal(new URL(path,'http://synthetic.invalid').searchParams.get('limit'),'1');
   calls++;return delta([],[],`limited_${calls}`,calls===2);
  }}});
  assert.equal((await engine.run()).status,'complete');assert.equal(calls,2);
 }finally{await repo.db.close();}
});

test('canonical optional fields retain JSON wire semantics and existing command hashes',()=>{
 assert.equal(canonical({b:undefined,a:[undefined,1]}),'{"a":[null,1]}');
 assert.equal(canonical({...command,supersedes_operation_id:undefined}),canonical(command));
 assert.throws(()=>canonical(undefined),/unsupported_canonical_value/);
});

test('quarantine requires explicit original-owner review, current scope/permission and fenced status lookup before identical retry',async()=>{
 const {repo,store}=await setup();
 try{
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const before=await store.operationDetails(command.operation_id);await repo.invalidateScope();
  const owner=randomUUID(),now=Date.parse(at);await repo.acquireLease(owner,now,60000);
  await assert.rejects(store.allowReviewedRetry(command.operation_id,caps,true,{owner,now}),/download_current_scope/);
  const fresh=await snapshot(store);await store.stageSnapshotPage(fresh.page,'snapshot_cursor',at);
  await assert.rejects(store.allowReviewedRetry(command.operation_id,caps,false,{owner,now}),/owner_review/);
  await assert.rejects(store.allowReviewedRetry(command.operation_id,{...caps,commands:{'poultry.mortality.record':{available:false}}},true,{owner,now}),/permission/);
  await assert.rejects(store.allowReviewedRetry(command.operation_id,caps,true,{owner:'foreign',now}),/lease_lost/);
  await store.allowReviewedRetry(command.operation_id,caps,true,{owner,now});
  assert.deepEqual(await store.operationDetails(command.operation_id),before);
  assert.equal((await store.queue())[0]?.status,'queued');assert.equal((await store.claim(now,owner))[0]?.operation_id,command.operation_id);
  await store.reconcile({...accepted(),outcome:'validation_failed',code:'invalid_fields',canonical_entities:undefined,entity_mappings:undefined,transaction_id:undefined,committed_at:undefined},at);
  await repo.invalidateScope();
  const rejection=await store.operationDetails(command.operation_id);
  await store.reconcile(rejection.receipt,at,{owner,now});
  assert.equal((await store.queue())[0]?.status,'rejected');assert.deepEqual(await store.operationDetails(command.operation_id),rejection);
 }finally{await repo.db.close();}
});
async function setup(path?:string) {
 const db=hostDatabase(path); await migrate(db); const repo=new Repository(db,identity); await repo.bindIdentity();
 return {repo,store:new SyncStore(repo,hash)};
}
async function snapshot(store:SyncStore,entities=[batch],packs=[pack], id=randomUUID()) {
 const digest=await hash(canonical(entities));
 const manifest={snapshot_id:id,deployment_id:identity.deploymentId,stream_epoch:epoch,scope_revision:scope,watermark:'1',
 expires_at:'2026-10-03T10:00:00Z',packs:[...packs].sort(),row_count:entities.length,manifest:[{page:0,row_count:entities.length,sha256:digest}],next_page_cursor:'snapshot_cursor'};
 await store.beginSnapshot(manifest,epoch,scope);
 return {manifest,page:{snapshot_id:id,page:0,entities,sha256:digest,page_complete:true,next_page_cursor:null,delta_cursor:'cursor_1'}};
}
function delta(changes:unknown[],fragments:unknown[],cursor:string,complete=true) {
 return {deployment_id:identity.deploymentId,stream_epoch:epoch,scope_revision:scope,run_watermark:'100',changes,fragments,next_cursor:cursor,run_complete:complete,server_time:at};
}
function upsert(e:Entity,tx:string,index=0,final=true,sequence='2',packs=[pack]) {
 return {...e,sequence,transaction_id:tx,fragment_index:index,fragment_final:final,kind:'upsert',pack_ids:packs};
}
function accepted(op=command) {
 const mortality=entity.parse({entity_type:op.entity_type,entity_uuid:op.entity_uuid,revision:'2',payload:{...op.payload,server_id:'1',created_at:at,updated_at:at,age_in_days:29}});
 return {operation_id:op.operation_id,outcome:'accepted',code:'accepted',message:'Recorded once',field_errors:{},recovery_action:'reconcile_and_pull',
 canonical_entities:[batch,mortality],entity_mappings:[{entity_type:op.entity_type,entity_uuid:op.entity_uuid,server_id:'1',revision:'2'}],transaction_id:randomUUID(),committed_at:at};
}
test('native coordination orchestration shares a flight and excludes a persisted-lease contender before HTTP',async()=>{
 const {repo,store}=await setup();let calls=0,auth=0;
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const before=await store.operationDetails(command.operation_id);
  const proof=await checkSyncCoordination({store,now:()=>Date.parse(at),authorize:async()=>{auth++;return caps;},api:{async request(path){
   assert.ok(path.startsWith('/mobile-sync/changes?'));calls++;return delta([],[],`overlap_${calls}`);
  }}},['native-first','native-second']);
  assert.equal(proof.sharedFlight,true);assert.equal(proof.contender.status,'busy');assert.equal(proof.contender.requests,0);
  assert.equal(proof.completed.commands,0);assert.equal(auth,1);assert.equal(calls,1);
  assert.deepEqual(await store.operationDetails(command.operation_id),before);
  assert.equal(await repo.db.first('SELECT owner FROM sync_lease'),null);
 }finally{await repo.db.close();}
});
test('coordination diagnostics refuse an already owned lease without authentication or removing its owner',async()=>{
 const {repo,store}=await setup();
 try {
  await repo.acquireLease('existing',Date.parse(at),60000);
  await assert.rejects(checkSyncCoordination({store,now:()=>Date.parse(at),authorize:async()=>{assert.fail('no auth');},api:{async request(){assert.fail('no HTTP');}}},
   ['native-first','native-second']),/first_lease_not_acquired/);
  assert.equal((await repo.db.first<{owner:string}>('SELECT owner FROM sync_lease'))?.owner,'existing');
 }finally{await repo.db.close();}
});
test('coordination diagnostics surface authorization failure and release only their lease',async()=>{
 const {repo,store}=await setup();
 try {
  await assert.rejects(checkSyncCoordination({store,now:()=>Date.parse(at),authorize:async()=>{throw new ApiError(403,'revoked');},api:{async request(){assert.fail('no HTTP');}}},
   ['native-first','native-second']),/revoked/);
  assert.equal(await repo.db.first('SELECT owner FROM sync_lease'),null);
 }finally{await repo.db.close();}
});
test('frozen bootstrap checksum failure retains last good replica/outbox; activation rolls back atomically',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store); await store.stageSnapshotPage(s.page,'snapshot_cursor',at); await repo.saveDraftAndEnqueue(command,hash);
  const next=await snapshot(store,[{...batch,revision:'2'}]);
  await assert.rejects(store.stageSnapshotPage({...next.page,sha256:'0'.repeat(64)},'snapshot_cursor',at),/checksum/);
  assert.equal((await store.batch(batch.entity_uuid))?.payload.server_id,'9007199254740993'); assert.equal(await repo.queueCount(),1);
  await repo.db.exec("CREATE TRIGGER fail_activate BEFORE UPDATE ON confirmed_entities BEGIN SELECT RAISE(ABORT,'activation_crash'); END;");
  await assert.rejects(store.stageSnapshotPage(next.page,'snapshot_cursor',at),/activation_crash/);
  assert.equal((await repo.db.first<{revision:string}>('SELECT revision FROM confirmed_entities'))?.revision,'1');
  assert.equal((await store.snapshot())?.nextPage,0); assert.equal(await store.cursor(),'cursor_1');
 } finally {await repo.db.close();}
});
test('multi-page bootstrap resumes after close; last replica only activates on final verified page',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'farm-phase4-owned-')),path=join(dir,'sync.db');let state=await setup(path);
 try {
  const s=await snapshot(state.store); const second={...batch,entity_uuid:randomUUID()};const h=await hash(canonical([second]));
  await state.store.restartStaging();await state.store.beginSnapshot({...s.manifest,row_count:2,manifest:[s.manifest.manifest[0],{page:1,row_count:1,sha256:h}]},epoch,scope);
  await state.store.stageSnapshotPage({...s.page,page_complete:false,next_page_cursor:'page_1',delta_cursor:undefined},'snapshot_cursor',at);
  assert.equal((await state.repo.batches()).length,0);await state.repo.db.close();state=await setup(path);
  assert.equal((await state.store.snapshot())?.cursor,'page_1');
  await state.store.stageSnapshotPage({...s.page,page:1,entities:[second],sha256:h},'page_1',at);
  assert.equal((await state.repo.batches()).length,2);assert.equal(await state.store.snapshot(),null);
 }finally{await state.repo.db.close();rmSync(dir,{recursive:true});}
});
test('large delta transaction is invisible until hidden-only final fragment; applied/download cursors stay distinct',async()=>{
 const {repo,store}=await setup(); const tx=randomUUID();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  await store.applyPage(delta([upsert({...batch,revision:'9007199254740993'},tx,0,false)],[{transaction_id:tx,fragment_index:0,fragment_final:false}],'cursor_2',false),'cursor_1');
  assert.equal((await repo.db.first<{revision:string}>('SELECT revision FROM confirmed_entities'))?.revision,'1');
  assert.equal(await store.cursor(),'cursor_2');assert.equal((await repo.db.first<{value:string}>("SELECT value FROM sync_state WHERE key='phase4:applied_cursor'"))?.value,'"cursor_1"');
  await store.applyPage(delta([],[{transaction_id:tx,fragment_index:1,fragment_final:true}],'cursor_3'),'cursor_2');
  assert.equal((await repo.db.first<{revision:string}>('SELECT revision FROM confirmed_entities'))?.revision,'9007199254740993');
  assert.equal((await repo.db.first<{value:string}>("SELECT value FROM sync_state WHERE key='phase4:applied_cursor'"))?.value,'"cursor_3"');
 }finally{await repo.db.close();}
});
test('pull apply failure rolls back cursor and entities; replay after restart is harmless',async()=>{
 const {repo,store}=await setup();const tx=randomUUID(),page=delta([upsert({...batch,revision:'2'},tx)],[{transaction_id:tx,fragment_index:0,fragment_final:true}],'cursor_2');
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  await repo.db.exec("CREATE TRIGGER fail_pull BEFORE UPDATE ON confirmed_entities BEGIN SELECT RAISE(ABORT,'pull_crash'); END;");
  await assert.rejects(store.applyPage(page,'cursor_1'),/pull_crash/);assert.equal(await store.cursor(),'cursor_1');
  assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM delta_fragments'))?.n,0);await repo.db.exec('DROP TRIGGER fail_pull');
  await store.applyPage(page,'cursor_1');await store.applyPage(page,'cursor_1');
  assert.equal(await store.cursor(),'cursor_2');
  assert.equal((await repo.db.first<{revision:string}>('SELECT revision FROM confirmed_entities'))?.revision,'2');
 }finally{await repo.db.close();}
});
test('delayed acknowledgement cannot resurrect tombstone or overwrite newer pull; later draft overlay survives',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const next={...command,operation_id:randomUUID()};await repo.saveDraftAndEnqueue(next,hash);
  const receipt=accepted();const tx=randomUUID();await store.applyPage(delta([{sequence:'3',transaction_id:tx,fragment_index:0,fragment_final:true,
   entity_type:command.entity_type,entity_uuid:command.entity_uuid,revision:'3',kind:'tombstone',pack_ids:[pack]}],[{transaction_id:tx,fragment_index:0,fragment_final:true}],'cursor_2'),'cursor_1');
  await store.reconcile(receipt,at);
  const row=await repo.db.first<{tombstone:number;revision:string}>('SELECT tombstone,revision FROM confirmed_entities WHERE entity_uuid=?',[command.entity_uuid]);
  assert.deepEqual({...row},{tombstone:1,revision:'3'});assert.equal((await repo.db.first<{operation_id:string}>('SELECT operation_id FROM pending_overlays'))?.operation_id,next.operation_id);
  await store.reconcile({...receipt,outcome:'replayed'},at);assert.equal(await repo.queueCount(),1);
 }finally{await repo.db.close();}
});
test('overlapping archive membership and pending batch dependency survive current-pack eviction',async()=>{
 const {repo,store}=await setup();const archive=`batch:${batch.entity_uuid}`,tx=randomUUID();
 try {
  const s=await snapshot(store,[batch],[pack,archive]);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const evict={sequence:'2',transaction_id:tx,fragment_index:0,fragment_final:true,entity_type:batch.entity_type,entity_uuid:batch.entity_uuid,revision:'2',kind:'evict_from_pack',pack_ids:[pack]};
  await store.applyPage(delta([evict],[{transaction_id:tx,fragment_index:0,fragment_final:true}],'cursor_2'),'cursor_1');
  assert.ok(await store.batch(batch.entity_uuid));assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM pack_membership WHERE pack_id=?',[archive]))?.n,1);
  await repo.db.run('DELETE FROM pack_membership WHERE pack_id=?',[archive]);
  await store.applyPage({...delta([{...evict,sequence:'101'}],[{transaction_id:tx,fragment_index:0,fragment_final:true}],'cursor_3'),run_watermark:'101'},'cursor_2');
  assert.ok(await store.batch(batch.entity_uuid)); assert.equal(await repo.queueCount(),1);
 }finally{await repo.db.close();}
});
test('parent rejection blocks child; unknown cannot discard/correct; terminal correction creates new linked command',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const child={...command,operation_id:randomUUID(),entity_uuid:randomUUID(),depends_on:[command.operation_id]};await repo.saveDraftAndEnqueue(child,hash);
  await repo.acquireLease('owner',100,60000);const first=await store.claim(100,'owner');assert.equal(first.length,1);
  await assert.rejects(store.discardUnsent(command.operation_id,true),/submitted/);
  await assert.rejects(store.correctTerminal(command.operation_id,{...child,operation_id:randomUUID(),supersedes_operation_id:command.operation_id}),/terminal_receipt/);
  await store.reconcile({operation_id:command.operation_id,outcome:'validation_failed',code:'invalid_business_event',message:'Review',field_errors:{quantity_dead:['Too many']},recovery_action:'review_and_supersede'},at);
  assert.equal((await store.claim(100,'owner')).length,0);assert.equal((await store.queue()).find(r=>r.operation_id===child.operation_id)?.status,'dependency_blocked');
  const correction={...command,operation_id:randomUUID(),entity_uuid:randomUUID(),supersedes_operation_id:command.operation_id};await store.correctTerminal(command.operation_id,correction);
  assert.equal((await repo.db.first<{supersedes_operation_id:string}>('SELECT supersedes_operation_id FROM outbox WHERE operation_id=?',[correction.operation_id]))?.supersedes_operation_id,command.operation_id);
  assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM receipts'))?.n,1);
 }finally{await repo.db.close();}
});
test('engine lost push response recovers original receipt without re-posting; no false acceptance on HTTP200',async()=>{
 const {repo,store}=await setup();let pushes=0,lookups=0,lost=true;const receipt=accepted();let ms=Date.parse(at);
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const api={async request(path:string,body?:unknown){
   if(path.startsWith('/mobile-sync/changes'))return delta([],[],`cursor_${randomUUID()}`);
   if(path==='/mobile-sync/push'){pushes++;assert.deepEqual((body as {operations:unknown[]}).operations,[command]);if(lost){lost=false;throw new Error('response_lost_after_commit');}throw new Error('duplicate_push');}
   if(path.startsWith('/mobile-sync/operations')){lookups++;return receipt;}throw new Error('Unexpected request');}};
  const engine=new SyncEngine({api,store,authorize:async()=>caps,owner:'owner',uploadsEnabled:true,now:()=>ms,random:()=>0});
  await assert.rejects(engine.run(),/response_lost/);assert.equal((await store.queue())[0]?.status,'retry_wait');
  ms+=60000;await engine.run();assert.equal(pushes,1);assert.equal(lookups,1);assert.equal(await repo.queueCount(),0);
  assert.deepEqual(JSON.parse((await repo.db.first<{command_json:string}>('SELECT command_json FROM outbox'))!.command_json),command);
 }finally{await repo.db.close();}
});
test('empty-visible-page continuation is bounded and gated native writes never submit',async()=>{
 const {repo,store}=await setup();let pulls=0;
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const engine=new SyncEngine({store,owner:'owner',uploadsEnabled:false,authorize:async()=>caps,api:{async request(path){assert.ok(path.startsWith('/mobile-sync/changes'));pulls++;return delta([],[],`cursor_${pulls+1}`,pulls===3);}},now:()=>Date.parse(at)});
  const results=await Promise.all([engine.run(),engine.run()]);assert.equal(pulls,3);assert.equal(results[0]?.requests,3);assert.equal(await repo.queueCount(),1);
  assert.equal((await store.queue())[0]?.ever_sent,0);assert.equal(backoff(1,0,60000),60000);
 }finally{await repo.db.close();}
});
test('expired cursor preserves pending exact evidence and old replica during replacement; scope reset quarantines',async()=>{
 const {repo,store}=await setup();let pulls=0;
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const engine=new SyncEngine({store,owner:'owner',uploadsEnabled:false,authorize:async()=>caps,now:()=>Date.parse(at),api:{async request(path){
   if(path.startsWith('/mobile-sync/changes')){pulls++;if(pulls===1)throw new ApiError(410,'resync_required');return delta([],[],'cursor_new');}
   if(path==='/mobile-sync/bootstrap')return s.manifest;if(path.includes('/pages?'))return s.page;throw new Error('unexpected');}}});
  await engine.run();assert.equal(await repo.queueCount(),1);assert.deepEqual(JSON.parse((await store.queue())[0]!.command_json),command);
  assert.ok(await store.batch(batch.entity_uuid));
  await repo.invalidateScope();assert.equal((await store.queue())[0]?.status,'quarantined');assert.equal((await repo.batches()).length,0);
 }finally{await repo.db.close();}
});
test('actual snapshot-not-found 404 restarts only staging, retaining the last replica and exact command',async()=>{
 const {repo,store}=await setup();
 try{
  const old=await snapshot(store);await store.stageSnapshotPage(old.page,'snapshot_cursor',at);
  await repo.saveDraftAndEnqueue(command,hash);const original=await store.operationDetails(command.operation_id);
  const staged=await snapshot(store);let manifests=0;
  const replacement={...staged.manifest,snapshot_id:randomUUID()};
  const engine=new SyncEngine({store,owner:'missing-snapshot',uploadsEnabled:false,authorize:async()=>caps,now:()=>Date.parse(at),api:{async request(path,body){
   if(path==='/mobile-sync/bootstrap'){
    manifests++;assert.deepEqual(await store.operationDetails(command.operation_id),original);
    assert.equal((await store.batch(batch.entity_uuid))?.payload.remaining_birds,100);
    if(manifests===1){assert.equal((body as {resume_snapshot_id:string}).resume_snapshot_id,staged.manifest.snapshot_id);throw new ApiError(404,'snapshot_not_found');}
    assert.equal((body as {resume_snapshot_id?:string}).resume_snapshot_id,undefined);return replacement;
   }
   if(path.includes('/pages?'))return {...staged.page,snapshot_id:replacement.snapshot_id};
   if(path.startsWith('/mobile-sync/changes?'))return delta([],[],'replacement_cursor');
   throw new Error('unexpected');
  }}});
  assert.equal((await engine.run()).status,'complete');assert.equal(manifests,2);assert.equal(await store.snapshot(),null);
  assert.deepEqual(await store.operationDetails(command.operation_id),original);assert.equal((await store.queue())[0]?.ever_sent,0);
 }finally{await repo.db.close();}
});

test('strict positive projections reject restricted fields, malformed fragment and foreign deployment',async()=>{
 const {repo,store}=await setup();
 try {
  assert.throws(()=>entity.parse({...batch,payload:{...batch.payload,salary:'1.00'}}));
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  await assert.rejects(store.applyPage({...delta([],[],'cursor_2'),deployment_id:randomUUID()},'cursor_1'),/identity/);
  const tx=randomUUID();assert.ok(changesPage.safeParse(delta([],[{transaction_id:tx,fragment_index:1,fragment_final:true}],'cursor_2')).success);
  await assert.rejects(store.applyPage(delta([],[{transaction_id:tx,fragment_index:1,fragment_final:true}],'cursor_2'),'cursor_1'),/fragment_gap/);
  assert.equal(await store.cursor(),'cursor_1');
 }finally{await repo.db.close();}
});

test('additive v1 to v2 upgrade preserves exact legacy commands, hashes, overlays and quarantine',async()=>{
 const db=hostDatabase();await migrate(db,migrations.slice(0,1));const repo=new Repository(db,identity);await repo.bindIdentity();
 const originals=['pending','unknown','quarantined'].map(state=>({state,op:{...command,operation_id:randomUUID(),entity_uuid:randomUUID()}}));
 try {
  await db.run('INSERT INTO confirmed_entities VALUES(?,?,?,?,0)',[batch.entity_type,batch.entity_uuid,'1',canonical(batch.payload)]);
  for(const {state,op} of originals){const digest=await hash(commandHashInput(identity,op));
   await db.run('INSERT INTO outbox(operation_id,entity_uuid,entity_type,actor_id,device_id,deployment_id,command_json,command_hash,captured_at,state) VALUES(?,?,?,?,?,?,?,?,?,?)',
    [op.operation_id,op.entity_uuid,op.entity_type,identity.actorId,identity.deviceId,identity.deploymentId,canonical(op),digest,op.captured_at,state]);
   await db.run('INSERT INTO pending_overlays VALUES(?,?,?,?)',[op.operation_id,op.entity_uuid,op.entity_type,canonical(op.payload)]);
  }
  await migrate(db);const store=new SyncStore(repo,hash);const rows=await store.queue();assert.equal(rows.length,3);
  for(const {state,op} of originals){const row=rows.find(r=>r.operation_id===op.operation_id)!;
   assert.equal(row.command_json,canonical(op));assert.equal(row.command_hash,await hash(commandHashInput(identity,op)));
   assert.equal(row.status,state==='pending'?'queued':state==='unknown'?'retry_wait':'quarantined');
  }
  assert.equal((await db.first<{n:number}>('SELECT COUNT(*) n FROM pending_overlays'))?.n,3);
  await repo.acquireLease('upgrade',100,60000);assert.equal((await store.claim(100,'upgrade')).length,2);
  await assert.rejects(store.discardUnsent(originals[2]!.op.operation_id,true),/submitted/);
 }finally{await db.close();}
});

test('mixed HTTP200 receipts confirm only accepted record; corrected failure trail and duplicate correction guard survive',async()=>{
 const {repo,store}=await setup();const next={...command,operation_id:randomUUID(),entity_uuid:randomUUID()};
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);await repo.saveDraftAndEnqueue(next,hash);
  const engine=new SyncEngine({store,owner:'mixed',uploadsEnabled:true,authorize:async()=>caps,now:()=>Date.parse(at),api:{async request(path){
   if(path.startsWith('/mobile-sync/changes'))return delta([],[],randomUUID());
   if(path==='/mobile-sync/push')return {protocol_version:1,deployment_id:identity.deploymentId,device_id:identity.deviceId,server_time:at,results:[accepted(),
    {operation_id:next.operation_id,outcome:'validation_failed',code:'invalid_business_event',message:'Review',field_errors:{quantity_dead:['Too many']},recovery_action:'review_and_supersede'}]};throw new Error('unexpected');}}});
  assert.equal((await engine.run()).status,'complete');assert.equal(await repo.queueCount(),1);assert.equal((await store.queue())[0]?.status,'rejected');
  assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM pending_overlays'))?.n,1);
  assert.deepEqual(await store.correction(next.operation_id),next);await assert.rejects(store.correction(command.operation_id),/terminal_receipt/);
  const correction={...next,operation_id:randomUUID(),entity_uuid:randomUUID(),supersedes_operation_id:next.operation_id};await store.correctTerminal(next.operation_id,correction);
  await assert.rejects(store.correctTerminal(next.operation_id,{...correction,operation_id:randomUUID(),entity_uuid:randomUUID()}),/already_retained/);
  assert.equal((await repo.db.first<{command_json:string}>('SELECT command_json FROM outbox WHERE operation_id=?',[next.operation_id]))?.command_json,canonical(next));
 }finally{await repo.db.close();}
});

test('429 pull retry delay persists across coordinators and blocks manual/automatic early retry',async()=>{
 const {repo,store}=await setup();let ms=Date.parse(at),calls=0,authorizations=0;
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  const options={store,owner:'throttled',uploadsEnabled:false,authorize:async()=>{authorizations++;return caps;},now:()=>ms,api:{async request(){calls++;if(calls===1)throw new ApiError(429,'request_429',60000);return delta([],[],'cursor_2');}}};
  await assert.rejects(new SyncEngine(options).run(),/429/);assert.equal(await store.notBefore(),ms+60000);
  assert.equal((await new SyncEngine(options).run()).status,'paused');assert.equal(calls,1);assert.equal(authorizations,1);
  ms+=60000;assert.equal((await new SyncEngine(options).run()).status,'complete');assert.equal(calls,2);
 }finally{await repo.db.close();}
});

test('invalid push envelope isolates unknown evidence rather than auto-resending or treating HTTP400 as terminal rejection',async()=>{
 for(const failure of [new ApiError(400,'request_400'),new SyntaxError('invalid response')]){
  const {repo,store}=await setup();let ms=Date.parse(at),pushes=0;
  try {
   const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
   const engine=new SyncEngine({store,owner:'invalid',uploadsEnabled:true,authorize:async()=>caps,now:()=>ms,api:{async request(path){
    if(path.startsWith('/mobile-sync/changes'))return delta([],[],randomUUID());pushes++;throw failure;}}});
   await assert.rejects(engine.run());assert.equal((await store.queue())[0]?.status,'quarantined');
   assert.equal((await repo.db.first<{state:string}>('SELECT state FROM outbox'))?.state,'unknown');
   assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM receipts'))?.n,0);
   ms+=60000;await engine.run();assert.equal(pushes,1);await assert.rejects(store.retry(command.operation_id,ms),/not_due/);
   await assert.rejects(store.correction(command.operation_id),/terminal_receipt/);
  }finally{await repo.db.close();}
 }
});

test('persisted lease fences old workers from activating pages or receipts after replacement',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store);await repo.acquireLease('old',100,10);await repo.acquireLease('replacement',111,60000);
  await assert.rejects(store.stageSnapshotPage(s.page,'snapshot_cursor',at,{owner:'old',now:111}),/lease_lost/);
  assert.equal(await store.cursor(),null);assert.equal((await repo.batches()).length,0);
  await store.stageSnapshotPage(s.page,'snapshot_cursor',at,{owner:'replacement',now:111});await repo.saveDraftAndEnqueue(command,hash);
  await assert.rejects(store.reconcile(accepted(),at,{owner:'old',now:111}),/lease_lost/);assert.equal(await repo.queueCount(),1);
  await assert.rejects(repo.invalidateScope({owner:'old',now:111}),/lease_lost/);assert.equal((await repo.batches()).length,1);
  await repo.releaseLease('old');assert.equal(await repo.renewLease('replacement',112),true);
 }finally{await repo.db.close();}
});

test('bounded empty-page runs resume; incomplete transaction cannot be overtaken or expired snapshot activated',async()=>{
 const {repo,store}=await setup();let calls=0;
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  const engine=new SyncEngine({store,owner:'bounded',uploadsEnabled:false,authorize:async()=>caps,now:()=>Date.parse(at),maxPages:2,api:{async request(){calls++;return delta([],[],`cursor_${calls+1}`,calls===4);}}});
  assert.equal((await engine.run()).status,'paused');assert.equal(calls,2);assert.equal(await store.lastSuccess(),null);
  assert.equal((await engine.run()).status,'complete');assert.equal(calls,4);
  const tx=randomUUID();await store.applyPage({...delta([upsert({...batch,revision:'2'},tx,0,false,'101')],[{transaction_id:tx,fragment_index:0,fragment_final:false}],'partial',false),run_watermark:'102'},'cursor_5');
  const later=randomUUID();await assert.rejects(store.applyPage({...delta([upsert({...batch,revision:'3'},later,0,true,'102')],[{transaction_id:later,fragment_index:0,fragment_final:true}],'overtake'),run_watermark:'102'},'partial'),/group_order/);
  assert.equal(await store.cursor(),'partial');assert.equal((await repo.db.first<{revision:string}>('SELECT revision FROM confirmed_entities'))?.revision,'1');
  const replacement=await snapshot(store);await assert.rejects(store.stageSnapshotPage(replacement.page,'snapshot_cursor','2026-10-03T10:00:00Z'),/expired/);assert.equal(await store.cursor(),'partial');
 }finally{await repo.db.close();}
});

test('explicit unsent discard retains immutable evidence, blocks children and never allows changed command hash to send',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const child={...command,operation_id:randomUUID(),entity_uuid:randomUUID(),depends_on:[command.operation_id]};await repo.saveDraftAndEnqueue(child,hash);
  await assert.rejects(store.discardUnsent(command.operation_id,false),/blocked_children/);await store.discardUnsent(command.operation_id,true);
  assert.equal((await store.queue()).find(r=>r.operation_id===command.operation_id)?.status,'discarded');
  assert.equal((await store.queue()).find(r=>r.operation_id===child.operation_id)?.reason,'parent_discarded');
  assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM outbox'))?.n,2);
  const other={...command,operation_id:randomUUID(),entity_uuid:randomUUID()};await repo.saveDraftAndEnqueue(other,hash);
  await repo.db.exec('DROP TRIGGER immutable_command');await repo.db.run('UPDATE outbox SET command_hash=? WHERE operation_id=?',['0'.repeat(64),other.operation_id]);
  await repo.acquireLease('digest',100,60000);await assert.rejects(store.claim(100,'digest'),/hash/);
  assert.equal((await store.queue()).find(r=>r.operation_id===other.operation_id)?.ever_sent,0);
 }finally{await repo.db.close();}
});

test('blocked dependency prefix cannot starve a later ready command',async()=>{
 const {repo,store}=await setup();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  await store.reconcile({operation_id:command.operation_id,outcome:'validation_failed',code:'invalid_business_event',message:'Review',field_errors:{},recovery_action:'review_and_supersede'},at);
  for(let i=0;i<30;i++)await repo.saveDraftAndEnqueue({...command,operation_id:randomUUID(),entity_uuid:randomUUID(),depends_on:[command.operation_id]},hash);
  const ready={...command,operation_id:randomUUID(),entity_uuid:randomUUID(),captured_at:at};await repo.saveDraftAndEnqueue(ready,hash);
  await repo.acquireLease('fair',100,60000);assert.deepEqual((await store.claim(100,'fair',1)).map(r=>r.operation_id),[ready.operation_id]);
  assert.equal((await repo.db.first<{n:number}>("SELECT COUNT(*) n FROM deliveries WHERE status='dependency_blocked'"))?.n,30);
 }finally{await repo.db.close();}
});

test('visible sequence remains ordered across pages and completed watermarks; malformed continuation rolls back',async()=>{
 const {repo,store}=await setup();const tx=randomUUID();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);
  await store.applyPage(delta([upsert({...batch,revision:'2'},tx,0,false,'10')],[{transaction_id:tx,fragment_index:0,fragment_final:false}],'partial',false),'cursor_1');
  await assert.rejects(store.applyPage(delta([upsert({...batch,revision:'3'},tx,1,true,'9')],[{transaction_id:tx,fragment_index:1,fragment_final:true}],'end'),'partial'),/order_or_pack/);
  assert.equal(await store.cursor(),'partial');await store.applyPage(delta([],[{transaction_id:tx,fragment_index:1,fragment_final:true}],'end'),'partial');
  const next=randomUUID();await assert.rejects(store.applyPage(delta([upsert({...batch,revision:'4'},next,0,true,'99')],[{transaction_id:next,fragment_index:0,fragment_final:true}],'bad'),'end'),/order_or_pack/);
  assert.equal((await store.coverage())?.watermark,'100');assert.equal(await store.cursor(),'end');
 }finally{await repo.db.close();}
});

test('idempotency mismatch queries the original receipt; differing canonical intent never retires the local overlay',async()=>{
 for(const matching of [true,false]){
  const {repo,store}=await setup();let lookups=0;
  try {
   const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
   const engine=new SyncEngine({store,owner:'original',uploadsEnabled:true,authorize:async()=>caps,now:()=>Date.parse(at),api:{async request(path){
    if(path.startsWith('/mobile-sync/changes'))return delta([],[],randomUUID());
    if(path.startsWith('/mobile-sync/operations')){lookups++;return accepted(matching?command:{...command,payload:{...command.payload,quantity_dead:1}});}
    return {protocol_version:1,deployment_id:identity.deploymentId,device_id:identity.deviceId,server_time:at,results:[{operation_id:command.operation_id,
      outcome:'conflict',code:'idempotency_mismatch',message:'Query original',field_errors:{},recovery_action:'query_original_operation'}]};}}});
   if(matching){await engine.run();assert.equal(await repo.queueCount(),0);}else{
    await assert.rejects(engine.run(),/payload_mismatch/);assert.equal((await store.queue())[0]?.status,'quarantined');
    assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM pending_overlays'))?.n,1);
    assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM receipts'))?.n,0);
   }
   assert.equal(lookups,1);
  }finally{await repo.db.close();}
 }
});

test('pulled event awaiting its receipt is not subtracted twice from provisional flock; overlay remains',async()=>{
 const {repo,store}=await setup();const tx=randomUUID();
 try {
  const s=await snapshot(store);await store.stageSnapshotPage(s.page,'snapshot_cursor',at);await repo.saveDraftAndEnqueue(command,hash);
  const receipt=accepted();const mortality=receipt.canonical_entities[1]!;
  await store.applyPage(delta([upsert({...batch,revision:'2',payload:{...batch.payload,remaining_birds:98,total_mortality:2}},tx),upsert(mortality,tx,0,true,'3')],
    [{transaction_id:tx,fragment_index:0,fragment_final:true}],'cursor_2'),'cursor_1');
  const flock=await store.batch(batch.entity_uuid);assert.equal(flock?.pendingMortality,0);assert.equal(flock?.unresolvedOperations,1);assert.equal(flock?.payload.remaining_birds,98);
  assert.equal((await repo.db.first<{n:number}>('SELECT COUNT(*) n FROM pending_overlays'))?.n,1);assert.equal(await repo.queueCount(),1);
 }finally{await repo.db.close();}
});
