import { phase4Pilot, phase5Pilot } from '../build-mode.native';
// Only the dedicated, embedded synthetic build on port7073. Ordinary apps and
// the retained Phase3 A/B sandbox stay gated, including development builds.
export const nativeSyncPilotEnabled = phase4Pilot || phase5Pilot;
export const nativeSyncGateReason = 'Native sync is enabled only in separate synthetic acceptance builds. This app cannot upload yet.';
