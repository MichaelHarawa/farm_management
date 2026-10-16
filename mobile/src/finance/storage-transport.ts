/** Platform-neutral, positive GET surface and local binding checks, NOT JWT authentication. */
import { z } from 'zod';
import { uuid } from '../protocol';

export const financialStorageGrantPath = '/mobile-sync/finance/storage/grant';
export const financialStorageRequestId = uuid.refine(value => value[14] === '4', 'Fresh random UUIDv4 required.');
export const financialStorageOptions = z.strictObject({ financialStorage: z.literal(1), requestId: financialStorageRequestId });
const accessClaims = z.object({ token_type: z.literal('access'), user_id: uuid, deployment_id: uuid,
  mobile_device_id: uuid, mobile_session_id: uuid, exp: z.number().int().positive() });
export interface MobileAccessBinding { actorId: string; deploymentId: string; deviceId: string; sessionId: string }

/** Decode only UUID binding claims from the token actually SENT. Django alone
 * verifies its signature/expiry. No Node Buffer, browser atob or saved access JWT.
 */
export function mobileAccessBinding(token: string): MobileAccessBinding {
  try {
    if (typeof token !== 'string' || token.length > 16384 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?![\s\S])/.test(token)) throw new Error();
    const payload = token.split('.')[1]!;
    if (payload.length % 4 === 1) throw new Error();
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
    let bits = 0, available = 0, escaped = '';
    for (const character of payload) {
      bits = (bits << 6) | alphabet.indexOf(character);
      available += 6;
      if (available >= 8) {
        available -= 8;
        escaped += '%' + ((bits >> available) & 255).toString(16).padStart(2, '0');
        bits &= (1 << available) - 1;
      }
    }
    if (bits !== 0) throw new Error();
    const claims = accessClaims.parse(JSON.parse(decodeURIComponent(escaped)));
    return { actorId: claims.user_id, deviceId: claims.mobile_device_id, deploymentId: claims.deployment_id, sessionId: claims.mobile_session_id };
  } catch { throw new Error('financial_storage_bound_access_required'); } // Never echo token/claim contents.
}
