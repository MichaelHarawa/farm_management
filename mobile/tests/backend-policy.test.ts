import test from 'node:test';
import assert from 'node:assert/strict';
import { selectedTestBackend, testBackendA, testBackendB } from '../src/test/backend-policy';
test('synthetic backend switching is explicitly gated to two local acceptance APIs', () => {
  const compiled = { environment: 'development' as const, apiBaseUrl: testBackendA };
  assert.equal(selectedTestBackend(testBackendB, compiled, true).apiBaseUrl, testBackendB);
  for (const base of ['http://10.0.2.2:7070/api/v1', 'https://farm.example/api/v1', testBackendB + '/extra']) {
    assert.throws(() => selectedTestBackend(base, compiled, true));
  }
  assert.throws(() => selectedTestBackend(testBackendB, compiled, false));
  assert.throws(() => selectedTestBackend(testBackendB, { ...compiled, environment: 'production' }, true));
});
