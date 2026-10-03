import { ApiError } from './client';

const stages = {
  sign_in_request: 'Django sign-in', device_registration: 'device registration',
  encrypted_store: 'encrypted local storage', current_user: 'current-user validation',
  capabilities: 'capability validation', save_session: 'secure session persistence',
} as const;
export type SessionStage = keyof typeof stages;

export function sessionErrorMessage(error: unknown, stage?: SessionStage): string {
  // Only application-owned codes/statuses and fixed stage labels. Never display
  // arbitrary native SQL, server bodies, fetch errors, passwords or key material.
  const allowed = ['database_key_missing', 'invalid_database_key', 'original_identity_mismatch',
    'sqlcipher_native_build_required', 'database_upgrade_required', 'sign_in_required',
    'mobile_backend_not_ready', 'clock_rollback', 'offline_window_expired',
    'online_sign_in_required', 'device_lock_required', 'device_unlock_cancelled'];
  let message = 'Could not open the session. Check the connection, credentials, device unlock and backend readiness. Existing local work is retained.';
  if (error instanceof Error && allowed.includes(error.message)) message = error.message;
  else if (error instanceof ApiError && [400, 401, 403, 404, 409, 429, 500, 503].includes(error.status)) {
    message = `Backend request failed (HTTP ${error.status}). Check credentials, device access and backend readiness. Existing local work is retained.`;
  }
  return stage ? `${message} Step: ${stages[stage]}.` : message;
}
