import { z } from 'zod';
import { instant, uuid, mortalityCommand } from '../protocol';

const quantity = z.number().int().positive().max(2147483647);
const text = (max = 4000) => z.string().max(max).refine(v => /\S/.test(v), 'Required');
const envelope = mortalityCommand.omit({ entity_type: true, action: true, payload: true, base_version: true });
const append = { base_version: z.null() };
const update = { base_version: z.string().regex(/^[1-9][0-9]{0,39}$/).nullable() };
const parent = { batch_uuid: uuid };
const reporter = { reported_by_name: text(200) };
export const poultryCommand = z.union([
  mortalityCommand,
  envelope.extend({ ...append, entity_type: z.literal('poultry.batch'), action: z.literal('book'), payload: z.strictObject({
    bird_type: z.enum(['broilers','layers','local','kloilers','mikolongwe']), broiler_strain: z.enum(['ross308','cobb500','']).optional(),
    source: z.enum(['central_poultry','proto','other']), source_other: z.string().max(200).optional(),
    booking_date: z.iso.date(), estimated_chick_arrival_date: z.iso.date(), supplier_name: z.string().max(200).optional(),
    booking_reference: z.string().max(120).optional(), expected_quantity: quantity, entry_date: instant, expected_maturity_date: instant }) }),
  envelope.extend({ ...update, entity_type: z.literal('poultry.batch'), action: z.literal('mark_delivered'), payload: z.strictObject(parent) }),
  envelope.extend({ ...update, entity_type: z.literal('poultry.batch'), action: z.literal('confirm_delivery'), payload: z.strictObject({ ...parent,
    entry_date: instant, expected_maturity_date: instant.optional(), quantity }) }),
  envelope.extend({ ...append, entity_type: z.literal('poultry.feed_usage'), action: z.literal('record'), payload: z.strictObject({ ...parent, ...reporter,
    feeding_start_date: instant, feeding_end_date: instant, feed_type: z.enum(['pre_starter','starter','grower','finisher','pullet_starter','pullet_grower','layers_marsh','layers_finisher']),
    feed_source: z.enum(['cp_feed','proto_feed','concentrates_feed','self_made']), quantity_given: quantity,
    unit_of_measurement: z.enum(['kg','g']), notes: text() }) }),
  envelope.extend({ ...append, entity_type: z.literal('poultry.treatment'), action: z.literal('record'), payload: z.strictObject({ ...parent, ...reporter,
    vaccination_date: instant, drug_category: z.enum(['vaccination','drug','antibiotic','vitamin','dewormer','other']),
    drug_vaccination_type: z.enum(['gumbolo','hitchner','lasota','other']), other_drug_vaccination: z.string().max(200).optional(),
    quantity, description: text(), timely_status: text(200) }) }),
  envelope.extend({ ...append, entity_type: z.literal('poultry.weight_sample'), action: z.literal('record'), payload: z.strictObject({ ...parent, ...reporter,
    sampled_at: instant, average_weight_g: quantity, sample_size: quantity, notes: z.string().max(4000).optional() }) }),
  envelope.extend({ ...append, entity_type: z.literal('poultry.adjustment_proposal'), action: z.literal('propose'), payload: z.strictObject({ ...parent,
    effective_at: instant, quantity_change: z.number().int().min(-2147483648).max(2147483647).refine(v => v !== 0), reason: text(255) }) }),
  envelope.extend({ ...update, entity_type: z.literal('poultry.adjustment_proposal'), action: z.enum(['approve','reject']), payload: z.strictObject({ reason: text(255) }) }),
  envelope.extend({ ...update, entity_type: z.literal('poultry.batch'), action: z.literal('recalculate_feed'), payload: z.strictObject({ ...parent, reason: text(255) }) }),
]).superRefine((command, ctx) => {
  if (['mark_delivered','confirm_delivery','approve','reject','recalculate_feed'].includes(command.action) && command.base_version === null && !command.depends_on.length)
    ctx.addIssue({ code: 'custom', path: ['base_version'], message: 'A confirmed revision or an explicit parent dependency is required.' });
});
export type PoultryCommand = z.infer<typeof poultryCommand>;
export const onlineOnly = (operation: PoultryCommand) => ['approve','reject','recalculate_feed'].includes(operation.action);
export const commandName = (operation: PoultryCommand) => `${operation.entity_type}.${operation.action}`;

export function normalizedPayload(payload: object): Record<string, unknown> {
  // Match Django's exact UTC microsecond normalization for *every* dated field.
  const instants=new Set(['mortality_date','feeding_start_date','feeding_end_date','vaccination_date','sampled_at','effective_at','entry_date','expected_maturity_date']);
  return Object.fromEntries(Object.entries(payload).map(([key, value]) => [key,
    instants.has(key) && typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(value)
      ? value.replace(/(?:\.(\d{1,6}))?Z$/, (_match, fraction: string | undefined) =>
        fraction && /[1-9]/.test(fraction) ? `.${fraction.padEnd(6, '0')}Z` : 'Z') : value]));
}
