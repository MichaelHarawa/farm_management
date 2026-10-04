import { useMemo,useState } from 'react';
import { useSession } from '../src/auth/session';
import { useSync } from '../src/sync/context';
import { phase4Pilot } from '../src/build-mode.native';
import { NativeSyncProbe } from '../src/test/native-sync';
import { Body,Button,Card,ErrorMessage,Notice,Screen } from '../src/components/ui';
export default function NativeSyncCheck() {
  const {session,settings,authorizeSync}=useSession();const {store,busy:syncBusy,notify,syncNow}=useSync();
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState<string|null>(null);const [error,setError]=useState<string|null>(null);
  const probe=useMemo(()=>phase4Pilot&&store&&session?new NativeSyncProbe(settings,session.user.username,store,session.client,authorizeSync):null,[store,session,settings,authorizeSync]);
  async function run(work:()=>Promise<string|void>) {
    setBusy(true);setError(null);setMessage(null);
    try {const result=await work();if(result)setMessage(result);notify();}
    catch(e){setError(`Native check did not pass: ${e instanceof Error&&/^[a-z0-9_]+$/.test(e.message)?e.message:'check_failed'}. Original records were not reset.`);}
    finally{setBusy(false);}
  }
  const disabled=!probe||busy||syncBusy;
  return <Screen title="Phase4 native acceptance"><Card title="Separate synthetic deployment only">
    <Body>Only this Phase4 Android package, test worker, port7073 and downloaded SYNTHETIC-PHASE4 batch. These are real local commands and Django effects, never farm financial records. PIN prompts remain private. Force-stop only when PAUSED is visible.</Body>
    <ErrorMessage message={error}/><Notice message={message}/>
    <Button title="Hold automatic sync for death checks" disabled={disabled} onPress={()=>{void run(()=>probe!.manual(true));}}/>
    <Button title="Capture three synthetic mortality entries offline" disabled={disabled} onPress={()=>{void run(()=>probe!.captureThree());}}/>
    <Button title="Verify exact original Phase4 drafts" disabled={disabled} onPress={()=>{void run(()=>probe!.verifyDrafts());}}/>
    <Button title="Checkpoint existing form commands without replacement" disabled={disabled} onPress={()=>{void run(()=>probe!.checkpointCurrentCommands());}}/>
    <Button title="Inspect native sync state" disabled={disabled} onPress={()=>{void run(()=>probe!.summary());}}/>
    <Button title="Pause inside real local save" disabled={disabled} onPress={()=>{void run(()=>probe!.pauseSave(setMessage));}}/>
    <Button title="Pause before push HTTP" disabled={disabled} onPress={()=>{void run(()=>probe!.pausePush(false,setMessage));}}/>
    <Button title="Pause after real committed push response" disabled={disabled} onPress={()=>{void run(()=>probe!.pausePush(true,setMessage));}}/>
    <Button title="Pause inside real pull-page transaction" disabled={disabled} onPress={()=>{void run(()=>probe!.pausePull(setMessage));}}/>
    <Button title="Pause after committed incomplete fragment" disabled={disabled} onPress={()=>{void run(()=>probe!.pauseCommittedFragment(setMessage));}}/>
    <Button title="Verify retained death checkpoint" disabled={disabled} onPress={()=>{void run(()=>probe!.verifyInterruption());}}/>
    <Button title="Add one synthetic mortality offline" disabled={disabled} onPress={()=>{void run(()=>probe!.addOne());}}/>
    <Button title="Add over-flock evidence for rejection review" disabled={disabled} onPress={()=>{void run(()=>probe!.addOne(1000));}}/>
    <Button title="Capture unsent parent and dependent offline" disabled={disabled} onPress={()=>{void run(()=>probe!.captureDependencyPair());}}/>
    <Button title="Verify explicit discard and original dependency" disabled={disabled} onPress={()=>{void run(()=>probe!.verifyDiscardedDependency());}}/>
    <Button title="Download only without uploads" disabled={disabled} onPress={()=>{void run(()=>probe!.downloadOnly());}}/>
    <Button title="Start real cursor recovery at one-page budget" disabled={disabled} onPress={()=>{void run(()=>probe!.startCursorRecovery());}}/>
    <Button title="Complete real expired snapshot recovery" disabled={disabled} onPress={()=>{void run(()=>probe!.completeExpiredSnapshot());}}/>
    <Button title="Verify real hidden-page continuation" disabled={disabled} onPress={()=>{void run(()=>probe!.hiddenContinuation());}}/>
    <Button title="Download overlapping current and batch packs" disabled={disabled} onPress={()=>{void run(()=>probe!.downloadOnly(true));}}/>
    <Button title="Verify native competing sync coordinators" disabled={disabled} onPress={()=>{void run(()=>probe!.coordinatorOverlap());}}/>
    <Button title="Replay actual original receipt against newer data" disabled={disabled} onPress={()=>{void run(()=>probe!.replayOldReceipt());}}/>
    <Button title="Run real manual sync" disabled={disabled} onPress={()=>{void run(syncNow);}}/>
    <Button title="Restore automatic sync" disabled={disabled} onPress={()=>{void run(()=>probe!.manual(false));}}/>
  </Card></Screen>;
}
