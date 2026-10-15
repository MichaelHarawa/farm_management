import assert from 'node:assert/strict';
import { test } from 'node:test';
import { financialUUIDEnvelope, financialUUIDOperation, financialUUIDResult, parseFinancialUUIDEnvelope,
  parseFinancialUUIDResponse } from '../src/finance/uuid-commands';
import { result as operationalResult } from '../src/sync/protocol';

const deployment = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const device = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const operation = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const source = 'dddddddd-dddd-5ddd-8ddd-dddddddddddd';
const invoice = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
const inner = 'ffffffff-ffff-5fff-8fff-ffffffffffff';
const version = 'a'.repeat(64), hash = 'b'.repeat(64);
const identity = { deploymentId: deployment, deviceId: device, actorId: invoice };
const command = { financial_command_version: 2, operation_id: operation, command: 'inventory.supplier_payment.record',
  captured_at: '2026-10-14T12:00:00.000001Z', depends_on: [], payload: { currency: 'MWK', payee: 'Synthetic supplier',
    payment_method: 'bank_transfer', external_reference: 'SYNTHETIC-TRANSFER', payment_date: '2026-01-12', total_payment_amount: '50.00',
    invoices: [{ invoice_group_id: invoice, invoice_version: version, total_payment_amount: '50.00',
      lines: [{ invoice_line_index: 0, amount: '50.00', funding_allocations: [{ funding_source: source, funding_version: version, amount: '50.00' }] }] }],
    notes: 'Original observed physical payment' } };
const envelope = { financial_protocol_version: 1, deployment_id: deployment, device_id: device, operations: [command] };
const accepted = { financial_command_version: 2, operation_id: operation, command: command.command, command_hash: hash,
  outcome: 'accepted', code: 'accepted', message: 'Observed supplier payment recorded once; original evidence retained.', field_errors: {},
  recovery_action: 'retain_receipt_never_resubmit', transaction_id: invoice, committed_at: command.captured_at,
  financial_evidence: { submission_id: inner, receipt_hash: version, payment_version: version, recorded_at: command.captured_at,
    basis: 'immutable_completed_financial_receipt_not_current_balance' } };
const response = { financial_protocol_version: 1, deployment_id: deployment, device_id: device, server_time: command.captured_at, results: [accepted] };
const expected = { identity, commandHashes: { [operation]: hash } };

test('financial UUID envelope and acknowledgements preserve exact capture and separate identities', () => {
  const before = structuredClone([envelope, response]);
  assert.deepEqual(parseFinancialUUIDEnvelope(envelope, identity), envelope);
  assert.deepEqual(parseFinancialUUIDResponse(response, expected), response);
  assert.deepEqual([envelope, response], before);
  assert.equal(operationalResult.safeParse(accepted).success, false);
  assert.equal(financialUUIDResult.safeParse({ ...accepted, outcome: 'replayed' }).success, true);
});

test('financial UUID input refuses legacy PK payload numbers newline strings and unknown financial fields', () => {
  for (const change of [{ funding_source: '9007199254740993' }, { funding_source: 3 }, { funding_version: `${version}\n` },
    { amount: 50.01 }, { amount: '50.00\n' }, { owner_id: invoice }]) {
    const invalid = structuredClone(command);
    Object.assign(invalid.payload.invoices[0]!.lines[0]!.funding_allocations[0]!, change);
    assert.equal(financialUUIDOperation.safeParse(invalid).success, false);
  }
  assert.equal(financialUUIDOperation.safeParse({ ...command, financial_command_version: 1 }).success, false);
  for (const suffix of ['\n', '\r\n', ' ']) {
    assert.equal(financialUUIDOperation.safeParse({ ...command, captured_at: `2026-10-14T12:00:00Z${suffix}` }).success, false);
  }
  assert.equal(financialUUIDEnvelope.safeParse({ ...envelope, actor_id: invoice }).success, false);
});

test('whole financial envelopes reject duplicate IDs self-dependencies cycles and excess operations', () => {
  const child = { ...command, operation_id: invoice, depends_on: [operation] };
  assert.equal(financialUUIDEnvelope.safeParse({ ...envelope, operations: [child, command] }).success, true);
  for (const operations of [[command, command], [{ ...command, depends_on: [operation] }],
    [{ ...command, depends_on: [invoice] }, child], Array(21).fill(command)]) {
    assert.equal(financialUUIDEnvelope.safeParse({ ...envelope, operations }).success, false);
  }
});

test('financial responses require exact expected command IDs hashes deployment and device', () => {
  for (const change of [{ deployment_id: invoice }, { device_id: invoice }, { results: [{ ...accepted, command_hash: version }] },
    { results: [{ ...accepted, operation_id: invoice }] }, { results: [accepted, accepted] }]) {
    assert.throws(() => parseFinancialUUIDResponse({ ...response, ...change }, expected));
  }
  assert.throws(() => parseFinancialUUIDEnvelope({ ...envelope, device_id: invoice }, identity));
  assert.throws(() => parseFinancialUUIDResponse(response, { ...expected, commandHashes: {} }));
});

test('unknown and contradictory financial outcomes cannot masquerade as accepted money', () => {
  for (const change of [{ financial_evidence: undefined }, { committed_at: undefined }, { transaction_id: undefined },
    { outcome: 'retry_later' }, { code: 'funding_reference_changed' }, { recovery_action: 'retry_unchanged' },
    { field_errors: { funding_allocations: 'Review this captured field; retain the original evidence.' } },
    { current_balance: '200.00' }, { resolution: {} }, { source_pk: '3' }]) {
    assert.equal(financialUUIDResult.safeParse({ ...accepted, ...change }).success, false);
  }
});

test('deferred dependency and reference conflicts retain original operation without success fields', () => {
  const base = { financial_command_version: 2, operation_id: operation, command: command.command, command_hash: hash,
    outcome: 'conflict', code: 'funding_reference_changed',
    message: 'Keep the original financial evidence; review the outcome before any further action.', field_errors: {}, recovery_action: 'review_and_supersede' };
  assert.equal(financialUUIDResult.safeParse(base).success, true);
  assert.equal(financialUUIDResult.safeParse({ ...base, outcome: 'dependency_blocked', code: 'dependency_blocked', recovery_action: 'wait_for_dependency' }).success, true);
  assert.equal(financialUUIDResult.safeParse({ ...base, outcome: 'retry_later', code: 'request_budget_exceeded', recovery_action: 'retry_unchanged' }).success, true);
  assert.equal(financialUUIDResult.safeParse({ ...base, outcome: 'retry_later', code: 'request_budget_exceeded', recovery_action: 'review_and_supersede' }).success, false);
});
