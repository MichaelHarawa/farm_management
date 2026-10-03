import { useLocalSearchParams,Redirect } from 'expo-router';
import { useEffect,useState } from 'react';
import { useSession } from '../../src/auth/session';
import { useSync } from '../../src/sync/context';
import { batchPayload } from '../../src/sync/protocol';
import { Body,Card,ErrorMessage,Loading,Screen } from '../../src/components/ui';
import { uuid } from '../../src/protocol';
export default function BatchDetail(){
  const {id}=useLocalSearchParams<{id:string}>();const {session}=useSession();const {store,revision}=useSync();
  const [value,setValue]=useState<{key:string;payload:ReturnType<typeof batchPayload.parse>|null;pending:number;unresolved:number;error:string|null}|null>(null);
  const key=`${session?.pointer.partition}:${id}:${revision}`;
  useEffect(()=>{let active=true;if(!store||!uuid.safeParse(id).success)return;
    store.batch(id).then(row=>{if(active)setValue({key,payload:row?batchPayload.parse(row.payload):null,pending:row?.pendingMortality??0,unresolved:row?.unresolvedOperations??0,error:null});})
      .catch(()=>{if(active)setValue({key,payload:null,pending:0,unresolved:0,error:'Local batch details are unavailable; records were not reset.'});});return()=>{active=false;};},[store,id,key]);
  if(!session)return <Redirect href="/"/>;
  if(!uuid.safeParse(id).success)return <Screen title="Batch unavailable"><ErrorMessage message="Invalid batch identity."/></Screen>;
  const row=value?.key===key?value:null;
  return <Screen title={row?.payload?.batch_id??'Downloaded batch'}>{!row?<Loading/>:<><ErrorMessage message={row.error}/>{row.payload?<>
    <Card title="Confirmed flock"><Body>Status: {row.payload.status}</Body><Body>{row.payload.remaining_birds} remaining birds • {row.payload.total_mortality} confirmed mortality</Body>
      <Body>Downloaded coverage only. Server reference {row.payload.server_id}; updated {row.payload.updated_at}.</Body></Card>
    <Card title="Provisional local work"><Body>{row.pending} additional mortality birds await server validation.</Body>
      <Body>{row.unresolved} operations await receipts. Events already represented in confirmed records are not subtracted twice; their original drafts remain until receipt reconciliation.</Body>
      <Body>Provisional remaining: {row.payload.remaining_birds-row.pending}. This is not an approved flock balance.</Body></Card>
    </>:<Card title="Not in the current cache"><Body>This batch may be undownloaded, deleted, or outside current coverage. No farm total can be inferred.</Body></Card>}</>}</Screen>;
}
