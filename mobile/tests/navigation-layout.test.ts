import { test } from 'node:test';
import assert from 'node:assert/strict';
import { navigationColumns } from '../src/components/navigation-layout';

test('small-screen navigation reflows with enlarged text and keeps all destinations visible', () => {
  assert.equal(navigationColumns(320, 1), 5);
  assert.equal(navigationColumns(320, 1.3), 3);
  assert.equal(navigationColumns(320, 2), 2);
  assert.equal(navigationColumns(640, 2), 5);
  assert.equal(navigationColumns(240, 1), 3);
  for (const scale of [1, 1.3, 2, 3]) {
    const columns = navigationColumns(320, scale);
    assert.ok(Math.ceil(5 / columns) <= 3);
  }
  assert.equal(navigationColumns(NaN, NaN), 5);
});
