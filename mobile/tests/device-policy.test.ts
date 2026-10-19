import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { deviceUnlockOptions } from '../src/auth/device-policy';

test('host prompt policy distinguishes financial entry without weakening ordinary unlock', () => {
  const operational = deviceUnlockOptions();
  assert.deepEqual(operational, { promptMessage: 'Unlock encrypted farm records',
    disableDeviceFallback: false, biometricsSecurityLevel: 'strong' });
  assert.deepEqual(deviceUnlockOptions('operational'), operational);
  const financial = deviceUnlockOptions('financial');
  assert.equal(financial.promptMessage, 'Unlock encrypted financial evidence');
  assert.notEqual(financial.promptMessage, operational.promptMessage);
  assert.deepEqual({ ...financial, promptMessage: operational.promptMessage }, operational);
  assert.equal(Object.isFrozen(financial), true);
});

test('unknown prompt purposes cannot supply arbitrary private-dialog text or override security options', () => {
  for (const invalid of [null, '', 'Financial', 'constructor', '__proto__', true, 1,
    'PRIVATE user-controlled prompt', { purpose: 'financial' }, ['financial']]) {
    assert.throws(() => deviceUnlockOptions(invalid), /^Error: device_unlock_purpose_invalid$/);
  }
});

test('native source wiring selects financial purpose while ordinary opener retains the default', () => {
  // Source-contract coverage only, not evidence that an Android prompt rendered.
  const native = readFileSync(new URL('../src/finance/native.ts', import.meta.url), 'utf8');
  const operational = readFileSync(new URL('../src/db/native.ts', import.meta.url), 'utf8');
  const device = readFileSync(new URL('../src/auth/device.ts', import.meta.url), 'utf8');
  assert.match(native, /unlock: \(\) => deviceUnlock\('financial'\)/);
  assert.match(operational, /await deviceUnlock\(\)/);
  assert.match(device, /authenticateAsync\(options\)/);
  assert(device.indexOf('deviceUnlockOptions(purpose)') < device.indexOf('getEnrolledLevelAsync()'));
});
