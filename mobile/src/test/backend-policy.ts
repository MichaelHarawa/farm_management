import type { AppSettings } from '../config';
export const testBackendA = 'http://10.0.2.2:7071/api/v1';
export const testBackendB = 'http://10.0.2.2:7072/api/v1';
export function testBackendAvailable(settings: AppSettings, enabled: boolean): boolean {
  return enabled && settings.environment === 'development' && [testBackendA, testBackendB].includes(settings.apiBaseUrl);
}
export function selectedTestBackend(base: string, compiled: AppSettings, enabled: boolean): AppSettings {
  if (!testBackendAvailable(compiled, enabled) || ![testBackendA, testBackendB].includes(base)) throw new Error('test_backend_unavailable');
  return { ...compiled, apiBaseUrl: base };
}
