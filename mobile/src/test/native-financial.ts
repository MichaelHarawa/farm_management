/** Explicit local-acceptance scratch diagnostics. No HTTP/grant/financial session. */
import * as Crypto from 'expo-crypto';
import * as SecureStore from 'expo-secure-store';
import * as SQLite from 'expo-sqlite';
import * as LocalAuthentication from 'expo-local-authentication';
import { File } from 'expo-file-system';
import { z } from 'zod';
import { phase5Pilot } from '../build-mode.native';
import { sha256 } from '../db/native';
import { financialDatabaseFileUri } from '../db/file-uri';
import type { Database } from '../db/sql';
import { financialNamespace } from '../finance/key-database';
import { openNativeFinancialDatabase } from '../finance/native';
import { FinancialEvidenceStore } from '../finance/evidence-store';
import { containsProbeAscii, continueFinancialProbeSeed, financialProbeRollback, makeFinancialProbe, seedFinancialProbe,
  validateFinancialProbe, verifyFinancialProbe, type FinancialProbeDescriptor } from './financial-probe';
import { traceFinancialProbe, type FinancialProbeStep } from './financial-probe-diagnostics';

const marker = 'native-financial-storage-probe-v1';
const secure = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
const settings = { environment: 'development' as const, apiBaseUrl: 'http://10.0.2.2:7074/api/v1' };
let running = false;
function ensure(value: unknown): asserts value { if (!value) throw new Error('financial_scratch_check_failed'); }
async function exclusive(work: (step: (value: FinancialProbeStep) => void) => Promise<string>) {
  if (!phase5Pilot || running) throw new Error('financial_scratch_unavailable');
  running = true;
  try { return await traceFinancialProbe(work); } finally { running = false; }
}
async function descriptor() {
  const raw = await SecureStore.getItemAsync(marker, secure);
  if (!raw) throw new Error('prepare_financial_scratch_first');
  return validateFinancialProbe(JSON.parse(raw), sha256);
}
async function namespace(value: FinancialProbeDescriptor) { return financialNamespace(settings, value.identity, sha256); }
function file(name: string) { return new File(financialDatabaseFileUri(SQLite.defaultDatabaseDirectory, name)); }
async function closeCheckpoint(db: Database) { await db.exec('PRAGMA wal_checkpoint(TRUNCATE)'); await db.close(); }

async function encryptedReaders(value: FinancialProbeDescriptor) {
  const names = await namespace(value);
  const bytes = await file(names.database).bytes();
  ensure(bytes.length >= 4096 && !containsProbeAscii(bytes.slice(0, 16), 'SQLite format 3') &&
    !containsProbeAscii(bytes, value.operation.payload.external_reference));
  for (const wrongKey of [true, false]) {
    const raw = await SQLite.openDatabaseAsync(names.database, { useNewConnection: true });
    try {
      if (wrongKey) await raw.execAsync(`PRAGMA key="x'${'00'.repeat(32)}'"`);
      let refused = false;
      try { await raw.getFirstAsync('SELECT count(*) FROM sqlite_master'); } catch { refused = true; }
      ensure(refused);
    } finally { await raw.closeAsync(); }
  }
}

export function prepareNativeFinancialProbe() {
  return exclusive(async step => {
    step('descriptor_read');
    if (await SecureStore.getItemAsync(marker, secure)) throw new Error('existing_financial_scratch_retained');
    step('fixture_creation');
    const value = await makeFinancialProbe(Crypto.randomUUID, sha256);
    step('namespace');
    const names = await namespace(value);
    step('new_files');
    for (const name of [names.database, names.database + '-wal', names.database + '-shm']) ensure(!file(name).exists);
    step('new_keys');
    for (const key of [names.key, names.policy, names.access]) ensure(!await SecureStore.getItemAsync(key, secure));
    step('descriptor_write');
    await SecureStore.setItemAsync(marker, JSON.stringify(value), secure); // Retain descriptor even on cancellation/failure.
    step('keyed_open');
    const db = await openNativeFinancialDatabase(names, step);
    try {
      step('seed');
      await seedFinancialProbe(db, value, sha256);
      step('rollback');
      await financialProbeRollback(db, value, Crypto.randomUUID, sha256);
      step('checkpoint_close');
      await closeCheckpoint(db);
    } finally { await db.close(); }
    step('encrypted_readers');
    await encryptedReaders(value);
    return `PREPARED: financial scratch only. One immutable SQL fixture plus paired pending evidence; actual cipher, unkeyed/wrong-key refusal and atomic rollback checked. ID ${value.operation.operation_id}; hash ${value.commandHash}. No grant, financial capture, posting or upload. Force-stop externally, then Verify retained financial probe.`;
  });
}

export function verifyNativeFinancialProbe() {
  return exclusive(async step => {
    step('descriptor_read');
    const value = await descriptor();
    step('namespace');
    const names = await namespace(value);
    step('existing_file');
    ensure(file(names.database).exists); // Never create a missing retained scratch file.
    step('keyed_open');
    const db = await openNativeFinancialDatabase(names, step);
    try {
      step('verify');
      const store = await FinancialEvidenceStore.open(db, value.identity, sha256);
      await verifyFinancialProbe(db, value, sha256);
      step('locked');
      let locked = false;
      try { await store.page(); } catch (error) { locked = error instanceof Error && error.message === 'financial_storage_locked_retain_original'; }
      ensure(locked);
      step('checkpoint_close');
      await closeCheckpoint(db);
    } finally { await db.close(); }
    step('encrypted_readers');
    await encryptedReaders(value);
    return `PASS: exact retained financial scratch ID ${value.operation.operation_id}, original payload and hash ${value.commandHash}; paired pending evidence and encrypted/wrong-key/unkeyed checks pass. Store remains unauthorized. External force-stop/reboot evidence must be recorded separately. Scratch retained; no grant, payment, posting or upload tested.`;
  });
}

export function missingKeyNativeFinancialProbe() {
  return exclusive(async step => {
    step('descriptor_read');
    const value = await descriptor();
    step('namespace');
    const names = await namespace(value);
    step('existing_file');
    ensure(file(names.database).exists);
    step('keyed_open');
    const db = await openNativeFinancialDatabase(names, step);
    try {
      step('verify'); await FinancialEvidenceStore.open(db, value.identity, sha256); await verifyFinancialProbe(db, value, sha256);
      step('checkpoint_close'); await closeCheckpoint(db);
    }
    finally { await db.close(); }
    step('pin_policy');
    const policy = JSON.parse(await SecureStore.getItemAsync(names.policy, secure) ?? 'null');
    ensure(policy?.version === 1 && policy.policy === 'device-unlock' && policy.initialized === true); // Never downgrade biometrics.
    step('scratch_key_read');
    const original = await SecureStore.getItemAsync(names.key, { ...secure, requireAuthentication: false });
    ensure(original && /^[0-9a-f]{64}(?![\s\S])/.test(original));
    step('file_snapshot');
    const before = await file(names.database).bytes();
    // ONLY a verified newly owned scratch key. Never persist/export restoration material.
    try {
      step('missing_key');
      await SecureStore.deleteItemAsync(names.key, secure);
      let refused = false;
      try { const unexpected = await openNativeFinancialDatabase(names, step); await unexpected.close(); }
      catch (error) { refused = error instanceof Error && error.message === 'financial_database_key_missing'; }
      step('missing_key');
      ensure(refused && !await SecureStore.getItemAsync(names.key, secure));
      step('unchanged_file');
      const after = await file(names.database).bytes();
      ensure(before.length === after.length && before.every((byte, index) => byte === after[index]));
    } finally {
      // Preserve the failing check's step if restoration succeeds; expose restoration only if IT fails.
      try { await SecureStore.setItemAsync(names.key, original, { ...secure, requireAuthentication: false }); }
      catch (error) { step('restore_key'); throw error; }
    }
    step('restored_evidence');
    const reopened = await openNativeFinancialDatabase(names, step);
    try { step('restored_evidence'); await FinancialEvidenceStore.open(reopened, value.identity, sha256); await verifyFinancialProbe(reopened, value, sha256); }
    finally { await reopened.close(); }
    return `PASS: missing owned financial scratch key refused without resetting file or recreating key; in-memory restoration recovered exact original ID/payload/hash. Scratch retained. This is NOT recovery of a genuinely lost user key or biometric acceptance.`;
  });
}

/** No key reads, PIN, DB open, HTTP, writes or deletion. The descriptor is synthetic only. */
export function inspectNativeFinancialProbe() {
  return exclusive(async step => {
    step('descriptor_read');
    const raw = await SecureStore.getItemAsync(marker, secure);
    step('enrollment');
    const level = await LocalAuthentication.getEnrolledLevelAsync();
    const enrollment = level === LocalAuthentication.SecurityLevel.SECRET ? 'PIN/password enrolled' :
      level === LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG ? 'strong biometrics enrolled' :
      level === LocalAuthentication.SecurityLevel.BIOMETRIC_WEAK ? 'weak biometrics enrolled' : 'no device unlock enrolled';
    if (!raw) return `INSPECTED (read-only): no scratch descriptor retained; ${enrollment}. No key, PIN, SQL or upload was used. This is not a PASS.`;
    step('descriptor_read');
    const value = await validateFinancialProbe(JSON.parse(raw), sha256);
    step('namespace');
    const names = await namespace(value);
    step('inspection');
    const main = file(names.database).exists, wal = file(names.database + '-wal').exists, shm = file(names.database + '-shm').exists;
    const policyRaw = await SecureStore.getItemAsync(names.policy, secure);
    const policySchema = z.strictObject({ version: z.literal(1), policy: z.enum(['biometric', 'device-unlock']), initialized: z.boolean() });
    let policy = 'missing';
    if (policyRaw) {
      let parsed: unknown;
      try { parsed = JSON.parse(policyRaw); } catch { /* Report fixed invalid state only. */ }
      const checked = policySchema.safeParse(parsed);
      policy = checked.success ? `${checked.data.policy}, initialized=${checked.data.initialized}` : 'invalid (retained)';
    }
    return `INSPECTED (read-only): original synthetic descriptor valid; main=${main}, WAL=${wal}, SHM=${shm}; key policy=${policy}; ${enrollment}. No key, PIN, SQL, write or upload. This is not a PASS. Continue retained preparation requires the original main file; never press Prepare to replace this descriptor.`;
  });
}

/** Resume only an EXISTING main scratch file; a missing file can never be replaced here. */
export function continueNativeFinancialProbe() {
  return exclusive(async step => {
    step('descriptor_read'); const value = await descriptor();
    step('namespace'); const names = await namespace(value);
    step('existing_file'); ensure(file(names.database).exists);
    step('keyed_open'); const db = await openNativeFinancialDatabase(names, step);
    try {
      step('seed'); await continueFinancialProbeSeed(db, value, sha256);
      step('rollback'); await financialProbeRollback(db, value, Crypto.randomUUID, sha256);
      step('checkpoint_close'); await closeCheckpoint(db);
    } finally { await db.close(); }
    step('encrypted_readers'); await encryptedReaders(value);
    return `PREPARED: original retained financial scratch continued, ID ${value.operation.operation_id}; hash ${value.commandHash}. No original file, key or operation was replaced. Cipher/rollback/readers checked; no grant, payment or upload. Force-stop externally, then Verify retained financial probe.`;
  });
}
