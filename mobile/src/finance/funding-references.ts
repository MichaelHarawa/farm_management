/** Private preparation contract only: no API, UI, cache or upload integration. */
import { z } from 'zod';
import { instant, uuid, type StoreIdentity } from '../protocol';

const digest = z.string().regex(/^[0-9a-f]{64}$/);
const referenceId = uuid.refine(value => value === value.toLowerCase());
const types = ['batch_collection', 'owner_capital', 'loan', 'grant', 'other_income', 'general_farm_cash'] as const;
const reference = z.strictObject({ reference_id: referenceId, reference_version: digest,
  source_type: z.enum(types), label: z.string().refine(value => value.trim() === value && [...value].length >= 1 && [...value].length <= 255),
  currency: z.literal('MWK'), cash_pool_id: referenceId,
  cash_pool_semantics: z.enum(['shared_batch_collection', 'source_specific']),
  balance_semantics: z.literal('not_a_cash_balance_or_reservation'),
}).superRefine((value, ctx) => {
  if (value.source_type === 'batch_collection' ? value.cash_pool_semantics !== 'shared_batch_collection' :
      value.cash_pool_semantics !== 'source_specific' || value.cash_pool_id !== value.reference_id) {
    ctx.addIssue({ code: 'custom', message: 'Invalid funding pool semantics; never infer separate alias balances.' });
  }
});
export const fundingReferencePage = z.strictObject({ financial_reference_version: z.literal(1),
  deployment_id: referenceId, device_id: referenceId, scope_revision: digest, catalog_version: digest,
  server_time: instant, access: z.literal('online_only_current_finance_writer'), offline_cache_seconds: z.literal(0),
  financial_uploads: z.literal(false), total_authorized_rows: z.number().int().min(0).max(1000),
  rows: z.array(reference).max(50), next_cursor: z.string().min(1).max(2048).nullable(),
}).superRefine((page, ctx) => {
  if (page.rows.length > page.total_authorized_rows ||
      new Set(page.rows.map(row => row.reference_id)).size !== page.rows.length ||
      page.next_cursor !== null && (page.rows.length === 0 || page.rows.length >= page.total_authorized_rows) ||
      page.rows.some((row, index) => {
        const previous = page.rows[index - 1];
        return previous !== undefined && row.reference_id <= previous.reference_id;
      })) {
    ctx.addIssue({ code: 'custom', message: 'Invalid catalog page membership; retain pending selections unchanged.' });
  }
});
export const fundingReferenceRows = z.array(z.strictObject({ funding_source: referenceId, funding_version: digest,
  amount: z.string().regex(/^(0|[1-9][0-9]{0,11})\.[0-9]{2}$/).refine(value => value !== '0.00'),
  classification: z.enum(['reinvestment', 'working_capital', 'cost_recovery', 'owner_distribution',
    'owner_capital_return', 'owner_drawing', 'owner_compensation', 'debt_service', 'other']).optional(),
})).min(1).max(100).refine(rows => new Set(rows.map(row => row.funding_source)).size === rows.length);

interface Expectation { identity: StoreIdentity; scopeRevision?: string; catalogVersion?: string }
export function parseFundingReferencePage(value: unknown, expected: Expectation) {
  const page = fundingReferencePage.parse(value);
  if (page.deployment_id !== expected.identity.deploymentId || page.device_id !== expected.identity.deviceId ||
      expected.scopeRevision !== undefined && page.scope_revision !== digest.parse(expected.scopeRevision) ||
      expected.catalogVersion !== undefined && page.catalog_version !== digest.parse(expected.catalogVersion)) {
    throw new Error('funding_reference_identity_or_scope_changed_retain_original');
  }
  return page;
}

/** In-memory completeness check, not activation of sensitive offline access. */
export function verifyFundingReferencePages(values: unknown[], expected: Expectation) {
  if (values.length === 0 || values.length > 20) throw new Error('funding_catalog_incomplete');
  const first = parseFundingReferencePage(values[0], expected);
  const pages = values.map(value => parseFundingReferencePage(value, { ...expected,
    scopeRevision: first.scope_revision, catalogVersion: first.catalog_version }));
  const rows = pages.flatMap(page => page.rows);
  if (pages.some((page, index) => page.total_authorized_rows !== first.total_authorized_rows ||
      (index === pages.length - 1 ? page.next_cursor !== null : page.next_cursor === null)) ||
      rows.length !== first.total_authorized_rows ||
      new Set(rows.map(row => row.reference_id)).size !== rows.length ||
      rows.some((row, index) => {
        const previous = rows[index - 1];
        return previous !== undefined && row.reference_id <= previous.reference_id;
      })) {
    throw new Error('funding_catalog_incomplete_or_changed_retain_original');
  }
  return rows;
}
