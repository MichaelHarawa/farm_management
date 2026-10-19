import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { phase6EvidenceEnabled, phase4PilotEnabled, phase5PilotEnabled, localAcceptanceEnabled } from '../src/build-mode-policy';
import { financialErrorMessage } from '../src/finance/errors';
import { ApiError } from '../src/auth/client';
import { visibleFinancialPage } from '../src/finance/screen-state';

const native = { applicationId: 'com.farmmanagement.mobile.dev.acceptance.phase6', buildType: 'localAcceptance' };
const base = 'http://10.0.2.2:7075/api/v1';
test('financial evidence acceptance needs its exact native sandbox, build type, flag and synthetic backend', () => {
  assert.equal(phase6EvidenceEnabled('development', base, true, native), true);
  for (const environment of ['staging', 'production', null]) assert.equal(phase6EvidenceEnabled(environment, base, true, native), false);
  for (const url of ['http://10.0.2.2:7070/api/v1', 'http://10.0.2.2:7074/api/v1', base + '/', 'https://farm.example/api/v1']) {
    assert.equal(phase6EvidenceEnabled('development', url, true, native), false);
  }
  for (const build of [null, { ...native, buildType: 'debug' }, { ...native, buildType: 'release' },
    { ...native, applicationId: 'com.farmmanagement.mobile.dev.acceptance.phase5' }, { ...native, applicationId: 'com.farmmanagement.mobile' }]) {
    assert.equal(phase6EvidenceEnabled('development', base, true, build), false);
  }
  for (const flag of [false, 'true', 1, null]) assert.equal(phase6EvidenceEnabled('development', base, flag, native), false);
  for (const gate of [phase4PilotEnabled, phase5PilotEnabled, localAcceptanceEnabled]) {
    assert.equal(gate('development', base, true, native), false); // Does not open any existing upload pilot.
  }
});
test('financial UI errors use fixed safe messages, never native SQL, private values or response text', () => {
  for (const error of [new Error('SELECT PRIVATE-key-payment'), new Error('constructor'), { message: 'device_lock_required' }, null]) {
    const message = financialErrorMessage(error); assert(!message.includes('PRIVATE')); assert(message.includes('retained'));
  }
  assert(financialErrorMessage(new Error('financial_database_key_missing')).includes('Do not reset'));
  assert(financialErrorMessage(new ApiError(403, 'PRIVATE-server-code')).includes('HTTP 403'));
  assert(!financialErrorMessage(new ApiError(403, 'PRIVATE-server-code')).includes('PRIVATE'));
});
test('sensitive local pages hide synchronously on lock, account change or a replacement session for the same actor', () => {
  const original = { actor: 'synthetic-worker' }, replacement = { actor: 'synthetic-worker' };
  const page = { owner: original, rows: ['synthetic protected evidence'] };
  assert.equal(visibleFinancialPage(page, original, true), page);
  for (const session of [null, replacement, { actor: 'synthetic-viewer' }]) assert.equal(visibleFinancialPage(page, session, true), null);
  assert.equal(visibleFinancialPage(page, original, false), null);
  assert.equal(visibleFinancialPage(null, original, true), null);
});
test('real Expo config isolates financial evidence and preserves all earlier acceptance profiles', () => {
  const profiles = [
    { port: '7071', flag: '', enabled: 'localAcceptance' },
    { port: '7073', flag: 'MOBILE_PHASE4_PILOT', enabled: 'phase4Pilot' },
    { port: '7074', flag: 'MOBILE_PHASE5_PILOT', enabled: 'phase5Pilot' },
    { port: '7075', flag: 'MOBILE_PHASE6_EVIDENCE', enabled: 'phase6Evidence' },
  ];
  for (const profile of profiles) {
    const env = { ...process.env, APP_ENV: 'development', MOBILE_RELEASE: '0', MOBILE_LOCAL_ACCEPTANCE: '1',
      MOBILE_PHASE4_PILOT: '0', MOBILE_PHASE5_PILOT: '0', MOBILE_PHASE6_EVIDENCE: '0',
      API_BASE_URL: `http://10.0.2.2:${profile.port}/api/v1`, ...(profile.flag ? { [profile.flag]: '1' } : {}) };
    const result = spawnSync(process.execPath, ['--require', 'tsx/cjs', '-e',
      "const c=require('./app.config.ts').default;process.stdout.write(JSON.stringify({extra:c.extra,backup:c.android.allowBackup}));"], { env, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
    const config = JSON.parse(result.stdout);
    assert.equal(config.extra[profile.enabled], true); assert.equal(config.backup, false);
    assert.equal(config.extra.apiBaseUrl, env.API_BASE_URL);
    if (profile.port === '7075') { assert.equal(config.extra.phase4Pilot, false); assert.equal(config.extra.phase5Pilot, false); }
  }
  const denied = spawnSync(process.execPath, ['--require', 'tsx/cjs', '-e', "require('./app.config.ts');"], { encoding: 'utf8',
    env: { ...process.env, APP_ENV: 'development', MOBILE_RELEASE: '0', MOBILE_LOCAL_ACCEPTANCE: '1',
      MOBILE_PHASE4_PILOT: '0', MOBILE_PHASE5_PILOT: '1', MOBILE_PHASE6_EVIDENCE: '1', API_BASE_URL: base } });
  assert.equal(denied.status, 1); assert(denied.stderr.includes('own isolated build'));
});
test('build wrapper refuses mixed profiles, foreign backend, production, release and unsupported ABIs before build tools', () => {
  for (const [args, changes] of [
    [['--phase6-evidence-acceptance', '--phase5-acceptance'], {}],
    [['--phase6-evidence-acceptance', '--phase4-acceptance'], {}],
    [['--phase6-evidence-acceptance'], { API_BASE_URL: 'http://10.0.2.2:7070/api/v1' }],
    [['--phase6-evidence-acceptance'], { APP_ENV: 'production' }],
    [['--phase6-evidence-acceptance'], { MOBILE_RELEASE: '1' }],
    [['--phase6-evidence-acceptance', '--abi=unsupported'], {}],
  ] as [string[], Record<string, string>][]) {
    const result = spawnSync(process.execPath, ['scripts/build-android.cjs', ...args], { encoding: 'utf8',
      env: { ...process.env, APP_ENV: 'development', API_BASE_URL: base, MOBILE_RELEASE: '0', ...changes } });
    assert.equal(result.status, 1); assert(!result.stdout.includes('prebuild'));
    assert.match(result.stderr, /Usage:|Local acceptance requires|Phase 6 evidence acceptance/);
  }
});
