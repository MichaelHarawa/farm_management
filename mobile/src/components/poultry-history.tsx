import { useEffect, useState } from 'react';
import { useSync } from '../sync/context';
import type { Entity } from '../sync/protocol';
import { Body, Button, Card, ErrorMessage } from './ui';
import { AdjustmentReview } from './adjustment-review';
const types: {type:Entity['entity_type'];label:string}[] = [
  {type:'poultry.mortality',label:'Mortality'},{type:'poultry.feed_usage',label:'Feed'},
  {type:'poultry.treatment',label:'Treatment / vaccination'},{type:'poultry.weight_sample',label:'Weights'},
  {type:'poultry.flock_adjustment',label:'Approved flock adjustments'},{type:'poultry.adjustment_proposal',label:'Adjustment proposals'},
];
export function PoultryHistory({batch}:{batch:string}) {
  const {store,revision}=useSync(); const [type,setType]=useState<Entity['entity_type']>('poultry.mortality'),[after,setAfter]=useState('');
  const [page,setPage]=useState<{key:string;rows:{entity_uuid:string;revision:string;payload_json:string}[]}|null>(null),[error,setError]=useState<string|null>(null);
  const key=`${store?.repository.identity.actorId}:${batch}:${type}:${after}:${revision}`;
  useEffect(()=>{let active=true;if(!store)return;
    store.history(batch,type,after).then(rows=>{if(active){setPage({key,rows});setError(null);}}).catch(()=>{if(active)setError('Local history is unavailable; no records were cleared.');});
    return()=>{active=false;};},[store,batch,type,after,key]);
  const rows=page?.key===key?page.rows:[];
  return <Card title="Downloaded operational history"><Body>25 records per stable UUID page. Original event dates are shown; this page is not a whole-farm total.</Body>
    {types.map(item=><Button key={item.type} title={item.label} selected={type===item.type} onPress={()=>{setType(item.type);setAfter('');}}/>)}
    <ErrorMessage message={error}/>
    {!rows.length&&<Body>No records on this downloaded page. Check coverage; missing or incomplete history must not be read as zero activity.</Body>}
    {rows.map(row=>{const payload=JSON.parse(row.payload_json);return <Card key={row.entity_uuid} title={`${payload.server_id} · ${payload.status??types.find(v=>v.type===type)!.label}`}>
      {Object.entries(payload).filter(([name])=>!['server_id','batch_uuid','created_at','updated_at'].includes(name))
        .map(([name,value])=><Body key={name}>{name.replaceAll('_',' ')}: {String(value??'Not available')}</Body>)}
      <Body>Server revision {row.revision} · UUID {row.entity_uuid}</Body>
      {type==='poultry.adjustment_proposal'&&<AdjustmentReview id={row.entity_uuid} revision={row.revision} status={payload.status}/>}
    </Card>;})}
    <Button title="Next 25 history records" disabled={rows.length<25} onPress={()=>setAfter(rows[rows.length-1]!.entity_uuid)}/>
    <Button title="First history page" disabled={!after} onPress={()=>setAfter('')}/>
  </Card>;
}
