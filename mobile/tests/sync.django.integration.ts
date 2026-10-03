// Only the guarded --phase4-test runner: newly owned synthetic PostgreSQL + real HTTP.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID,createHash } from 'node:crypto';
import { mkdtempSync,rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { AuthClient,httpTransport,type Credentials } from '../src/auth/client';
import { capabilitiesSchema,registrationSchema,tokenPairSchema,userSchema,type MortalityCommand } from '../src/protocol';
import { Repository,migrate } from '../src/db/repository';
import { hostDatabase } from './helpers';
import { SyncStore } from '../src/sync/store';
import { SyncEngine } from '../src/sync/engine';
test('real Django sync: paged bootstrap, offline close/reopen, committed push TCP loss, receipt recovery, web-equivalent read',async()=>{
 const base=process.env.MOBILE_TEST_API,password=process.env.MOBILE_TEST_PASSWORD;
 assert.ok(base?.startsWith('http://127.0.0.1:')&&password?.endsWith('-SyntheticOnly!'),'Use guarded --phase4-test runner.');
 const transport=httpTransport(base!);const login=tokenPairSchema.extend({user:userSchema}).parse(await transport('/auth/login',{username:'mobile-test-worker',password}));
 const reg=registrationSchema.parse(await transport('/mobile-sync/devices',{installation_id:randomUUID(),app_version:'0.3.0-phase4-host',platform:'android',protocol_version:1,device_label:'Synthetic phase4'},login.access));
 let credentials:Credentials={refresh:reg.refresh,rotation:'ready'};
 const client=new AuthClient(transport,{read:async()=>credentials,write:async v=>{credentials=v;}},async()=>{});client.setAccess(reg.access);
 const caps=capabilitiesSchema.parse(await client.read('/mobile-sync/capabilities'));
 const identity={actorId:login.user.id,deviceId:reg.device_id,deploymentId:reg.deployment_id};
 const dir=mkdtempSync(join(tmpdir(),'farm-phase4-http-owned-'));const path=join(dir,'local.db');
 const hash=async(s:string)=>createHash('sha256').update(s).digest('hex');
 let repo=new Repository(hostDatabase(path),identity);await migrate(repo.db);await repo.bindIdentity();let store=new SyncStore(repo,hash);
 let now=Date.now();let requestCount=0,maxRequestBytes=0,maxResponseBytes=0;
 const api={async request(path:string,body?:unknown){requestCount++;maxRequestBytes=Math.max(maxRequestBytes,Buffer.byteLength(JSON.stringify(body??null)));
  const value=await client.request(path,body);maxResponseBytes=Math.max(maxResponseBytes,Buffer.byteLength(JSON.stringify(value)));return value;}};
 try {
  let engine=new SyncEngine({store,api,authorize:async()=>caps,owner:'host-read',uploadsEnabled:false,now:()=>now});
  const first=await engine.run();assert.equal(first.status,'complete');assert.ok(first.pages>=3);const batch=(await repo.batches())[0];assert.ok(batch);
  const payload=JSON.parse(batch.payload_json);assert.equal(payload.remaining_birds,100);assert.equal(payload.target_selling_price,undefined);
  const operations:MortalityCommand[]=Array.from({length:3},()=>({operation_id:randomUUID(),entity_uuid:randomUUID(),entity_type:'poultry.mortality',action:'record',
   payload_version:1,base_version:null,captured_at:new Date(now).toISOString(),depends_on:[],payload:{batch_uuid:batch.entity_uuid,
    mortality_date:new Date(Date.parse(payload.entry_date)+86400000).toISOString(),quantity_dead:1,suspected_cause:'Unknown',description:'Synthetic offline observation',action_taken:'Reported',reported_by_name:'Synthetic worker'}}));
  const beforeOffline=requestCount;for(const op of operations)await repo.saveDraftAndEnqueue(op,hash);
  assert.equal(requestCount,beforeOffline);await repo.db.close();repo=new Repository(hostDatabase(path),identity);await migrate(repo.db);await repo.bindIdentity();store=new SyncStore(repo,hash);
  const retained=await store.queue();assert.equal(retained.length,3);assert.deepEqual(retained.map(r=>JSON.parse(r.command_json)).sort((a,b)=>a.operation_id.localeCompare(b.operation_id)),[...operations].sort((a,b)=>a.operation_id.localeCompare(b.operation_id)));
  engine=new SyncEngine({store,api,authorize:async()=>caps,owner:'host-write',uploadsEnabled:true,now:()=>now,random:()=>0});
  await assert.rejects(engine.run()); // Actual server commits then closes TCP without sending the response.
  assert.equal(await repo.queueCount(),3);await repo.db.close();repo=new Repository(hostDatabase(path),identity);await migrate(repo.db);await repo.bindIdentity();store=new SyncStore(repo,hash);now+=60000;
  engine=new SyncEngine({store,api,authorize:async()=>caps,owner:'host-recovered',uploadsEnabled:true,now:()=>now});
  await engine.run();assert.equal(await repo.queueCount(),0);assert.equal((await store.batch(batch.entity_uuid))?.payload.remaining_birds,97);
  const recovered=await repo.db.all<{operation_id:string;command_json:string;command_hash:string}>('SELECT operation_id,command_json,command_hash FROM outbox ORDER BY operation_id');
  assert.deepEqual(recovered.map(row=>({...row})),retained.map(({operation_id,command_json,command_hash})=>({operation_id,command_json,command_hash})));
  const events=await repo.db.all<{payload_json:string}>("SELECT payload_json FROM confirmed_entities WHERE entity_type='poultry.mortality' AND tombstone=0");assert.equal(events.length,3);
  const feed=await repo.db.first<{payload_json:string}>("SELECT payload_json FROM confirmed_entities WHERE entity_type='poultry.feed_usage' AND tombstone=0");assert.ok(feed);
  assert.equal(JSON.parse(feed.payload_json).current_number_of_birds,97);
  const web=await transport(`/poultry-management/${payload.server_id}/mortality`,undefined,login.access) as unknown[];assert.equal(web.length,3);
  assert.ok(requestCount<30,`Bounded pilot calls: ${requestCount}`);
  assert.ok(maxRequestBytes<=1024*1024&&maxResponseBytes<=1024*1024);
  process.stdout.write(`Phase4 measured engine requests=${requestCount}, max request bytes=${maxRequestBytes}, max response bytes=${maxResponseBytes}; auth registration/capability and ordinary web read excluded.\n`);
 }finally{await repo.db.close();rmSync(dir,{recursive:true});}
});
