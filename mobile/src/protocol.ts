import { z } from 'zod';
export const uuid = z.uuid().refine((v) => v === v.toLowerCase());
export const instant = z.iso.datetime({ precision: null }).refine((v) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v));
export const userSchema = z.object({ id: uuid, username: z.string(), full_name: z.string(), roles: z.array(z.object({ slug: z.string(), name: z.string() })) });
export type CurrentUser = z.infer<typeof userSchema>;
export const tokenPairSchema = z.object({ access: z.string().min(1), refresh: z.string().min(1) });
export const registrationSchema = tokenPairSchema.extend({ deployment_id: uuid, device_id: uuid, policy: z.object({ protocol_version: z.literal(1), operational_offline_days: z.number().positive().max(7), sensitive_offline_hours: z.number().positive().max(24) }) });
export const capabilitiesSchema = z.object({
  protocol_version: z.literal(1), schema_version: z.literal(1), policy_version: z.literal(1), projection_version: z.literal(1),
  deployment_id: uuid, device_id: uuid, stream_epoch: uuid, server_time: instant, scope_revision: z.string().min(1),
  entities: z.array(z.enum(['poultry.batch', 'poultry.mortality', 'poultry.feed_usage'])),
  commands: z.record(z.string(), z.object({ available: z.boolean(), payload_version: z.number().optional(), reason: z.string().optional() })),
  offline: z.object({ operational_days: z.number().positive().max(7), sensitive_hours: z.number().positive().max(24) }),
});
export type Capabilities = z.infer<typeof capabilitiesSchema>;
export interface StoreIdentity { deploymentId: string; actorId: string; deviceId: string }
export const mortalityCommand = z.strictObject({
  operation_id: uuid, entity_uuid: uuid, entity_type: z.literal('poultry.mortality'), action: z.literal('record'),
  payload_version: z.literal(1), base_version: z.null(), captured_at: instant,
  depends_on: z.array(uuid).max(20).refine((v) => new Set(v).size === v.length), supersedes_operation_id: uuid.optional(),
  payload: z.strictObject({ batch_uuid: uuid, mortality_date: instant, quantity_dead: z.number().int().positive().max(2147483647),
    suspected_cause: z.string().min(1).max(200).refine((v) => /\S/.test(v)), description: z.string().min(1).max(4000).refine((v) => /\S/.test(v)),
    action_taken: z.string().min(1).max(4000).refine((v) => /\S/.test(v)), reported_by_name: z.string().min(1).max(200).refine((v) => /\S/.test(v)) }),
});
export type MortalityCommand = z.infer<typeof mortalityCommand>;
