import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { migrate, Repository, normalizedInstant } from '../src/db/repository';
import { migrations } from '../src/db/schema';
import { hostDatabase, command, identity } from './helpers';
const hash = async (value: string) => createHash('sha256').update(value).digest('hex');
async function setup(path?: string) {
  const db = hostDatabase(path); await migrate(db); const repo = new Repository(db, identity); await repo.bindIdentity();
  await db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)', ['poultry.batch', command.payload.batch_uuid, '9007199254740993', '{"amount":"9007199254740993.01"}']);
  return repo;
}
test('prepared insert: atomic overlay/outbox, immutable UUID/content, exact payload', async () => {
  const repo = await setup();
  try {
    await repo.saveDraftAndEnqueue(command, hash);
    assert.equal(await repo.queueCount(), 1);
    const stored = await repo.db.first<{ command_json: string }>('SELECT command_json FROM outbox');
    assert.deepEqual(JSON.parse(stored!.command_json), command);
    assert.equal((await repo.batches())[0]?.payload_json, '{"amount":"9007199254740993.01"}');
    await assert.rejects(repo.db.run('UPDATE outbox SET command_json=?', ['changed']), /immutable_operation/);
    await assert.rejects(repo.saveDraftAndEnqueue(command, hash), /UNIQUE/);
    await assert.rejects(repo.db.run('DELETE FROM outbox'), /retain_operation_evidence/);
    await assert.rejects(repo.db.run('INSERT INTO operation_dependencies VALUES(?,?)', [command.operation_id, randomUUID()]), /FOREIGN KEY/);
    await assert.rejects(repo.saveDraftAndEnqueue({ ...command, operation_id: randomUUID(), payload: { ...command.payload, batch_uuid: randomUUID() } }, hash), /download_parent_first/);
  } finally { await repo.db.close(); }
});
test('failure between draft and outbox rolls back both; scoped quarantine preserves evidence', async () => {
  const repo = await setup();
  try {
    await repo.db.exec("CREATE TRIGGER injected BEFORE INSERT ON pending_overlays BEGIN SELECT RAISE(ABORT,'disk_failure'); END;");
    await assert.rejects(repo.saveDraftAndEnqueue(command, hash), /disk_failure/);
    assert.equal(await repo.queueCount(), 0);
    assert.equal((await repo.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))!.count, 0);
    await repo.db.exec('DROP TRIGGER injected');
    await repo.saveDraftAndEnqueue(command, hash);
    await repo.invalidateScope();
    assert.equal((await repo.batches()).length, 0);
    assert.equal(await repo.queueCount(), 1);
    assert.equal((await repo.db.first<{ state: string }>('SELECT state FROM outbox'))!.state, 'quarantined');
  } finally { await repo.db.close(); }
});
test('migration rollback and close/reopen retain previous schema and original identity', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'farm-mobile-owned-test-'));
  const path = join(directory, 'owned.db');
  let repo = await setup(path);
  try {
    await repo.saveDraftAndEnqueue(command, hash);
    await assert.rejects(migrate(repo.db, [...migrations, 'CREATE TABLE failed_upgrade(id TEXT); INVALID SQL;']));
    assert.equal((await repo.db.first<{ user_version: number }>('PRAGMA user_version'))!.user_version, migrations.length);
    assert.equal(await repo.db.first("SELECT name FROM sqlite_master WHERE name='failed_upgrade'"), null);
    await repo.db.close();
    repo = new Repository(hostDatabase(path), identity); await migrate(repo.db); await repo.bindIdentity();
    assert.equal(await repo.queueCount(), 1);
    await assert.rejects(new Repository(repo.db, { ...identity, actorId: randomUUID() }).bindIdentity(), /original_identity_mismatch/);
    await assert.rejects(new Repository(repo.db, { ...identity, deploymentId: randomUUID() }).bindIdentity(), /original_identity_mismatch/);
    await assert.rejects(new Repository(repo.db, { ...identity, deviceId: randomUUID() }).bindIdentity(), /original_identity_mismatch/);
    await assert.rejects(new Repository(repo.db, { ...identity, actorId: randomUUID() }).batches(), /original_identity_mismatch/);
    await assert.rejects(migrate(repo.db, []), /database_upgrade_required/);
  } finally { await repo.db.close(); rmSync(directory, { recursive: true }); }
});
test('UTC canonical hash precision preserves microseconds without rewriting captured evidence', () => {
  assert.equal(normalizedInstant('2026-09-30T06:35:00.100Z'), '2026-09-30T06:35:00.100000Z');
  assert.equal(normalizedInstant('2026-09-30T06:35:00.123456Z'), '2026-09-30T06:35:00.123456Z');
  assert.equal(normalizedInstant('2026-09-30T06:35:00.000Z'), '2026-09-30T06:35:00Z');
});
test('persisted lease is exclusive, expires and releases only its owner', async () => {
  const repo = await setup();
  try {
    assert.deepEqual(await Promise.all([repo.acquireLease('a', 100), repo.acquireLease('b', 100)]), [true, false]);
    await repo.releaseLease('b'); assert.equal(await repo.acquireLease('b', 101), false);
    assert.equal(await repo.acquireLease('b', 30_101), true);
    await repo.releaseLease('a'); assert.equal(await repo.acquireLease('a', 30_102), false);
    await repo.releaseLease('b'); assert.equal(await repo.acquireLease('a', 30_102), true);
  } finally { await repo.db.close(); }
});
test('real SQLite max-page exhaustion retains the prior committed outbox and overlay', async () => {
  const repo = await setup();
  try {
    await repo.saveDraftAndEnqueue(command, hash);
    const pages = (await repo.db.first<{ page_count: number }>('PRAGMA page_count'))!.page_count;
    await repo.db.exec(`PRAGMA max_page_count=${pages}`);
    await assert.rejects(repo.saveDraftAndEnqueue({ ...command, operation_id: randomUUID(), entity_uuid: randomUUID(), payload: { ...command.payload, description: 'x'.repeat(4000), action_taken: 'y'.repeat(4000) } }, hash), /full/i);
    assert.equal(await repo.queueCount(), 1);
    assert.equal((await repo.db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))!.count, 1);
  } finally { await repo.db.close(); }
});
test('separate user database contains no other user queue; validation and queue bounds fail explicitly', async () => {
  const first = await setup(); const secondDb = hostDatabase();
  try {
    await first.saveDraftAndEnqueue(command, hash);
    await migrate(secondDb); const second = new Repository(secondDb, { ...identity, actorId: randomUUID() }); await second.bindIdentity();
    assert.equal(await second.queueCount(), 0); assert.deepEqual(await second.batches(), []);
    await assert.rejects(first.saveDraftAndEnqueue({ ...command, payload: { ...command.payload, quantity_dead: 0 } }, hash));
    await first.db.transaction(async (tx) => {
      for (let i = 0; i < 4999; i++) await tx.run('INSERT INTO outbox(operation_id,entity_uuid,entity_type,actor_id,device_id,deployment_id,command_json,command_hash,captured_at) VALUES(?,?,?,?,?,?,?,?,?)', [randomUUID(), randomUUID(), 'poultry.mortality', identity.actorId, identity.deviceId, identity.deploymentId, '{}', 'synthetic', command.captured_at]);
    });
    await assert.rejects(first.saveDraftAndEnqueue({ ...command, operation_id: randomUUID() }, hash), /queue_limit/);
    assert.equal(await first.queueCount(), 5000);
  } finally { await first.db.close(); await secondDb.close(); }
});
