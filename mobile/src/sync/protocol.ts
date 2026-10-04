import { z } from 'zod';
import { instant, uuid } from '../protocol';

export const counter = z.string().regex(/^(0|[1-9][0-9]*)$/).max(40);
const text = z.string().max(4000);
const integer = z.number().int().safe();
const date = z.iso.date().nullable();
const common = { server_id: counter, created_at: instant, updated_at: instant };
const decimal = z.string().regex(/^-?\d+(\.\d+)?$/).max(60);
const operationalSummary = z.strictObject({ calculation_version: text, feed_record_count: integer.nonnegative(), feed_total_kg: decimal,
  feed_per_bird_started_kg: decimal.nullable(), feed_denominator: z.literal('actual_birds_received'), feed_denominator_birds: integer.nonnegative(),
  growth: z.strictObject({ state: z.enum(['missing_sample','target_available','target_not_applicable']), sample: z.strictObject({
    sampled_at: instant, sample_size: integer.positive(), average_weight_g: integer.positive(), age_in_days: integer.nonnegative(),
    target_weight_g: integer.nullable(), strain: text.nullable(), deviation_percent: decimal.nullable() }).nullable() }),
  mortality: z.strictObject({ dead_birds: integer.nonnegative(), actual_arrivals: integer.nonnegative(), rate_percent: decimal.nullable(),
    threshold_percent: decimal, alert: z.boolean().nullable(), formula: text }), stock_integration: z.literal('not_linked_phase6'), fcr: z.null() });
export const batchPayload = z.strictObject({ ...common, batch_id: text, bird_type: text, broiler_strain: text,
  source: text, source_other: text, booking_date: date, estimated_chick_arrival_date: date,
  expected_quantity: integer.nullable(), actual_quantity_received: integer.nullable(), entry_date: instant,
  expected_maturity_date: instant, delivery_confirmed_at: instant.nullable(), quantity: integer,
  closed_at: instant.nullable(), status: text, initial_birds: integer, sold_bird_count: integer,
  total_mortality: integer, remaining_birds: integer, approved_adjustment_count: integer,
  supplier_name: text.optional(), booking_reference: text.optional(), operational_summary: operationalSummary.optional() });
const mortalityPayload = z.strictObject({ ...common, batch_uuid: uuid, mortality_date: instant,
  quantity_dead: integer.positive(), age_in_days: integer, suspected_cause: text, description: text,
  action_taken: text, reported_by_name: text });
const feedPayload = z.strictObject({ ...common, batch_uuid: uuid, initial_age: integer, feeding_start_date: instant,
  feeding_end_date: instant, feed_type: text, feed_source: text, quantity_given: integer, unit_of_measurement: text,
  current_number_of_birds: integer, population_calculation_version: text, population_calculated_at: instant.nullable(),
  notes: text.nullable(), reported_by_name: text, quantity_kg: z.string().regex(/^-?\d+(\.\d+)?$/).max(60) });
const treatmentPayload = z.strictObject({ ...common, batch_uuid: uuid, vaccination_date: instant, drug_category: text,
  drug_vaccination_type: text, other_drug_vaccination: text, quantity: integer.positive(), description: text, timely_status: text, reported_by_name: text });
const weightPayload = z.strictObject({ ...common, batch_uuid: uuid, sampled_at: instant, age_in_days: integer.nonnegative(), sample_size: integer.positive(),
  average_weight_g: integer.positive(), notes: text, reported_by_name: text });
const adjustmentPayload = z.strictObject({ ...common, batch_uuid: uuid, effective_at: instant, quantity_change: integer, reason: text, status: z.enum(['approved','reversed']) });
const proposalPayload = z.strictObject({ ...common, batch_uuid: uuid, effective_at: instant, quantity_change: integer, reason: text,
  status: z.enum(['pending','approved','rejected']), review_reason: text, adjustment_server_id: counter.nullable() });
const entityType = z.enum(['poultry.batch','poultry.mortality','poultry.feed_usage','poultry.treatment','poultry.weight_sample','poultry.flock_adjustment','poultry.adjustment_proposal']);
const payloads = { 'poultry.batch': batchPayload, 'poultry.mortality': mortalityPayload, 'poultry.feed_usage': feedPayload,
  'poultry.treatment': treatmentPayload, 'poultry.weight_sample': weightPayload, 'poultry.flock_adjustment': adjustmentPayload, 'poultry.adjustment_proposal': proposalPayload };
export const entity = z.strictObject({ entity_type: entityType, entity_uuid: uuid, revision: counter, payload: z.unknown() })
  .transform((v) => ({ ...v, payload: payloads[v.entity_type].parse(v.payload) }));
export type Entity = z.infer<typeof entity>;
export const pack = z.string().refine((s) => ['operational-current-v1','operational-current-v2'].includes(s) || /^batch(?:-v2)?:[0-9a-f-]{36}$/.test(s) && uuid.safeParse(s.slice(s.indexOf(':')+1)).success);
const packs = z.array(pack).max(20).refine((v) => new Set(v).size === v.length);
const cursor = z.string().min(1).max(16384);
export const bootstrap = z.strictObject({ snapshot_id: uuid, deployment_id: uuid, stream_epoch: uuid,
  scope_revision: z.string().min(1).max(256), watermark: counter, expires_at: instant, packs,
  row_count: integer.nonnegative().max(100000), manifest: z.array(z.strictObject({ page: integer.nonnegative(),
    row_count: integer.nonnegative().max(500), sha256: z.string().regex(/^[a-f0-9]{64}$/) })).min(1).max(100001), next_page_cursor: cursor });
export type Bootstrap = z.infer<typeof bootstrap>;
export const bootstrapPage = z.strictObject({ snapshot_id: uuid, page: integer.nonnegative(), entities: z.array(entity).max(500),
  sha256: z.string().regex(/^[a-f0-9]{64}$/), page_complete: z.boolean(), next_page_cursor: cursor.nullable(), delta_cursor: cursor.optional() });
export type BootstrapPage = z.infer<typeof bootstrapPage>;
export const fragment = z.strictObject({ transaction_id: uuid, fragment_index: integer.nonnegative().max(10000), fragment_final: z.boolean() });
export const change = fragment.extend({ sequence: counter, entity_type: entityType, entity_uuid: uuid,
  revision: counter, kind: z.enum(['upsert','tombstone','evict_from_pack']), pack_ids: packs,
  payload: z.unknown().optional(), origin_operation_id: uuid.optional() }).transform((v) => {
    if (v.kind === 'upsert') return { ...v, payload: payloads[v.entity_type].parse(v.payload) };
    if (v.payload !== undefined) throw new Error('unexpected_change_payload');
    return v;
  });
export type Change = z.infer<typeof change>;
export const changesPage = z.strictObject({ deployment_id: uuid, stream_epoch: uuid, scope_revision: z.string().min(1).max(256),
  run_watermark: counter, changes: z.array(change).max(500), fragments: z.array(fragment).max(500),
  next_cursor: cursor, run_complete: z.boolean(), server_time: instant });
export type ChangesPage = z.infer<typeof changesPage>;
export const result = z.strictObject({ operation_id: uuid,
  outcome: z.enum(['accepted','replayed','conflict','validation_failed','period_locked','permission_denied','dependency_blocked','retry_later']),
  code: z.string().max(100), message: z.string().max(500), field_errors: z.record(z.string(),z.unknown()), recovery_action: z.string().max(100),
  canonical_entities: z.array(entity).max(500).optional(), entity_mappings: z.array(z.strictObject({ entity_type: entityType,
    entity_uuid: uuid, server_id: counter, revision: counter })).max(500).optional(), transaction_id: uuid.optional(), committed_at: instant.optional(),
}).superRefine((v, ctx) => {
  if (['accepted','replayed'].includes(v.outcome) && (!v.canonical_entities?.length || !v.entity_mappings?.length || !v.transaction_id || !v.committed_at))
    ctx.addIssue({ code: 'custom', message: 'Incomplete accepted receipt' });
});
export type Result = z.infer<typeof result>;
export const pushResponse = z.strictObject({ protocol_version: z.literal(1), deployment_id: uuid, device_id: uuid,
  server_time: instant, results: z.array(result).min(1).max(50) });
export function newer(a: string, b: string) { return a.length > b.length || a.length === b.length && a > b; }
export function byteLength(v: string) {
  let bytes = 0;
  for (const char of v) { const cp = char.codePointAt(0)!; bytes += cp < 128 ? 1 : cp < 2048 ? 2 : cp < 65536 ? 3 : 4; }
  return bytes;
}
