import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { FinancialEvidenceStore, financialEvidenceHashInput } from '../src/finance/evidence-store';
import { canonical } from '../src/db/repository';
import { hostDatabase } from './helpers';
import { containsProbeAscii, continueFinancialProbeSeed, financialProbeRollback, makeFinancialProbe, seedFinancialProbe,
  validateFinancialProbe, verifyFinancialProbe } from '../src/test/financial-probe';

const sha = async (value: string) => createHash('sha256').update(value).digest('hex');

test('financial scratch fixture is strict, random, exact-decimal evidence with no invented authority', async () => {
  const first = await makeFinancialProbe(randomUUID, sha), next = await makeFinancialProbe(randomUUID, sha);
  assert.notEqual(first.nonce, next.nonce);
  assert.notDeepEqual(first.identity, next.identity);
  assert.notEqual(first.operation.operation_id, next.operation.operation_id);
  assert.equal(first.operation.payload.total_payment_amount, '12.34');
  assert.equal(first.operation.captured_at, '2026-10-16T06:00:00.123456Z');
  assert.equal(first.commandHash, await sha(financialEvidenceHashInput(first.identity, first.operation)));
  assert.equal('grant' in first || 'accepted' in first || 'token' in first, false);
  assert.deepEqual(await validateFinancialProbe(JSON.parse(JSON.stringify(first)), sha), first);
  await assert.rejects(validateFinancialProbe({ ...first, grant: {} }, sha));
});

test('real host SQLite scratch seeding stays unauthorized and rollback retains one exact original pair', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await seedFinancialProbe(db, fixture, sha);
    await financialProbeRollback(db, fixture, randomUUID, sha);
    const store = await FinancialEvidenceStore.open(db, fixture.identity, sha);
    await assert.rejects(store.page(), /financial_storage_locked_retain_original/);
    await assert.rejects(store.capture(fixture.operation), /financial_storage_locked_retain_original/);
    assert.equal((await db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version, 1);
    assert.equal(await db.first("SELECT * FROM financial_meta WHERE key='authorization'"), null);
    await verifyFinancialProbe(db, fixture, sha);
  } finally { await db.close(); }
});

test('owned on-disk scratch reopen proves the original operation payload hash and pending linkage without a grant', async t => {
  const directory = await mkdtemp(join(tmpdir(), 'farm-native-financial-fixture-'));
  t.after(() => rm(directory, { recursive: true, force: true })); // This newly owned host test folder only.
  const path = join(directory, 'scratch.db'), fixture = await makeFinancialProbe(randomUUID, sha);
  const first = hostDatabase(path);
  try { await seedFinancialProbe(first, fixture, sha); } finally { await first.close(); }
  const second = hostDatabase(path);
  try {
    const store = await FinancialEvidenceStore.open(second, fixture.identity, sha);
    await verifyFinancialProbe(second, JSON.parse(JSON.stringify(fixture)), sha);
    await assert.rejects(store.page(), /financial_storage_locked_retain_original/);
    const row = await second.first<{ operation_id: string; operation_json: string; command_hash: string }>('SELECT * FROM financial_commands');
    assert.equal(row?.operation_id, fixture.operation.operation_id);
    assert.equal(row?.operation_json, canonical(fixture.operation));
    assert.equal(row?.command_hash, fixture.commandHash);
  } finally { await second.close(); }
});

test('scratch descriptor changes refuse rather than creating a replacement command or treating real payment as fixture', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha);
  for (const changed of [
    { ...fixture, nonce: randomUUID() }, { ...fixture, commandHash: '0'.repeat(64) },
    { ...fixture, identity: { ...fixture.identity, actorId: randomUUID() } },
    { ...fixture, operation: { ...fixture.operation, operation_id: randomUUID() } },
    { ...fixture, operation: { ...fixture.operation, payload: { ...fixture.operation.payload, payee: 'Actual supplier' } } },
    { ...fixture, operation: { ...fixture.operation, payload: { ...fixture.operation.payload, total_payment_amount: '12.35' } } },
  ]) await assert.rejects(validateFinancialProbe(changed, sha));
});

test('another valid scratch identity/owner cannot verify or fault-inject over the original rows', async () => {
  const original = await makeFinancialProbe(randomUUID, sha), foreign = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await seedFinancialProbe(db, original, sha);
    const before = await db.all('SELECT * FROM financial_commands');
    await assert.rejects(verifyFinancialProbe(db, foreign, sha), /financial_scratch_integrity_failed/);
    await assert.rejects(financialProbeRollback(db, foreign, randomUUID, sha), /financial_scratch_integrity_failed/);
    assert.equal(await db.first("SELECT * FROM sqlite_master WHERE name='native_financial_probe_abort'"), null);
    assert.deepEqual(await db.all('SELECT * FROM financial_commands'), before);
    await verifyFinancialProbe(db, original, sha);
  } finally { await db.close(); }
});

test('fault while first scratch pair is seeded rolls back its owner marker and command, never invents success', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await FinancialEvidenceStore.open(db, fixture.identity, sha);
    await db.exec("CREATE TRIGGER injected_first_seed_abort BEFORE INSERT ON financial_delivery BEGIN SELECT RAISE(ABORT,'injected_first_seed'); END");
    await assert.rejects(seedFinancialProbe(db, fixture, sha), /injected_first_seed/);
    assert.equal((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_commands'))?.count, 0);
    assert.equal((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_delivery'))?.count, 0);
    assert.equal(await db.first("SELECT * FROM financial_meta WHERE key='native-scratch-owner'"), null);
    await assert.rejects(verifyFinancialProbe(db, fixture, sha), /financial_scratch_integrity_failed/);
  } finally { await db.close(); }
});

test('native encrypted-file ASCII scanner detects exact plaintext markers without logging bytes or keys', () => {
  const bytes = new TextEncoder().encode('prefix-SYNTHETIC-P6-marker-suffix');
  assert.equal(containsProbeAscii(bytes, 'SYNTHETIC-P6-marker'), true);
  assert.equal(containsProbeAscii(bytes, 'different-marker'), false);
  assert.equal(containsProbeAscii(bytes.slice(0, 5), 'SYNTHETIC-P6-marker'), false);
  assert.equal(containsProbeAscii(new TextEncoder().encode('SQLite format 3\0'), 'SQLite format 3'), true);
});

test('explicit scratch continuation seeds only a pristine original schema then retains exact evidence on repeat', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await FinancialEvidenceStore.open(db, fixture.identity, sha);
    assert.equal(await continueFinancialProbeSeed(db, fixture, sha), 'seeded_original');
    const before = await db.all('SELECT * FROM financial_commands');
    assert.equal(await continueFinancialProbeSeed(db, fixture, sha), 'retained_original');
    assert.deepEqual(await db.all('SELECT * FROM financial_commands'), before);
    await verifyFinancialProbe(db, fixture, sha);
    assert.equal(await db.first("SELECT * FROM financial_meta WHERE key='authorization'"), null);
  } finally { await db.close(); }
});

test('scratch continuation refuses partial evidence without filling a missing pending row or reseeding', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await FinancialEvidenceStore.open(db, fixture.identity, sha);
    await db.run('INSERT INTO financial_commands VALUES(?,?,?,?)', [fixture.operation.operation_id, canonical(fixture.operation), fixture.commandHash, 1]);
    const before = await db.all('SELECT * FROM financial_commands');
    await assert.rejects(continueFinancialProbeSeed(db, fixture, sha), /financial_scratch_integrity_failed/);
    assert.deepEqual(await db.all('SELECT * FROM financial_commands'), before);
    assert.equal((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_delivery'))?.count, 0);
  } finally { await db.close(); }
});

test('scratch continuation cannot reattribute an original fixture to a new valid descriptor', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), foreign = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await seedFinancialProbe(db, fixture, sha);
    const before = await db.all('SELECT * FROM financial_meta');
    await assert.rejects(continueFinancialProbeSeed(db, foreign, sha), /financial_storage_identity_mismatch_retain_original/);
    assert.deepEqual(await db.all('SELECT * FROM financial_meta'), before);
    await verifyFinancialProbe(db, fixture, sha);
  } finally { await db.close(); }
});

test('scratch continuation refuses unauthorized owner/authorization metadata even on an otherwise empty schema', async () => {
  for (const metadata of [['native-scratch-owner', randomUUID()], ['authorization', '{"blocked":true}']] as const) {
    const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
    try {
      await FinancialEvidenceStore.open(db, fixture.identity, sha);
      await db.run('INSERT INTO financial_meta VALUES(?,?)', [...metadata]);
      const before = await db.all('SELECT * FROM financial_meta');
      await assert.rejects(continueFinancialProbeSeed(db, fixture, sha), /financial_scratch_integrity_failed/);
      assert.deepEqual(await db.all('SELECT * FROM financial_meta'), before);
      assert.equal((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_commands'))?.count, 0);
    } finally { await db.close(); }
  }
});

test('scratch continuation refuses blank or truncated retained schema instead of reinitializing it', async () => {
  const fixture = await makeFinancialProbe(randomUUID, sha), db = hostDatabase();
  try {
    await assert.rejects(continueFinancialProbeSeed(db, fixture, sha), /financial_scratch_integrity_failed/);
    assert.equal((await db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version, 0);
    assert.deepEqual(await db.all("SELECT name FROM sqlite_master WHERE type='table'"), []);
  } finally { await db.close(); }
});
