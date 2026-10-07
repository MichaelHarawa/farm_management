import { useSession } from '../../src/auth/session';
import { useQueueCount } from '../../src/components/queue';
import { Body, Card, Screen } from '../../src/components/ui';
import { useSync } from '../../src/sync/context';
import { useEffect,useState } from 'react';
import type { Coverage } from '../../src/sync/store';
export default function Today() {
  const { session } = useSession(); const queued = useQueueCount();
  const {store,revision,enabled}=useSync();const [download,setDownload]=useState<{store:typeof store;coverage:Coverage|null}|null>(null);
  useEffect(()=>{let active=true;store?.coverage().then(coverage=>{if(active)setDownload({store,coverage});}).catch(()=>{if(active)setDownload({store,coverage:null});});return()=>{active=false;};},[store,revision]);
  const coverage=download?.store===store?download.coverage:null;
  return <Screen title="Today"><Card title={`Welcome, ${session?.user.full_name ?? ''}`}>
    <Body>Authorized at {session?.capabilities.server_time}. Farm display timezone: Africa/Blantyre.</Body>
    <Body>Offline session ends {session ? new Date(session.pointer.clock.validatedServerMs + session.pointer.clock.operationalDays * 86400_000).toISOString() : '—'}.</Body>
  </Card><Card title="Download coverage"><Body>{coverage?`Downloaded ${coverage.packs.join(', ')} at ${coverage.completedAt}. Open Batches for confirmed and provisional counts.`:'No completed data download yet. No farm totals can be inferred.'}</Body><Body>Financial totals are not available in this phase. Open a downloaded batch for dated feed, mortality and weight-sample indicators; missing history is not a healthy or zero result.</Body></Card>
    <Card title="Local work"><Body>{queued === null ? 'Queue count unavailable' : `${queued} retained operations (not confirmed farm totals)`}</Body><Body>{enabled?'Synthetic operational sync is enabled. Check each record in Sync for its own server outcome.':'Native uploads are disabled in this build. See Sync for details.'}</Body></Card>
  </Screen>;
}
