import { DatabaseSync } from 'node:sqlite';
import type { Database, SqlConnection, SqlValue } from '../src/db/sql';
import type { MortalityCommand, StoreIdentity } from '../src/protocol';
export function hostDatabase(path = ':memory:'): Database {
  const db = new DatabaseSync(path);
  const sql: SqlConnection = {
    async exec(statement) { db.exec(statement); },
    async run(statement, values = []) { return { changes: Number(db.prepare(statement).run(...values).changes) }; },
    async first<T>(statement: string, values: SqlValue[] = []) { return db.prepare(statement).get(...values) as T ?? null; },
    async all<T>(statement: string, values: SqlValue[] = []) { return db.prepare(statement).all(...values) as T[]; },
  };
  let tail: Promise<unknown> = Promise.resolve();
  function serial<T>(work: () => Promise<T>) { const result = tail.then(work); tail = result.catch(() => {}); return result; }
  return { exec: (s) => serial(() => sql.exec(s)), run: (s, v) => serial(() => sql.run(s, v)),
    first: <T>(s: string, v?: SqlValue[]) => serial(() => sql.first<T>(s, v)), all: <T>(s: string, v?: SqlValue[]) => serial(() => sql.all<T>(s, v)),
    async transaction<T>(work: (tx: SqlConnection) => Promise<T>) {
      return serial(async () => { db.exec('BEGIN IMMEDIATE'); try { const result = await work(sql); db.exec('COMMIT'); return result; } catch (error) { try { db.exec('ROLLBACK'); } catch { /* Preserve SQLITE_FULL. */ } throw error; } });
    }, async close() { await serial(async () => db.close()); } };
}
export const identity: StoreIdentity = { actorId: '4c28be23-19f0-4574-b861-19c47e0bcb7e', deviceId: '8d7455a0-92b1-451f-97d5-43d216d0a341', deploymentId: '1a28be23-19f0-4574-b861-19c47e0bcb7e' };
export const command: MortalityCommand = { operation_id: '9b7b91cb-0271-4be7-a0ee-22f4d775b473', entity_uuid: '31d8a2fb-fd4b-4998-a807-c2c173755fcf', entity_type: 'poultry.mortality', action: 'record', payload_version: 1, base_version: null, captured_at: '2026-09-30T06:35:00Z', depends_on: [], payload: { batch_uuid: '6f2337e0-72bf-436c-a516-8657bc8fa870', mortality_date: '2026-09-30T06:30:00Z', quantity_dead: 2, suspected_cause: 'Unknown', description: 'Synthetic', action_taken: 'Reported', reported_by_name: 'Synthetic worker' } };
