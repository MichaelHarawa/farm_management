/** Closed prompt purposes; only wording changes, never the unlock strength/fallback policy. */
export type DeviceUnlockPurpose = 'operational' | 'financial';
export function deviceUnlockOptions(purpose: unknown = 'operational') {
  if (purpose !== 'operational' && purpose !== 'financial') throw new Error('device_unlock_purpose_invalid');
  return Object.freeze({
    promptMessage: purpose === 'financial' ? 'Unlock encrypted financial evidence' : 'Unlock encrypted farm records',
    disableDeviceFallback: false,
    biometricsSecurityLevel: 'strong' as const,
  });
}
