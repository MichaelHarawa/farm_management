import { useRef,useState } from 'react';
import { Alert } from 'react-native';
import * as Crypto from 'expo-crypto';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
import { poultryCommand } from '../poultry/commands';
import { submitOnlinePoultry } from '../poultry/online';
import { Body,Button,ErrorMessage,Field,Notice } from './ui';

export function FeedMaintenance({batch,revision}:{batch:string;revision:string}) {
  const {session,authorizeSync}=useSession(),{store,busy,enabled,notify}=useSync();
  const locked=useRef(false),[running,setRunning]=useState(false),[reason,setReason]=useState(''),[error,setError]=useState<string|null>(null),[notice,setNotice]=useState<string|null>(null);
  if(!enabled||!session?.capabilities.commands['poultry.batch.recalculate_feed']?.available)return null;
  async function confirm() {
    if(!store||!session||busy||locked.current)return;
    locked.current=true;setRunning(true);setError(null);
    try {
      const original=await store.originalOnlineIntent(batch);
      const terminal=original?null:await store.terminalOnlineIntent(batch,'recalculate_feed');
      if(!original&&!reason.trim()){setError('Enter a recalculation reason.');locked.current=false;setRunning(false);return;}
      const command=original?.command??poultryCommand.parse({operation_id:Crypto.randomUUID(),entity_uuid:batch,entity_type:'poultry.batch',action:'recalculate_feed',
        payload_version:1,base_version:revision,captured_at:new Date().toISOString(),depends_on:[],payload:{batch_uuid:batch,reason},
        ...(terminal?{supersedes_operation_id:terminal.command.operation_id}:{})});
      Alert.alert('Recalculate original feed populations online?',`Operation ${command.operation_id}. ${terminal?`Linked correction of ${terminal.command.operation_id}. `:''}Current access, revision and dated evidence are rechecked. No stock issue or financial cost is created.`,
        [{text:'Keep unchanged',style:'cancel',onPress:()=>{locked.current=false;setRunning(false);}},{text:'Confirm online recalculation',onPress:()=>{
          void (async()=>{if(!original)await store.repository.saveDraftAndEnqueue(command,store.hash,'online');
            const receipt=await submitOnlinePoultry({store,api:session.client,authorize:authorizeSync,operationId:command.operation_id,owner:Crypto.randomUUID(),confirmed:true});
            setNotice(`Original server outcome: ${receipt.outcome} (${receipt.code}).`);
          })().catch(()=>setError('Recalculation did not complete. Original intent remains and will not execute automatically; retry only with online confirmation.'))
            .finally(()=>{locked.current=false;setRunning(false);notify();});
        }}],{cancelable:false});
    }catch{setError('Original intent could not be checked. Nothing was replaced.');locked.current=false;setRunning(false);}
  }
  return <><Body>Supervisor maintenance; online-only and replay-protected.</Body>
    <Field label="Online feed recalculation reason" value={reason} onChangeText={setReason} maxLength={255} editable={!busy&&!running}/>
    <Button title="Review / recalculate feed populations online…" disabled={busy||running} onPress={()=>{void confirm();}}/>
    <ErrorMessage message={error}/><Notice message={notice}/></>;
}
