import * as SQLite from 'expo-sqlite';
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import { File } from 'expo-file-system';
import type { Database, SqlConnection, SqlValue } from './sql';
import { migrate, Repository } from './repository';
import { deviceUnlock } from '../auth/device';
import type { StoreIdentity } from '../protocol';
import { databaseFileUri } from './file-uri';

function connection(db: SQLite.SQLiteDatabase): SqlConnection {
  return {
    exec: (sql) => db.execAsync(sql),
    async run(sql, values = []) {
      const statement = await db.prepareAsync(sql);
      try { const result = await statement.executeAsync(values); return { changes: result.changes }; }
      finally { await statement.finalizeAsync(); }
    },
    async first<T>(sql: string, values: SqlValue[] = []) {
      const statement = await db.prepareAsync(sql);
      try { return await (await statement.executeAsync<T>(values)).getFirstAsync(); }
      finally { await statement.finalizeAsync(); }
    },
    async all<T>(sql: string, values: SqlValue[] = []) {
      const statement = await db.prepareAsync(sql);
      try { return await (await statement.executeAsync<T>(values)).getAllAsync(); }
      finally { await statement.finalizeAsync(); }
    },
  };
}

export function adaptNative(db: SQLite.SQLiteDatabase): Database {
  // SQL transactions and close share a serial gate. Only tx connection is used inside a transaction.
  let tail: Promise<unknown> = Promise.resolve();
  let closed = false;
  function serialized<T>(work: () => Promise<T>): Promise<T> {
    const result = tail.then(work); tail = result.catch(() => {}); return result;
  }
  const sql = connection(db);
  return {
    exec: (statement) => serialized(() => sql.exec(statement)),
    run: (statement, values) => serialized(() => sql.run(statement, values)),
    first: <T>(statement: string, values?: SqlValue[]) => serialized(() => sql.first<T>(statement, values)),
    all: <T>(statement: string, values?: SqlValue[]) => serialized(() => sql.all<T>(statement, values)),
    transaction: <T>(work: (tx: SqlConnection) => Promise<T>) => serialized(async () => {
      // SDK's withExclusiveTransactionAsync opens a NEW unkeyed connection. Keep
      // SQLCipher key/FK settings on this keyed handle; the serial gate prevents
      // unrelated async work joining the explicit IMMEDIATE transaction.
      await sql.exec('BEGIN IMMEDIATE');
      try { const value = await work(sql); await sql.exec('COMMIT'); return value; }
      catch (error) {
        try { await sql.exec('ROLLBACK'); } catch { /* SQLITE_FULL may already roll back; retain the original error. */ }
        throw error;
      }
    }),
    close: () => serialized(async () => { if (!closed) { await db.closeAsync(); closed = true; } }),
  };
}

export const sha256 = (text: string) => Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text);
export async function storePartition(base: string, identity: Pick<StoreIdentity, 'actorId' | 'deploymentId'>) {
  return sha256(`${base}\n${identity.deploymentId}\n${identity.actorId}`);
}

export async function openEncrypted(partition: string, identity: StoreIdentity): Promise<Repository> {
  if (!/^[a-f0-9]{64}$/.test(partition)) throw new Error('invalid_partition');
  const name = `farm-${partition}.db`;
  const keyName = `db-key-${partition}`;
  const supportsCryptoPrompt = await deviceUnlock();
  const policyName = `db-key-policy-${partition}`;
  let policy = await SecureStore.getItemAsync(policyName);
  const exists = new File(databaseFileUri(SQLite.defaultDatabaseDirectory, name)).exists;
  if (!policy) {
    if (exists) throw new Error('database_key_missing');
    policy = supportsCryptoPrompt ? 'biometric' : 'device-unlock';
    await SecureStore.setItemAsync(policyName, policy);
  }
  if (!['biometric', 'device-unlock'].includes(policy)) throw new Error('invalid_database_key');
  // Existing biometric keys never silently downgrade when enrollment changes.
  const options = { requireAuthentication: policy === 'biometric', authenticationPrompt: 'Unlock encrypted farm records', keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
  let key = await SecureStore.getItemAsync(keyName, options);
  if (!key) {
    if (exists) throw new Error('database_key_missing');
    key = Array.from(await Crypto.getRandomBytesAsync(32), (v) => v.toString(16).padStart(2, '0')).join('');
    await SecureStore.setItemAsync(keyName, key, options);
  }
  if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('invalid_database_key');
  const native = await SQLite.openDatabaseAsync(name, { useNewConnection: true });
  try {
    // PRAGMA cannot bind the key: only validated random hex is interpolated, never user input.
    await native.execAsync(`PRAGMA key="x'${key}'";`);
    const cipher = await native.getFirstAsync<Record<string, string>>('PRAGMA cipher_version');
    if (!cipher || !Object.values(cipher).some(Boolean)) throw new Error('sqlcipher_native_build_required');
    await native.getFirstAsync('SELECT count(*) FROM sqlite_master');
    const db = adaptNative(native);
    await migrate(db);
    const repository = new Repository(db, identity);
    await repository.bindIdentity();
    return repository;
  } catch (error) {
    await native.closeAsync();
    throw error; // Never delete/reset database or key to hide a migration failure.
  }
}
