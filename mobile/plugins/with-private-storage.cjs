const { withAndroidManifest, withDangerousMod, withProjectBuildGradle, withMainApplication } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
// Generated resources, not hand-edited native files: survive every prebuild.
module.exports = (config, options) => {
  config = withMainApplication(config, (mod) => {
    if (mod.modResults.language !== 'kt') throw new Error('Expected the SDK 57 Kotlin application.');
    // The local acceptance variant must load its packaged bundle without Metro.
    // Ordinary debug builds still enable native developer support.
    let contents = mod.modResults.contents;
    if (!contents.includes('add(FarmBuildInfoPackage())')) {
      const packages = /PackageList\(this\).packages\.apply\s*\{/;
      const fallback = /PackageList\(this\).packages/;
      if (packages.test(contents)) contents = contents.replace(packages, '$&\n          add(FarmBuildInfoPackage())');
      else if (fallback.test(contents)) contents = contents.replace(fallback, '$&.apply { add(FarmBuildInfoPackage()) }');
      else throw new Error('Expected the SDK 57 native package list.');
    }
    if (!contents.includes('useDevSupport = BuildConfig.DEBUG,')) {
      const anchor = /context = applicationContext,/;
      if (!anchor.test(contents)) throw new Error('Expected the SDK 57 ExpoReactHostFactory context.');
      contents = contents.replace(anchor, '$&\n      useDevSupport = BuildConfig.DEBUG,');
    }
    mod.modResults.contents = contents;
    return mod;
  });
  config = withProjectBuildGradle(config, (mod) => {
    if (mod.modResults.language !== 'groovy') throw new Error('Expected the SDK 57 Groovy root build file.');
    // Native libraries such as expo-sqlite do not select rootProject.ext.ndkVersion
    // themselves. Keep them on the same template NDK as the app instead of a
    // machine-dependent legacy ndk-bundle (or AGP's different default version).
    const block = `\n// FARM_LIBRARY_NDK_VERSION\nsubprojects { subproject ->\n subproject.plugins.withId('com.android.library') {\n  subproject.android.ndkVersion = rootProject.ext.ndkVersion\n }\n}\n// FARM_LIBRARY_NDK_VERSION_END\n`;
    const existing = /\n\/\/ FARM_LIBRARY_NDK_VERSION\n[\s\S]*?\/\/ FARM_LIBRARY_NDK_VERSION_END\n/;
    mod.modResults.contents = existing.test(mod.modResults.contents)
      ? mod.modResults.contents.replace(existing, block) : mod.modResults.contents + block;
    return mod;
  });
  config = withAndroidManifest(config, (mod) => {
    const application = mod.modResults.manifest.application[0].$;
    application['android:allowBackup'] = 'false';
    application['android:fullBackupContent'] = '@xml/farm_backup_rules';
    application['android:dataExtractionRules'] = '@xml/farm_extraction_rules';
    application['android:networkSecurityConfig'] = '@xml/farm_network_security';
    application['android:usesCleartextTraffic'] = 'false';
    return mod;
  });
  return withDangerousMod(config, ['android', async (mod) => {
    const base = mod.modRequest.platformProjectRoot;
    const applicationPackage = config.android.package;
    if (!/^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$/.test(applicationPackage)) throw new Error('Invalid native application package.');
    const kotlin = path.join(base, 'app/src/main/java', ...applicationPackage.split('.'));
    fs.mkdirSync(kotlin, { recursive: true });
    fs.writeFileSync(path.join(kotlin, 'FarmBuildInfoPackage.kt'), `package ${applicationPackage}

import com.facebook.react.ReactPackage
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.uimanager.ViewManager

// Public compiled build identity only. No credentials or farm data are exposed.
class FarmBuildInfoPackage : ReactPackage {
 override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(FarmBuildInfoModule(context))
 override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
class FarmBuildInfoModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
 override fun getName(): String = "FarmBuildInfo"
 override fun getConstants(): Map<String, Any> = mapOf(
  "applicationId" to BuildConfig.APPLICATION_ID,
  "buildType" to BuildConfig.BUILD_TYPE
 )
}
`);
    const xml = path.join(base, 'app/src/main/res/xml');
    fs.mkdirSync(xml, { recursive: true });
    const domains = ['root', 'file', 'database', 'sharedpref', 'external', 'device_root', 'device_file', 'device_database', 'device_sharedpref'];
    const exclusions = domains.map((domain) => `<exclude domain="${domain}" path="."/>`).join('');
    fs.writeFileSync(path.join(xml, 'farm_backup_rules.xml'), `<full-backup-content>${exclusions}</full-backup-content>`);
    fs.writeFileSync(path.join(xml, 'farm_extraction_rules.xml'), `<data-extraction-rules><cloud-backup disableIfNoEncryptionCapabilities="true">${exclusions}</cloud-backup><device-transfer>${exclusions}</device-transfer></data-extraction-rules>`);
    const secure = '<network-security-config><base-config cleartextTrafficPermitted="false"/></network-security-config>';
    fs.writeFileSync(path.join(xml, 'farm_network_security.xml'), secure);
    // A same-name debug source-set resource overrides main; release always uses main.
    const debug = path.join(base, 'app/src/debug/res/xml');
    fs.mkdirSync(debug, { recursive: true });
    const host = options.developmentHost;
    if (host && !/^[a-zA-Z0-9.-]+$/.test(host)) throw new Error('Invalid debug host.');
    const localNetwork = host ? `<network-security-config><base-config cleartextTrafficPermitted="false"/><domain-config cleartextTrafficPermitted="true"><domain includeSubdomains="false">${host}</domain></domain-config></network-security-config>` : secure;
    fs.writeFileSync(path.join(debug, 'farm_network_security.xml'), localNetwork);
    const acceptance = path.join(base, 'app/src/localAcceptance/res/xml');
    fs.mkdirSync(acceptance, { recursive: true });
    fs.writeFileSync(path.join(acceptance, 'farm_network_security.xml'), config.extra.environment === 'development' ? localNetwork : secure);
    // Gradle fails closed even if someone invokes assembleRelease without the wrapper script.
    const appGradle = path.join(base, 'app/build.gradle');
    let gradle = fs.readFileSync(appGradle, 'utf8');
    const marker = '// FARM_RELEASE_CONFIGURATION_GUARD';
    const valid = config.extra.environment !== 'development' && config.extra.localAcceptance !== true && config.extra.apiBaseUrl.startsWith('https://');
    // Library release variants also serve localAcceptance. Guard application
    // release tasks specifically; no application release exception is granted.
    const block = `\n${marker}\ngradle.taskGraph.whenReady { graph ->\n if (graph.allTasks.any { it.project == project && it.name.toLowerCase().contains('release') } && ${!valid}) {\n throw new GradleException('Regenerate with APP_ENV=staging/production and an HTTPS API_BASE_URL before release.')\n }\n}\n// FARM_RELEASE_CONFIGURATION_GUARD_END\n`;
    const existing = /\n\/\/ FARM_RELEASE_CONFIGURATION_GUARD\n[\s\S]*?\n}\n(?:\/\/ FARM_RELEASE_CONFIGURATION_GUARD_END\n)?/;
    gradle = existing.test(gradle) ? gradle.replace(existing, block) : gradle + block;
    // Separate Android package/data sandbox, debug-signed only. Release library
    // fallbacks exclude Expo's launcher. Embedded JS uses production mode;
    // application-owned synthetic probes require an explicit native test flag.
    const phase4 = config.extra.phase4Pilot === true;
    const acceptanceAllowed = config.extra.environment === 'development' && config.android.package === 'com.farmmanagement.mobile.dev' &&
      config.extra.apiBaseUrl === `http://10.0.2.2:${phase4 ? '7073' : '7071'}/api/v1` && config.extra.localAcceptance === true;
    const acceptanceBlock = `
// FARM_LOCAL_ACCEPTANCE
android {
 buildTypes {
  localAcceptance {
   initWith(buildTypes.debug)
   debuggable false
   jniDebuggable false
   signingConfig signingConfigs.debug
   applicationIdSuffix '.acceptance${phase4 ? '.phase4' : ''}'
   versionNameSuffix '-offline-test'
   matchingFallbacks = ['release']
   resValue 'string', 'app_name', 'Farm Management (offline test)'
  }
 }
}
gradle.taskGraph.whenReady { graph ->
 if (graph.allTasks.any { it.project == project && it.name.toLowerCase().contains('localacceptance') }) {
  if (${!acceptanceAllowed} || (System.getenv('APP_ENV') ?: 'development') != 'development' || System.getenv('MOBILE_RELEASE') == '1' || System.getenv('MOBILE_LOCAL_ACCEPTANCE') != '1') {
   throw new GradleException('Local acceptance requires the explicit synthetic development build; it is not a release artifact.')
  }
  if (findProperty('expo.devlauncher.configureInRelease') == 'true' || findProperty('expo.devmenu.configureInRelease') == 'true') {
   throw new GradleException('Local acceptance must not include the development launcher/menu.')
  }
  def bundleTask = graph.allTasks.find { it.project == project && it.name == 'createBundleLocalAcceptanceJsAndAssets' }
  if (bundleTask != null && bundleTask.devEnabled.get()) {
   throw new GradleException('Embedded acceptance requires a production-mode JS bundle, not Metro tooling.')
  }
 }
}
// FARM_LOCAL_ACCEPTANCE_END
`;
    const acceptanceExisting = /\n\/\/ FARM_LOCAL_ACCEPTANCE\n[\s\S]*?\/\/ FARM_LOCAL_ACCEPTANCE_END\n/;
    gradle = acceptanceExisting.test(gradle) ? gradle.replace(acceptanceExisting, acceptanceBlock) : gradle + acceptanceBlock;
    fs.writeFileSync(appGradle, gradle);
    return mod;
  }]);
};
