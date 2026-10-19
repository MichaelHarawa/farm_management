/** Closed diagnostic vocabulary. Never render native SQL, payloads, tokens or keys. */
const steps = {
  start: 'starting the scratch action',
  descriptor_read: 'reading the retained scratch descriptor',
  fixture_creation: 'creating the synthetic fixture',
  namespace: 'deriving the scratch namespace',
  new_files: 'checking that scratch files are absent',
  new_keys: 'checking that scratch key names are unused',
  descriptor_write: 'retaining the original scratch descriptor',
  existing_file: 'checking the original retained database exists',
  keyed_open: 'opening the independently keyed native database',
  seed: 'initializing or verifying the original scratch fixture',
  rollback: 'checking scratch transaction rollback',
  checkpoint_close: 'checkpointing and closing scratch SQL',
  encrypted_readers: 'checking encrypted file and wrong-key readers',
  verify: 'verifying the exact original scratch evidence',
  locked: 'checking public financial access remains locked',
  pin_policy: 'checking the scratch PIN-only policy',
  scratch_key_read: 'reading the original scratch key privately',
  file_snapshot: 'snapshotting the closed scratch file',
  missing_key: 'checking missing-key refusal',
  unchanged_file: 'checking the scratch file was not changed',
  restore_key: 'restoring only the original scratch key',
  restored_evidence: 'verifying original evidence after key restoration',
  inspection: 'reading scratch file and policy metadata',
  enrollment: 'reading device-unlock enrollment metadata',
  native_files: 'native file and companion checks',
  native_policy_read: 'native key-policy read',
  native_unlock: 'private native device unlock',
  native_policy_write: 'native key-policy provisioning',
  native_key_read: 'native private key read',
  native_key_generation: 'native random-key generation',
  native_key_write: 'native private key provisioning',
  native_sqlite_open: 'native SQLite connection open',
  native_cipher_key: 'native cipher-key application',
  native_cipher_version: 'native cipher-version check',
  native_schema_read: 'native keyed schema read',
  native_modes: 'native journal/security setup',
  native_policy_finalize: 'native initialized-policy persistence',
} as const;
export type FinancialProbeStep = keyof typeof steps;
const codes = new Set(['financial_scratch_check_failed', 'financial_scratch_integrity_failed',
  'existing_financial_scratch_retained', 'prepare_financial_scratch_first',
  'financial_database_missing_retain_key', 'financial_database_key_missing',
  'financial_database_open_failed_retain_original', 'financial_database_close_failed',
  'financial_database_already_owned', 'sqlcipher_native_build_required',
  'device_lock_required', 'device_unlock_cancelled', 'invalid_financial_database_filename',
  'invalid_database_directory', 'financial_storage_identity_mismatch_retain_original',
  'financial_storage_upgrade_or_review_required']);
class FinancialProbeFailure extends Error {
  constructor(readonly step: FinancialProbeStep, readonly code: string) { super('financial_scratch_step_failed'); }
}
export async function traceFinancialProbe<T>(work: (step: (value: FinancialProbeStep) => void) => Promise<T>) {
  let current: FinancialProbeStep = 'start';
  try { return await work(value => { current = value; }); }
  catch (error) {
    const code = error instanceof Error && codes.has(error.message) ? error.message : 'native_or_validation_failure';
    throw new FinancialProbeFailure(current, code); // Deliberately no raw cause/stack/message propagation.
  }
}
export function financialProbeFailureMessage(error: unknown) {
  const preserved = 'Preserve the scratch database/key/descriptor. No grant, payment or upload was executed.';
  if (error instanceof FinancialProbeFailure && Object.prototype.hasOwnProperty.call(steps, error.step) &&
      (codes.has(error.code) || error.code === 'native_or_validation_failure')) {
    return `FAILED at ${steps[error.step]}. Code: ${error.code}. ${preserved}`;
  }
  return `FAILED or cancelled before a diagnostic result was available. ${preserved}`;
}
