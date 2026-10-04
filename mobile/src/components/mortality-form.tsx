import { useEffect,useState } from 'react';
import { Alert } from 'react-native';
import { useForm,Controller } from 'react-hook-form';
import { router } from 'expo-router';
import * as Crypto from 'expo-crypto';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
import { mortalityCommand,uuid,type MortalityCommand } from '../protocol';
import { batchPayload } from '../sync/protocol';
import { Body,Button,Card,ErrorMessage,Field,Notice,Screen } from './ui';
import { farmEventFields,farmEventUtc,farmTimezone } from './event-time';
import { nativeSyncGateReason } from '../sync/pilot-gate';

const defaults=()=>({batch_uuid:'',...farmEventFields(new Date().toISOString()),quantity:'',suspected_cause:'Unknown',description:'',action_taken:'',reported_by_name:''});
type Values=ReturnType<typeof defaults>;
export function MortalityForm({correctionId}:{correctionId?:string}){
  const {session}=useSession();const {store,enabled,notify,revision}=useSync();
  const [local,setLocal]=useState<{store:typeof store;after:string;revision:number;downloaded:boolean;rows:{entity_uuid:string;payload_json:string}[]}|null>(null);
  const [after,setAfter]=useState('');const [original,setOriginal]=useState<MortalityCommand|null>(null);
  const [busy,setBusy]=useState(false);const [error,setError]=useState<string|null>(null);const [saved,setSaved]=useState<string|null>(null);
  const [errorAttempt,setErrorAttempt]=useState(0);
  const {control,handleSubmit,reset,setValue}=useForm({defaultValues:defaults()});
  useEffect(()=>{let active=true;if(!store)return;
    Promise.all([store.coverage(),store.repository.batches(after)]).then(([coverage,rows])=>{if(active)setLocal({store,after,revision,downloaded:!!coverage,rows});})
      .catch(()=>{if(active)setError('Cannot read downloaded batches. Existing work was not reset.');});return()=>{active=false;};},[store,after,revision]);
  useEffect(()=>{let active=true;if(!correctionId||!store)return;
    if(!uuid.safeParse(correctionId).success)return;
    store.correction(correctionId).then(op=>{if(active){setOriginal(op);reset({batch_uuid:op.payload.batch_uuid,...farmEventFields(op.payload.mortality_date),
      quantity:String(op.payload.quantity_dead),suspected_cause:op.payload.suspected_cause,description:op.payload.description,action_taken:op.payload.action_taken,reported_by_name:op.payload.reported_by_name});}})
      .catch(()=>{if(active)setError('A correction needs a known terminal receipt. Unknown or confirmed commands cannot be corrected here.');});return()=>{active=false;};},[store,correctionId,reset]);
  const view=local?.store===store&&local.after===after&&local.revision===revision?local:null;
  const permitted=enabled&&!!view?.downloaded&&!!session?.capabilities.commands['poultry.mortality.record']?.available&&(!correctionId||!!original);
  async function save(values:Values){
    if(!permitted||!store||!session)return;
    setBusy(true);setError(null);setSaved(null);
    try {
      if(!/^\d+$/.test(values.quantity))throw new Error('form_invalid');
      const op:MortalityCommand=mortalityCommand.parse({operation_id:Crypto.randomUUID(),entity_uuid:Crypto.randomUUID(),entity_type:'poultry.mortality',
        action:'record',payload_version:1,base_version:null,captured_at:new Date().toISOString(),depends_on:original?.depends_on??[],
        ...(correctionId?{supersedes_operation_id:correctionId}:{}),payload:{batch_uuid:values.batch_uuid,mortality_date:farmEventUtc(values.event_day,values.event_time),
          quantity_dead:Number(values.quantity),suspected_cause:values.suspected_cause,description:values.description,action_taken:values.action_taken,reported_by_name:values.reported_by_name}});
      const batch=await store.batch(op.payload.batch_uuid);
      if(!batch||!['active','mature','selling'].includes(batch.payload.status))throw new Error('batch_unavailable');
      if(correctionId)await store.correctTerminal(correctionId,op);else await store.repository.saveDraftAndEnqueue(op,store.hash);
      notify();setSaved(`Saved on this device, awaiting Django validation. New operation ${op.operation_id}.`);
      if(!correctionId)reset(defaults());
    }catch{setErrorAttempt(value=>value+1);setError('Could not save. Choose a downloaded production batch, positive whole-bird quantity, valid farm date/time and all evidence fields. A retained correction must be reviewed in Sync; the original record was not edited.');}
    finally{setBusy(false);}
  }
  return <Screen title={correctionId?'Correct rejected mortality':'Record mortality'}>
    {correctionId&&<Card title="New linked correction"><Body>Original operation: {correctionId}. Its payload, hash and failure receipt remain unchanged. This creates a different operation and event UUID; original dependent records stay blocked until reviewed.</Body>
      <Button title="Return to Sync without changing evidence" disabled={busy} onPress={()=>router.replace('/(tabs)/sync')}/></Card>}
    <Card title="Choose a downloaded production batch">
      {(view?.downloaded?view.rows:[]).map(row=>{const batch=batchPayload.parse(JSON.parse(row.payload_json));return <Button key={row.entity_uuid} title={`${batch.batch_id} • ${batch.status} • ${batch.remaining_birds} confirmed birds`}
        disabled={!permitted||busy||!['active','mature','selling'].includes(batch.status)} onPress={()=>setValue('batch_uuid',row.entity_uuid)}/>;})}
      {!view?.rows.length&&<Body>No batch on this page. Downloaded coverage is required; missing data is not a zero flock.</Body>}
      <Button title="Next 25 downloaded batches" disabled={!view||view.rows.length<25||busy} onPress={()=>setAfter(view!.rows[view!.rows.length-1]!.entity_uuid)}/>
      <Button title="First downloaded batches" disabled={!after||busy} onPress={()=>setAfter('')}/>
    </Card>
    <Card title="Offline operational evidence"><Body>Enter the actual farm date and time in {farmTimezone}, not the phone’s timezone. It is stored as UTC separately from device capture time. Saving does not confirm a farm event.</Body>
      {!enabled&&<Body>{nativeSyncGateReason}</Body>}{!view?.downloaded&&<Body>An authenticated batch download is required before offline capture.</Body>}
      <Controller control={control} name="batch_uuid" render={({field})=><Field label="Selected downloaded batch UUID" value={field.value} editable={false}/>}/>
      <Controller control={control} name="event_day" render={({field})=><Field label="Farm event date (YYYY-MM-DD)" value={field.value} onChangeText={field.onChange} autoCapitalize="none" editable={permitted&&!busy}/>}/>
      <Controller control={control} name="event_time" render={({field})=><Field label="Farm event time (24-hour HH:mm:ss)" value={field.value} onChangeText={field.onChange} autoCapitalize="none" editable={permitted&&!busy}/>}/>
      <Controller control={control} name="quantity" render={({field})=><Field label="Dead birds (whole birds)" value={field.value} onChangeText={field.onChange} keyboardType="number-pad" editable={permitted&&!busy}/>}/>
      {(['suspected_cause','description','action_taken','reported_by_name'] as const).map(name=><Controller key={name} control={control} name={name} render={({field})=><Field
        label={{suspected_cause:'Suspected cause',description:'Description',action_taken:'Action taken',reported_by_name:'Observed reporter'}[name]} value={field.value} onChangeText={field.onChange} editable={permitted&&!busy} maxLength={name==='description'||name==='action_taken'?4000:200}/>}/>)}
      <ErrorMessage message={error} announcementKey={errorAttempt}/><Notice message={saved}/>
      <Button title={busy?'Saving locally…':correctionId?'Save new linked correction':'Save mortality on this device'} disabled={!permitted||busy||!!(correctionId&&saved)} onPress={()=>{
        if(correctionId)Alert.alert('Save a new correction?','The original rejection remains. The new operation will require its own Django validation.',[{text:'Review form',style:'cancel'},{text:'Save correction',onPress:()=>{void handleSubmit(save)();}}]);else void handleSubmit(save)();
      }}/>
      {!correctionId&&<Button title="Clear unsubmitted form" disabled={busy} onPress={()=>Alert.alert('Clear this form?','This only clears fields not yet saved. Retained operations are not deleted.',[{text:'Keep form',style:'cancel'},{text:'Clear form',onPress:()=>reset(defaults())}])}/>}
    </Card><Card title="Other workflows"><Body>Feed, treatment, sales and finance remain later phases. No financial posting is enabled.</Body></Card>
  </Screen>;
}
