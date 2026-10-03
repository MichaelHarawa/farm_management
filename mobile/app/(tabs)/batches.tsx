import { useEffect, useState } from 'react';
import { useSession } from '../../src/auth/session';
import { Body, Button, Card, ErrorMessage, Loading, Screen } from '../../src/components/ui';
import { router } from 'expo-router';
import { useSync } from '../../src/sync/context';
export default function Batches() {
  const { session } = useSession();
  const {revision}=useSync();
  const [cursor, setCursor] = useState('');
  const [page, setPage] = useState<{ session: typeof session; cursor: string; rows: { entity_uuid: string; payload_json: string }[]; error: string | null } | null>(null);
  const busy = page?.cursor !== cursor || page?.session !== session;
  const rows = busy ? [] : page?.rows ?? [];
  const error = busy ? null : page?.error ?? null;
  useEffect(() => {
    let active = true;
    session?.repository.batches(cursor).then((data) => { if (active) setPage({ session, cursor, rows: data, error: null }); }).catch(() => { if (active) setPage({ session, cursor, rows: [], error: 'Cannot read the local batch page. Records were not reset.' }); });
    return () => { active = false; };
  }, [session, cursor,revision]);
  return <Screen title="Downloaded batches"><Body>Local page • 25 records at most • Not a whole-farm report</Body><ErrorMessage message={error} />
    {busy ? <Loading /> : rows.length ? rows.map((row) => {
      const payload = JSON.parse(row.payload_json) as { batch_id?: string; status?: string };
      return <Card key={row.entity_uuid} title={payload.batch_id ?? row.entity_uuid}><Body>{payload.status ?? 'Status unavailable'}</Body>
        <Button title={`Open ${payload.batch_id ?? 'batch'}`} onPress={()=>router.push(`/batch/${row.entity_uuid}`)} /></Card>;
    }) : <Card title="No local batches"><Body>No activated batch download is available. This does not mean the farm has no batches. Check the Sync tab.</Body></Card>}
    <Button disabled={busy || rows.length < 25} title="Next local page" onPress={() => setCursor(rows[rows.length - 1]!.entity_uuid)} />
    <Button disabled={busy || !cursor} title="First local page" onPress={() => setCursor('')} />
  </Screen>;
}
