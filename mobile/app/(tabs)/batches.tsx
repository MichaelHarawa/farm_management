import { useEffect, useState } from 'react';
import { useSession } from '../../src/auth/session';
import { Body, Button, Card, ErrorMessage, Field, Loading, Screen } from '../../src/components/ui';
import { router } from 'expo-router';
import { useSync } from '../../src/sync/context';
export default function Batches() {
  const { session } = useSession();
  const {revision}=useSync();
  const [cursor, setCursor] = useState('');
  const [search,setSearch]=useState(''),[status,setStatus]=useState('');
  const [page, setPage] = useState<{ session: typeof session; cursor: string;search:string;status:string; rows: { entity_uuid: string; payload_json: string;local_only?:number }[]; error: string | null } | null>(null);
  const busy = page?.cursor !== cursor || page?.session !== session || page?.search!==search || page?.status!==status;
  const rows = busy ? [] : page?.rows ?? [];
  const error = busy ? null : page?.error ?? null;
  useEffect(() => {
    let active = true;
    (session?.capabilities.projection_version===2?session.repository.poultryBatches(cursor,search,status):session?.repository.batches(cursor))
      ?.then((data) => { if (active) setPage({ session, cursor,search,status, rows: data, error: null }); }).catch(() => { if (active) setPage({ session, cursor,search,status, rows: [], error: 'Cannot read the local batch page. Records were not reset.' }); });
    return () => { active = false; };
  }, [session, cursor,revision,search,status]);
  return <Screen title="Downloaded batches"><Body>Local page • 25 records at most • Not a whole-farm report</Body><ErrorMessage message={error} />
    {session?.capabilities.projection_version===2&&<Card title="Find local batches">
      <Field label="Search downloaded reference or UUID" value={search} maxLength={120} onChangeText={value=>{setSearch(value);setCursor('');}}/>
      {['','booked','delivered','planned','active','mature','selling','closed'].map(value=><Button key={value} title={value||'All local statuses'} selected={status===value}
        onPress={()=>{setStatus(value);setCursor('');}}/>)}
      {session.capabilities.commands['poultry.batch.book']?.available&&<Button title="Book chicks offline" onPress={()=>router.push({pathname:'/(tabs)/record',params:{workflow:'book'}})}/>}
    </Card>}
    {busy ? <Loading /> : rows.length ? rows.map((row) => {
      const payload = JSON.parse(row.payload_json) as { batch_id?: string; status?: string };
      return <Card key={row.entity_uuid} title={payload.batch_id ?? row.entity_uuid}><Body>{row.local_only?'Provisional booking; official reference pending':payload.status ?? 'Status unavailable'}</Body>
        <Button title={`Open ${payload.batch_id ?? 'batch'}`} onPress={()=>router.push(`/batch/${row.entity_uuid}`)} /></Card>;
    }) : <Card title="No local batches"><Body>No activated batch download is available. This does not mean the farm has no batches. Check the Sync tab.</Body></Card>}
    <Button disabled={busy || rows.length < 25} title="Next local page" onPress={() => setCursor(rows[rows.length - 1]!.entity_uuid)} />
    <Button disabled={busy || !cursor} title="First local page" onPress={() => setCursor('')} />
  </Screen>;
}
