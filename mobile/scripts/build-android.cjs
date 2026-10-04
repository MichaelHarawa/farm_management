const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '..');
const windows = process.platform === 'win32';
const args = process.argv.slice(2);
const phase4 = args.includes('--phase4-acceptance');
const phase5 = args.includes('--phase5-acceptance');
const acceptance = args.includes('--acceptance') || phase4 || phase5;
const abi = args.find((arg) => arg.startsWith('--abi='))?.slice('--abi='.length);
if (phase4 && phase5 || args.some((arg) => !['--acceptance', '--phase4-acceptance', '--phase5-acceptance', '--release'].includes(arg) && !arg.startsWith('--abi=')) ||
    (abi && !['x86_64', 'arm64-v8a', 'armeabi-v7a', 'x86'].includes(abi))) {
  console.error('Usage: npm run build:android -- [--acceptance|--phase4-acceptance|--phase5-acceptance] [--abi=x86_64|arm64-v8a|armeabi-v7a|x86]');
  process.exit(1);
}
if (acceptance && ((process.env.APP_ENV ?? 'development') !== 'development' || process.env.MOBILE_RELEASE === '1')) {
  console.error('Local acceptance requires APP_ENV=development and cannot be a release build.');
  process.exit(1);
}
if (phase4 && process.env.API_BASE_URL && process.env.API_BASE_URL !== 'http://10.0.2.2:7073/api/v1') {
  console.error('Phase 4 acceptance can only use its new synthetic backend on port7073.'); process.exit(1);
}
if (phase5 && process.env.API_BASE_URL && process.env.API_BASE_URL !== 'http://10.0.2.2:7074/api/v1') {
  console.error('Phase 5 acceptance can only use its separate synthetic backend on port7074.'); process.exit(1);
}
const buildEnvironment = { ...process.env, MOBILE_LOCAL_ACCEPTANCE: acceptance ? '1' : '0', MOBILE_PHASE4_PILOT: phase4 ? '1' : '0',
  MOBILE_PHASE5_PILOT: phase5 ? '1' : '0',
  ...(phase4 ? { API_BASE_URL: 'http://10.0.2.2:7073/api/v1' } : phase5 ? { API_BASE_URL: 'http://10.0.2.2:7074/api/v1' } : {}), NODE_ENV: acceptance ? 'production' : process.env.NODE_ENV ?? 'development' };
const sdk = process.env.ANDROID_HOME;
const javaHome = process.env.JAVA_HOME;
if (!sdk || !fs.existsSync(path.join(sdk, 'platforms', 'android-36', 'android.jar'))) {
  console.error('Native build pending: set ANDROID_HOME to an installed SDK with platform 36. Do not use Expo Go as a substitute.');
  process.exit(1);
}
if (!javaHome) { console.error('Native build pending: set JAVA_HOME to JDK 17 or 21 in this terminal.'); process.exit(1); }
const java = spawnSync(path.join(javaHome, 'bin', windows ? 'java.exe' : 'java'), ['-version'], { encoding: 'utf8' });
if (java.status !== 0 || !/version "(?:17|21)[.\"]/.test(java.stderr + java.stdout)) {
  console.error('Native build pending: JAVA_HOME must select a working JDK 17 or 21. JDK 17 remains the React Native recommended fallback.'); process.exit(1);
}
if (args.includes('--release')) {
  console.error('Signed release is Phase 10. This command builds a development APK only.');
  process.exit(1);
}
// SDK 57 recreates native folders by default. Preserve generated build caches
// and avoid deleting files while an IDE's Gradle importer holds them open.
const prebuild = spawnSync(windows ? 'npx.cmd' : 'npx', ['expo', 'prebuild', '--platform', 'android', '--no-install', '--no-clean'], { cwd: root, stdio: 'inherit', shell: windows, env: buildEnvironment });
if (prebuild.status !== 0) process.exit(prebuild.status ?? 1);
if (acceptance) console.log(`Building Farm Management (offline test): separate .dev.acceptance${phase5 ? '.phase5' : phase4 ? '.phase4' : ''} package, embedded JS, debug signing. Not for distribution.`);
const gradleArgs = [acceptance ? 'assembleLocalAcceptance' : 'assembleDebug', '--no-daemon', '--console=plain', '--max-workers=2', '--project-cache-dir', '.gradle-verification'];
if (abi) gradleArgs.push(`-PreactNativeArchitectures=${abi}`);
const build = spawnSync(windows ? 'gradlew.bat' : './gradlew', gradleArgs, {
  cwd: path.join(root, 'android'), stdio: 'inherit', shell: windows,
  env: buildEnvironment,
});
process.exit(build.status ?? 1);
