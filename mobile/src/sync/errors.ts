import {ZodError} from 'zod';
import {ApiError} from '../auth/client';

const internalCodes=new Set([
  'snapshot_identity_or_manifest','snapshot_changed','snapshot_expired','snapshot_page_order',
  'snapshot_checksum_or_completion','snapshot_row_count','snapshot_missing_parent','snapshot_budget',
  'pull_identity_or_cursor','pull_budget_or_no_progress','bootstrap_required',
  'sync_canceled','sync_lease_lost','sync_run_budget','session_locked','sign_in_required',
  'server_identity_mismatch','foreign_receipt','push_receipt_set_mismatch','receipt_changed',
  'receipt_entity_mismatch','receipt_payload_mismatch','mapping_rebound','query_original_operation',
  'response_too_large',
]);
const serverCodes=new Set([
  'resync_required','scope_reset_required','snapshot_not_found','snapshot_pack_mismatch',
  'snapshot_limit','operation_not_found','unsupported_protocol',
]);

function diagnostic(error:unknown):string{
  if(error instanceof ApiError)return `${serverCodes.has(error.code)?error.code:'backend_request'} (HTTP ${error.status})`;
  if(error instanceof ZodError)return 'protocol_validation';
  if(error instanceof SyntaxError)return 'invalid_json';
  if(error instanceof Error){
    if(internalCodes.has(error.message))return error.message;
    if(/\bSQLITE_CONSTRAINT\b|\b(?:UNIQUE|CHECK|FOREIGN KEY|NOT NULL) constraint failed/i.test(error.message))return 'local_integrity_conflict';
    if(/\bSQLITE_BUSY\b|\bdatabase is locked\b/i.test(error.message))return 'local_store_busy';
  }
  return 'unclassified_failure';
}

// Never display arbitrary server/native/validation text: it may contain a JWT,
// SQL, database key or record payload. Native acceptance gets only fixed codes.
export function syncErrorMessage(error:unknown,action:'sync'|'batch_download',nativeDiagnostic=false):string{
  let message=action==='sync'?'Sync did not complete. Pending work and original operation IDs are retained.':
    'Batch download did not complete. Existing data and work remain.';
  if(error instanceof ApiError&&[401,403].includes(error.status))message='Sign in again to validate access. Original local work is retained.';
  else if(error instanceof ApiError&&error.status===429&&error.code==='snapshot_limit')message=
    'The server download limit is reached. Resume an existing incomplete download or retry after its snapshots expire. Existing data and pending work are retained.';
  return nativeDiagnostic?`${message} Check: ${diagnostic(error)}.`:message;
}
