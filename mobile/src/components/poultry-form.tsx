import { useEffect, useRef, useState } from 'react';
import * as Crypto from 'expo-crypto';
import { Alert } from 'react-native';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
import { buildFormCommand, formDefaults, formFromCommand, workflows, type Workflow } from '../poultry/forms';
import { Body, Button, Card, ErrorMessage, Field, Loading, Notice, Screen } from './ui';
import { FarmDateInput } from './farm-date-input';

export function PoultryForm({workflow,batchId,correctionId}:{workflow:Workflow;batchId?:string;correctionId?:string}) {
  const {session}=useSession(); const {store,enabled,revision,notify}=useSync();
  const key=correctionId?`correction:${correctionId}`:`poultry:${workflow}:${batchId??'new'}`;
  const [values,setValues]=useState<Record<string,string>>(()=>({...formDefaults(workflow),batch_uuid:batchId??''}));
  const [ready,setReady]=useState(false),[saving,setSaving]=useState(false),[after,setAfter]=useState('');
  const [rows,setRows]=useState<{entity_uuid:string;payload_json:string;local_only:number}[]>([]);
  const [errors,setErrors]=useState<Record<string,string>>({}),[notice,setNotice]=useState<string|null>(null),[attempt,setAttempt]=useState(0);
  const writes=useRef<Promise<void>>(Promise.resolve());
  const [corrected,setCorrected]=useState(false);
  const definition=workflows[workflow];
  const permitted=enabled&&session?.capabilities.projection_version===2&&session.capabilities.commands[`${definition.entity}.${definition.action}`]?.available===true;
  useEffect(()=>{let active=true;if(!store)return;
    Promise.all([store.repository.form<Record<string,string>>(key),correctionId?store.queuedCorrection(correctionId):Promise.resolve(null)])
      .then(([saved,original])=>{if(active){setValues(saved??(original?formFromCommand(workflow,original):{...formDefaults(workflow),batch_uuid:batchId??''}));setReady(true);}})
      .catch(()=>{if(active)setErrors({form:'Draft recovery failed. Do not clear the original store.'});});
    return()=>{active=false;};},[store,key,workflow,batchId,correctionId]);
  useEffect(()=>{let active=true;if(!store)return;
    store.repository.poultryBatches(after).then(page=>{if(active)setRows(page);}).catch(()=>{if(active)setErrors({form:'Could not read the local batch page.'});});
    return()=>{active=false;};},[store,after,revision]);
  function change(next:Record<string,string>) {
    if(!store||!ready||saving)return;
    setValues(next);setNotice('Saving unsubmitted form on this device…');
    writes.current=writes.current.catch(()=>{}).then(()=>store.repository.saveForm(key,next));
    void writes.current.then(()=>setNotice('Unsubmitted form saved locally; no event is confirmed.'))
      .catch(()=>setErrors({form:'Form changes could not be saved. Keep this screen open and retry; prior work is retained.'}));
  }
  async function save() {
    if(!store||!session||!permitted||!ready||saving||corrected)return;
    setSaving(true);setErrors({});setNotice(null);setAttempt(v=>v+1);
    try {
      await writes.current;
      const selectedBatch=values.batch_uuid??'';
      const dependency=workflow==='book'?null:await store.repository.batchDependency(selectedBatch);
      const confirmed=workflow==='book'?null:await store.batch(selectedBatch);
      const status=dependency?.action==='confirm_delivery'?'active':dependency?.action==='mark_delivered'?'delivered':confirmed?.payload.status??(dependency?.action==='book'?'booked':null);
      if(workflow==='mark_delivered'&&status!=='booked'||workflow==='confirm_delivery'&&status!=='delivered') {
        setErrors({batch_uuid:'Complete the preceding booked → delivered step first. No operation was saved.'});return;
      }
      if(!['book','mark_delivered','confirm_delivery'].includes(workflow)&&!['active','mature','selling'].includes(status??'')) {
        setErrors({batch_uuid:'Confirm actual arrival before recording production. A pending arrival remains a required parent dependency.'});return;
      }
      const lifecycle=workflow==='mark_delivered'||workflow==='confirm_delivery';
      const built=buildFormCommand(workflow,values,session.capabilities,{operation_id:Crypto.randomUUID(),entity_uuid:lifecycle?selectedBatch:Crypto.randomUUID(),
        captured_at:new Date().toISOString(),depends_on:dependency?[dependency.operation_id]:[],base_version:lifecycle&&!dependency?confirmed?.revision??null:null,
        ...(correctionId?{supersedes_operation_id:correctionId}:{})});
      if(!built.command){setErrors(built.errors);return;}
      await store.repository.saveDraftAndEnqueue(built.command,store.hash,'queued',key);
      if(correctionId)setCorrected(true);
      setValues({...formDefaults(workflow),batch_uuid:batchId??''});notify();
      setNotice(`${definition.title} saved on this device. Operation ${built.command.operation_id}. Awaiting Django validation; no confirmed flock or financial total was changed.`);
    } catch {setErrors({form:'Could not save. Original form/work is retained. Check the downloaded parent, preceding delivery steps and field values.'});}
    finally{setSaving(false);}
  }
  async function clearForm() {
    if(!store||saving)return;
    setSaving(true);
    try {await writes.current;await store.repository.clearForm(key);
      setValues({...formDefaults(workflow),batch_uuid:batchId??''});setNotice('Unsubmitted form cleared. Retained operations remain.');
    }catch{setErrors({form:'Could not clear the unsubmitted form. The prior draft remains recoverable.'});}
    finally{setSaving(false);}
  }
  return <Screen title={definition.title}>
    {!ready?<Loading label="Recovering this user’s encrypted form…"/>:<>
      <Card title="Local-first farm evidence"><Body>Farm dates use Africa/Blantyre. Capture time is separate. Saving does not confirm an event; Sync shows individual Django outcomes.</Body>
        {correctionId&&<Body>Correction of terminal operation {correctionId}. The original payload, hash and receipt stay unchanged; dependent children are not silently reparented. Review the original dates and field feedback before saving a new linked operation.</Body>}
        {!permitted&&<Body>This workflow requires the separate Phase 5 test build, current permission and downloaded reference data.</Body>}
        {workflow==='proposal'&&<Body>Evidence only: this proposal changes no bird count. An authorized online review is required.</Body>}
        {(workflow==='feed'||workflow==='treatment')&&<Body>No stock issue, supplier payment or second batch cost is created here. Stock-backed capture requires Phase 6.</Body>}
      </Card>
      {workflow!=='book'&&<Card title="Choose a local batch">
        <Body>Selected batch: {values.batch_uuid||'Not selected'}. Local page only; not a whole-farm list.</Body>
        {rows.map(row=>{const batch=JSON.parse(row.payload_json);return <Button key={row.entity_uuid}
          title={`${batch.batch_id} • ${row.local_only?'provisional booking':batch.status}`} selected={values.batch_uuid===row.entity_uuid}
          disabled={!permitted||saving} onPress={()=>change({...values,batch_uuid:row.entity_uuid})}/>;})}
        {!rows.length&&<Body>No local batch on this page. Missing download does not mean an empty farm.</Body>}
        <ErrorMessage message={errors.batch_uuid??null} announcementKey={attempt}/>
        <Button title="Next 25 local batches" disabled={rows.length<25||saving} onPress={()=>setAfter(rows[rows.length-1]!.entity_uuid)}/>
        <Button title="First local batches" disabled={!after||saving} onPress={()=>setAfter('')}/>
      </Card>}
      <Card title="Record actual observations">
        {definition.fields.map(field=><ReactField key={field.name} field={field} values={values} disabled={!permitted||saving}
          choices={session?.capabilities.lookups?.choices[field.choices??'']??[]} onChange={change} error={errors[field.name]??null} attempt={attempt}/>)}
        <ErrorMessage message={errors.form??null} announcementKey={attempt}/><Notice message={notice}/>
        <Button title={saving?'Saving locally…':`Save ${definition.title.toLowerCase()} on this device`} disabled={!permitted||saving||!ready||corrected}
          onPress={()=>{if(correctionId)Alert.alert('Save new linked correction?','Original evidence is retained. This new operation requires its own Django validation.',
            [{text:'Review fields',style:'cancel'},{text:'Save correction',onPress:()=>{void save();}}]);else void save();}}/>
        <Button title="Clear this unsubmitted form…" disabled={saving} onPress={()=>Alert.alert('Clear unsubmitted fields?',
          'Saved operations and their evidence are not deleted.',[{text:'Keep form',style:'cancel'},{text:'Clear form',onPress:()=>{
            void clearForm();
          }}])}/>
      </Card>
    </>}
  </Screen>;
}

function ReactField({field,values,choices,onChange,error,disabled,attempt}:{field:typeof workflows[Workflow]['fields'][number];
  values:Record<string,string>;choices:{value:string;label:string}[];onChange(next:Record<string,string>):void;error:string|null;disabled:boolean;attempt:number}) {
  const value=values[field.name]??'';
  return <>
    {field.kind==='instant'||field.kind==='date'?<FarmDateInput label={field.label} day={field.kind==='date'?value:values[`${field.name}:day`]!}
      time={field.kind==='date'?'12:00:00':values[`${field.name}:time`]!} disabled={disabled} dateOnly={field.kind==='date'} onChange={(day,time)=>onChange(
        field.kind==='date'?{...values,[field.name]:day}:{...values,[`${field.name}:day`]:day,[`${field.name}:time`]:time})}/>:
      field.kind==='choice'?<><Body>{field.label}: {choices.find(c=>c.value===value)?.label??'Not selected'}</Body>
        {choices.map(choice=><Button key={choice.value} title={`${field.label}: ${choice.label}`} selected={value===choice.value} disabled={disabled}
          onPress={()=>onChange({...values,[field.name]:choice.value})}/>)}
        {field.optional&&<Button title={`Clear ${field.label}`} disabled={disabled} onPress={()=>onChange({...values,[field.name]:''})}/>}
      </>:<Field label={field.label} value={value} editable={!disabled} maxLength={field.max??4000}
        keyboardType={field.kind==='positive'?'number-pad':field.kind==='signed'?'numbers-and-punctuation':'default'}
        onChangeText={text=>onChange({...values,[field.name]:text})}/>}
    <ErrorMessage message={error} announcementKey={attempt}/>
  </>;
}
