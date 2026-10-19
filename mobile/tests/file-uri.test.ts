import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { databaseFileUri, financialDatabaseFileUri } from '../src/db/file-uri';
import { financialNamespace, openFinancialDatabase } from '../src/finance/key-database';
import { identity } from './helpers';

test('SQLite Android paths become absolute file URIs without changing the database name', () => {
  const name = `farm-${'a'.repeat(64)}.db`;
  const directory = '/data/user/0/com.farmmanagement.mobile.dev/files/SQLite';
  assert.equal(databaseFileUri(directory, name), `file://${directory}/${name}`);
  assert.equal(new URL(databaseFileUri(directory, name)).protocol, 'file:');
  assert.equal(databaseFileUri(`${directory}/`, name), `file://${directory}/${name}`);
  assert.equal(databaseFileUri('file:///private/SQLite/', name), `file:///private/SQLite/${name}`);
  assert.equal(databaseFileUri('/private/farm records/#1%/SQLite', name), `file:///private/farm%20records/%231%25/SQLite/${name}`);
  for (const directory of ['relative', 'content://store', 'https://example.test', '']) {
    assert.throws(() => databaseFileUri(directory, name), /invalid_database_directory/);
  }
  assert.throws(() => databaseFileUri('/private/SQLite', '../other.db'), /invalid_database_filename/);
});

test('financial main WAL and SHM paths have a separate closed native-file allowlist', () => {
  const main = `farm-finance-v1-${'a'.repeat(64)}.db`;
  const directory = '/data/user/0/com.farmmanagement.mobile.dev.acceptance.phase5/files/SQLite';
  for (const name of [main, main + '-wal', main + '-shm']) {
    assert.equal(financialDatabaseFileUri(directory, name), `file://${directory}/${name}`);
    assert.equal(financialDatabaseFileUri(directory + '/', name), `file://${directory}/${name}`);
    assert.equal(financialDatabaseFileUri('file:///private/SQLite/', name), `file:///private/SQLite/${name}`);
    assert.equal(financialDatabaseFileUri('/private/farm records/#1%/SQLite', name), `file:///private/farm%20records/%231%25/SQLite/${name}`);
    assert.throws(() => databaseFileUri(directory, name), /invalid_database_filename/); // Original operational policy is unchanged.
  }
});

test('financial file paths reject operational names, traversal, suffix injection and alternate profiles', () => {
  const main = `farm-finance-v1-${'b'.repeat(64)}.db`;
  for (const name of [`farm-${'b'.repeat(64)}.db`, main.toUpperCase(), '../' + main, '/tmp/' + main,
    main + '\n', main + '?key=value', main + '-journal', main + '-wal-shm', main + '.db',
    main.replace('v1-', 'v2-'), main.replace('b'.repeat(64), 'b'.repeat(63))]) {
    assert.throws(() => financialDatabaseFileUri('/private/SQLite', name), /invalid_financial_database_filename/);
  }
  for (const directory of ['relative', 'content://store', 'https://example.test', '']) {
    assert.throws(() => financialDatabaseFileUri(directory, main), /invalid_database_directory/);
  }
});

test('real namespace-derived financial filenames pass the same adapter boundary as native existence checks', async () => {
  const hash = async (value: string) => createHash('sha256').update(value).digest('hex');
  const namespace = await financialNamespace({ environment: 'development', apiBaseUrl: 'http://10.0.2.2:7074/api/v1' }, identity, hash);
  const directory = '/data/user/0/com.farmmanagement.mobile.dev.acceptance.phase5/files/SQLite';
  assert.throws(() => databaseFileUri(directory, namespace.database), /invalid_database_filename/); // Reproduces pre-PIN regression.
  const checked: string[] = [], keys = new Map<string, string>();
  let unlocks = 0, opens = 0;
  await assert.rejects(openFinancialDatabase(namespace, { hash, randomKey: async () => 'c'.repeat(64),
    async unlock() { unlocks++; return false; },
    keys: { async get(name) { return keys.get(name) ?? null; }, async set(name, value) { keys.set(name, value); } },
    async exists(name) { checked.push(financialDatabaseFileUri(directory, name)); return false; },
    async open() { opens++; throw new Error('intentional_stop_before_native_SQL'); },
  }), /financial_database_open_failed_retain_original/);
  assert.deepEqual(checked.sort(), [namespace.database, namespace.database + '-wal', namespace.database + '-shm'].map(name => `file://${directory}/${name}`).sort());
  assert.equal(unlocks, 1);
  assert.equal(opens, 1); // HOST control-flow proof only; no fake cipher/native acceptance.
});

test('operational filename validation remains unchanged while financial companion paths are isolated', () => {
  const operational = `farm-${'d'.repeat(64)}.db`;
  assert.equal(databaseFileUri('/private/SQLite', operational), `file:///private/SQLite/${operational}`);
  for (const name of [operational, operational + '-wal', operational + '-shm']) {
    assert.throws(() => financialDatabaseFileUri('/private/SQLite', name), /invalid_financial_database_filename/);
  }
  for (const name of [operational + '-wal', operational + '-shm']) assert.throws(() => databaseFileUri('/private/SQLite', name), /invalid_database_filename/);
});
