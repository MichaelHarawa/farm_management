import { test } from 'node:test';
import assert from 'node:assert/strict';
import { databaseFileUri } from '../src/db/file-uri';

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
