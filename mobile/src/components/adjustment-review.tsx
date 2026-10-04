import { useRef, useState } from 'react';
import { Alert } from 'react-native';
import * as Crypto from 'expo-crypto';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
import { poultryCommand } from '../poultry/commands';
import { submitOnlinePoultry } from '../poultry/online';
import { Body, Button, ErrorMessage, Field, Notice } from './ui';

export function AdjustmentReview({id,revision,status}:{id:string;revision:string;status:string}) {
  const {session,authorizeSync}=useSession(),{store,busy,enabled,notify}=useSync();
  const [reason,setReason]=useState(''),[running,setRunning]=useState(false),[error,setError]=useState<string|null>(null),[notice,setNotice]=useState<string|null>(null);
  const confirming=useRef(false);
  const permitted=enabled&&session?.capabilities.commands['poultry.adjustment_proposal.approve']?.available;
  if(!permitted||status!=='pending')return <Body>Proposal {status}. Only authorized online approval changes the confirmed count.</Body>;
  async function confirm(action:'approve'|'reject') {
    if(!store||!session||confirming.current||running||busy)return;
    confirming.current=true;setRunning(true);setError(null);
    try {
      const prior=await store.originalOnlineIntent(id);
      const terminal=prior?null:await store.terminalOnlineIntent(id,action);
      if(!prior&&!reason.trim()){setError('Enter an online review reason.');confirming.current=false;setRunning(false);return;}
      const command=prior?.command??poultryCommand.parse({operation_id:Crypto.randomUUID(),entity_uuid:id,entity_type:'poultry.adjustment_proposal',action,
        payload_version:1,base_version:revision,captured_at:new Date().toISOString(),depends_on:[],payload:{reason},
        ...(terminal?{supersedes_operation_id:terminal.command.operation_id}:{})});
      Alert.alert(`${command.action==='approve'?'Approve':'Reject'} this original proposal online?`,
        `Proposal ${id}. Reason: ${'reason' in command.payload?command.payload.reason:''}. ${prior?'Resume the original retained intent and query its receipt first.':terminal?`New linked correction of ${terminal.command.operation_id}; current revision and original flock dates are revalidated.`:'Approval revalidates original dates, period and the complete dated flock.'}`,
        [{text:'Keep pending',style:'cancel',onPress:()=>{confirming.current=false;setRunning(false);}},{text:'Confirm online review',onPress:()=>{
          setRunning(true);setNotice(null);
          void (async()=>{
            if(!prior)await store.repository.saveDraftAndEnqueue(command,store.hash,'online');
            const receipt=await submitOnlinePoultry({store,api:session.client,authorize:authorizeSync,operationId:command.operation_id,owner:Crypto.randomUUID(),confirmed:true});
            notify();setNotice(`Server review: ${receipt.outcome} (${receipt.code}). Retained original operation ${command.operation_id}.`);
          })().catch(()=>setError('Review did not complete. Its original intent is retained and will not run automatically. Retry online to query that same operation.'))
            .finally(()=>{confirming.current=false;setRunning(false);notify();});
        }}],{cancelable:false});
    }catch{setError('Original review intent could not be loaded. No replacement was created.');confirming.current=false;setRunning(false);}
  }
  return <><Field label="Online proposal review reason" value={reason} onChangeText={setReason} maxLength={255} editable={!running&&!busy}/>
    <Button title="Approve original flock proposal online…" disabled={running||busy} onPress={()=>{void confirm('approve');}}/>
    <Button title="Reject original flock proposal online…" disabled={running||busy} onPress={()=>{void confirm('reject');}}/>
    <ErrorMessage message={error}/><Notice message={notice}/></>;
}
