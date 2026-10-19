/** Native-port CONTROL FLOW only; the cipher response is a double, not encryption proof. */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { financialNamespace, openFinancialDatabase, type FinancialDatabasePorts } from '../src/finance/key-database';
import { hostDatabase, identity } from './helpers';

const sha = async (value: string) => createHash('sha256').update(value).digest('hex');
const settings = { environment: 'development' as const, apiBaseUrl: 'http://10.0.2.2:7074/api/v1' };
async function fixture() {
  const namespace = await financialNamespace(settings, { ...identity, actorId: randomUUID() }, sha);
  const values = new Map<string, string>(), files = new Set<string>(), events: string[] = [];
  const state = { strong: false, cipher: true, keyFailure: false, closeFailure: false, opens: 0, randoms: 0 };
  const ports: FinancialDatabasePorts = { hash: sha,
    async randomKey() { state.randoms++; return 'f'.repeat(64); },
    async unlock() { events.push('unlock'); return state.strong; },
    keys: {
      async get(name, authenticated) { events.push(name === namespace.key ? `key_get_${authenticated}` : 'policy_get'); return values.get(name) ?? null; },
      async set(name, value, authenticated) { events.push(name === namespace.key ? `key_set_${authenticated}` : 'policy_set'); values.set(name, value); },
    },
    async exists(name) { return files.has(name); },
    async open(name) {
      state.opens++; files.add(name); events.push('open');
      const db = hostDatabase();
      return { ...db, async exec(sql) {
        if (sql.startsWith('PRAGMA key=')) { events.push('key_applied'); if (state.keyFailure) throw new Error('PRIVATE-KEY-OR-SQL-MUST-NOT-ESCAPE'); }
        return db.exec(sql);
      }, async first<T>(sql: string, args?: Parameters<typeof db.run>[1]): Promise<T | null> {
        if (sql === 'PRAGMA cipher_version') { events.push('cipher_probe'); return state.cipher ? { cipher_version: 'HOST-DOUBLE-NOT-SQLCIPHER' } as T : null; }
        return db.first<T>(sql, args);
      }, async close() {
        events.push('close');
        if (state.closeFailure) throw new Error('synthetic_native_close_failure');
        await db.close();
      } };
    },
  };
  return { namespace, values, files, events, state, ports };
}

test('financial namespace is independent and includes canonical backend, actor, deployment AND device', async () => {
  const original = await financialNamespace(settings, identity, sha);
  assert.match(original.database, /^farm-finance-v1-/);
  assert.match(original.key, /^finance-key-v1-/);
  assert.notEqual(original.key, `db-key-${original.partition}`);
  for (const key of ['actorId', 'deviceId', 'deploymentId'] as const) {
    assert.notDeepEqual(await financialNamespace(settings, { ...identity, [key]: randomUUID() }, sha), original);
  }
  assert.notDeepEqual(await financialNamespace({ ...settings, apiBaseUrl: 'http://10.0.2.2:7073/api/v1' }, identity, sha), original);
  await assert.rejects(financialNamespace({ ...settings, apiBaseUrl: 'https://user:secret@example.invalid/api/v1' }, identity, sha));
  await assert.rejects(financialNamespace(settings, identity, async () => 'a'.repeat(64) + '\n'));
});

test('new PIN-only store uses its own key and configures the SAME handle before cipher/schema reads', async () => {
  const f = await fixture();
  const db = await openFinancialDatabase(f.namespace, f.ports);
  try {
    assert.equal(f.state.randoms, 1);
    assert.equal(f.values.get(f.namespace.key), 'f'.repeat(64));
    assert.deepEqual(JSON.parse(f.values.get(f.namespace.policy)!), { version: 1, policy: 'device-unlock', initialized: true });
    assert.ok(f.events.indexOf('key_applied') < f.events.indexOf('cipher_probe'));
    assert.ok(f.events.includes('key_get_false'));
  } finally { await db.close(); }
});

test('optional financial native tracing carries only closed stage codes, never names keys or SQL', async () => {
  const f = await fixture(), stages: string[] = [];
  const db = await openFinancialDatabase(f.namespace, f.ports, stage => stages.push(stage));
  try {
    assert.deepEqual(stages, ['native_files', 'native_policy_read', 'native_unlock', 'native_policy_write', 'native_key_read',
      'native_key_generation', 'native_key_write', 'native_sqlite_open', 'native_cipher_key', 'native_cipher_version',
      'native_schema_read', 'native_modes', 'native_policy_finalize']);
    assert.doesNotMatch(stages.join('|'), new RegExp(`${f.namespace.partition}|${'f'.repeat(64)}|PRAGMA`));
  } finally { await db.close(); }
});

test('optional stage callback identifies native key-apply failure while redaction and cleanup stay unchanged', async () => {
  const f = await fixture(), stages: string[] = []; f.state.keyFailure = true;
  await assert.rejects(openFinancialDatabase(f.namespace, f.ports, stage => stages.push(stage)), error =>
    error instanceof Error && error.message === 'financial_database_open_failed_retain_original');
  assert.equal(stages.at(-1), 'native_cipher_key'); assert.ok(f.events.includes('close'));
  assert.doesNotMatch(stages.join('|'), /PRIVATE|SQL|PRAGMA/);
});

test('a failed diagnostic callback cannot skip native unlock or leave database ownership stuck', async () => {
  const f = await fixture();
  await assert.rejects(openFinancialDatabase(f.namespace, f.ports, stage => {
    if (stage === 'native_unlock') throw new Error('PRIVATE observer failure');
  }), /financial_database_open_failed_retain_original/);
  assert.equal(f.events.includes('unlock'), false); assert.equal(f.state.opens, 0); assert.equal(f.state.randoms, 0);
  const db = await openFinancialDatabase(f.namespace, f.ports);
  try { assert.equal(f.state.opens, 1); assert.equal(f.events.includes('unlock'), true); }
  finally { await db.close(); }
});

test('an existing biometric policy NEVER downgrades on a later PIN-only unlock', async () => {
  const f = await fixture();
  f.files.add(f.namespace.database);
  f.values.set(f.namespace.policy, JSON.stringify({ version: 1, policy: 'biometric', initialized: true }));
  f.values.set(f.namespace.key, 'a'.repeat(64));
  const db = await openFinancialDatabase(f.namespace, f.ports);
  try {
    assert.ok(f.events.includes('key_get_true'));
    assert.equal(f.state.randoms, 0);
    assert.equal(JSON.parse(f.values.get(f.namespace.policy)!).policy, 'biometric');
  } finally { await db.close(); }
});

test('missing policy or key beside an existing database refuses without replacement or reset', async () => {
  for (const missing of ['policy', 'key'] as const) {
    const f = await fixture();
    f.files.add(f.namespace.database);
    if (missing === 'key') f.values.set(f.namespace.policy, JSON.stringify({ version: 1, policy: 'device-unlock', initialized: true }));
    const before = [...f.values];
    await assert.rejects(openFinancialDatabase(f.namespace, f.ports), /key_missing/);
    assert.deepEqual([...f.values], before); assert.equal(f.state.randoms, 0); assert.equal(f.state.opens, 0);
    assert.equal(f.files.size, 1);
  }
});

test('missing initialized database or orphaned WAL/SHM cannot become a fresh blank store', async () => {
  for (const companion of ['', '-wal', '-shm']) {
    const f = await fixture();
    f.values.set(f.namespace.policy, JSON.stringify({ version: 1, policy: 'device-unlock', initialized: true }));
    f.values.set(f.namespace.key, 'a'.repeat(64));
    if (companion) f.files.add(f.namespace.database + companion);
    const before = [...f.values];
    await assert.rejects(openFinancialDatabase(f.namespace, f.ports), /database_missing_retain_key/);
    assert.deepEqual([...f.values], before); assert.equal(f.state.opens, 0); assert.equal(f.state.randoms, 0);
  }
});

test('interrupted pre-file provisioning may resume with the SAME key, not silently generate another', async () => {
  const f = await fixture();
  f.values.set(f.namespace.policy, JSON.stringify({ version: 1, policy: 'device-unlock', initialized: false }));
  f.values.set(f.namespace.key, 'a'.repeat(64));
  const db = await openFinancialDatabase(f.namespace, f.ports);
  try { assert.equal(f.state.randoms, 0); assert.equal(f.values.get(f.namespace.key), 'a'.repeat(64)); }
  finally { await db.close(); }
});

test('unknown policy, malformed key, absent cipher or keying error are safe failures without resets', async () => {
  for (const failure of ['policy', 'key', 'cipher', 'pragma'] as const) {
    const f = await fixture();
    if (failure === 'policy') f.values.set(f.namespace.policy, '{PRIVATE-INVALID');
    if (failure === 'key') { f.values.set(f.namespace.policy, JSON.stringify({ version: 1, policy: 'device-unlock', initialized: false })); f.values.set(f.namespace.key, 'PRIVATE-INVALID'); }
    if (failure === 'cipher') f.state.cipher = false;
    if (failure === 'pragma') f.state.keyFailure = true;
    await assert.rejects(openFinancialDatabase(f.namespace, f.ports), error => error instanceof Error &&
      /^(financial_database_open_failed_retain_original|sqlcipher_native_build_required)$/.test(error.message));
    assert.ok([...f.values.keys()].every(key => key === f.namespace.policy || key === f.namespace.key));
    if (f.state.opens) assert.equal(f.events.at(-1), 'close');
  }
});

test('single owner excludes a second opener until successful close, including a failed native close', async () => {
  const f = await fixture();
  const db = await openFinancialDatabase(f.namespace, f.ports);
  await assert.rejects(openFinancialDatabase(f.namespace, f.ports), /already_owned/);
  f.state.closeFailure = true;
  await assert.rejects(db.close(), /financial_database_close_failed/);
  await assert.rejects(openFinancialDatabase(f.namespace, f.ports), /already_owned/);
  f.state.closeFailure = false;
  await db.close();
  const reopened = await openFinancialDatabase(f.namespace, f.ports);
  await reopened.close();
  assert.equal(f.state.randoms, 1);
});

test('unlock cancellation creates neither key nor database and releases opener ownership', async () => {
  const f = await fixture();
  const original = f.ports.unlock;
  f.ports.unlock = async () => { throw new Error('device_unlock_cancelled'); };
  await assert.rejects(openFinancialDatabase(f.namespace, f.ports), /device_unlock_cancelled/);
  assert.equal(f.values.size, 0); assert.equal(f.state.opens, 0);
  f.ports.unlock = original;
  const db = await openFinancialDatabase(f.namespace, f.ports); await db.close();
});

test('tampered namespace cannot redirect finance opener to an operational database/key', async () => {
  const f = await fixture();
  await assert.rejects(openFinancialDatabase({ ...f.namespace, database: `farm-${f.namespace.partition}.db` }, f.ports), /namespace_mismatch/);
  assert.equal(f.state.opens, 0); assert.equal(f.events.length, 0);
});
