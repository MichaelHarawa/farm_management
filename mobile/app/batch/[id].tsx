import { useLocalSearchParams,Redirect,router } from 'expo-router';
import { Alert } from 'react-native';
import * as Crypto from 'expo-crypto';
import { useEffect,useState } from 'react';
import { useSession } from '../../src/auth/session';
import { useSync } from '../../src/sync/context';
import { batchPayload } from '../../src/sync/protocol';
import { Body,Button,Card,ErrorMessage,Loading,Screen } from '../../src/components/ui';
import { PoultryHistory } from '../../src/components/poultry-history';
import { workflows, type Workflow } from '../../src/poultry/forms';
import { uuid } from '../../src/protocol';
import { farmEventFields } from '../../src/components/event-time';
import { FeedMaintenance } from '../../src/components/feed-maintenance';
export default function BatchDetail(){
  const {id}=useLocalSearchParams<{id:string}>();const {session}=useSession();const {store,revision,busy,downloadBatch,notify}=useSync();
  const [pendingBooking,setPendingBooking]=useState<{key:string;payload:Record<string,unknown>}|null>(null),[packError,setPackError]=useState<string|null>(null);
  const [value,setValue]=useState<{key:string;payload:ReturnType<typeof batchPayload.parse>|null;pending:number;unresolved:number;error:string|null;asOf?:string;serverRevision?:string}|null>(null);
  const key=`${session?.pointer.partition}:${id}:${revision}`;
  useEffect(()=>{let active=true;if(!store)return;
    store.repository.poultryBatches('',id).then(rows=>{const row=rows.find(r=>r.entity_uuid===id&&r.local_only);if(active)setPendingBooking(row?{key,payload:JSON.parse(row.payload_json)}:null);})
      .catch(()=>{if(active)setPackError('Pending local booking could not be read. Original work was not reset.');});
    return()=>{active=false;};},[store,id,key]);
  useEffect(()=>{let active=true;if(!store||!uuid.safeParse(id).success)return;
    Promise.all([store.batch(id),store.coverage()]).then(([row,coverage])=>{if(active)setValue({key,payload:row?batchPayload.parse(row.payload):null,pending:row?.pendingMortality??0,unresolved:row?.unresolvedOperations??0,error:null,asOf:coverage?.completedAt,serverRevision:row?.revision});})
      .catch(()=>{if(active)setValue({key,payload:null,pending:0,unresolved:0,error:'Local batch details are unavailable; records were not reset.'});});return()=>{active=false;};},[store,id,key]);
  if(!session)return <Redirect href="/"/>;
  if(!uuid.safeParse(id).success)return <Screen title="Batch unavailable"><ErrorMessage message="Invalid batch identity."/></Screen>;
  const row=value?.key===key?value:null;
  return <Screen title={row?.payload?.batch_id??'Downloaded batch'}>{!row?<Loading/>:<><ErrorMessage message={row.error}/>{row.payload?<>
    <Card title="Confirmed flock"><Body>Status: {row.payload.status}</Body><Body>{['booked','delivered','planned'].includes(row.payload.status)?'Not a received production flock; do not treat expected quantities as confirmed birds.':`${row.payload.remaining_birds} remaining birds • ${row.payload.total_mortality} confirmed mortality`}</Body>
      <Body>Downloaded coverage only. Server reference {row.payload.server_id}; updated {row.payload.updated_at}.</Body></Card>
    <Card title="Provisional local work"><Body>{row.pending} additional mortality birds await server validation.</Body>
      <Body>{row.unresolved} operations await receipts. Events already represented in confirmed records are not subtracted twice; their original drafts remain until receipt reconciliation.</Body>
      <Body>Provisional remaining: {row.payload.remaining_birds-row.pending}. This is not an approved flock balance.</Body></Card>
    {session.capabilities.projection_version===2&&<>
      <Card title="Arrival and lifecycle"><Body>Booking: {row.payload.booking_date??'No booking date recorded'} • expected {row.payload.expected_quantity??'Unavailable'} chicks</Body>
        <Body>Marked delivered: {row.payload.delivery_confirmed_at??'Not recorded'}</Body><Body>Actual arrival: {row.payload.entry_date} • {row.payload.actual_quantity_received??'Not confirmed'} chicks</Body>
        <Body>Expected maturity: {row.payload.expected_maturity_date} • closed {row.payload.closed_at??'Not closed'}</Body>
        <Body>{row.payload.actual_quantity_received!==null&&row.asOf?`Age ${Math.max(0,Math.round((Date.parse(farmEventFields(row.asOf).event_day+'T00:00:00Z')-Date.parse(farmEventFields(row.payload.entry_date).event_day+'T00:00:00Z'))/86400000))} farm calendar days as of download ${row.asOf}; not a live age indicator.`:'Arrival/coverage not confirmed; age is unavailable.'}</Body>
        <Body>Supplier: {row.payload.supplier_name||row.payload.source} • supplier reference {row.payload.booking_reference||'Not recorded'}</Body>
      </Card>
      <Card title="Confirmed feed and growth">
        {row.payload.operational_summary?<>
          <Body>{row.payload.operational_summary.feed_record_count?`${row.payload.operational_summary.feed_total_kg} kg recorded feed in ${row.payload.operational_summary.feed_record_count} events`:'No recorded feed evidence; not proof of zero consumption.'}</Body>
          <Body>Feed per bird started: {row.payload.operational_summary.feed_record_count?row.payload.operational_summary.feed_per_bird_started_kg??'Not available':'Not available'} kg, denominator {row.payload.operational_summary.feed_denominator_birds} actual arrivals. Not FCR.</Body>
          <Body>Growth: {row.payload.operational_summary.growth.state.replaceAll('_',' ')}.</Body>
          {row.payload.operational_summary.growth.sample&&<Body>Sample {row.payload.operational_summary.growth.sample.sampled_at} • age {row.payload.operational_summary.growth.sample.age_in_days} days • {row.payload.operational_summary.growth.sample.sample_size} weighed birds • average {row.payload.operational_summary.growth.sample.average_weight_g} g.
            Target {row.payload.operational_summary.growth.sample.target_weight_g??'Not applicable'} g; deviation {row.payload.operational_summary.growth.sample.deviation_percent??'Not applicable'}%.</Body>}
          <Body>Mortality: {row.payload.operational_summary.mortality.rate_percent??'Not available'}% • threshold {row.payload.operational_summary.mortality.threshold_percent}%. {row.payload.operational_summary.mortality.formula}.
            {row.payload.operational_summary.mortality.alert===true?' Threshold reached: review recorded evidence.':''}</Body>
        </>:<Body>Summary not downloaded. Do not infer healthy growth or zero activity.</Body>}
      </Card><PoultryHistory batch={id}/>
    </>}
    </>:pendingBooking?.key===key?<Card title="Provisional local booking"><Body>No official server reference or received flock yet.</Body>
      {Object.entries(pendingBooking.payload).map(([name,value])=><Body key={name}>{name.replaceAll('_',' ')}: {String(value)}</Body>)}
    </Card>:<Card title="Not in the current cache"><Body>This batch may be undownloaded, deleted, or outside current coverage. No farm total can be inferred.</Body></Card>}
    {session.capabilities.projection_version===2&&<Card title="Batch actions">
      {row.serverRevision&&<FeedMaintenance batch={id} revision={row.serverRevision}/>}
      {(Object.entries(workflows) as [Workflow,typeof workflows[Workflow]][]).filter(([name,value])=>name!=='book'&&session.capabilities.commands[`${value.entity}.${value.action}`]?.available)
        .map(([name,value])=><Button key={name} title={value.title} disabled={busy} onPress={()=>router.push({pathname:'/(tabs)/record',params:{workflow:name,batch:id}})}/>)}
      <Button title="Download or refresh this complete batch pack" disabled={busy||(!row.payload&&!!pendingBooking)} onPress={()=>{void downloadBatch(id);}}/>
      <Button title="Remove this batch’s downloaded data…" disabled={busy||!row.payload} onPress={()=>Alert.alert('Remove downloaded batch?',
        'Removal is refused if any local draft, pending operation, attachment or required parent needs this batch. Retained operation receipts are not erased.',
        [{text:'Keep offline data',style:'cancel'},{text:'Remove downloaded data',onPress:()=>{if(store)void store.removeBatch(id,Crypto.randomUUID(),Date.now()).then(()=>{notify();router.replace('/(tabs)/batches');})
          .catch(()=>setPackError('Removal refused. Finish the download and retain any parent needed by pending records or unsubmitted forms.'));}}])}/>
      <ErrorMessage message={packError}/>
    </Card>}
  </>}</Screen>;
}
