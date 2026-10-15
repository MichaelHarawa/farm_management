/** Private UUID financial protocol candidate. No native API/outbox/UI integration. */
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';
import { fundingReferenceRows } from './funding-references';

const digest = z.string().regex(/^[0-9a-f]{64}$/);
const money = z.string().regex(/^(0|[1-9][0-9]{0,11})\.[0-9]{2}$/).refine(value => value !== '0.00');
const text = (maximum: number) => z.string().refine(value => [...value].length >= 1 && [...value].length <= maximum);
export const financialUUIDOperation = z.strictObject({ financial_command_version: z.literal(2), operation_id: uuid,
  command: z.literal('inventory.supplier_payment.record'), captured_at: instant,
  depends_on: z.array(uuid).max(20).refine(ids => new Set(ids).size === ids.length), supersedes_operation_id: uuid.optional(),
  payload: z.strictObject({ currency: z.literal('MWK'), payee: text(160), payment_method: z.enum(['cash', 'mobile_money', 'bank_transfer']),
    external_reference: text(120), payment_date: z.iso.date(), total_payment_amount: money,
    invoices: z.array(z.strictObject({ invoice_group_id: uuid, invoice_version: digest, total_payment_amount: money,
      lines: z.array(z.strictObject({ invoice_line_index: z.number().int().min(0).max(49), amount: money,
        funding_allocations: fundingReferenceRows.max(50) })).min(1).max(50) })).min(1).max(10),
    notes: z.string().refine(value => [...value].length <= 4000),
  }),
}).superRefine((command, ctx) => {
  const lines = command.payload.invoices.flatMap(invoice => invoice.lines);
  if (lines.length > 50 || lines.reduce((count, line) => count + line.funding_allocations.length, 0) > 100 ||
      command.depends_on.includes(command.operation_id) || byteLength(JSON.stringify(command)) > 1048576) {
    ctx.addIssue({ code: 'custom', message: 'Invalid financial command dependency or evidence budget; retain original work.' });
  }
});
export const financialUUIDEnvelope = z.strictObject({ financial_protocol_version: z.literal(1), deployment_id: uuid,
  device_id: uuid, operations: z.array(financialUUIDOperation).min(1).max(20),
}).superRefine((envelope, ctx) => {
  const commands = new Map(envelope.operations.map(command => [command.operation_id, command]));
  let invalid = commands.size !== envelope.operations.length || byteLength(JSON.stringify(envelope)) > 1048576;
  const visiting = new Set<string>(), visited = new Set<string>();
  function visit(id: string) {
    if (visiting.has(id)) { invalid = true; return; }
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dependency of commands.get(id)?.depends_on ?? []) {
      if (commands.has(dependency)) visit(dependency);
    }
    visiting.delete(id);
    visited.add(id);
  }
  for (const id of commands.keys()) visit(id);
  if (invalid) ctx.addIssue({ code: 'custom', message: 'Malformed financial envelope; no command may be dispatched from this request.' });
});

const review = 'Keep the original financial evidence; review the outcome before any further action.';
const accepted = 'Observed supplier payment recorded once; original evidence retained.';
const fields = ['payment_date', 'total_payment_amount', 'payee', 'external_reference', 'invoices', 'funding_allocations'] as const;
const fieldProperties = Object.fromEntries(fields.map(field => [field,
  z.literal('Review this captured field; retain the original evidence.').optional()]));
export const financialUUIDResult = z.strictObject({ financial_command_version: z.literal(2), operation_id: uuid,
  command: z.literal('inventory.supplier_payment.record'), command_hash: digest,
  outcome: z.enum(['accepted', 'replayed', 'validation_failed', 'permission_denied', 'period_locked', 'conflict', 'dependency_blocked', 'retry_later']),
  code: z.enum(['accepted', 'idempotency_mismatch', 'permission_denied', 'period_locked', 'invalid_business_event',
    'possible_duplicate', 'insufficient_cash_or_payable', 'invalid_supersession', 'supersession_already_accepted', 'future_capture',
    'dependency_blocked', 'dependency_profile_mismatch', 'command_unavailable', 'funding_reference_unavailable',
    'funding_reference_changed', 'invoice_reference_unavailable', 'request_budget_exceeded']),
  message: z.enum([review, accepted]), field_errors: z.strictObject(fieldProperties),
  recovery_action: z.enum(['recover_original_operation', 'review_and_supersede', 'wait_for_dependency', 'retry_unchanged', 'retain_receipt_never_resubmit']),
  financial_evidence: z.strictObject({ submission_id: uuid, receipt_hash: digest, payment_version: digest,
    recorded_at: instant, basis: z.literal('immutable_completed_financial_receipt_not_current_balance') }).optional(),
  transaction_id: uuid.optional(), committed_at: instant.optional(),
}).superRefine((result, ctx) => {
  const successful = result.outcome === 'accepted' || result.outcome === 'replayed';
  const expectedRecovery = successful ? 'retain_receipt_never_resubmit' : result.outcome === 'dependency_blocked' ? 'wait_for_dependency' :
    result.outcome === 'retry_later' ? 'retry_unchanged' : result.code === 'idempotency_mismatch' ? 'recover_original_operation' : 'review_and_supersede';
  const compatible = {
    accepted: ['accepted'], replayed: ['accepted'], permission_denied: ['permission_denied'], period_locked: ['period_locked'],
    validation_failed: ['invalid_business_event', 'future_capture', 'dependency_profile_mismatch'],
    conflict: ['idempotency_mismatch', 'possible_duplicate', 'insufficient_cash_or_payable', 'invalid_supersession',
      'supersession_already_accepted', 'funding_reference_unavailable', 'funding_reference_changed', 'invoice_reference_unavailable'],
    dependency_blocked: ['dependency_blocked'], retry_later: ['command_unavailable', 'request_budget_exceeded'],
  }[result.outcome].includes(result.code);
  if (!compatible || result.recovery_action !== expectedRecovery ||
      (successful ? result.message !== accepted || !result.financial_evidence || !result.transaction_id || !result.committed_at ||
        Object.keys(result.field_errors).length > 0 : result.message !== review || result.financial_evidence !== undefined ||
        result.transaction_id !== undefined || result.committed_at !== undefined)) {
    ctx.addIssue({ code: 'custom', message: 'Contradictory financial acknowledgement; retain original evidence and query its original operation.' });
  }
});
export const financialUUIDResponse = z.strictObject({ financial_protocol_version: z.literal(1), deployment_id: uuid,
  device_id: uuid, server_time: instant, results: z.array(financialUUIDResult).min(1).max(20),
}).refine(response => new Set(response.results.map(result => result.operation_id)).size === response.results.length);

export function parseFinancialUUIDEnvelope(value: unknown, identity: StoreIdentity) {
  const envelope = financialUUIDEnvelope.parse(value);
  if (envelope.deployment_id !== identity.deploymentId || envelope.device_id !== identity.deviceId) {
    throw new Error('financial_uuid_environment_mismatch_retain_original');
  }
  return envelope;
}

/** Validation only: this never changes balances or retires an operational overlay. */
export function parseFinancialUUIDResponse(value: unknown, expected: { identity: StoreIdentity; commandHashes: Record<string, string> }) {
  const response = financialUUIDResponse.parse(value);
  if (response.deployment_id !== expected.identity.deploymentId || response.device_id !== expected.identity.deviceId ||
      response.results.length !== Object.keys(expected.commandHashes).length || response.results.some(result =>
        result.command_hash !== digest.parse(expected.commandHashes[result.operation_id]))) {
    throw new Error('financial_uuid_receipt_mismatch_retain_original');
  }
  return response;
}
