import 'tsx/cjs'; // Expo transpiles the config, not imported local TS modules.
import type { ExpoConfig } from 'expo/config';
import { validateSettings } from './src/config';

const settings = validateSettings(process.env.APP_ENV ?? 'development', process.env.API_BASE_URL ?? 'http://10.0.2.2:7071/api/v1', process.env.MOBILE_RELEASE === '1');
const localAcceptance = process.env.MOBILE_LOCAL_ACCEPTANCE === '1';
const phase4Pilot = process.env.MOBILE_PHASE4_PILOT === '1';
const phase5Pilot = process.env.MOBILE_PHASE5_PILOT === '1';
if (phase5Pilot && (!localAcceptance || phase4Pilot)) throw new Error('Phase 5 requires its own isolated acceptance build.');
if (phase4Pilot && !localAcceptance) throw new Error('Phase 4 pilot requires the isolated local acceptance build.');
if (localAcceptance && (settings.environment !== 'development' || settings.apiBaseUrl !== `http://10.0.2.2:${phase5Pilot ? '7074' : phase4Pilot ? '7073' : '7071'}/api/v1` || process.env.MOBILE_RELEASE === '1')) {
  throw new Error('Offline acceptance is restricted to the separate local synthetic backend build.');
}
const config: ExpoConfig = {
  name: `Farm Management${settings.environment === 'production' ? '' : ` (${settings.environment})`}`,
  slug: 'farm-management-mobile', version: '0.3.0', scheme: 'farm-management', platforms: ['android'],
  android: { package: `com.farmmanagement.mobile${settings.environment === 'production' ? '' : settings.environment === 'staging' ? '.staging' : '.dev'}`, allowBackup: false },
  extra: { ...settings, localAcceptance, phase4Pilot, phase5Pilot },
  plugins: ['expo-router', '@react-native-community/datetimepicker', ['expo-secure-store', { configureAndroidBackup: false }],
    ['expo-sqlite', { useSQLCipher: true }],
    ['expo-build-properties', { android: { minSdkVersion: 24, compileSdkVersion: 36, targetSdkVersion: 36 } }],
    ['./plugins/with-private-storage.cjs', { developmentHost: new URL(settings.apiBaseUrl).protocol === 'http:' ? new URL(settings.apiBaseUrl).hostname : null }]],
};
export default config;
