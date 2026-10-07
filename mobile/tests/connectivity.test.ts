import assert from 'node:assert/strict';
import test from 'node:test';
import { canAttemptBackendSync } from '../src/sync/connectivity';

test('a connected LAN or VPN need not have validated public internet to reach Django', () => {
  assert.equal(canAttemptBackendSync({ isConnected: true, isInternetReachable: false }), true);
});

test('a known disconnected device does not start a backend request', () => {
  assert.equal(canAttemptBackendSync({ isConnected: false, isInternetReachable: false }), false);
  assert.equal(canAttemptBackendSync({ isConnected: false, isInternetReachable: true }), false);
});

test('unknown network hints defer reachability to the bounded configured-backend request', () => {
  assert.equal(canAttemptBackendSync({}), true);
  assert.equal(canAttemptBackendSync({ isInternetReachable: false }), true);
});

test('ordinary validated internet still permits a backend attempt, not local authorization', () => {
  assert.equal(canAttemptBackendSync({ isConnected: true, isInternetReachable: true }), true);
});
