import * as LocalAuthentication from 'expo-local-authentication';

export async function deviceUnlock(): Promise<boolean> {
  const level = await LocalAuthentication.getEnrolledLevelAsync();
  if (level < LocalAuthentication.SecurityLevel.SECRET) throw new Error('device_lock_required');
  const result = await LocalAuthentication.authenticateAsync({ promptMessage: 'Unlock encrypted farm records', disableDeviceFallback: false, biometricsSecurityLevel: 'strong' });
  if (!result.success) throw new Error('device_unlock_cancelled');
  // SecureStore's crypto-bound Android prompt requires class-3 biometrics; it
  // cannot use PIN fallback. PIN-only phones instead use app/device unlock plus
  // the OS Keystore-wrapped key, explicitly recorded per store (not equivalent).
  return level === LocalAuthentication.SecurityLevel.BIOMETRIC_STRONG;
}
