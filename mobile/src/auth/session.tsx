import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import Constants from 'expo-constants';
import { developmentChecksEnabled, localAcceptance, phase5Pilot } from '../build-mode.native';
import { validateSettings } from '../config';
import { capabilitiesSchema, registrationSchema, tokenPairSchema, userSchema, type Capabilities, type CurrentUser } from '../protocol';
import { openEncrypted, storePartition } from '../db/native';
import type { Repository } from '../db/repository';
import { AuthClient, httpTransport } from './client';
import { offlineAccess } from './offline';
import { sessionErrorMessage, type SessionStage } from './errors';
import { SessionLifecycle } from './lifecycle';
import { vault, type SessionPointer } from './vault';
import { selectedTestBackend, testBackendA, testBackendAvailable, testBackendB } from '../test/backend-policy';

const extra = Constants.expoConfig?.extra;
const compiledSettings = validateSettings(String(extra?.environment ?? ''), String(extra?.apiBaseUrl ?? ''), !__DEV__ && !localAcceptance);
const testControls = testBackendAvailable(compiledSettings, localAcceptance);
interface CachedSession { user: CurrentUser; capabilities: Capabilities }
interface OpenSession extends CachedSession { repository: Repository; pointer: SessionPointer; client: AuthClient }
interface State { ready: boolean; busy: boolean; error: string | null; session: OpenSession | null }
interface ContextValue extends State {
  settings: typeof compiledSettings;
  testControls: boolean;
  switchTestBackend(): Promise<void>;
  testRefresh(): Promise<void>;
  signIn(username: string, password: string): Promise<void>;
  unlock(): Promise<void>;
  signOut(): Promise<void>;
  lock(): Promise<void>;
  revalidate(): Promise<void>;
  authorizeSync(): Promise<Capabilities>;
}
const Context = createContext<ContextValue | null>(null);
export function useSession() { const value = useContext(Context); if (!value) throw new Error('Session provider required'); return value; }

function checkpoint(pointer: SessionPointer, now: number) {
  if (!offlineAccess(pointer.clock, now).allowed) pointer.offlineAllowed = false;
  pointer.clock.highWaterMs = Math.max(pointer.clock.highWaterMs, now);
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ ready: !testControls, busy: false, error: null, session: null });
  const [settings, setSettings] = useState(compiledSettings);
  const [lifecycle] = useState(() => new SessionLifecycle<OpenSession>((session) => setState((s) => ({ ...s, session }))));
  const running = useRef(false);
  const stage = useRef<SessionStage | undefined>(undefined);

  const close = useCallback(() => {
    const now = Date.now();
    return lifecycle.retire(lifecycle.generation, async (previous) => {
      if (previous) {
        checkpoint(previous.pointer, now);
        await vault.writePointer(previous.pointer);
      }
    });
  }, [lifecycle]);
  async function action(work: (generation: number) => Promise<void>) {
    if (running.current) return;
    running.current = true;
    stage.current = undefined;
    setState((s) => ({ ...s, busy: true, error: null }));
    try { await lifecycle.settled(); await work(lifecycle.generation); }
    catch (error) {
      const message = sessionErrorMessage(error, developmentChecksEnabled ? stage.current : undefined);
      setState((s) => ({ ...s, error: message }));
    } finally { stage.current = undefined; running.current = false; setState((s) => ({ ...s, busy: false })); }
  }
  function clientFor(pointer: SessionPointer, repository: Repository, generation: number) {
    return new AuthClient(httpTransport(pointer.base, phase5Pilot ? 2 : 1), vault.credentials(pointer.partition), async () => {
      await lifecycle.retire(generation, async (previous) => {
        try {
          await vault.writePointer({ ...pointer, offlineAllowed: false });
          await repository.invalidateScope();
        } finally {
          // A denied initial sign-in has not published a session yet.
          if (previous?.repository !== repository) await repository.db.close();
        }
      });
    });
  }
  async function publish(session: OpenSession, generation: number) {
    if (!lifecycle.isCurrent(generation) || AppState.currentState !== 'active') {
      session.client.lock(); await session.repository.db.close(); throw new Error('session_locked');
    }
    lifecycle.publish(session, generation);
  }
  async function signIn(username: string, password: string) {
    await action(async () => {
      await close();
      const generation = lifecycle.generation;
      const old = await vault.readPointer();
      if (old) await vault.writePointer({ ...old, offlineAllowed: false });
      stage.current = 'sign_in_request';
      // A LAN backend may be reachable without validated public internet.
      // The bounded HTTP request, not Android's network hint, is authority.
      const transport = httpTransport(settings.apiBaseUrl, phase5Pilot ? 2 : 1);
      const login = tokenPairSchema.extend({ user: userSchema }).parse(await transport('/auth/login', { username, password }));
      stage.current = 'device_registration';
      const registration = registrationSchema.parse(await transport('/mobile-sync/devices', {
        installation_id: await vault.installation(settings.apiBaseUrl, login.user.id), app_version: '0.3.0',
        platform: 'android', protocol_version: 1, device_label: 'Farm Android',
      }, login.access));
      const identity = { actorId: login.user.id, deploymentId: registration.deployment_id, deviceId: registration.device_id };
      const partition = await storePartition(settings.apiBaseUrl, identity);
      stage.current = 'encrypted_store';
      const repository = await openEncrypted(partition, identity);
      let handedOff = false;
      try {
        const pointer: SessionPointer = { base: settings.apiBaseUrl, partition, identity, offlineAllowed: false,
          clock: { validatedLocalMs: 0, validatedServerMs: 0, highWaterMs: 0, operationalDays: 0, sensitiveHours: 0 } };
        await vault.credentials(partition).write({ refresh: registration.refresh, rotation: 'ready' });
        const client = clientFor(pointer, repository, generation);
        client.setAccess(registration.access);
        stage.current = 'current_user';
        const user = userSchema.parse(await client.read('/auth/me'));
        stage.current = 'capabilities';
        const capabilities = capabilitiesSchema.parse(await client.read('/mobile-sync/capabilities'));
        if (user.id !== identity.actorId || capabilities.deployment_id !== identity.deploymentId || capabilities.device_id !== identity.deviceId) throw new Error('server_identity_mismatch');
        const saved = await repository.metadata<CachedSession>('session');
        if (saved && saved.capabilities.scope_revision !== capabilities.scope_revision) await repository.invalidateScope();
        stage.current = 'save_session';
        await repository.setMetadata('session', { user, capabilities });
        const now = Date.now();
        pointer.offlineAllowed = true;
        pointer.clock = { validatedLocalMs: now, validatedServerMs: Date.parse(capabilities.server_time), highWaterMs: now,
          operationalDays: capabilities.offline.operational_days, sensitiveHours: capabilities.offline.sensitive_hours };
        await vault.writePointer(pointer);
        await publish({ user, capabilities, repository, pointer, client }, generation);
        handedOff = true;
      } finally { if (!handedOff) await repository.db.close(); }
    });
  }
  async function unlock() {
    await action(async (generation) => {
      const pointer = await vault.readPointer();
      if (!pointer || pointer.base !== settings.apiBaseUrl || !pointer.offlineAllowed) throw new Error('sign_in_required');
      const stored = await vault.credentials(pointer.partition).read();
      if (!stored || stored.rotation !== 'ready') throw new Error('sign_in_required');
      const access = offlineAccess(pointer.clock, Date.now());
      if (!access.allowed) {
        await vault.writePointer({ ...pointer, offlineAllowed: false });
        throw new Error(access.reason);
      }
      stage.current = 'encrypted_store';
      const repository = await openEncrypted(pointer.partition, pointer.identity);
      try {
        const afterUnlock = offlineAccess(pointer.clock, Date.now());
        if (!afterUnlock.allowed) throw new Error(afterUnlock.reason);
        const saved = await repository.metadata<CachedSession>('session');
        if (!saved) throw new Error('online_sign_in_required');
        const cached = { user: userSchema.parse(saved.user), capabilities: capabilitiesSchema.parse(saved.capabilities) };
        if (cached.user.id !== pointer.identity.actorId || cached.capabilities.deployment_id !== pointer.identity.deploymentId || cached.capabilities.device_id !== pointer.identity.deviceId) throw new Error('original_identity_mismatch');
        stage.current = 'save_session';
        pointer.clock.highWaterMs = Math.max(pointer.clock.highWaterMs, Date.now());
        await vault.writePointer(pointer);
        await publish({ ...cached, repository, pointer, client: clientFor(pointer, repository, generation) }, generation);
      } catch (error) { await repository.db.close(); throw error; }
    });
  }
  async function signOut() {
    await action(async (generation) => {
      let logout: { base: string; refresh: string } | undefined;
      // Detach before the first SecureStore await. A persistence error must
      // never leave the user's farm data or client open after sign-out.
      await lifecycle.retire(generation, async (previous) => {
        const pointer = previous?.pointer ?? await vault.readPointer();
        if (!pointer) return;
        pointer.offlineAllowed = false;
        await vault.writePointer(pointer);
        const credentials = vault.credentials(pointer.partition);
        const stored = await credentials.read();
        await credentials.write({ refresh: '', rotation: 'reauthenticate' });
        if (stored?.refresh && stored.rotation === 'ready') logout = { base: pointer.base, refresh: stored.refresh };
      });
      if (logout) {
        try { await httpTransport(logout.base)('/auth/logout', { refresh: logout.refresh }); }
        catch { setState((s) => ({ ...s, error: 'Signed out locally. Server logout was not confirmed; reconnect to revoke this device if needed.' })); }
      }
    });
  }
  async function switchTestBackend() {
    await action(async () => {
      if (!testBackendAvailable(settings, testControls)) throw new Error('test_backend_unavailable');
      await close();
      const previous = await vault.readPointer();
      if (previous) await vault.writePointer({ ...previous, offlineAllowed: false });
      const next = selectedTestBackend(settings.apiBaseUrl === testBackendA ? testBackendB : testBackendA, compiledSettings, testControls);
      await vault.writeTestBackend(next.apiBaseUrl);
      setSettings(next);
    });
  }
  async function revalidate(forceRefresh = false) {
    await action(async (generation) => {
      const session = lifecycle.current;
      if (!session) return;
      await lifecycle.failClosed(generation, async () => {
        // Disable cached restart before checking. Every failure, including
        // transport/schema errors, closes the previous visible authorization.
        session.pointer.offlineAllowed = false;
        await vault.writePointer(session.pointer);
        if (forceRefresh) {
          if (!testBackendAvailable(settings, testControls) || session.user.username !== 'mobile-test-worker') throw new Error('test_backend_unavailable');
          await session.client.refresh(); // Real Django rotation; no fabricated transport response.
        }
        const user = userSchema.parse(await session.client.read('/auth/me'));
        const capabilities = capabilitiesSchema.parse(await session.client.read('/mobile-sync/capabilities'));
        if (user.id !== session.pointer.identity.actorId || capabilities.device_id !== session.pointer.identity.deviceId || capabilities.deployment_id !== session.pointer.identity.deploymentId) throw new Error('sign_in_required');
        if (capabilities.scope_revision !== session.capabilities.scope_revision) await session.repository.invalidateScope();
        await session.repository.setMetadata('session', { user, capabilities });
        const now = Date.now();
        session.pointer.clock = { validatedLocalMs: now, validatedServerMs: Date.parse(capabilities.server_time), highWaterMs: now,
          operationalDays: capabilities.offline.operational_days, sensitiveHours: capabilities.offline.sensitive_hours };
        session.pointer.offlineAllowed = true;
        await vault.writePointer(session.pointer);
        await publish({ ...session, user, capabilities }, generation);
      });
    });
  }
  const authorizeSync = useCallback(async (): Promise<Capabilities> => {
    const session = lifecycle.current; const generation = lifecycle.generation;
    if (!session || running.current) throw new Error('session_locked');
    running.current=true;
    try { return await lifecycle.failClosed(generation,async () => {
      session.pointer.offlineAllowed=false; await vault.writePointer(session.pointer);
      const user=userSchema.parse(await session.client.read('/auth/me'));
      const capabilities=capabilitiesSchema.parse(await session.client.read('/mobile-sync/capabilities'));
      if (!lifecycle.isCurrent(generation) || lifecycle.current!==session || user.id!==session.pointer.identity.actorId ||
        capabilities.deployment_id!==session.pointer.identity.deploymentId || capabilities.device_id!==session.pointer.identity.deviceId) throw new Error('sign_in_required');
      if (session.capabilities.scope_revision!==capabilities.scope_revision) await session.repository.invalidateScope();
      await session.repository.setMetadata('session',{user,capabilities});
      const now=Date.now();
      session.pointer.clock={validatedLocalMs:now,validatedServerMs:Date.parse(capabilities.server_time),highWaterMs:now,
        operationalDays:capabilities.offline.operational_days,sensitiveHours:capabilities.offline.sensitive_hours};
      session.pointer.offlineAllowed=true;await vault.writePointer(session.pointer);
      if (!lifecycle.isCurrent(generation) || lifecycle.current!==session) throw new Error('session_locked');
      session.user=user;session.capabilities=capabilities;setState((s)=>({...s}));
      return capabilities;
    }); } finally { running.current=false; }
  },[lifecycle]);
  useEffect(() => {
    if (!testControls) return;
    let active = true;
    void vault.readTestBackend().then((base) => {
      if (active && base) setSettings(selectedTestBackend(base, compiledSettings, testControls));
    }).catch(() => {
      if (active) setState((s) => ({ ...s, error: 'Invalid synthetic backend selection. No store was opened.' }));
    }).finally(() => { if (active) setState((s) => ({ ...s, ready: true })); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const tick = async () => {
      const session = lifecycle.current;
      const generation = lifecycle.generation;
      if (!session) return;
      const now = Date.now();
      if (!offlineAccess(session.pointer.clock, now).allowed) {
        await lifecycle.retire(generation, async () => {
          await vault.writePointer({ ...session.pointer, offlineAllowed: false });
        });
        return;
      }
      await lifecycle.failClosed(generation, async () => {
        checkpoint(session.pointer, now);
        await vault.writePointer(session.pointer);
      });
    };
    const timer = setInterval(() => { void tick().catch(() => {}); }, 15_000);
    const subscription = AppState.addEventListener('change', (value) => {
      if (value !== 'active' && lifecycle.current) void close().catch(() => {});
    });
    return () => { clearInterval(timer); subscription.remove(); };
  }, [close, lifecycle]);
  return <Context.Provider value={{ ...state, settings, testControls, signIn, unlock, signOut, lock: close,
    revalidate: () => revalidate(), authorizeSync, switchTestBackend, testRefresh: () => revalidate(true) }}>{children}</Context.Provider>;
}
