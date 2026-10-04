import { useRef,useState } from 'react';
import { Alert } from 'react-native';
import * as Crypto from 'expo-crypto';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
import { submitOnlinePoultry } from '../poultry/online';
import { Button,ErrorMessage,Notice } from './ui';

export function OnlineRecovery({id}:{id:string}) {
  const {session,authorizeSync}=useSession(),{store,busy,enabled,notify}=useSync();
  const locked=useRef(false),[running,setRunning]=useState(false),[error,setError]=useState<string|null>(null),[notice,setNotice]=useState<string|null>(null);
  async function review() {
    if(!store||!session||busy||locked.current)return;
    locked.current=true;setRunning(true);setError(null);
    try {
      const original=await store.operationDetails(id);
      Alert.alert('Recover original online intent?',`${original.command.action} • ${id}. This queries the original receipt first. Only if absent, a fresh authorized confirmation permits that same immutable action. It never creates a replacement ID.`,
        [{text:'Keep retained',style:'cancel',onPress:()=>{locked.current=false;setRunning(false);}},{text:'Confirm original action online',onPress:()=>{
          void submitOnlinePoultry({store,api:session.client,authorize:authorizeSync,operationId:id,owner:Crypto.randomUUID(),confirmed:true})
            .then(result=>setNotice(`Original server outcome: ${result.outcome} (${result.code}).`))
            .catch(()=>setError('Online recovery did not complete. Original evidence remains. Isolated work requires the separate current-scope review first.'))
            .finally(()=>{locked.current=false;setRunning(false);notify();});
        }}],{cancelable:false});
    }catch{setError('Original online intent unavailable. No replacement was created.');locked.current=false;setRunning(false);}
  }
  return <><Button title="Recover / confirm original online action…" disabled={busy||running||!enabled} onPress={()=>{void review();}}/>
    <ErrorMessage message={error}/><Notice message={notice}/></>;
}
