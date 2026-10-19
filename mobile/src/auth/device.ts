import * as LocalAuthentication from 'expo-local-authentication';
import { deviceUnlockOptions, type DeviceUnlockPurpose } from './device-policy';

export async function deviceUnlock(purpose: DeviceUnlockPurpose = 'operational'): Promise<boolean> {
  const options = deviceUnlockOptions(purpose);
  const level = await LocalAuthentication.getEnrolledLevelAsync();
  if (level < LocalAuthentication.SecurityLevel.SECRET) throw new Error('device_lock_required');
  const result = await LocalAuthentication.authenticateAsync(options);
  if (!result.success) throw new Error('device_unlock_cancelled');
  // SecureStore's crypto-bound Android prompt requires class-3 biometrics; it
  // cannot use PIN fallback. PIN-only phones instead use app/device unlock plus
  // the OS Keystore-wrapped key, explicitly recorded per store (not equivalent).
  return level === LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG;
}
