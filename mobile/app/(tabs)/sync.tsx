import { useEffect,useState } from 'react';
import { Alert } from 'react-native';
import { router } from 'expo-router';
import { useSession } from '../../src/auth/session';
import { useSync } from '../../src/sync/context';
import type { Coverage,Delivery } from '../../src/sync/store';
import { useQueueCount } from '../../src/components/queue';
import { Body,Button,Card,ErrorMessage,Field,Notice,Screen } from '../../src/components/ui';
import { nativeSyncGateReason } from '../../src/sync/pilot-gate';
import { OperationDetails } from '../../src/components/operation-details';
import { uuid } from '../../src/protocol';
import { onlineOnly,poultryCommand } from '../../src/poultry/commands';
import { workflows } from '../../src/poultry/forms';
import { OnlineRecovery } from '../../src/components/online-recovery';
export default function Sync(){
 const {session,busy:authBusy,error:authError,revalidate}=useSession();const {store,revision,busy,error,message,enabled,syncNow,notify,reviewQuarantined,downloadBatch}=useSync();const queued=useQueueCount();
 const [batchDownload,setBatchDownload]=useState(''),[downloadDetails,setDownloadDetails]=useState<{store:typeof store;revision:number;value:Awaited<ReturnType<NonNullable<typeof store>['downloadState']>>}|null>(null);
 const [observedNow]=useState(()=>Date.now());
 const [after,setAfter]=useState('');const [details,setDetails]=useState<{store:typeof store;after:string;revision:number;rows:Delivery[];coverage:Coverage|null;last:string|null;error:string|null}|null>(null);
 useEffect(()=>{let active=true;if(!store)return;
  Promise.all([store.queue(after),store.coverage(),store.lastSuccess()]).then(([rows,coverage,last])=>{if(active)setDetails({store,after,revision,rows,coverage,last,error:null});})
   .catch(()=>{if(active)setDetails({store,after,revision,rows:[],coverage:null,last:null,error:'Cannot read local sync details. Records were not reset.'});});return()=>{active=false;};},[store,after,revision]);
 const view=details?.store===store&&details.after===after&&details.revision===revision?details:null;
 const downloadState=downloadDetails?.store===store&&downloadDetails.revision===revision?downloadDetails.value:null;
 useEffect(()=>{let active=true;if(store)void store.downloadState().then(value=>{if(active)setDownloadDetails({store,revision,value});}).catch(()=>{if(active)setDownloadDetails(null);});
  return()=>{active=false;};},[store,revision]);
 return <Screen title="Sync & local work"><Card title="Download coverage"><Body>{view?.coverage?`${view.coverage.packs.join(', ')} • downloaded ${view.coverage.completedAt} • watermark ${view.coverage.watermark}`:'No activated download. This is not an empty-farm result.'}</Body>
  <Body>Last complete server run: {view?.last??'Not yet completed'}</Body>{!enabled&&<Body>{nativeSyncGateReason}</Body>}
  <Button disabled={busy||authBusy||!enabled} title={busy?'Synchronizing…':'Sync now / download batches'} onPress={()=>{void syncNow();}}/><Notice message={message}/></Card>
  {session?.capabilities.projection_version===2&&<Card title="Offline coverage limits">
    <Body>Only named downloaded packs are covered. Current-pack records are not a whole-farm archive. Summary values remain as of the downloaded watermark, not live internet totals.</Body>
    <Body>{view?.coverage&&observedNow-Date.parse(view.coverage.completedAt)>86400000?'Download is older than 24 hours; it may be stale. Refresh when online.':'Check the download timestamp before relying on these values; offline changes on other devices are unknown.'}</Body>
    <Body>{!downloadState?'Coverage check unavailable or still loading; do not assume the download is complete.':downloadState.staging||downloadState.incompleteTransaction||downloadState.requiresBootstrap?'Download incomplete / refresh required. Last verified data is retained; missing history is not zero activity.':'No staged download remains.'}</Body>
    <Body>Explicitly removed batches (up to 100 listed): {downloadState?downloadState.excluded.map(b=>b.batch_uuid).join(', ')||'None listed':'Checking this user’s local store…'}. Automatic current-pack sync does not restore these.</Body>
    <Field label="Batch UUID for complete offline download" value={batchDownload} onChangeText={setBatchDownload} maxLength={36} autoCapitalize="none" editable={!busy}/>
    <Button title="Download this batch’s complete pack" disabled={busy||!enabled||!uuid.safeParse(batchDownload).success} onPress={()=>{void downloadBatch(batchDownload);}}/>
  </Card>}
  <Card title="Retained operations"><Body>{queued===null?'Count unavailable':`${queued} retained records needing confirmation or review`}</Body><Body>Confirmed receipts are not pending cash or flock effects. Each operation has its own outcome.</Body></Card>
  <ErrorMessage message={error??view?.error??authError??null}/>
  {view?.rows.map(row=>{const op=poultryCommand.parse(JSON.parse(row.command_json)),online=onlineOnly(op);
    const correctionWorkflow=Object.entries(workflows).find(([,w])=>w.entity===op.entity_type&&w.action===op.action)?.[0];
    return <Card key={row.operation_id} title={`${row.status} • ${row.operation_id}`}>
    <Body>{row.reason??'Awaiting server validation'} • attempts {row.attempts}</Body><Body>{op.entity_type} · {op.action} · captured {op.captured_at}</Body>
    {online&&<><Body>Explicit online intent. Automatic sync will not execute it, including after reconnect or restart.</Body>
      {!['conflict','rejected','discarded'].includes(row.status)&&<OnlineRecovery id={row.operation_id}/>}</>}
    <Body>Original hash: {row.command_hash}. Unknown outcomes cannot be edited or discarded. Terminal correction requires a new linked operation.</Body>
    <OperationDetails key={`${session?.pointer.partition}:${row.operation_id}`} store={store!} id={row.operation_id}/>
    {row.status==='conflict'&&<Body>The server found competing or inconsistent farm state. Review the known receipt and current batch before a linked correction; neither event is overwritten.</Body>}
    {row.status==='rejected'&&<Body>Django did not accept this event. Review its field feedback, event date, flock limit and current permission. Do not change the original evidence or shift its date to bypass a lock.</Body>}
    {row.status==='dependency_blocked'&&<Body>A parent operation has not been confirmed. This child stays retained; correcting or discarding its parent never silently changes the child.</Body>}
    {row.status==='retry_wait'&&!online&&<><Body>Retry no earlier than {new Date(row.next_ms).toISOString()}. The original status is checked before any replay.</Body><Button title="Retry original operation" accessibilityLabel={`Retry original operation ${row.operation_id}`} disabled={busy||!enabled} onPress={()=>{
      void store!.retry(row.operation_id,Date.now()).then(()=>syncNow()).catch(()=>Alert.alert('Retry is not ready','Wait for the retry delay or review this record. Neither its ID nor its payload was changed.'));
    }}/></>}
    {['conflict','rejected'].includes(row.status)&&!online&&correctionWorkflow&&<Button title="Review and create linked correction" accessibilityLabel={`Review and create linked correction ${row.operation_id}`} disabled={busy||!enabled} onPress={()=>router.push({pathname:'/(tabs)/record',params:{supersedes:row.operation_id,...(session?.capabilities.projection_version===2?{workflow:correctionWorkflow}:{})}})}/>}
    {row.status==='quarantined'&&<><Body>This evidence is isolated from automatic uploads. Scope changes or invalid responses require review; it is not a confirmed server rejection and cannot be blindly corrected or replayed.</Body>
      <Button title="Review original isolated operation online…" accessibilityLabel={`Review original isolated operation online ${row.operation_id}`} disabled={busy||authBusy||!enabled} onPress={()=>Alert.alert('Review original intent?',
        'Read the original record details first. This checks current access and the original server receipt. Only an explicit operation-not-found plus current downloaded scope/permission can restore the identical command for delivery. Nothing is edited or reparented.',
        [{text:'Keep isolated',style:'cancel'},{text:'Review original',onPress:()=>{void reviewQuarantined(row.operation_id).catch(()=>{});}}])}/></>}
    {!row.ever_sent&&['queued','dependency_blocked'].includes(row.status)&&<Button title="Discard unsent draft…" accessibilityLabel={`Discard unsent draft ${row.operation_id}`} disabled={busy} onPress={()=>Alert.alert('Discard unsent draft?',
      `Operation ${row.operation_id}, ${op.entity_type} ${op.action}, captured ${op.captured_at}. This retires only this unsent overlay. Original evidence remains; any dependent records stay blocked and need explicit correction.`,[{text:'Keep draft',style:'cancel'},{text:'Discard unsent',style:'destructive',onPress:()=>{void store!.discardUnsent(row.operation_id,true).then(notify).catch(()=>Alert.alert('Cannot discard','This command may have been submitted. Its original evidence was retained.'));}}])}/>}
  </Card>;})}
  <Button title="Next 25 local operations" disabled={!view||view.rows.length<25} onPress={()=>setAfter(view!.rows[view!.rows.length-1]!.operation_id)}/>
  <Button title="First local operations" disabled={!after} onPress={()=>setAfter('')}/>
  <Card title="Authorization"><Body>Last validated: {session?.capabilities.server_time}</Body><Button disabled={authBusy||busy} title="Check current server access" onPress={()=>{void revalidate();}}/></Card>
 </Screen>;
}
