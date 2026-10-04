// Explicit invocation only: the evidence-owned, separate synthetic Phase5 API.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID,createHash } from 'node:crypto';
import { mkdtempSync,rmSync,readFileSync,writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AuthClient,httpTransport,type Credentials } from '../src/auth/client';
import { capabilitiesSchema,registrationSchema,tokenPairSchema,userSchema } from '../src/protocol';
import { Repository,migrate,canonical } from '../src/db/repository';
import { hostDatabase } from './helpers';
import { SyncStore } from '../src/sync/store';
import { SyncEngine } from '../src/sync/engine';
import { poultryCommand,type PoultryCommand } from '../src/poultry/commands';
import { submitOnlinePoultry } from '../src/poultry/online';

test('real Django poultry: offline parent chain/shift, exact close-reopen, per-command lost-response recovery, explicit approval and ordinary API reconciliation',async()=>{
  const ownership=JSON.parse(readFileSync('../docs/mobile/evidence/phase05-native-ownership.json','utf8'));
  const secret=JSON.parse(readFileSync('../tmp/phase05-synthetic-credentials.json','utf8'));
  assert.equal(ownership.kind,'owned_phase5_native_backend');assert.equal(ownership.port,7074);assert.equal(ownership.ready,true);
  assert.match(ownership.database,/^test_mobile_phase05_[0-9a-f]{12}$/);assert.equal(secret.database,ownership.database);assert.equal(secret.deployment,ownership.deployment);
  assert.equal(secret.kind,'phase5_synthetic_only');assert.match(secret.password,/-SyntheticOnly!$/);
  const localDocker=process.env.MOBILE_PHASE5_TEST_DOCKER==='1'&&process.cwd()==='/app/mobile';
  const transport=httpTransport(localDocker?'http://farm-mobile-phase05:7074/api/v1':'http://127.0.0.1:7074/api/v1',2);
  const login=tokenPairSchema.extend({user:userSchema}).parse(await transport('/auth/login',{username:'mobile-test-supervisor',password:secret.password}));
  const reg=registrationSchema.parse(await transport('/mobile-sync/devices',{installation_id:randomUUID(),app_version:'0.3.0-phase5-host',platform:'android',protocol_version:1,device_label:'Synthetic Phase5 host'},login.access));
  assert.equal(reg.deployment_id,ownership.deployment);
  let credentials:Credentials={refresh:reg.refresh,rotation:'ready'};
  const client=new AuthClient(transport,{read:async()=>credentials,write:async v=>{credentials=v;}},async()=>{});client.setAccess(reg.access);
  const authorize=async()=>capabilitiesSchema.parse(await client.read('/mobile-sync/capabilities'));
  const caps=await authorize();assert.equal(caps.projection_version,2);assert.equal(caps.lookups?.stock_linked_capture,false);
  const identity={actorId:login.user.id,deviceId:reg.device_id,deploymentId:reg.deployment_id};
  const dir=mkdtempSync(join(tmpdir(),'farm-phase5-http-owned-')),path=join(dir,'local.db');
  const hash=async(s:string)=>createHash('sha256').update(s).digest('hex');
  let repo=new Repository(hostDatabase(path),identity);await migrate(repo.db);await repo.bindIdentity();let store=new SyncStore(repo,hash);
  let now=Date.now(),pushes=0,lost=0,transportFailures=0;const visited=new Set<string>();
  const api={async request(route:string,body?:unknown){const value=await client.request(route,body);
    // Real response was received from PostgreSQL commit, then deliberately lost
    // at the client boundary. This is host evidence, NOT native/TCP evidence.
    if(route==='/mobile-sync/push'){pushes++;const results=(value as {results:{operation_id:string;outcome:string}[]}).results;
      const accepted=results.find(r=>r.outcome==='accepted'&&!visited.has(r.operation_id));
      if(accepted){visited.add(accepted.operation_id);lost++;throw new Error('Deliberately lost committed host response');}}
    return value;}};
  const engine=()=>new SyncEngine({store,api,authorize,owner:randomUUID(),uploadsEnabled:true,defaultPacks:['operational-current-v2'],now:()=>now,random:()=>0});
  const make=(kind:string,action:string,payload:object,extra:object={}):PoultryCommand=>poultryCommand.parse({operation_id:randomUUID(),entity_uuid:randomUUID(),entity_type:kind,action,
    payload_version:1,base_version:null,captured_at:new Date().toISOString(),depends_on:[],payload,...extra});
  try{
    assert.equal((await engine().run()).status,'complete');
    const arrival=new Date(Date.now()-3*86400000).toISOString(),maturity=new Date(Date.parse(arrival)+46*86400000).toISOString(),observed=new Date(Date.parse(arrival)+86400000).toISOString();
    const book=make('poultry.batch','book',{bird_type:'broilers',broiler_strain:'ross308',source:'central_poultry',booking_date:arrival.slice(0,10),estimated_chick_arrival_date:arrival.slice(0,10),
      expected_quantity:120,entry_date:arrival,expected_maturity_date:maturity,booking_reference:'SYNTHETIC-PHASE5-HOST'});
    const parent=book.entity_uuid;
    const delivered=make('poultry.batch','mark_delivered',{batch_uuid:parent},{entity_uuid:parent,depends_on:[book.operation_id]});
    const confirmed=make('poultry.batch','confirm_delivery',{batch_uuid:parent,entry_date:arrival,quantity:100,expected_maturity_date:maturity},{entity_uuid:parent,depends_on:[delivered.operation_id]});
    const base={batch_uuid:parent,reported_by_name:'Synthetic observed worker'};
    const operations=[book,delivered,confirmed,
      ...([{quantity_given:1500,unit_of_measurement:'g'},{quantity_given:2,unit_of_measurement:'kg'}] as const).map(q=>make('poultry.feed_usage','record',{
        ...base,...q,feeding_start_date:observed,feeding_end_date:observed,feed_type:'starter',feed_source:'cp_feed',notes:'Synthetic weighed feed'},{depends_on:[confirmed.operation_id]})),
      make('poultry.treatment','record',{...base,vaccination_date:observed,drug_category:'vaccination',drug_vaccination_type:'other',other_drug_vaccination:'Synthetic vial',quantity:1,
        description:'Unit: vial; synthetic evidence only',timely_status:'Observed as given'},{depends_on:[confirmed.operation_id]}),
      make('poultry.weight_sample','record',{...base,sampled_at:observed,sample_size:10,average_weight_g:75,notes:'Synthetic weight sample'},{depends_on:[confirmed.operation_id]}),
      make('poultry.mortality','record',{...base,mortality_date:observed,quantity_dead:2,suspected_cause:'Unknown',description:'Synthetic count',action_taken:'Reported'},{depends_on:[confirmed.operation_id]}),
      make('poultry.adjustment_proposal','propose',{batch_uuid:parent,effective_at:observed,quantity_change:-3,reason:'Synthetic verified count proposal'},{depends_on:[confirmed.operation_id]})];
    // Save all offline without any request, close the actual SQLite connection,
    // reopen and compare canonical commands and stored hashes before delivery.
    for(const operation of operations)await repo.saveDraftAndEnqueue(operation,hash);
    const originals=await repo.db.all('SELECT operation_id,command_json,command_hash FROM outbox ORDER BY operation_id');
    await repo.db.close();repo=new Repository(hostDatabase(path),identity);await migrate(repo.db);await repo.bindIdentity();store=new SyncStore(repo,hash);
    assert.deepEqual(await repo.db.all('SELECT operation_id,command_json,command_hash FROM outbox ORDER BY operation_id'),originals);
    for(let i=0;i<15&&await repo.queueCount();i++){try{await engine().run();}catch(error){
      if(error instanceof TypeError&&error.message==='fetch failed'){transportFailures++;process.stdout.write(`Host transport failure ${(error.cause as {code?:string})?.code??'unknown'}; retained originals are checked before replay.\n`);if(transportFailures>=3)throw new Error('Host transport unavailable; acceptance not passed.');}
      else assert.match(String(error),/lost committed/);
    }now+=60000;}
    assert.equal(await repo.queueCount(),0,canonical(await store.queue()));
    assert.deepEqual(await repo.db.all('SELECT operation_id,command_json,command_hash FROM outbox ORDER BY operation_id'),originals);
    const arrived=await store.batch(parent);assert.equal(arrived?.payload.remaining_birds,98);
    assert.equal(arrived?.payload.expected_quantity,120);assert.equal(arrived?.payload.actual_quantity_received,100);
    assert.equal(arrived?.payload.operational_summary.feed_total_kg,'3.500');assert.equal(arrived?.payload.operational_summary.feed_denominator_birds,100);
    assert.equal(arrived?.payload.operational_summary.fcr,null);
    const proposal=operations[8]!,projection=(await store.operationDetails(proposal.operation_id)).receipt!.canonical_entities!.find(e=>e.entity_uuid===proposal.entity_uuid)!;
    const approve=make('poultry.adjustment_proposal','approve',{reason:'Verified count online'},{entity_uuid:proposal.entity_uuid,base_version:projection.revision});
    await repo.saveDraftAndEnqueue(approve,hash,'online');await engine().run();assert.equal((await store.queue()).find(r=>r.operation_id===approve.operation_id)?.ever_sent,0);
    let onlinePosts=0;
    const onlineApi={async request(route:string,body?:unknown){const value=await client.request(route,body);if(route==='/mobile-sync/poultry-online'){onlinePosts++;throw new Error('Lost online result after commit');}return value;}};
    await assert.rejects(submitOnlinePoultry({store,api:onlineApi,authorize,owner:randomUUID(),operationId:approve.operation_id,confirmed:true,now:()=>Date.now()}),/Lost online/);
    await submitOnlinePoultry({store,api:onlineApi,authorize,owner:randomUUID(),operationId:approve.operation_id,confirmed:false,now:()=>Date.now()});
    assert.equal(onlinePosts,1);assert.equal(await repo.queueCount(),0);await engine().run();
    const final=await store.batch(parent);assert.equal(final?.payload.remaining_birds,95);assert.equal(final?.payload.approved_adjustment_count,-3);
    const web=await transport(`/poultry-management/${final?.payload.server_id}/feed_usage`,undefined,login.access) as unknown[];
    assert.equal(web.length,2);
    for(const operation of [...operations,approve]){const details=await store.operationDetails(operation.operation_id);assert.equal(details.receipt?.outcome,'accepted');}
    writeFileSync('../docs/mobile/evidence/phase05-host-http-integration.json',JSON.stringify({
      captured_at:new Date().toISOString(),result:'passed',evidence_kind:'host SQLite plus real Django/PostgreSQL HTTP; not native Android or TCP fault',
      runtime:process.version,database:ownership.database,deployment:ownership.deployment,batch_uuid:parent,
      expected_arrivals:120,actual_arrivals:100,remaining_birds:95,approved_adjustment:-3,feed_kg:'3.500',fcr:null,
      queued_events:9,explicit_approvals:1,push_requests:pushes,deliberately_lost_host_responses:lost,real_transport_interruptions:transportFailures,online_posts:onlinePosts,
      exact_offline_reopen_and_post_reconciliation_preservation:true,ordinary_rest_feed_rows:web.length,
      original_operations:await Promise.all([...operations,approve].map(async operation=>({operation_id:operation.operation_id,
        command:`${operation.entity_type}.${operation.action}`,hash:(await store.operationDetails(operation.operation_id)).hash,outcome:'accepted'}))),
    },null,2)+'\n');
    process.stdout.write(`Phase5 host HTTP reconciliation: 9 queued events, 1 explicit approval, 100 actual / 120 expected arrivals, 95 remaining birds, 3.500 kg feed, ${pushes} pushes, ${lost} deliberately lost host responses, ${transportFailures} real transport interruptions, 1 online POST. Not Android evidence.\n`);
  }finally{await repo.db.close();rmSync(dir,{recursive:true});}
});
