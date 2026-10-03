import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

type GradleMod = { modResults: { language: string; contents: string }; modRequest: Record<string, unknown> };
const withPrivateStorage = createRequire(import.meta.url)('../plugins/with-private-storage.cjs') as
  (config: Record<string, unknown>, options: { developmentHost: string | null }) => {
    mods: { android: {
      projectBuildGradle: (mod: GradleMod) => Promise<GradleMod>;
      mainApplication: (mod: GradleMod) => Promise<GradleMod>;
      dangerous: (mod: { modRequest: { platformProjectRoot: string } }) => Promise<unknown>;
    } };
  };

test('native config aligns library NDK with the template and remains idempotent', async () => {
  const config = withPrivateStorage({ name: 'Synthetic config', slug: 'synthetic-config' }, { developmentHost: null });
  const apply = config.mods.android.projectBuildGradle;
  const original = 'apply plugin: "expo-root-project"\n';
  const once = await apply({ modResults: { language: 'groovy', contents: original }, modRequest: {} });
  const twice = await apply(once);
  assert.equal(twice.modResults.contents, once.modResults.contents);
  assert.equal((twice.modResults.contents.match(/^\/\/ FARM_LIBRARY_NDK_VERSION$/gm) ?? []).length, 1);
  assert.ok(twice.modResults.contents.startsWith(original));
  assert.match(twice.modResults.contents, /subproject\.android\.ndkVersion = rootProject\.ext\.ndkVersion/);
  assert.doesNotMatch(twice.modResults.contents, /ndk-bundle|27\.1\.12297006/);
  await assert.rejects(apply({ modResults: { language: 'kotlin', contents: '' }, modRequest: {} }), /Groovy/);
});

test('offline acceptance packages its own bundle and retains release network/backup safeguards', async (t) => {
  const base = await mkdtemp(path.join(tmpdir(), 'farm-native-config-'));
  t.after(async () => { await rm(base, { recursive: true, force: true }); });
  await mkdir(path.join(base, 'app'), { recursive: true });
  await writeFile(path.join(base, 'app/build.gradle'), 'apply plugin: "com.android.application"\n');
  const config = withPrivateStorage({ name: 'Synthetic config', slug: 'synthetic-config',
    android: { package: 'com.farmmanagement.mobile.dev' },
    extra: { environment: 'development', apiBaseUrl: 'http://10.0.2.2:7071/api/v1', localAcceptance: true },
  }, { developmentHost: '10.0.2.2' });
  const apply = () => config.mods.android.dangerous({ modRequest: { platformProjectRoot: base } });
  await apply();
  const once = await readFile(path.join(base, 'app/build.gradle'), 'utf8');
  await apply();
  const twice = await readFile(path.join(base, 'app/build.gradle'), 'utf8');
  assert.equal(twice, once);
  assert.equal((twice.match(/^\/\/ FARM_LOCAL_ACCEPTANCE$/gm) ?? []).length, 1);
  assert.match(twice, /applicationIdSuffix '\.acceptance'/);
  assert.match(twice, /debuggable false/);
  assert.match(twice, /signingConfig signingConfigs\.debug/);
  assert.match(twice, /matchingFallbacks = \['release'\]/);
  assert.match(twice, /bundleTask != null && bundleTask\.devEnabled\.get\(\)/);
  assert.doesNotMatch(twice, /devEnabled\.set\(true\)/);
  assert.match(twice, /System.getenv\('MOBILE_LOCAL_ACCEPTANCE'\) != '1'/);
  assert.match(twice, /it\.project == project && it\.name\.toLowerCase\(\)\.contains\('release'\) \} && true/);
  assert.match(twice, /expo\.devlauncher\.configureInRelease/);
  assert.match(twice, /Farm Management \(offline test\)/);
  const mainNetwork = await readFile(path.join(base, 'app/src/main/res/xml/farm_network_security.xml'), 'utf8');
  const acceptanceNetwork = await readFile(path.join(base, 'app/src/localAcceptance/res/xml/farm_network_security.xml'), 'utf8');
  assert.doesNotMatch(mainNetwork, /cleartextTrafficPermitted="true"/);
  assert.equal((acceptanceNetwork.match(/<domain /g) ?? []).length, 1);
  assert.match(acceptanceNetwork, /includeSubdomains="false">10\.0\.2\.2<\/domain>/);
  const backup = await readFile(path.join(base, 'app/src/main/res/xml/farm_backup_rules.xml'), 'utf8');
  assert.match(backup, /<exclude domain="database" path="\."\/>/);

  const source = 'ExpoReactHostFactory.getDefaultReactHost(\n      context = applicationContext,\n      packageList = PackageList(this).packages\n)';
  const mainOnce = await config.mods.android.mainApplication({ modResults: { language: 'kt', contents: source }, modRequest: {} });
  const mainTwice = await config.mods.android.mainApplication(mainOnce);
  assert.equal(mainTwice.modResults.contents, mainOnce.modResults.contents);
  assert.equal((mainTwice.modResults.contents.match(/useDevSupport = BuildConfig.DEBUG/g) ?? []).length, 1);
  assert.equal((mainTwice.modResults.contents.match(/add\(FarmBuildInfoPackage\(\)\)/g) ?? []).length, 1);
  const nativeInfo = await readFile(path.join(base, 'app/src/main/java/com/farmmanagement/mobile/dev/FarmBuildInfoPackage.kt'), 'utf8');
  assert.match(nativeInfo, /"applicationId" to BuildConfig\.APPLICATION_ID/);
  assert.match(nativeInfo, /"buildType" to BuildConfig\.BUILD_TYPE/);

  const production = withPrivateStorage({ name: 'Synthetic config', slug: 'synthetic-config',
    android: { package: 'com.farmmanagement.mobile' },
    extra: { environment: 'production', apiBaseUrl: 'https://farm.example/api/v1' },
  }, { developmentHost: null });
  await production.mods.android.dangerous({ modRequest: { platformProjectRoot: base } });
  const productionGradle = await readFile(path.join(base, 'app/build.gradle'), 'utf8');
  assert.match(productionGradle, /if \(true \|\| \(System.getenv\('APP_ENV'\)/);
  assert.doesNotMatch(await readFile(path.join(base, 'app/src/localAcceptance/res/xml/farm_network_security.xml'), 'utf8'), /cleartextTrafficPermitted="true"/);

  const pilot=withPrivateStorage({name:'Synthetic Phase4',slug:'synthetic-phase4',android:{package:'com.farmmanagement.mobile.dev'},
    extra:{environment:'development',apiBaseUrl:'http://10.0.2.2:7073/api/v1',localAcceptance:true,phase4Pilot:true}}, {developmentHost:'10.0.2.2'});
  await pilot.mods.android.dangerous({modRequest:{platformProjectRoot:base}});
  const pilotGradle=await readFile(path.join(base,'app/build.gradle'),'utf8');
  assert.match(pilotGradle,/applicationIdSuffix '\.acceptance\.phase4'/);
  assert.match(pilotGradle,/if \(false \|\| \(System.getenv\('APP_ENV'\)/);
  assert.match(pilotGradle,/contains\('release'\) \} && true/);
});
