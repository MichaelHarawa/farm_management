import { test } from 'node:test';
import assert from 'node:assert/strict';
import { localAcceptanceEnabled, phase4PilotEnabled } from '../src/build-mode-policy';
import { validateSettings } from '../src/config';

test('embedded synthetic diagnostics require the explicit flag, actual native test package/type and exact local deployment URL', () => {
  const base = 'http://10.0.2.2:7071/api/v1';
  const nativeBuild = { applicationId: 'com.farmmanagement.mobile.dev.acceptance', buildType: 'localAcceptance' };
  assert.equal(localAcceptanceEnabled('development', base, true, nativeBuild), true);
  for (const args of [
    ['production', base, true, nativeBuild], ['staging', base, true, nativeBuild],
    ['development', base, false, nativeBuild], ['development', base, 'true', nativeBuild],
    ['development', base, true, { ...nativeBuild, buildType: 'release' }],
    ['development', base, true, { ...nativeBuild, applicationId: 'com.farmmanagement.mobile' }],
    ['development', base, true, null],
    ['development', 'http://10.0.2.2:7070/api/v1', true, nativeBuild],
    ['development', 'https://farm.example/api/v1', true, nativeBuild],
  ]) assert.equal(localAcceptanceEnabled(...args as [unknown, unknown, unknown, unknown]), false);
  // Existing production validation stays fail closed; the test policy does not
  // grant cleartext production/staging access or change validateSettings.
  assert.throws(() => validateSettings('development', base, true));
  assert.throws(() => validateSettings('production', base, false));
});

test('Phase4 pilot cannot enable uploads in A/B, ordinary debug, staging or release builds', () => {
  const args: [unknown, unknown, unknown, unknown] = ['development', 'http://10.0.2.2:7073/api/v1', true,
    { applicationId: 'com.farmmanagement.mobile.dev.acceptance.phase4', buildType: 'localAcceptance' }];
  assert.equal(phase4PilotEnabled(...args), true);
  for (const change of [
    [0, 'production'], [0, 'staging'], [1, 'http://10.0.2.2:7071/api/v1'], [1, 'http://10.0.2.2:7072/api/v1'],
    [1, 'https://farm.example/api/v1'], [2, false], [2, 'true'], [3, null],
    [3, { applicationId: 'com.farmmanagement.mobile.dev.acceptance', buildType: 'localAcceptance' }],
    [3, { applicationId: 'com.farmmanagement.mobile.dev.acceptance.phase4', buildType: 'release' }],
    [3, { applicationId: 'com.farmmanagement.mobile.dev', buildType: 'debug' }],
  ] as [number, unknown][]) {
    const altered = [...args] as typeof args; altered[change[0]] = change[1];
    assert.equal(phase4PilotEnabled(...altered), false);
  }
});
