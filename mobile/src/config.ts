export type Environment = 'development' | 'staging' | 'production';
export interface AppSettings { environment: Environment; apiBaseUrl: string }

export function validateSettings(environment: string, apiBaseUrl: string, release = false): AppSettings {
  if (!['development', 'staging', 'production'].includes(environment)) throw new Error('Select APP_ENV explicitly.');
  const url = new URL(apiBaseUrl);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/api/v1') {
    throw new Error('API_BASE_URL must end in /api/v1 without credentials, query or fragment.');
  }
  const local = url.hostname === '10.0.2.2' || url.hostname === 'localhost' || url.hostname === '127.0.0.1' ||
    /^192\.168\.\d{1,3}\.\d{1,3}$/.test(url.hostname) || /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(url.hostname) ||
    /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(url.hostname);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && environment === 'development' && !release && local)) {
    throw new Error('HTTPS is required except for a private development host in a debug build.');
  }
  if (release && environment === 'development') throw new Error('Release requires staging or production configuration.');
  return { environment: environment as Environment, apiBaseUrl: url.toString().replace(/\/$/, '') };
}
