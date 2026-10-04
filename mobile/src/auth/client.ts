import { tokenPairSchema } from '../protocol';
import { byteLength } from '../sync/protocol';

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, readonly retryAfterMs = 0) { super(code); }
}
export interface Credentials { refresh: string; rotation: 'ready' | 'in_flight' | 'reauthenticate' }
export interface CredentialStore {
  read(): Promise<Credentials | null>;
  write(value: Credentials, isCurrent?: () => boolean): Promise<void>;
}
export type Transport = (path: string, body?: unknown, access?: string) => Promise<unknown>;

// Access JWTs live only in memory. Durable rotation intent closes the crash/lost-response gap.
export class AuthClient {
  private access: string | null = null;
  private flight: Promise<void> | null = null;
  private denial: Promise<void> | null = null;
  private generation = 0;
  private locked = false;
  constructor(private transport: Transport, private credentials: CredentialStore, private onDenied: () => Promise<void>) {}

  setAccess(token: string) {
    if (this.locked) throw new ApiError(401, 'session_locked');
    this.access = token;
  }
  lock() { this.generation++; this.access = null; this.locked = true; }
  private deny() {
    if (!this.denial) { this.lock(); this.denial = this.onDenied(); }
    return this.denial;
  }
  async refresh(): Promise<void> {
    if (this.locked) throw new ApiError(401, 'session_locked');
    if (this.flight) return this.flight;
    const generation = this.generation;
    const isCurrent = () => generation === this.generation && !this.locked;
    const requireCurrent = () => { if (!isCurrent()) throw new ApiError(401, 'session_locked'); };
    this.flight = (async () => {
      const stored = await this.credentials.read();
      requireCurrent();
      if (!stored || stored.rotation !== 'ready') {
        await this.deny();
        throw new ApiError(401, 'sign_in_required');
      }
      // Write BEFORE sending. After a process death, never retry a possibly consumed refresh token.
      await this.credentials.write({ ...stored, rotation: 'in_flight' }, isCurrent);
      requireCurrent();
      try {
        const pair = tokenPairSchema.parse(await this.transport('/auth/refresh', { refresh: stored.refresh }));
        requireCurrent();
        await this.credentials.write({ refresh: pair.refresh, rotation: 'ready' }, isCurrent);
        requireCurrent();
        this.access = pair.access;
      } catch {
        // A locked client's late response cannot replace credentials from a
        // newer login or invoke its old session's denial callback.
        requireCurrent();
        this.access = null;
        // No token/content/logging in errors; no replay loop on transport ambiguity.
        try { await this.credentials.write({ refresh: '', rotation: 'reauthenticate' }, isCurrent); }
        finally { if (isCurrent()) await this.deny(); }
        throw new ApiError(401, 'sign_in_required');
      }
    })().finally(() => { this.flight = null; });
    return this.flight;
  }

  async read(path: '/auth/me' | '/mobile-sync/capabilities'): Promise<unknown> {
    return this.request(path);
  }
  async request(path: string, body?: unknown): Promise<unknown> {
    if (this.locked) throw new ApiError(401, 'session_locked');
    if (!['/auth/me', '/mobile-sync/capabilities','/mobile-sync/bootstrap','/mobile-sync/push','/mobile-sync/poultry-online'].includes(path) &&
      !/^\/mobile-sync\/(?:bootstrap\/[0-9a-f-]{36}\/pages\?cursor=[A-Za-z0-9%_.~-]+|changes\?cursor=[A-Za-z0-9%_.~-]+&limit=\d+|operations\/[0-9a-f-]{36})$/.test(path)) throw new ApiError(403, 'route_unavailable');
    if (path.length > 50000) throw new ApiError(400,'invalid_cursor');
    const generation = this.generation;
    if (!this.access) await this.refresh();
    const sent = this.access;
    try {
      const result = await this.transport(path, body, sent ?? undefined);
      if (generation !== this.generation) throw new ApiError(401, 'session_locked');
      return result;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (generation !== this.generation) throw new ApiError(401, 'session_locked');
      if (error.status === 403) { await this.deny(); throw error; }
      if (error.status !== 401) throw error;
      if (this.access === sent) await this.refresh();
      // Retry exactly once; another 401 requires sign-in, not another rotation.
      try {
        const result = await this.transport(path, body, this.access ?? undefined);
        if (generation !== this.generation) throw new ApiError(401, 'session_locked');
        return result;
      }
      catch (retryError) {
        if (generation !== this.generation) throw new ApiError(401, 'session_locked');
        if (retryError instanceof ApiError && [401, 403].includes(retryError.status)) {
          await this.deny();
        }
        throw retryError;
      }
    }
  }
}

export function httpTransport(base: string, poultryVersion: 1|2 = 1): Transport {
  return async (path, body, access) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30_000);
    try {
      const response = await fetch(`${base}${path}`, { method: body === undefined ? 'GET' : 'POST',
        signal: controller.signal, redirect: 'error', headers: { 'Content-Type': 'application/json',
          ...(poultryVersion === 2 ? { 'X-Mobile-Poultry-Version': '2' } : {}), ...(access ? { Authorization: `Bearer ${access}` } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (!response.ok) {
        // Deliberately do not echo arbitrary server error text, request bodies or JWTs.
        let code = response.status === 503 ? 'mobile_backend_not_ready' : `request_${response.status}`;
        const errorText = await response.text();
        if (errorText.length < 8192) {
          try { const supplied = JSON.parse(errorText).code;
            if (['resync_required','scope_reset_required','snapshot_not_found','snapshot_pack_mismatch','snapshot_limit','operation_not_found','unsupported_protocol'].includes(supplied)) code = supplied;
          } catch { /* Only allowlisted codes, never arbitrary error content. */ }
        }
        const retry = response.headers.get('Retry-After');
        const retryAfterMs = retry && /^\d+$/.test(retry) ? Math.min(Number(retry)*1000,86400000) :
          retry && Number.isFinite(Date.parse(retry)) ? Math.max(0,Math.min(Date.parse(retry)-Date.now(),86400000)) : 0;
        throw new ApiError(response.status,code,retryAfterMs);
      }
      if (response.status === 204) return null;
      if (Number(response.headers.get('Content-Length')) > 1024*1024) throw new Error('response_too_large');
      const text = await response.text();
      if (byteLength(text) > 1024*1024) throw new Error('response_too_large');
      return JSON.parse(text);
    } finally { clearTimeout(timeout); }
  };
}
