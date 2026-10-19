/** Native-only adapter. Separate financial files/keys; no operational migration or upload. */
import * as SQLite from 'expo-sqlite';
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import { File } from 'expo-file-system';
import { adaptNative, sha256 } from '../db/native';
import { financialDatabaseFileUri } from '../db/file-uri';
import { deviceUnlock } from '../auth/device';
import type { AuthClient } from '../auth/client';
import type { AppSettings } from '../config';
import type { StoreIdentity } from '../protocol';
import { FinancialEvidenceStore } from './evidence-store';
import { FinancialCompartment } from './compartment';
import { FinancialStorageGrantReader } from './storage-client';
import { financialNamespace, openFinancialDatabase, type FinancialDatabasePorts, type FinancialDatabaseStep, type FinancialNamespace } from './key-database';

const secure = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
const pointerQueues = new Map<string, Promise<unknown>>();
function pointerWork<T>(key: string, work: () => Promise<T>): Promise<T> {
  const task = (pointerQueues.get(key) ?? Promise.resolve()).then(work);
  const settled = task.catch(() => {});
  pointerQueues.set(key, settled);
  void settled.then(() => { if (pointerQueues.get(key) === settled) pointerQueues.delete(key); });
  return task;
}
const ports: FinancialDatabasePorts = {
  hash: sha256, unlock: () => deviceUnlock('financial'),
  async randomKey() { return Array.from(await Crypto.getRandomBytesAsync(32), byte => byte.toString(16).padStart(2, '0')).join(''); },
  keys: {
    get: (name, authenticated = false) => SecureStore.getItemAsync(name, { ...secure, requireAuthentication: authenticated,
      authenticationPrompt: 'Unlock encrypted financial evidence' }),
    set: (name, value, authenticated = false) => SecureStore.setItemAsync(name, value, { ...secure, requireAuthentication: authenticated,
      authenticationPrompt: 'Unlock encrypted financial evidence' }),
  },
  async exists(name) { return new File(financialDatabaseFileUri(SQLite.defaultDatabaseDirectory, name)).exists; },
  async open(name) { return adaptNative(await SQLite.openDatabaseAsync(name, { useNewConnection: true })); },
};

/** Shared actual native opener; returns no key material. Diagnostics use owned scratch names only. */
export function openNativeFinancialDatabase(namespace: FinancialNamespace, trace?: (step: FinancialDatabaseStep) => void) {
  return openFinancialDatabase(namespace, ports, trace);
}

/** No PIN, SQL, key read/creation or network request merely to revoke this marker. */
export async function denyNativeFinancialAccess(settings: AppSettings, identity: StoreIdentity) {
  const namespace = await financialNamespace(settings, identity, sha256);
  await pointerWork(namespace.access, () => SecureStore.setItemAsync(namespace.access, '{"version":1,"status":"denied"}', secure));
}

/** Creation is lazy: no key/database/prompt/request until an explicit finance action. */
export function createNativeFinancialCompartment(settings: AppSettings, identity: StoreIdentity, streamEpoch: string,
  auth: AuthClient, isCurrent: () => boolean): FinancialCompartment {
  const boundSettings = Object.freeze({ ...settings }), boundIdentity = Object.freeze({ ...identity });
  const namespace = financialNamespace(boundSettings, boundIdentity, sha256);
  return new FinancialCompartment({ ...boundIdentity, streamEpoch }, {
    now: Date.now, isCurrent,
    access: {
      async read() {
        const descriptor = await namespace;
        return pointerWork(descriptor.access, async () => {
          const raw = await SecureStore.getItemAsync(descriptor.access, secure);
          return raw ? JSON.parse(raw) : null;
        });
      },
      async write(value) {
        const descriptor = await namespace;
        const serialized = JSON.stringify(value);
        await pointerWork(descriptor.access, () => SecureStore.setItemAsync(descriptor.access, serialized, secure));
      },
    },
    async open() {
      const db = await openNativeFinancialDatabase(await namespace);
      try { return await FinancialEvidenceStore.open(db, boundIdentity, sha256); }
      catch (error) { await db.close(); throw error; } // Never delete/reset a key/file after schema failure.
    },
    reader: () => new FinancialStorageGrantReader(auth, { ...boundIdentity, streamEpoch }, Crypto.randomUUID),
  });
}
