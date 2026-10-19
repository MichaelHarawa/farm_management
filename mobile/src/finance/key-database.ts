/** Independently keyed financial database. No deletion, reset or key downgrade. */
import { z } from 'zod';
import { validateSettings, type AppSettings } from '../config';
import { canonical } from '../db/repository';
import type { Database } from '../db/sql';
import { uuid, type StoreIdentity } from '../protocol';

const hex = z.string().regex(/^[0-9a-f]{64}(?![\s\S])/);
const identitySchema = z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid });
const policySchema = z.strictObject({ version: z.literal(1), policy: z.enum(['biometric', 'device-unlock']), initialized: z.boolean() });
export interface FinancialKeys {
  get(name: string, authenticated?: boolean): Promise<string | null>;
  set(name: string, value: string, authenticated?: boolean): Promise<void>;
}
export interface FinancialDatabasePorts {
  hash(value: string): Promise<string>;
  randomKey(): Promise<string>;
  unlock(): Promise<boolean>;
  keys: FinancialKeys;
  exists(name: string): Promise<boolean>;
  open(name: string): Promise<Database>;
}
export interface FinancialNamespace { partition: string; database: string; key: string; policy: string; access: string }
export type FinancialDatabaseStep = 'native_files' | 'native_policy_read' | 'native_unlock' | 'native_policy_write' |
  'native_key_read' | 'native_key_generation' | 'native_key_write' | 'native_sqlite_open' | 'native_cipher_key' |
  'native_cipher_version' | 'native_schema_read' | 'native_modes' | 'native_policy_finalize';
const owners = new Set<string>();

export async function financialNamespace(settings: AppSettings, identity: StoreIdentity, hash: FinancialDatabasePorts['hash']): Promise<FinancialNamespace> {
  const base = validateSettings(settings.environment, settings.apiBaseUrl).apiBaseUrl;
  const bound = identitySchema.parse(identity);
  const partition = hex.parse(await hash(canonical({ profile: 'financial-evidence-private-v1', base, identity: bound })));
  return { partition, database: `farm-finance-v1-${partition}.db`, key: `finance-key-v1-${partition}`,
    policy: `finance-policy-v1-${partition}`, access: `finance-access-v1-${partition}` };
}

/** Caller initializes/verifies schema BEFORE returning an accessible repository. */
export async function openFinancialDatabase(namespace: FinancialNamespace, ports: FinancialDatabasePorts,
  trace?: (step: FinancialDatabaseStep) => void): Promise<Database> {
  const id = hex.parse(namespace.partition);
  if (namespace.database !== `farm-finance-v1-${id}.db` || namespace.key !== `finance-key-v1-${id}` ||
      namespace.policy !== `finance-policy-v1-${id}` || namespace.access !== `finance-access-v1-${id}`) throw new Error('financial_namespace_mismatch');
  if (owners.has(id)) throw new Error('financial_database_already_owned');
  owners.add(id);
  let db: Database | null = null;
  try {
    trace?.('native_files');
    // Check ALL companions. An orphaned encrypted WAL must never become a fresh
    // blank store merely because its main database file is missing.
    const [main, wal, shm] = await Promise.all([ports.exists(namespace.database), ports.exists(namespace.database + '-wal'), ports.exists(namespace.database + '-shm')]);
    if (!main && (wal || shm)) throw new Error('financial_database_missing_retain_key');
    trace?.('native_policy_read');
    const raw = await ports.keys.get(namespace.policy);
    let policy = raw ? policySchema.parse(JSON.parse(raw)) : null;
    if (!policy && main) throw new Error('financial_database_key_missing');
    if (policy?.initialized && !main) throw new Error('financial_database_missing_retain_key');
    trace?.('native_unlock');
    const strong = await ports.unlock();
    if (!policy) {
      policy = { version: 1, policy: strong ? 'biometric' : 'device-unlock', initialized: false };
      trace?.('native_policy_write');
      await ports.keys.set(namespace.policy, JSON.stringify(policy));
    }
    const authenticated = policy.policy === 'biometric'; // NEVER downgrade an existing biometric key.
    trace?.('native_key_read');
    let key = await ports.keys.get(namespace.key, authenticated);
    if (!key) {
      if (main || policy.initialized) throw new Error('financial_database_key_missing');
      trace?.('native_key_generation');
      key = hex.parse(await ports.randomKey());
      trace?.('native_key_write');
      await ports.keys.set(namespace.key, key, authenticated);
    }
    key = hex.parse(key);
    trace?.('native_sqlite_open');
    db = await ports.open(namespace.database);
    trace?.('native_cipher_key');
    await db.exec(`PRAGMA key="x'${key}'";`); // Only validated 32-byte random hex, NEVER user input.
    trace?.('native_cipher_version');
    const cipher = await db.first<Record<string, unknown>>('PRAGMA cipher_version');
    if (!cipher || !Object.values(cipher).some(value => typeof value === 'string' && value.length > 0)) throw new Error('sqlcipher_native_build_required');
    trace?.('native_schema_read');
    await db.first('SELECT count(*) FROM sqlite_master'); // Wrong key/corrupt DB must fail, never reset.
    trace?.('native_modes');
    await db.exec('PRAGMA journal_mode=WAL; PRAGMA secure_delete=ON;');
    if (!policy.initialized) {
      trace?.('native_policy_finalize');
      await ports.keys.set(namespace.policy, JSON.stringify({ ...policy, initialized: true }));
    }
    const opened = db;
    let closed = false, closing: Promise<void> | null = null;
    return { ...opened, close() {
      if (closed) return Promise.resolve();
      if (closing) return closing;
      closing = opened.close().then(() => { closed = true; owners.delete(id); }).catch(() => {
        closing = null; // Keep ownership if native close failed; a second handle must not open.
        throw new Error('financial_database_close_failed');
      });
      return closing;
    } };
  } catch (error) {
    let safelyClosed = db === null;
    try { await db?.close(); safelyClosed = true; } catch { /* Keep process ownership quarantined. */ }
    if (safelyClosed) owners.delete(id);
    const safe = ['financial_database_missing_retain_key', 'financial_database_key_missing', 'sqlcipher_native_build_required',
      'device_lock_required', 'device_unlock_cancelled'];
    if (error instanceof Error && safe.includes(error.message)) throw error;
    throw new Error('financial_database_open_failed_retain_original'); // Never echo a native SQL/key error.
  }
}
