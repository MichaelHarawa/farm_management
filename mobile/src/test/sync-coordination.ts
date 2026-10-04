import { SyncEngine, type EngineOptions } from '../sync/engine';

// Acceptance-only orchestration. All storage and successful HTTP responses still
// go through the real engine; uploads are disabled for both competing workers.
export async function checkSyncCoordination(
  options: Omit<EngineOptions, 'owner' | 'uploadsEnabled'>,
  owners: [string, string],
  holdTimeoutMs = 10000,
) {
  if (!owners[0] || !owners[1] || owners[0] === owners[1] ||
      !Number.isInteger(holdTimeoutMs) || holdTimeoutMs < 1 || holdTimeoutMs > 60000) {
    throw new Error('invalid_coordination_check');
  }
  let entered!: () => void, release!: () => void;
  const leased = new Promise<void>(resolve => { entered = resolve; });
  const gate = new Promise<void>(resolve => { release = resolve; });
  let permit = false, authorizations = 0, requests = 0, contenderCalls = 0;
  const first = new SyncEngine({ ...options, owner: owners[0], uploadsEnabled: false,
    authorize: async () => {
      entered(); await gate;
      if (!permit) throw new Error('coordination_check_aborted');
      authorizations++; return options.authorize();
    },
    api: { request: async (path, body) => { requests++; return options.api.request(path, body); } },
  });
  const second = new SyncEngine({ ...options, owner: owners[1], uploadsEnabled: false,
    authorize: async () => { contenderCalls++; return options.authorize(); },
    api: { request: async (path, body) => { contenderCalls++; return options.api.request(path, body); } },
  });
  const original = first.run();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error('coordination_hold_timeout')), holdTimeoutMs);
  });
  try {
    await Promise.race([
      leased,
      original.then(() => { throw new Error('coordination_first_lease_not_acquired'); }),
      timeout,
    ]);
    // A second trigger on the provider's engine must share exactly one flight.
    if (first.run() !== original) throw new Error('coordination_flight_not_shared');
    const lease = await Promise.race([options.store.repository.db.first<{ owner: string }>('SELECT owner FROM sync_lease WHERE id=1'),timeout]);
    if (lease?.owner !== owners[0]) throw new Error('coordination_durable_lease_missing');
    // An independent engine must see the persisted lease BEFORE authorization
    // or any HTTP, rather than relying only on a JavaScript busy flag.
    const contender = await Promise.race([second.run(),timeout]);
    if (contender.status !== 'busy' || contender.requests || contender.pages || contender.commands || contenderCalls) {
      throw new Error('coordination_contender_not_excluded');
    }
    clearTimeout(timer); permit = true; release();
    const completed = await original;
    if (completed.status !== 'complete' || completed.commands || authorizations !== 1 || requests < 1) {
      throw new Error('coordination_real_run_not_complete');
    }
    const after = await options.store.repository.db.first<{ owner: string }>('SELECT owner FROM sync_lease WHERE id=1');
    if (after?.owner === owners[0] || after?.owner === owners[1]) throw new Error('coordination_lease_not_released');
    return { sharedFlight: true, contender, authorizations, requests, completed };
  } finally {
    clearTimeout(timer); first.cancel(); second.cancel(); release();
    // Settle any held first worker on failure; never leave a diagnostic lease
    // or unhandled promise behind. Engine ownership fencing performs cleanup.
    await original.catch(() => {});
  }
}
