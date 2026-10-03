import { useEffect,useState } from 'react';
import type { SyncStore } from '../sync/store';
import { Body,Button,ErrorMessage } from './ui';
export function OperationDetails({store,id}:{store:SyncStore;id:string}) {
  const [expanded,setExpanded]=useState(false);
  const [details,setDetails]=useState<Awaited<ReturnType<SyncStore['operationDetails']>>|null>(null);
  const [error,setError]=useState<string|null>(null);
  useEffect(()=>{let active=true;if(!expanded)return;
    store.operationDetails(id).then(value=>{if(active)setDetails(value);}).catch(()=>{if(active)setError('Cannot read this record. No evidence was changed.');});
    return()=>{active=false;};},[expanded,store,id]);
  return <><Button title={expanded?'Hide original record details':'View original record and server outcome'} onPress={()=>setExpanded(v=>!v)}/>
    {expanded&&<><ErrorMessage message={error}/>{details&&<>
      <Body>Event UUID: {details.command.entity_uuid}. Event UTC time: {details.command.payload.mortality_date}.</Body>
      <Body>Cause: {details.command.payload.suspected_cause}. Description: {details.command.payload.description}.</Body>
      <Body>Action taken: {details.command.payload.action_taken}. Observed reporter: {details.command.payload.reported_by_name}.</Body>
      <Body>Dependencies: {details.command.depends_on.join(', ')||'None'}. Corrects: {details.command.supersedes_operation_id??'None'}.</Body>
      <Body>{details.receipt?`Known server outcome: ${details.receipt.outcome} (${details.receipt.code}).`:'No terminal server receipt. Submission outcome may still be unknown; do not recreate this record.'}</Body>
      {details.receipt?.field_errors&&<Body>Server field feedback: {JSON.stringify(details.receipt.field_errors)}</Body>}
    </>}</>}
  </>;
}
