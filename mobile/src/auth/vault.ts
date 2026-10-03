import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import type { Credentials, CredentialStore } from './client';
import type { OfflineClock } from './offline';
import type { StoreIdentity } from '../protocol';
import { sha256 } from '../db/native';
import { serializedCredentials } from './credential-store';

export interface SessionPointer { partition: string; base: string; identity: StoreIdentity; offlineAllowed: boolean; clock: OfflineClock }
const secureOptions = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
let pointerWrites: Promise<unknown> = Promise.resolve();
const credentialStores = new Map<string, CredentialStore>();
export const vault = {
  async readTestBackend() { return SecureStore.getItemAsync('synthetic-test-backend', secureOptions); },
  async writeTestBackend(base: string) { await SecureStore.setItemAsync('synthetic-test-backend', base, secureOptions); },
  async readPointer(): Promise<SessionPointer | null> {
    const raw = await SecureStore.getItemAsync('active-session', secureOptions);
    return raw ? JSON.parse(raw) as SessionPointer : null;
  },
  async writePointer(pointer: SessionPointer) {
    const serialized = JSON.stringify(pointer);
    const write = pointerWrites.then(() => SecureStore.setItemAsync('active-session', serialized, secureOptions));
    pointerWrites = write.catch(() => {});
    await write;
  },
  credentials(partition: string): CredentialStore {
    let store = credentialStores.get(partition);
    if (store) return store;
    store = serializedCredentials({
      async read() {
        const raw = await SecureStore.getItemAsync(`refresh-${partition}`, secureOptions);
        return raw ? JSON.parse(raw) as Credentials : null;
      },
      async write(value) { await SecureStore.setItemAsync(`refresh-${partition}`, JSON.stringify(value), secureOptions); },
    });
    credentialStores.set(partition, store);
    return store;
  },
  async installation(base: string, actor: string) {
    const key = `installation-${await sha256(`${base}\n${actor}`)}`;
    let id = await SecureStore.getItemAsync(key, secureOptions);
    if (!id) { id = Crypto.randomUUID(); await SecureStore.setItemAsync(key, id, secureOptions); }
    return id;
  },
};
