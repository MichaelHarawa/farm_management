/** Fresh explicit command discovery, not a cached role, native grant or sync switch. */
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';
import type { MobileAccessBinding } from './storage-transport';

export const financialCommandCapabilities = z.strictObject({
  financial_protocol_version: z.literal(1), financial_command_version: z.literal(2),
  deployment_id: uuid, device_id: uuid, actor_id: uuid, server_time: instant,
  access: z.literal('online_only_current_authority'), offline_cache_seconds: z.literal(0),
  packs: z.array(z.never()).max(0), requires_separate_native_storage_grant: z.literal(true),
  submission_enabled: z.boolean(), status_recovery_enabled: z.literal(true),
  commands: z.array(z.literal('inventory.supplier_payment.record')).max(1),
  limits: z.strictObject({ request_bytes: z.literal(1048576), response_bytes: z.literal(131072), operations: z.literal(20),
    dependencies_per_operation: z.literal(20), invoices_per_operation: z.literal(10),
    lines_per_operation: z.literal(50), funding_rows_per_operation: z.literal(100) }),
}).superRefine((value, context) => {
  if (value.submission_enabled !== (value.commands.length === 1)) {
    context.addIssue({ code: 'custom', message: 'Financial command availability is inconsistent.' });
  }
});

export function parseFinancialCommandCapabilities(value: unknown, binding: MobileAccessBinding, identity: StoreIdentity) {
  const raw = JSON.stringify(value);
  if (typeof raw !== 'string' || byteLength(raw) > 8192) throw new Error('financial_command_capabilities_too_large');
  const parsed = financialCommandCapabilities.parse(value);
  if (parsed.actor_id !== identity.actorId || parsed.device_id !== identity.deviceId || parsed.deployment_id !== identity.deploymentId ||
      binding.actorId !== identity.actorId || binding.deviceId !== identity.deviceId || binding.deploymentId !== identity.deploymentId) {
    throw new Error('financial_command_identity_mismatch');
  }
  return parsed;
}
