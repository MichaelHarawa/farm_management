import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import { z } from 'zod';
import type { AppSettings } from '../config';
import { developmentChecksEnabled } from '../build-mode.native';
import type { SessionPointer } from '../auth/vault';
import { sha256, storePartition } from '../db/native';
import { canonical, normalizedInstant, Repository } from '../db/repository';
import type { Database, SqlConnection } from '../db/sql';
import { mortalityCommand, type Capabilities, type CurrentUser, type MortalityCommand } from '../protocol';
import { testBackendA, testBackendB, testBackendAvailable } from './backend-policy';

const markerKey = 'synthetic-account-isolation-v1';
const protectedTrigger = 'synthetic_account_keep_quarantined';
const digest = z.string().regex(/^[a-f0-9]{64}$/);
const owner = z.strictObject({ deploymentId: z.uuid(), actorId: z.uuid(), deviceId: z.uuid() });
const fixtureSchema = z.strictObject({
  version: z.literal(1), partition: digest, identity: owner, command: mortalityCommand,
  commandHash: digest,
});
const checkpointSchema = z.strictObject({
  fixture: fixtureSchema,
  viewer: z.strictObject({ partition: digest, identity: owner }).optional(),
  complete: z.boolean(),
});
type Fixture = z.infer<typeof fixtureSchema>;
type Checkpoint = z.infer<typeof checkpointSchema>;
export interface AccountProbeSession {
  repository: Repository; pointer: SessionPointer; user: CurrentUser; capabilities: Capabilities;
}
const secureOptions = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
function ensure(value: unknown): asserts value { if (!value) throw new Error('account_probe_check_failed'); }

export function accountProbeAvailable(settings: AppSettings, session: AccountProbeSession | null): boolean {
  return testBackendAvailable(settings, developmentChecksEnabled) &&
    !!session && session.pointer.base === settings.apiBaseUrl &&
    ['mobile-test-worker', 'mobile-test-viewer'].includes(session.user.username);
}

async function guard(settings: AppSettings, session: AccountProbeSession, username: string) {
  ensure(accountProbeAvailable(settings, session) && session.user.username === username);
  const { pointer, user, capabilities, repository } = session;
  ensure(user.id === pointer.identity.actorId && capabilities.deployment_id === pointer.identity.deploymentId &&
    capabilities.device_id === pointer.identity.deviceId && canonical(repository.identity) === canonical(pointer.identity));
  ensure(pointer.partition === await storePartition(settings.apiBaseUrl, pointer.identity));
  ensure(canonical(await repository.metadata('identity')) === canonical(pointer.identity));
}

function checkpointKey(session: AccountProbeSession) {
  return `native-account-${owner.parse(session.pointer.identity).deploymentId}`;
}
async function readCheckpoint(session: AccountProbeSession): Promise<Checkpoint | null> {
  const value = await SecureStore.getItemAsync(checkpointKey(session), secureOptions);
  return value ? checkpointSchema.parse(JSON.parse(value)) : null;
}
async function writeCheckpoint(session: AccountProbeSession, value: Checkpoint) {
  // Only the owned synthetic fixture/IDs/hash; never credentials, keys or real farm records.
  await SecureStore.setItemAsync(checkpointKey(session), JSON.stringify(checkpointSchema.parse(value)), secureOptions);
}

async function rowCounts(db: SqlConnection) {
  return db.first<{ entities: number; outbox: number; overlays: number; other: number }>(`SELECT
    (SELECT COUNT(*) FROM confirmed_entities) AS entities,
    (SELECT COUNT(*) FROM outbox) AS outbox,
    (SELECT COUNT(*) FROM pending_overlays) AS overlays,
    ((SELECT COUNT(*) FROM operation_dependencies) + (SELECT COUNT(*) FROM receipts) +
      (SELECT COUNT(*) FROM entity_mappings) + (SELECT COUNT(*) FROM conflicts) +
      (SELECT COUNT(*) FROM sync_state) + (SELECT COUNT(*) FROM sync_lease) +
      (SELECT COUNT(*) FROM pack_manifests) + (SELECT COUNT(*) FROM pack_membership) +
      (SELECT COUNT(*) FROM attachment_jobs)) AS other`);
}
async function requireEmpty(db: SqlConnection) {
  const counts = await rowCounts(db);
  ensure(counts && counts.entities === 0 && counts.outbox === 0 && counts.overlays === 0 && counts.other === 0);
  const extra = await db.first<{ count: number }>(
    "SELECT COUNT(*) AS count FROM metadata WHERE key NOT IN ('identity','session')");
  ensure(extra?.count === 0);
}

// The existing repository primitive executes on this same already-keyed outer
// transaction, making its synthetic parent, command, quarantine and marker one commit.
function transactionRepository(tx: SqlConnection, session: AccountProbeSession): Repository {
  const db: Database = { ...tx, transaction: async (work) => work(tx),
    close: async () => { throw new Error('account_probe_does_not_own_session_connection'); } };
  return new Repository(db, session.pointer.identity);
}

async function verifyFixture(session: AccountProbeSession, fixture: Fixture, replica: 'full' | 'retained' = 'full') {
  ensure(canonical(fixture.identity) === canonical(session.pointer.identity) && fixture.partition === session.pointer.partition);
  ensure(canonical(await session.repository.metadata(markerKey)) === canonical(fixture));
  const { command } = fixture;
  const row = await session.repository.db.first<{
    operation_id: string; entity_uuid: string; entity_type: string; actor_id: string; device_id: string;
    deployment_id: string; command_json: string; command_hash: string; captured_at: string;
    state: string; attempts: number;
  }>('SELECT * FROM outbox WHERE operation_id=?', [command.operation_id]);
  ensure(row && row.operation_id === command.operation_id && row.entity_uuid === command.entity_uuid &&
    row.entity_type === command.entity_type && row.actor_id === fixture.identity.actorId &&
    row.device_id === fixture.identity.deviceId && row.deployment_id === fixture.identity.deploymentId &&
    row.command_json === canonical(command) && row.command_hash === fixture.commandHash &&
    row.captured_at === command.captured_at && row.state === 'quarantined' && row.attempts === 0);
  const normalized = { ...command, captured_at: normalizedInstant(command.captured_at),
    payload: { ...command.payload, mortality_date: normalizedInstant(command.payload.mortality_date) } };
  ensure(row.command_hash === await sha256(canonical({ deployment_id: fixture.identity.deploymentId,
    actor_id: fixture.identity.actorId, device_id: fixture.identity.deviceId, operation: normalized })));
  const overlay = await session.repository.db.first<{ entity_uuid: string; entity_type: string; payload_json: string }>(
    'SELECT entity_uuid,entity_type,payload_json FROM pending_overlays WHERE operation_id=?', [command.operation_id]);
  ensure(overlay && overlay.entity_uuid === command.entity_uuid && overlay.entity_type === command.entity_type &&
    overlay.payload_json === canonical(command.payload));
  const counts = await rowCounts(session.repository.db);
  ensure(counts && (replica === 'full' ? counts.entities === 1 : counts.entities === 0 || counts.entities === 1) &&
    counts.outbox === 1 && counts.overlays === 1 && counts.other === 0);
  const batch = await session.repository.db.first<{ payload_json: string; tombstone: number }>(
    'SELECT payload_json,tombstone FROM confirmed_entities WHERE entity_type=? AND entity_uuid=?',
    ['poultry.batch', command.payload.batch_uuid]);
  if (replica === 'full' || counts.entities === 1) {
    ensure(batch?.tombstone === 0 && batch.payload_json === canonical({ batch_id: 'SYNTHETIC ACCOUNT PROBE — NEVER UPLOAD' }));
  } else ensure(batch === null);
  const trigger = await session.repository.db.first<{ name: string }>(
    'SELECT name FROM sqlite_master WHERE type=? AND name=?', ['trigger', protectedTrigger]);
  ensure(trigger?.name === protectedTrigger);
}

export async function verifyRetainedDraft(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker');
  const checkpoint = await readCheckpoint(session);
  ensure(checkpoint);
  await verifyFixture(session, checkpoint.fixture, 'retained');
  return 'PASS: exact original operation UUID, immutable command contents, recomputed hash, capture timestamp, owner/device/deployment and overlay match the saved checkpoint. One quarantined operation, zero attempts. Confirmed replica may be evicted; no parent was reinserted and no upload ran.';
}

const originSchema = z.strictObject({ base: z.literal(testBackendA), partition: digest, identity: owner,
  operationId: z.uuid(), entityId: z.uuid(), commandHash: digest });
const originKey = 'synthetic-environment-origin-v1';
export async function rememberEnvironmentOrigin(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker');
  ensure(settings.apiBaseUrl === testBackendA);
  const checkpoint = await readCheckpoint(session); ensure(checkpoint);
  await verifyFixture(session, checkpoint.fixture, 'retained');
  const origin = originSchema.parse({ base: settings.apiBaseUrl, partition: session.pointer.partition,
    identity: session.pointer.identity, operationId: checkpoint.fixture.command.operation_id,
    entityId: checkpoint.fixture.command.entity_uuid, commandHash: checkpoint.fixture.commandHash });
  await SecureStore.setItemAsync(originKey, JSON.stringify(origin), secureOptions);
  return 'PREPARED: original backend A identity and operation digest retained securely. Switch to test backend B and sign in online; no record contents or credentials are exported.';
}
export async function verifyEnvironmentIsolation(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker'); ensure(settings.apiBaseUrl === testBackendB);
  const raw = await SecureStore.getItemAsync(originKey, secureOptions); ensure(raw);
  const origin = originSchema.parse(JSON.parse(raw));
  ensure(origin.partition !== session.pointer.partition && origin.identity.deploymentId !== session.pointer.identity.deploymentId &&
    origin.identity.actorId !== session.pointer.identity.actorId && origin.identity.deviceId !== session.pointer.identity.deviceId);
  await requireEmpty(session.repository.db);
  ensure(await readCheckpoint(session) === null && await session.repository.metadata(markerKey) === null);
  ensure(await session.repository.db.first('SELECT operation_id FROM outbox WHERE operation_id=?', [origin.operationId]) === null);
  return 'PASS: real backend B has distinct deployment/user/device/store, zero queue and no backend A operation or fixture. Phase 3 has no upload route/worker. Switch back to A and sign in to verify exact original work.';
}
export async function verifyEnvironmentReturn(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker'); ensure(settings.apiBaseUrl === testBackendA);
  const raw = await SecureStore.getItemAsync(originKey, secureOptions); ensure(raw);
  const origin = originSchema.parse(JSON.parse(raw));
  const checkpoint = await readCheckpoint(session); ensure(checkpoint);
  ensure(origin.partition === session.pointer.partition && canonical(origin.identity) === canonical(session.pointer.identity) &&
    origin.operationId === checkpoint.fixture.command.operation_id && origin.entityId === checkpoint.fixture.command.entity_uuid &&
    origin.commandHash === checkpoint.fixture.commandHash);
  await verifyFixture(session, checkpoint.fixture, 'retained');
  return 'PASS: returning from real backend B recovered backend A’s exact original identity, operation UUID/contents/hash and overlay. Quarantine and zero upload attempts are unchanged.';
}

export async function prepareAccountFixture(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker');
  ensure(session.capabilities.commands['poultry.mortality.record']?.available === true);
  const checkpoint = await readCheckpoint(session);
  const saved = await session.repository.metadata<unknown>(markerKey);
  let fixture: Fixture;
  if (saved) {
    fixture = fixtureSchema.parse(saved);
    await verifyFixture(session, fixture);
    if (checkpoint) ensure(canonical(checkpoint.fixture) === canonical(fixture));
  } else {
    ensure(checkpoint === null);
    const now = new Date().toISOString();
    const command: MortalityCommand = {
      operation_id: Crypto.randomUUID(), entity_uuid: Crypto.randomUUID(), entity_type: 'poultry.mortality',
      action: 'record', payload_version: 1, base_version: null, captured_at: now, depends_on: [],
      payload: { batch_uuid: Crypto.randomUUID(), mortality_date: now, quantity_dead: 1,
        suspected_cause: 'Synthetic account-isolation probe', description: 'Synthetic local fixture. Never upload.',
        action_taken: 'Retain quarantined on this test installation', reported_by_name: 'Synthetic test worker' },
    };
    fixture = await session.repository.db.transaction(async (tx) => {
      await requireEmpty(tx);
      const repository = transactionRepository(tx, session);
      await repository.bindIdentity();
      await tx.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)',
        ['poultry.batch', command.payload.batch_uuid, '1', canonical({ batch_id: 'SYNTHETIC ACCOUNT PROBE — NEVER UPLOAD' })]);
      await repository.saveDraftAndEnqueue(command, sha256);
      await tx.run("UPDATE outbox SET state='quarantined' WHERE operation_id=?", [command.operation_id]);
      const row = await tx.first<{ command_hash: string }>('SELECT command_hash FROM outbox WHERE operation_id=?', [command.operation_id]);
      const value = fixtureSchema.parse({ version: 1, partition: session.pointer.partition,
        identity: session.pointer.identity, command, commandHash: row?.command_hash });
      await repository.setMetadata(markerKey, value, tx);
      // Permanent guard for this sole synthetic operation. A later queue engine
      // must not promote it to pending/unknown or treat it as a server result.
      await tx.exec(`CREATE TRIGGER synthetic_account_keep_quarantined
        BEFORE UPDATE OF state ON outbox
        WHEN OLD.operation_id=(SELECT json_extract(value,'$.command.operation_id') FROM metadata WHERE key='synthetic-account-isolation-v1')
          AND NEW.state <> 'quarantined'
        BEGIN SELECT RAISE(ABORT,'synthetic_account_fixture_is_quarantined'); END;`);
      return value;
    });
    await verifyFixture(session, fixture);
  }
  if (!checkpoint) await writeCheckpoint(session, { fixture, complete: false });
  return 'PREPARED: one synthetic worker draft and outbox are retained in quarantine. Sign out, sign in as mobile-test-viewer, then verify viewer isolation here. No uploads run.';
}

export async function verifyViewerIsolation(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-viewer');
  ensure(session.capabilities.commands['poultry.mortality.record']?.available === false);
  const checkpoint = await readCheckpoint(session);
  ensure(checkpoint && checkpoint.fixture.identity.deploymentId === session.pointer.identity.deploymentId &&
    checkpoint.fixture.identity.actorId !== session.pointer.identity.actorId &&
    checkpoint.fixture.identity.deviceId !== session.pointer.identity.deviceId &&
    checkpoint.fixture.partition !== session.pointer.partition);
  await requireEmpty(session.repository.db);
  ensure(await session.repository.metadata(markerKey) === null && await session.repository.queueCount() === 0);
  const fixtureRow = await session.repository.db.first('SELECT operation_id FROM outbox WHERE operation_id=?',
    [checkpoint.fixture.command.operation_id]);
  ensure(fixtureRow === null);
  await writeCheckpoint(session, { ...checkpoint, complete: false,
    viewer: { partition: session.pointer.partition, identity: session.pointer.identity } });
  return 'PASS: viewer has a distinct user/device/store, zero queued work, no worker fixture, and Django denies mortality capture. Sign out, sign in as mobile-test-worker, then verify retained work here.';
}

export async function verifyWorkerReturn(settings: AppSettings, session: AccountProbeSession): Promise<string> {
  await guard(settings, session, 'mobile-test-worker');
  ensure(session.capabilities.commands['poultry.mortality.record']?.available === true);
  const checkpoint = await readCheckpoint(session);
  ensure(checkpoint?.viewer && checkpoint.viewer.identity.actorId !== session.pointer.identity.actorId &&
    checkpoint.viewer.identity.deploymentId === session.pointer.identity.deploymentId &&
    checkpoint.viewer.partition !== session.pointer.partition);
  await verifyFixture(session, checkpoint.fixture);
  await writeCheckpoint(session, { ...checkpoint, complete: true });
  return 'PASS: original worker recovered the exact command UUID/hash, original owner and matching overlay after viewer sign-in. One synthetic draft/outbox remains quarantined. Real account switching used the app session; no uploads or record deletions ran.';
}
