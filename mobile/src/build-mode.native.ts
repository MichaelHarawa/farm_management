import Constants from 'expo-constants';
import { NativeModules } from 'react-native';
import { localAcceptanceEnabled, phase4PilotEnabled, phase5PilotEnabled, phase6EvidenceEnabled } from './build-mode-policy';

const extra = Constants.expoConfig?.extra;
export const phase4Pilot = extra?.localAcceptance === true && phase4PilotEnabled(extra?.environment, extra?.apiBaseUrl, extra?.phase4Pilot, NativeModules.FarmBuildInfo);
export const phase5Pilot = extra?.localAcceptance === true && phase5PilotEnabled(extra?.environment, extra?.apiBaseUrl, extra?.phase5Pilot, NativeModules.FarmBuildInfo);
export const phase6Evidence = extra?.localAcceptance === true && extra?.phase4Pilot === false && extra?.phase5Pilot === false &&
  phase6EvidenceEnabled(extra?.environment, extra?.apiBaseUrl, extra?.phase6Evidence, NativeModules.FarmBuildInfo);
export const localAcceptance = phase4Pilot || phase5Pilot || phase6Evidence || localAcceptanceEnabled(extra?.environment, extra?.apiBaseUrl, extra?.localAcceptance, NativeModules.FarmBuildInfo);
export const developmentChecksEnabled = __DEV__ || localAcceptance;
