import { useEffect, useState } from 'react';
import { useSession } from '../auth/session';
import { useSync } from '../sync/context';
export function useQueueCount() {
  const { session } = useSession();
  const { revision } = useSync();
  const [result, setResult] = useState<{ session: typeof session; count: number | null } | null>(null);
  useEffect(() => {
    let active = true;
    if (!session) return;
    session.repository.queueCount().then((value) => { if (active) setResult({ session, count: value }); }).catch(() => { if (active) setResult({ session, count: null }); });
    return () => { active = false; };
  }, [session,revision]);
  return result?.session === session ? result.count : null;
}
