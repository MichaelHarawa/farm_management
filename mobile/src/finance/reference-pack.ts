/** Private reference-pack decoder/completeness proof. NO HTTP/SQLite/native grant. */
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';
import { canonical } from '../db/repository';
import { byteLength } from '../sync/protocol';
import { fundingReferencePage } from './funding-references';
import { invoiceReferencePage } from './invoice-references';

export const referencePackId = 'financial-references-private-v1' as const;
const basis = 'financial-reference-pack-private-v1';
const digest = z.string().length(64).regex(/^[0-9a-f]{64}$/);
const counterPattern = /^(0|[1-9][0-9]{0,18})(?![\s\S])/;
const counter = z.string().max(19).regex(counterPattern)
  .refine(value => counterPattern.test(value) && BigInt(value) <= 9223372036854775807n);
const revision = counter.refine(value => value !== '0');
const integer = z.number().int().safe().nonnegative();
const cursor = z.string().min(1).max(4096);
const funding = z.strictObject({ financial_projection_version: z.literal(1),
  reference: fundingReferencePage.shape.rows.element, available: z.boolean(), source_version: digest });
const invoice = z.strictObject({ financial_projection_version: z.literal(1), invoice: invoiceReferencePage.shape.rows.element });
const commonEntity = { entity_uuid: uuid, revision };
export const referencePackEntity = z.union([
  z.strictObject({ ...commonEntity, entity_type: z.literal('finance.funding_selection'), payload: funding }),
  z.strictObject({ ...commonEntity, entity_type: z.literal('finance.invoice_reference'), payload: invoice }),
]);
const context = { financial_reference_pack_version: z.literal(1), pack_id: z.literal(referencePackId),
  deployment_id: uuid, stream_epoch: uuid, device_id: uuid, actor_id: uuid, scope_revision: digest,
  server_time: instant, access: z.literal('online_only_current_finance_writer'),
  offline_cache_seconds: z.literal(0), financial_uploads: z.literal(false) };
const descriptor = z.strictObject({ page: integer, row_count: integer.max(50), sha256: digest });
const withinExpiry = (value: { expires_at: string; server_time: string }) => {
  const remaining = Date.parse(value.expires_at) - Date.parse(value.server_time);
  return remaining > 0 && remaining <= 900000;
};
const bounded = (value: unknown) => byteLength(JSON.stringify(value)) <= 131072;
export const referencePackManifest = z.strictObject({ ...context, snapshot_id: uuid, watermark: counter,
  catalog_version: digest, expires_at: instant, row_count: integer.max(1100),
  manifest: z.array(descriptor).min(1).max(1100), next_page_cursor: cursor,
}).superRefine((value, ctx) => {
  if (!withinExpiry(value) || !bounded(value) || value.manifest.some((page, index) => page.page !== index ||
      page.row_count === 0 && (value.manifest.length !== 1 || value.row_count !== 0)) ||
      value.manifest.reduce((sum, page) => sum + page.row_count, 0) !== value.row_count) {
    ctx.addIssue({ code: 'custom', message: 'Invalid reference manifest; retain the previous replica and pending work.' });
  }
});
export const referencePackPage = z.strictObject({ ...context, snapshot_id: uuid, watermark: counter,
  catalog_version: digest, expires_at: instant, page: integer, sha256: digest,
  entities: z.array(referencePackEntity).max(50), next_page_cursor: cursor.nullable(), delta_cursor: cursor.nullable(),
}).refine(value => withinExpiry(value) && bounded(value) && (value.next_page_cursor === null) !== (value.delta_cursor === null));
const fragment = z.strictObject({ transaction_id: uuid, fragment_index: integer, fragment_final: z.boolean() });
const changeCommon = { ...commonEntity, ...fragment.shape, sequence: revision };
const change = z.union([
  z.strictObject({ ...changeCommon, entity_type: z.literal('finance.funding_selection'), kind: z.literal('upsert'), payload: funding }),
  z.strictObject({ ...changeCommon, entity_type: z.literal('finance.invoice_reference'), kind: z.literal('upsert'), payload: invoice }),
  z.strictObject({ ...changeCommon, entity_type: z.enum(['finance.funding_selection', 'finance.invoice_reference']), kind: z.literal('tombstone') }),
]);
export const referencePackDelta = z.strictObject({ ...context, run_watermark: counter,
  changes: z.array(change).max(50), fragments: z.array(fragment).max(50), next_cursor: cursor, run_complete: z.boolean(),
}).superRefine((value, ctx) => {
  // Zod can continue parent refinements after a child's regex/refinement error.
  // Never let malformed text reach BigInt or turn safeParse into an exception.
  if (!counter.safeParse(value.run_watermark).success || value.changes.some(item =>
    !revision.safeParse(item.sequence).success || !revision.safeParse(item.revision).success)) return;
  const ids = value.fragments.map(item => item.transaction_id);
  let groupIndex = -1;
  if (!bounded(value) || new Set(ids).size !== ids.length ||
      value.fragments.some((item, index) => index < value.fragments.length - 1 && !item.fragment_final) ||
      value.run_complete && value.fragments.some(item => !item.fragment_final) ||
      value.changes.some((item, index) => {
        const previous = value.changes[index - 1];
        const expected = value.fragments.find(part => part.transaction_id === item.transaction_id);
        const nextGroup = ids.indexOf(item.transaction_id);
        const invalid = !expected || expected.fragment_index !== item.fragment_index || expected.fragment_final !== item.fragment_final ||
          nextGroup < groupIndex || BigInt(item.sequence) > BigInt(value.run_watermark) ||
          previous !== undefined && BigInt(item.sequence) <= BigInt(previous.sequence) ||
          item.kind === 'tombstone' && (item.entity_type !== 'finance.funding_selection' || BigInt(item.revision) < 2n);
        groupIndex = nextGroup;
        return invalid;
      })) {
    ctx.addIssue({ code: 'custom', message: 'Invalid reference delta or group completion; do not advance its cursor.' });
  }
});

export interface ReferencePackExpectation { identity: StoreIdentity; epoch: string; scopeRevision: string }
function bound<T extends { deployment_id: string; device_id: string; actor_id: string; stream_epoch: string; scope_revision: string }>(
  value: T, expected: ReferencePackExpectation): T {
  if (value.deployment_id !== uuid.parse(expected.identity.deploymentId) || value.device_id !== uuid.parse(expected.identity.deviceId) ||
      value.actor_id !== uuid.parse(expected.identity.actorId) || value.stream_epoch !== uuid.parse(expected.epoch) ||
      value.scope_revision !== digest.parse(expected.scopeRevision)) throw new Error('financial_reference_pack_scope_changed_retain_work');
  return value;
}
export function parseReferencePackManifest(value: unknown, expected: ReferencePackExpectation) {
  return bound(referencePackManifest.parse(value), expected);
}
export function parseReferencePackDelta(value: unknown, expected: ReferencePackExpectation, afterVisibleSequence?: string) {
  const page = bound(referencePackDelta.parse(value), expected);
  if (afterVisibleSequence !== undefined && (BigInt(counter.parse(afterVisibleSequence)) > BigInt(page.run_watermark) ||
      page.changes.some(row => BigInt(row.sequence) <= BigInt(afterVisibleSequence)))) throw new Error('financial_reference_delta_reordered_retain_cursor');
  return page;
}

/** Finite IN-MEMORY completeness proof only. Caller MUST NOT activate a partial
 * pack or treat this as the future encrypted sensitive-cache/offline policy. */
export async function verifyReferencePackPages(manifestValue: unknown, values: unknown[], expected: ReferencePackExpectation,
  hash: (text: string) => Promise<string>) {
  const manifest = parseReferencePackManifest(manifestValue, expected);
  if (values.length !== manifest.manifest.length) throw new Error('financial_reference_pack_incomplete');
  const pages = values.map(value => bound(referencePackPage.parse(value), expected));
  for (const [index, page] of pages.entries()) {
    const descriptor = manifest.manifest[index];
    if (!descriptor || page.page !== index || page.snapshot_id !== manifest.snapshot_id || page.watermark !== manifest.watermark ||
        page.catalog_version !== manifest.catalog_version || page.expires_at !== manifest.expires_at ||
        page.entities.length !== descriptor.row_count || page.sha256 !== descriptor.sha256 ||
        await hash(canonical(page.entities)) !== page.sha256 ||
        (index === pages.length - 1 ? page.next_page_cursor !== null || page.delta_cursor === null :
          page.next_page_cursor === null || page.delta_cursor !== null)) throw new Error('financial_reference_pack_page_mismatch_retain_replica');
  }
  const rows = pages.flatMap(page => page.entities);
  const key = (row: typeof rows[number]) => `${row.entity_type}:${row.entity_uuid}`;
  if (rows.length !== manifest.row_count || byteLength(canonical(rows)) > 2097152 ||
      rows.some((row, index) => { const previous = rows[index - 1]; return previous !== undefined && key(row) <= key(previous); }) ||
      new Set(rows.map(row => row.entity_uuid)).size !== rows.length ||
      await hash(canonical({ basis, scope: manifest.scope_revision, rows })) !== manifest.catalog_version) {
    throw new Error('financial_reference_pack_incomplete_or_changed_retain_replica');
  }
  const last = pages[pages.length - 1];
  if (!last || last.delta_cursor === null) throw new Error('financial_reference_pack_incomplete');
  return { manifest, rows, deltaCursor: last.delta_cursor };
}
