import assert from 'node:assert/strict';
import { test } from 'node:test';
import { financialProbeFailureMessage, traceFinancialProbe } from '../src/test/financial-probe-diagnostics';

test('scratch tracing returns actual work result without inventing a pass or authority', async () => {
  const events: string[] = [];
  const result = await traceFinancialProbe(async step => {
    step('descriptor_read'); events.push('read'); step('inspection'); events.push('inspect');
    return 'INSPECTED only';
  });
  assert.equal(result, 'INSPECTED only'); assert.deepEqual(events, ['read', 'inspect']);
});

test('unknown native SQL key and payload errors become fixed step/code without a raw cause', async () => {
  let caught: unknown;
  try { await traceFinancialProbe(async step => { step('native_cipher_key'); throw new Error('PRAGMA key=PRIVATE-KEY token=PRIVATE-TOKEN payee=PRIVATE-PAYEE'); }); }
  catch (error) { caught = error; }
  const text = financialProbeFailureMessage(caught);
  assert.match(text, /FAILED at native cipher-key application/);
  assert.match(text, /native_or_validation_failure/);
  assert.doesNotMatch(text, /PRIVATE|PRAGMA|token=/);
  assert.ok(caught instanceof Error);
  assert.equal(caught.message, 'financial_scratch_step_failed'); assert.equal(caught.cause, undefined);
  assert.doesNotMatch(JSON.stringify(caught), /PRIVATE/);
});

test('known unlock refusal keeps only its exact fixed reason and closed stage label', async () => {
  let caught: unknown;
  try { await traceFinancialProbe(async step => { step('native_unlock'); throw new Error('device_lock_required'); }); }
  catch (error) { caught = error; }
  assert.match(financialProbeFailureMessage(caught), /private native device unlock\. Code: device_lock_required/);
});

test('raw errors objects and near-match codes cannot enter user-facing diagnostic text', async () => {
  for (const error of [new Error('PRIVATE-KEY'), { message: 'device_lock_required PRIVATE-KEY' }, 'PRIVATE-KEY', null]) {
    assert.doesNotMatch(financialProbeFailureMessage(error), /PRIVATE/);
  }
  let caught: unknown;
  try { await traceFinancialProbe(async step => { step('native_unlock'); throw new Error('device_lock_required\nPRIVATE'); }); }
  catch (error) { caught = error; }
  assert.match(financialProbeFailureMessage(caught), /native_or_validation_failure/);
  assert.doesNotMatch(financialProbeFailureMessage(caught), /PRIVATE/);
});

test('damaged or forged diagnostic metadata fails closed instead of displaying arbitrary strings', async () => {
  let caught: unknown;
  try { await traceFinancialProbe(async () => { throw new Error('device_lock_required'); }); }
  catch (error) { caught = error; }
  assert.ok(caught instanceof Error);
  Object.assign(caught, { code: 'PRIVATE-KEY', step: 'PRIVATE-PAYEE' });
  const text = financialProbeFailureMessage(caught);
  assert.match(text, /before a diagnostic result/); assert.doesNotMatch(text, /PRIVATE/);
  Object.assign(caught, { code: 'device_lock_required', step: 'constructor' });
  assert.match(financialProbeFailureMessage(caught), /before a diagnostic result/);
});

test('preparation exclusion and missing original file have explicit non-success preservation messages', async () => {
  for (const [stage, code] of [['descriptor_read', 'existing_financial_scratch_retained'], ['existing_file', 'financial_scratch_check_failed']] as const) {
    let caught: unknown;
    try { await traceFinancialProbe(async step => { step(stage); throw new Error(code); }); } catch (error) { caught = error; }
    const text = financialProbeFailureMessage(caught);
    assert.match(text, /^FAILED/); assert.match(text, /Preserve the scratch/);
    assert.doesNotMatch(text, /PREPARED|PASS/);
  }
});
