import { ApiError } from '../auth/client';

const messages: Record<string, string> = {
  financial_storage_reauthentication_required: 'Financial evidence needs fresh online authorization. Original local work is retained.',
  financial_compartment_locked: 'Financial evidence is locked. Unlock or request current authorization; original evidence is retained.',
  financial_compartment_busy: 'A financial storage action is already running. Wait before trying again.',
  financial_storage_window_expired_reauthenticate: 'Financial access has expired. Request current online authorization; original evidence is retained.',
  financial_storage_clock_rollback: 'The device clock moved backwards. Financial evidence remains locked; request current online authorization.',
  financial_database_key_missing: 'The original financial key is unavailable. Do not reset the database; retain it for review.',
  financial_database_missing_retain_key: 'The original financial database is missing. Its retained key must not be replaced.',
  financial_evidence_review_required: 'Original financial evidence needs review. Nothing was deleted, replaced or uploaded.',
  device_unlock_cancelled: 'Private unlock was cancelled. Existing evidence is retained.',
  device_lock_required: 'Configure a private device lock before opening financial evidence.',
  granted_financial_fixture_descriptor_required: 'No original synthetic fixture descriptor is available. Do not replace existing evidence; retain it for review.',
  granted_financial_fixture_unavailable: 'This synthetic fixture is available only to the isolated Phase 6 test manager. No financial evidence was uploaded.',
  granted_financial_fixture_stale: 'The original unlocked financial session changed. Reopen it before checking its retained synthetic fixture.',
  granted_financial_fixture_descriptor_invalid: 'The retained synthetic fixture descriptor is invalid. Nothing was reset or replaced; retain it for review.',
  granted_financial_fixture_descriptor_changed: 'The original synthetic fixture descriptor changed. Nothing was reset or replaced; retain it for review.',
  granted_financial_fixture_scope_mismatch: 'The synthetic fixture belongs to a different backend or account scope. Its original evidence is retained.',
  granted_financial_fixture_evidence_mismatch: 'The exact original synthetic evidence could not be verified. Nothing was reset, replaced or uploaded; retain it for review.',
  granted_financial_fixture_review_required: 'The private synthetic fixture file needs review. Nothing was reset or replaced.',
  granted_financial_fixture_failed: 'The synthetic storage check did not complete. Its original descriptor and evidence are retained; retry only the original after review.',
};
export function financialErrorMessage(error: unknown): string {
  if (error instanceof Error && Object.prototype.hasOwnProperty.call(messages, error.message)) return messages[error.message]!;
  if (error instanceof ApiError && [400, 401, 403, 404, 409, 429, 500, 503].includes(error.status)) {
    return `Financial authorization or storage request did not complete (HTTP ${error.status}). Existing evidence is retained; no posting or upload was performed.`;
  }
  return 'Financial access did not complete. Check current authorization, connection and private unlock. Original evidence is retained; no posting or upload was performed.';
}
