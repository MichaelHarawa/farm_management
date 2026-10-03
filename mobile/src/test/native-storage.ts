import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';
import { File } from 'expo-file-system';
import { developmentChecksEnabled } from '../build-mode.native';
import { openEncrypted, sha256 } from '../db/native';
import { migrate, Repository } from '../db/repository';
import { migrations } from '../db/schema';
import { databaseFileUri } from '../db/file-uri';
import type { MortalityCommand, StoreIdentity } from '../protocol';

function ensure(condition: unknown, message: string): asserts condition { if (!condition) throw new Error(message); }
async function seedSyntheticDraft(repository: Repository): Promise<MortalityCommand> {
  const batchUuid = Crypto.randomUUID();
  await repository.db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)', ['poultry.batch', batchUuid, '1', '{"batch_id":"SYNTHETIC"}']);
  const command: MortalityCommand = { operation_id: Crypto.randomUUID(), entity_uuid: Crypto.randomUUID(), entity_type: 'poultry.mortality', action: 'record', payload_version: 1,
    base_version: null, captured_at: new Date().toISOString(), depends_on: [], payload: { batch_uuid: batchUuid, mortality_date: new Date().toISOString(), quantity_dead: 1,
      suspected_cause: 'Synthetic', description: 'Storage probe only', action_taken: 'No upload', reported_by_name: 'Synthetic actor' } };
  await repository.saveDraftAndEnqueue(command, sha256);
  return command;
}
export async function runNativeStorageProbe(retainForProcessDeath = false): Promise<string> {
  if (!developmentChecksEnabled) throw new Error('development_only');
  if (retainForProcessDeath && await SecureStore.getItemAsync('native-crash-probe')) throw new Error('verify_existing_probe_first');
  const identity: StoreIdentity = { actorId: Crypto.randomUUID(), deploymentId: Crypto.randomUUID(), deviceId: Crypto.randomUUID() };
  const partition = await sha256(`synthetic-native-probe\n${Crypto.randomUUID()}`);
  const name = `farm-${partition}.db`;
  let repository = await openEncrypted(partition, identity);
  try {
    await repository.setMetadata('synthetic-storage-probe', true);
    const command = await seedSyntheticDraft(repository);
    await repository.db.exec("CREATE TRIGGER probe_failure BEFORE INSERT ON pending_overlays BEGIN SELECT RAISE(ABORT,'injected_failure'); END");
    let failed = false;
    try { await repository.saveDraftAndEnqueue({ ...command, operation_id: Crypto.randomUUID(), entity_uuid: Crypto.randomUUID() }, sha256); }
    catch { failed = true; }
    ensure(failed && await repository.queueCount() === 1, 'atomic_save_failed');
    await repository.db.exec('DROP TRIGGER probe_failure');
    ensure(await repository.acquireLease('first', 1000), 'lease_failed');
    ensure(!(await repository.acquireLease('second', 1001)), 'lease_overlap');
    let migrationFailed = false;
    try { await migrate(repository.db, [...migrations, 'CREATE TABLE rollback_probe(id TEXT); INVALID SQL;']); } catch { migrationFailed = true; }
    ensure(migrationFailed && await repository.queueCount() === 1, 'migration_preservation_failed');
    ensure((await repository.db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version === migrations.length, 'migration_version_changed');
    ensure(await repository.db.first("SELECT name FROM sqlite_master WHERE name='rollback_probe'") === null, 'migration_ddl_survived');
    // Exhaust only this owned scratch database's page budget, never device disk.
    const pages = (await repository.db.first<{ page_count: number }>('PRAGMA page_count'))?.page_count;
    const maximum = (await repository.db.first<{ max_page_count: number }>('PRAGMA max_page_count'))?.max_page_count;
    ensure(Number.isSafeInteger(pages) && Number.isSafeInteger(maximum), 'page_limits_unavailable');
    await repository.db.exec(`PRAGMA max_page_count=${pages}`);
    let full = false;
    try {
      await repository.saveDraftAndEnqueue({ ...command, operation_id: Crypto.randomUUID(), entity_uuid: Crypto.randomUUID(),
        payload: { ...command.payload, description: 'x'.repeat(4000), action_taken: 'y'.repeat(4000) } }, sha256);
    } catch (error) { full = error instanceof Error && /full/i.test(error.message); }
    finally { await repository.db.exec(`PRAGMA max_page_count=${maximum}`); }
    ensure(full && await repository.queueCount() === 1, 'disk_full_preservation_failed');
    ensure((await repository.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))?.count === 1, 'disk_full_overlay_changed');
    let identityRejected = false;
    try { await new Repository(repository.db, { ...identity, actorId: Crypto.randomUUID() }).bindIdentity(); }
    catch (error) { identityRejected = error instanceof Error && error.message === 'original_identity_mismatch'; }
    ensure(identityRejected, 'foreign_identity_accepted');
    await repository.db.close();
    repository = await openEncrypted(partition, identity);
    ensure(await repository.queueCount() === 1, 'correct_key_reopen_failed');
    ensure((await repository.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))?.count === 1, 'overlay_reopen_failed');
    await repository.db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
    await repository.db.close();
    const bytes = await new File(databaseFileUri(SQLite.defaultDatabaseDirectory, name)).bytes();
    ensure(String.fromCharCode(...bytes.slice(0, 15)) !== 'SQLite format 3', 'plaintext_database_header');
    const wrong = await SQLite.openDatabaseAsync(name, { useNewConnection: true });
    try {
      await wrong.execAsync(`PRAGMA key="x'${'00'.repeat(32)}'"`);
      let wrongFailed = false;
      try { await wrong.getFirstAsync('SELECT count(*) FROM sqlite_master'); } catch { wrongFailed = true; }
      ensure(wrongFailed, 'wrong_key_was_accepted');
    } finally { await wrong.closeAsync(); }
    const noKey = await SQLite.openDatabaseAsync(name, { useNewConnection: true });
    try {
      let plainFailed = false;
      try { await noKey.getFirstAsync('SELECT count(*) FROM sqlite_master'); } catch { plainFailed = true; }
      ensure(plainFailed, 'unkeyed_reader_was_accepted');
    } finally { await noKey.closeAsync(); }
    if (retainForProcessDeath) {
      await SecureStore.setItemAsync('native-crash-probe', JSON.stringify({ partition, identity }));
      return 'PREPARED: one synthetic draft/outbox retained. Force-stop and relaunch Android, reopen the locked native storage checks, then verify this probe. No uploads run.';
    }
    // Clean only the successful probe's freshly owned synthetic DB/key, never user stores.
    await SQLite.deleteDatabaseAsync(name);
    await SecureStore.deleteItemAsync(`db-key-${partition}`);
    await SecureStore.deleteItemAsync(`db-key-policy-${partition}`);
    return 'PASS: SQLCipher present, keyed reopen, wrong/unkeyed read rejected, encrypted header, foreign keys, atomic rollback, migration rollback, disk-full preservation, foreign identity rejection and exclusive lease. Synthetic probe removed. Process-death and physical-device checks are separate.';
  } catch (error) {
    try { await repository.db.close(); } catch { /* Preserve failed synthetic evidence. */ }
    throw error;
  }
}

export async function runNativeMissingKeyProbe(): Promise<string> {
  if (!developmentChecksEnabled) throw new Error('development_only');
  const identity: StoreIdentity = { actorId: Crypto.randomUUID(), deploymentId: Crypto.randomUUID(), deviceId: Crypto.randomUUID() };
  const partition = await sha256(`synthetic-key-probe\n${Crypto.randomUUID()}`);
  const name = `farm-${partition}.db`;
  const keyName = `db-key-${partition}`;
  const policyName = `db-key-policy-${partition}`;
  let repository = await openEncrypted(partition, identity);
  try {
    // PIN-only recovery scenario. Do not downgrade or alter biometric policies.
    ensure(await SecureStore.getItemAsync(policyName) === 'device-unlock', 'pin_only_probe');
    await repository.setMetadata('synthetic-key-probe', true);
    await seedSyntheticDraft(repository);
    await repository.db.exec('PRAGMA wal_checkpoint(TRUNCATE)');
    await repository.db.close();
    const file = new File(databaseFileUri(SQLite.defaultDatabaseDirectory, name));
    const before = await file.bytes();
    const keyOptions = { requireAuthentication: false, keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
    const originalKey = await SecureStore.getItemAsync(keyName, keyOptions);
    ensure(originalKey && /^[a-f0-9]{64}$/.test(originalKey), 'scratch_key_unavailable');
    // Only the freshly owned synthetic key is removed. Keep its restoration
    // material in memory; never print it or create a key-export/recovery file.
    await SecureStore.deleteItemAsync(keyName);
    try {
      let missingRejected = false;
      try {
        const unexpected = await openEncrypted(partition, identity);
        await unexpected.db.close();
      } catch (error) { missingRejected = error instanceof Error && error.message === 'database_key_missing'; }
      ensure(missingRejected, 'missing_key_not_rejected');
      ensure(await SecureStore.getItemAsync(keyName) === null, 'key_was_recreated');
      const after = await file.bytes();
      ensure(before.length === after.length && before.every((value, index) => value === after[index]), 'missing_key_changed_database');
    } finally { await SecureStore.setItemAsync(keyName, originalKey, keyOptions); }
    repository = await openEncrypted(partition, identity);
    ensure(await repository.metadata('synthetic-key-probe') === true && await repository.queueCount() === 1, 'restored_key_outbox_missing');
    ensure((await repository.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))?.count === 1, 'restored_key_overlay_missing');
    await repository.db.close();
    await SQLite.deleteDatabaseAsync(name);
    await SecureStore.deleteItemAsync(keyName);
    await SecureStore.deleteItemAsync(policyName);
    return 'PASS: missing scratch key refused access without resetting the database or recreating a key. Restoring the original scratch key recovered its exact draft/outbox. Only the owned synthetic probe was removed. Actual lost user keys cannot be recovered this way.';
  } catch (error) {
    try { await repository.db.close(); } catch { /* Keep failed synthetic evidence. */ }
    throw error;
  }
}

export async function verifyNativeCrashProbe(): Promise<string> {
  if (!developmentChecksEnabled) throw new Error('development_only');
  const raw = await SecureStore.getItemAsync('native-crash-probe');
  if (!raw) throw new Error('prepare_probe_first');
  const { partition, identity } = JSON.parse(raw) as { partition: string; identity: StoreIdentity };
  const repository = await openEncrypted(partition, identity);
  try {
    ensure(await repository.metadata('synthetic-storage-probe') === true, 'not_an_owned_synthetic_probe');
    ensure(await repository.queueCount() === 1, 'crash_outbox_missing');
    ensure((await repository.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))?.count === 1, 'crash_overlay_missing');
  } finally { await repository.db.close(); }
  // Name is validated by openEncrypted before the exact scratch store is removed.
  await SQLite.deleteDatabaseAsync(`farm-${partition}.db`);
  await SecureStore.deleteItemAsync(`db-key-${partition}`);
  await SecureStore.deleteItemAsync(`db-key-policy-${partition}`);
  await SecureStore.deleteItemAsync('native-crash-probe');
  return 'PASS: retained synthetic draft/outbox reopened. Record the external force-stop/reboot evidence separately. Only the synthetic probe was removed.';
}
