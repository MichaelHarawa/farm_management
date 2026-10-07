import {useMemo,useRef,useState} from 'react';
import {useSession} from '../auth/session';
import {useSync} from '../sync/context';
import {phase5Pilot} from '../build-mode.native';
import {NativePoultryProbe} from '../test/native-poultry';
import {Body,Button,Card,ErrorMessage} from './ui';

export function NativePoultryCheck(){
  const {session,settings,busy}=useSession();const {store,busy:syncing}=useSync();
  const probe=useMemo(()=>session&&store?new NativePoultryProbe(settings,session,store):null,[session,store,settings]);
  const running=useRef(false);const [checking,setChecking]=useState(false),[result,setResult]=useState<string|null>(null),[error,setError]=useState<string|null>(null);
  if(!phase5Pilot||!probe)return null;
  async function run(work:()=>Promise<string>){
    if(running.current||busy||syncing)return;running.current=true;setChecking(true);setError(null);setResult(null);
    try{setResult(await work());}catch{setError('Native poultry check not passed. Require the original synthetic deployment/download and preserve all existing work. No replacement record or upload is created by this check.');}
    finally{running.current=false;setChecking(false);}
  }
  const disabled=busy||syncing||checking;
  return <Card title="Phase5 owned native recovery checks">
    <Body>Only this separate synthetic deployment and the current original account. Capture work through the ordinary forms while offline. These checks never generate events, approve proposals or upload records.</Body>
    <Button disabled={disabled} title="Hold automatic Phase5 sync" onPress={()=>{void run(()=>probe.manual(true));}}/>
    <Button disabled={disabled} title="Checkpoint existing offline Phase5 operations" onPress={()=>{void run(()=>probe.checkpoint());}}/>
    <Button disabled={disabled} title="Verify exact retained Phase5 operations" onPress={()=>{void run(()=>probe.verify());}}/>
    <Button disabled={disabled} title="Restore automatic Phase5 sync" onPress={()=>{void run(()=>probe.manual(false));}}/>
    <Body>{result??'Not run'}</Body><ErrorMessage message={error}/>
  </Card>;
}
