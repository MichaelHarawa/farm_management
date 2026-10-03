import { createContext,useContext,useEffect,useMemo,useCallback,useState } from 'react';
import { AppState } from 'react-native';
import * as Network from 'expo-network';
import * as Crypto from 'expo-crypto';
import { useSession } from '../auth/session';
import { sha256 } from '../db/native';
import { SyncStore } from './store';
import { SyncEngine } from './engine';
import { nativeSyncPilotEnabled,nativeSyncGateReason } from './pilot-gate';
import { ApiError } from '../auth/client';
import { result as receiptSchema } from './protocol';

interface SyncContextValue { store:SyncStore|null; revision:number; busy:boolean; message:string|null; error:string|null;
  enabled:boolean; notify():void; syncNow():Promise<void>; reviewQuarantined(id:string):Promise<void> }
const Context=createContext<SyncContextValue|null>(null);
export function useSync(){const value=useContext(Context);if(!value)throw new Error('Sync provider required');return value;}
export function SyncProvider({children}:{children:React.ReactNode}){
  const {session,authorizeSync}=useSession();
  const store=useMemo(()=>session?new SyncStore(session.repository,sha256):null,[session]);
  const [revision,setRevision]=useState(0);
  const [result,setResult]=useState<{engine:SyncEngine|null;busy:boolean;message:string|null;error:string|null}|null>(null);
  const engine=useMemo(()=>store&&session?new SyncEngine({store,api:session.client,authorize:authorizeSync,owner:Crypto.randomUUID(),uploadsEnabled:nativeSyncPilotEnabled}):null,[store,session,authorizeSync]);
  const notify=()=>setRevision(v=>v+1);
  const syncNow=useCallback(async(automatic=false)=>{
    if (!nativeSyncPilotEnabled || !engine) {setResult({engine,busy:false,message:nativeSyncGateReason,error:null});return;}
    try {
      if(automatic&&await store?.repository.metadata('native-phase4-manual'))return;
      setResult({engine,busy:true,message:null,error:null});
      const network=await Network.getNetworkStateAsync();
      if (network.isConnected===false || network.isInternetReachable===false) {
        setResult(s=>s?.engine===engine?{engine,busy:false,message:'Offline. Downloaded records and pending work remain on this device.',error:null}:s);return;
      }
      const outcome=await engine.run();
      setResult(s=>s?.engine===engine?{engine,busy:false,error:null,message:outcome.status==='complete'?'Server sync run completed. Check each retained record for acceptance or review.':outcome.status==='busy'?'Another worker owns the sync lease.':'Sync paused at its request budget or retry delay; downloaded work is retained.'}:s);
      setRevision(v=>v+1);
    }catch(e){setResult(s=>s?.engine===engine?{engine,busy:false,message:null,error:e instanceof ApiError&&[401,403].includes(e.status)?'Sign in again to validate access. Original local work is retained.':'Sync did not complete. Pending work and original operation IDs are retained.'}:s);}
  },[engine,store]);
  const reviewQuarantined=useCallback(async(id:string)=>{
    if(!nativeSyncPilotEnabled || !store || !session || !engine)throw new Error('sync_disabled');
    const owner=Crypto.randomUUID();
    if(!await store.repository.acquireLease(owner,Date.now(),60000))throw new Error('sync_busy');
    setResult({engine,busy:true,message:null,error:null});
    try{
      const caps=await authorizeSync();
      let receipt:unknown;
      try{receipt=await session.client.request(`/mobile-sync/operations/${id}`);}
      catch(e){if(!(e instanceof ApiError&&e.status===404&&e.code==='operation_not_found'))throw e;
        await store.allowReviewedRetry(id,caps,true,{owner,now:Date.now()});}
      if(receipt){const parsed=receiptSchema.parse(receipt);if(parsed.operation_id!==id)throw new Error('foreign_receipt');
        await store.reconcile(parsed,new Date().toISOString(),{owner,now:Date.now()});}
      setRevision(v=>v+1);setResult({engine,busy:false,message:'Original server outcome checked. Original ID, payload and hash are retained; review the resulting status before sync.',error:null});
    }catch(e){setResult({engine,busy:false,message:null,error:'Review did not complete. Download current scope and validate access; original isolated evidence remains.'});throw e;}
    finally{try{await store.repository.releaseLease(owner);}catch{/* Retain original evidence if session closed. */}}
  },[store,session,engine,authorizeSync]);
  useEffect(()=>{
    if(!engine)return;
    if(nativeSyncPilotEnabled)void Promise.resolve().then(()=>syncNow(true));
    const app=AppState.addEventListener('change',state=>{if(state==='active'&&nativeSyncPilotEnabled)void syncNow(true);else if(state!=='active')engine.cancel();});
    const network=Network.addNetworkStateListener(state=>{if(nativeSyncPilotEnabled&&state.isConnected&&AppState.currentState==='active')void syncNow(true);});
    return()=>{engine.cancel();app.remove();network.remove();};
  },[engine,syncNow]);
  const visible=result?.engine===engine?result:null;
  return <Context.Provider value={{store,revision,busy:visible?.busy??false,message:visible?.message??null,error:visible?.error??null,enabled:nativeSyncPilotEnabled,notify,syncNow,reviewQuarantined}}>{children}</Context.Provider>;
}
