// A bundled acceptance app cannot run Expo's Metro-only development runtime.
// Enable synthetic diagnostics explicitly, only for this separate native build.
// Android release guards reject development config and this test flag.
export function localAcceptanceEnabled(environment: unknown, apiBaseUrl: unknown, flag: unknown, nativeBuild: unknown): boolean {
  if (!nativeBuild || typeof nativeBuild !== 'object') return false;
  const build = nativeBuild as Record<string, unknown>;
  return environment === 'development' && apiBaseUrl === 'http://10.0.2.2:7071/api/v1' && flag === true &&
    build.applicationId === 'com.farmmanagement.mobile.dev.acceptance' && build.buildType === 'localAcceptance';
}

// The upload pilot has its own Android sandbox and can never point at A/B or
// the farm API. Flags alone cannot enable it in an ordinary debug/release app.
export function phase4PilotEnabled(environment: unknown, apiBaseUrl: unknown, flag: unknown, nativeBuild: unknown): boolean {
  if (!nativeBuild || typeof nativeBuild !== 'object') return false;
  const build = nativeBuild as Record<string, unknown>;
  return environment === 'development' && apiBaseUrl === 'http://10.0.2.2:7073/api/v1' && flag === true &&
    build.applicationId === 'com.farmmanagement.mobile.dev.acceptance.phase4' && build.buildType === 'localAcceptance';
}

export function phase5PilotEnabled(environment: unknown, apiBaseUrl: unknown, flag: unknown, nativeBuild: unknown): boolean {
  if (!nativeBuild || typeof nativeBuild !== 'object') return false;
  const build = nativeBuild as Record<string, unknown>;
  return environment === 'development' && apiBaseUrl === 'http://10.0.2.2:7074/api/v1' && flag === true &&
    build.applicationId === 'com.farmmanagement.mobile.dev.acceptance.phase5' && build.buildType === 'localAcceptance';
}
