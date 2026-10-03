# Farm Management Android operational pilot

Phase 3 foundation plus Phase 4 sync source. API36/API24 shell/storage checks and many security scenarios pass with JDK21. [Phase 4 source/host tests](../docs/mobile/checkpoints/PHASE_04.md) implement verified download, atomic deltas, durable upload/receipt recovery, local mortality capture and queue controls. **Native synchronization is still disabled** in `src/sync/pilot-gate.ts`, pending original backend A-return/authenticated TalkBack checks and Phase4 emulator acceptance. Host success/builds do not complete native gates. Django remains authoritative; finance, attachments and production deployment remain off.

From the root, reproduce guarded real sync integration with local PostgreSQL settings below and `python docs/mobile/tools/phase03_local_backend.py --phase4-test`. It creates/removes a new synthetic DB, never the farm/retained Phase3 deployments. A future native fixture uses `--serve --phase4-serve --port 7073`, leaves7071/7072 untouched and loses the first accepted push response. Do not point the retained-fixture app at a replacement deployment or enable uploads just to skip acceptance. See the Phase4 checkpoint for remaining emulator steps.

## Workstation checks

Node 24.x (>=24.3), npm, JDK 17 or 21 and Android Studio/SDK are required. JDK 21 remains this workstation's default for Spring Boot; the build wrapper accepts both versions. React Native recommends 17 as a fallback, selected only in a mobile terminal if needed. SDK platform/target 36, build tools 36.0.0, NDK 27.1.12297006; SDK min 24. Generated native versions: Gradle 9.3.1, AGP 8.12.0, Kotlin 2.1.20. Accept required Android licenses yourself through Android Studio; this project does not silently accept licenses. Use normal permitted official npm/Google/Maven access; do not bypass organizational controls.

From `mobile/` in PowerShell:

```powershell
npm.cmd ci
npm.cmd run lint
npm.cmd run typecheck
npm.cmd test
npx.cmd expo install --check
npx.cmd expo-doctor
```

Tests use Node's real, **unencrypted host SQLite**, including child-process termination, disk-page exhaustion and migration rollback. They are not Android encryption/Keystore/accessibility evidence. The separately guarded integration runner below exercises the same typed auth client through real Django HTTP/PostgreSQL, not a mocked response.

Direct dependencies and transitives are in the independent lockfile. `react-dom` is pinned to React 19.2.3 only to satisfy Router's peer resolution; application code imports no DOM/Next.js APIs. ESLint 9.39.4 matches the SDK config's development baseline but npm reports it deprecated; reassess a compatible lint upgrade during hardening. npm 11 reports unapproved optional install scripts for esbuild/unrs-resolver; checks currently work using their packaged platform binaries. No global script policy was changed.

## Safe local Django target

The user selected a **separate synthetic local backend**, not the existing farm at port 7070. Development defaults to `http://10.0.2.2:7071/api/v1`. The original farm's sync migrations/flags stay unapplied/off.

From the repository root, automated HTTP checks create an absent/new PostgreSQL database, migrate it, create synthetic worker/viewer users, run one integration scenario, then remove only that database:

```powershell
$env:POSTGRES_HOST = '127.0.0.1'
$env:POSTGRES_PORT = '5437'
& .\venv\Scripts\python.exe docs/mobile/tools/phase03_local_backend.py
```

For emulator acceptance, keep a dedicated terminal running:

```powershell
& .\venv\Scripts\python.exe docs/mobile/tools/phase03_local_backend.py --serve --port 7071
```

This prints freshly generated **synthetic-only** credentials. The database survives only until Ctrl+C; then it is removed. Use one server invocation for the full offline/restart/account-switch exercise. Restarting the helper intentionally creates a new deployment identity and users; old phone stores will not bind to it. Abruptly killing this server process can leave its named owned test DB; inspect its exact identity/active connections before cleanup, never drop the farm. No default or real-user password is shipped.

For the controlled native role check, `docs/mobile/tools/phase03_native_policy.py` accepts `inspect`, `downgrade` and `restore` with an explicit `--database` equal to the current owned database in acceptance evidence. From the repository root, use the same process-only local PostgreSQL host/port above. Inspect first; downgrade only while the synthetic worker is unlocked, select Sync → Check current server access, verify read-only capability and retained queue, then immediately restore and revalidate. The helper checks exact role transitions and factory users and refuses the source/another owned database. It does not create a database, clear a cache or repair readiness. Run `python docs/mobile/tools/test_phase03_native_policy.py` for the connection-free target-guard tests. The dated checkpoint records the actual API24 pass; this is not a real-user role-management workflow.

The helper binds loopback by default. An emulator reaches desktop loopback via `10.0.2.2`; device `localhost` is the phone. A physical phone needs reachable LAN binding (`--serve --bind 0.0.0.0`), an explicit development host in Django ALLOWED_HOSTS, a deliberately scoped firewall rule, and a matching API_BASE_URL; no wildcard CORS/hosts are added. HTTPS staging is the preferred physical-phone option. The helper's default allowlist does **not** pretend every LAN address is authorized.

## Native build after installation

Set paths to the installations you actually verified, scoped to this terminal:

```powershell
# Verified workstation SDK path; replace on another workstation.
$env:ANDROID_HOME = 'C:\Android\SDK'
# Keep the existing JAVA_HOME (JDK 21 on this workstation).
# Process-only workaround for the observed Windows Java socket-directory error:
$env:JAVA_TOOL_OPTIONS = (@($env:JAVA_TOOL_OPTIONS,
  '-Djdk.net.unixdomain.tmpdir=C:/Android/SDK/.temp') | Where-Object { $_ }) -join ' '
$env:APP_ENV = 'development'
$env:API_BASE_URL = 'http://10.0.2.2:7071/api/v1'
npx.cmd expo prebuild --platform android --no-install --no-clean
npm.cmd run build:android
npm.cmd run android
```

`android` runs a native Expo development build, never Expo Go. `build:android` fails before downloads when SDK platform 36/JDK 17 or 21 are unavailable; it generates the native project and runs `assembleDebug` when ready. Gradle/SDK repositories must be reachable normally. Gradle can download missing required packages under licenses already accepted by the user; it does not authorize this project to accept new licenses.

The user-level `ANDROID_HOME` already points to `C:\Android\SDK`, but the current Codex process did not inherit it. Restart Codex/your terminal to refresh that value, or set it in the mobile terminal as above. No permanent JAVA_HOME/PATH change is needed. Both JDKs initially failed `Selector.open()`/Gradle with `Unable to establish loopback connection` / `UnixDomainSockets ... Invalid argument: connect`. Using the existing short SDK `.temp` directory for this process's Java socket files allowed JDK 21 to start the actual build. This is a documented [Java socket-directory property](https://docs.oracle.com/en/java/javase/17/core/java-networking.html), not a firewall/security-policy change; the exact underlying Windows filter/path cause has not been established. Do not edit global Java options to apply it to Spring Boot.

Native folders are generated/ignored; keep edits in config/plugins and regenerate after changing API environment. Review prebuild changes. SDK 57 recreates native folders by default; the debug wrapper uses `--no-clean` to preserve build caches and avoid deleting files locked by an IDE's Gradle importer. The config plugin aligns native-library NDK versions with the template's root NDK, avoiding accidental legacy `ndk-bundle` selection. A successful prebuild only proves generation, not compilation. Debug default icon/launch assets are Expo-generated, not a finished product identity. Signed APK/AAB/store distribution is Phase 10.

For the local debug client, start Metro in a separate mobile terminal and keep it open:

```powershell
# This workstation initially bound localhost only to IPv6; prefer IPv4 for 10.0.2.2.
$env:NODE_OPTIONS = "$env:NODE_OPTIONS --dns-result-order=ipv4first"
npm.cmd start -- --localhost
```

Verify `http://127.0.0.1:8081/status` returns `packager-status:running`. The emulator can then use `http://10.0.2.2:8081` for Metro under the existing debug-only host exception. API port 7071 remains separate. Configure a test screen-lock PIN on the emulator; never send your PIN/password to logs or chat. Physical-phone/biometric acceptance remains separate.

For staging/production set `APP_ENV` and a real HTTPS `API_BASE_URL` ending exactly `/api/v1`. No trailing slash, URL credentials, query or fragment. Set `MOBILE_RELEASE=1` when generating release configuration. Config, release Gradle guard and runtime fail closed on development/HTTP release configuration; main Android network policy denies cleartext, while the **debug resource only** allows the single configured private development hostname. Public bundle settings contain no server/DB secrets.

## Standalone offline acceptance build

The normal development client needs Metro to load its code. To test startup without Metro, use the separate local acceptance variant with the same terminal-scoped SDK/Java/API settings above:

```powershell
npm.cmd run build:android -- --acceptance --abi=x86_64
```

The output is `android/app/build/outputs/apk/localAcceptance/app-localAcceptance.apk`, labelled **Farm Management (offline test)**, package `com.farmmanagement.mobile.dev.acceptance`. It embeds a production-mode JavaScript/Hermes bundle (Expo's development runtime requires Metro), disables native developer support, uses a separate private data sandbox, and is debug-signed **only for local testing**, not distribution. Synthetic probes require the explicit generated acceptance flag, actual compiled native package/build type, development environment and exact synthetic API on port7071. The wrapper supplies that build flag; a direct Gradle retry also requires `MOBILE_LOCAL_ACCEPTANCE=1` with the same previously generated acceptance config. Main/release network policy still denies cleartext; application release tasks reject this test configuration. It does not overwrite or clear the normal `.dev` app. A successful build alone is not an offline runtime result.

Keep one synthetic backend invocation alive for the entire account exercise. Sign in as its freshly generated worker, then More → **Prepare worker isolation fixture**. This inserts one clearly synthetic, permanently quarantined local command and overlay, not a server record. Sign out, sign in as the same backend's viewer, and select **Verify viewer isolation**. Sign out and return to the worker, then **Verify returned worker fixture**. The fixture is deliberately retained with its original operation ID; no upload or reassignment occurs. Never use real accounts or point these tools at port7070.

After caching the worker session, use airplane mode and force-stop/reopen this offline-test app. Privately unlock its cached session and verify the retained worker fixture. Do not clear app data, reinstall from scratch, or create a new test backend to make a failed test pass. Restore emulator connectivity after the test. Physical-phone/biometric acceptance remains separate.

### Remaining emulator security checks

The actual compiled local-acceptance variant can select only the two development APIs on ports7071/7072 using **Switch synthetic test backend**. Ordinary/release builds cannot enable this picker through public settings. Switching closes the old store, disables cached restart and requires online sign-in; it does not erase the original encrypted partition. Keep both factory servers alive throughout an environment test. Use **Remember backend A origin**, switch/sign in to the independently created B deployment, then **Verify backend B isolation** before preparing any B fixture. Return to A, sign in online, and use **Verify backend A return**. This verifies exact original identity/command/hash/overlay; Phase3 still has no business upload worker. Phase4 must separately verify queue-engine target binding.

After failed authorization the confirmed replica is intentionally evicted. Use **Verify exact retained draft**, which compares the original checkpoint UUID, canonical command, recomputed hash, capture time, original owner/device/deployment, overlay, quarantine and zero attempts without requiring that confirmed parent. Do not press Prepare again or reinsert a parent to make the older full-replica verifier pass.

For a real lost refresh response, start the second factory backend from the repository root with the same process-only PostgreSQL host/port. Choose a **new, absent** evidence filename for each run:

```powershell
& .\venv\Scripts\python.exe docs/mobile/tools/phase03_local_backend.py --serve --port 7072 --drop-first-refresh-response --fault-evidence docs/mobile/evidence/phase03-response-loss-your-run.json
```

After ordinary B sign-in and preparing its local quarantined fixture, **Test real token refresh** makes the existing auth client call actual Django. The test-only WSGI harness allows the first successful rotation/blacklist to finish, then closes TCP before response delivery. Its file records counts only, never JWTs, headers or bodies. Expect sign-in required, exactly one successful/dropped refresh and zero pushes. Force-stop/reopen, attempt cached unlock and confirm denial with no additional refresh request. Sign in online and run the exact-retained check. This is not a mock success and does not alter production middleware.

`phase03_native_policy.py` also supports `revoke-session`, with explicit `--database`, `--ownership-evidence` and `--session-id`. Inspect first and match the active synthetic worker session to the native sign-in; revoke only that exact session. The evidence must establish this factory-owned database, not merely a name prefix. Normal **Check current server access** should return403, close the session and persist cached denial across restart, without a refresh loop. New online sign-in may create a new session; it must not revive the revoked one. Verify the exact retained draft afterward. Never revoke real sessions to prove acceptance.

`phase03_owned_http_check.py` diagnoses intermittent readiness failures on an already-evidence-owned factory database. It requires an explicit local port7071/7072 and temporary factory password in `PHASE03_SYNTHETIC_PASSWORD`, checks the two-user inventory and ready stream, and performs ordinary login/registration/me/capability requests on an existing synthetic Android installation. Only safe status/error-code metadata is printed. It creates an ordinary synthetic session but no business records, refresh or identity reset. Host HTTP success does not establish native environment-return acceptance. Neither helper repairs readiness or migrates/resets a database.

If that same owned server needs a process restart, `phase03_owned_backend.py --check-only --database <exact-owned-name> --ownership-evidence <owned-evidence> --port 7071` verifies its existing local database, two unchanged synthetic users and ready deployment. The serving invocation omits `--check-only` and reuses those exact identities/passwords/schema without create/seed/reset/drop. Verify the old test process's full command line before stopping only that process; **Ctrl+C in the original factory would delete its owned database**, so do not use it when proving same-deployment recovery. The recovery server verifies its actual database on each request thread before Django executes, closes thread connections, and exposes only Phase3 auth/registration/capability routes. It is not a production server or Phase4 upload target. Stopping this recovery server deliberately retains its explicitly owned database; cleanup is a separate exact-target operation after retained-work checks are no longer needed.

TalkBack acceptance uses the separately created **FarmAcceptanceTalkBack36** Play-enabled API36 emulator, which already includes Android Accessibility Suite/TalkBack16; no Google account login is required. Screen-lock setup and PIN prompts remain private. Check spoken field/button labels and focus order, automatic error announcements, all five tab destinations and selected/queue feedback with TalkBack actually bound and speaking. Restore the original accessibility state afterward. Physical-phone/biometric checks are user-deferred for this emulator milestone, not waived for release. See the dated emulator-finalization evidence for actual pass/pending status.

The labelled native navigation reflows into fewer columns with enlarged text, keeping all five destinations visible instead of truncating fixed-height labels. API36 native checks pass at200% text size on320×640; body content and long actions remain scrollable. Selected tabs and exact retained queue counts have accessibility labels/state. This does not substitute for TalkBack or physical-device tests. Changing Android configuration/backgrounding locks the session; privately unlock its existing cache rather than signing in afresh to test retention.

The locked **Native storage checks** route also offers **Run PIN-only missing-key probe**. It uses only its own scratch store, temporarily removes that scratch key, verifies missing-key failure preserves ciphertext, restores the same key, and verifies recovery. It requires three private PIN approvals; it never removes a user's key. The normal SQLCipher probe now additionally checks disk-full rollback, failed migration rollback and foreign-actor binding. Record actual native results separately from host tests.

## Security and recovery boundaries

- Access tokens are memory-only. SecureStore holds bound refresh credentials, rotation intent, partition pointer, installation IDs and per-store random 256-bit keys. The initial unbound login pair is discarded after registration.
- Refresh is single-flight, journals `in_flight` before sending and persists the rotated refresh before resumed reads. Interrupted/ambiguous rotation requires online sign-in; no stale-token loop. A 403 invalidates access without refreshing.
- Partition key = SHA-256(API base + deployment UUID + original user UUID). Persisted identity also requires the original registered device UUID. New accounts/environments cannot bind the old repository. Installation UUID is stable per API/user; revoked IDs are never replaced automatically to evade revocation.
- Every database open requires Android device unlock. Class-3 biometric devices additionally use SecureStore's crypto-bound biometric prompt. PIN-only devices use device-credential unlock plus a Keystore-wrapped key; this is explicitly **not** equivalent to per-read biometric key authorization. Existing biometric keys never silently downgrade. Hardware-backed/StrongBox availability is device-specific and not claimed without measurement. PIN fallback, enrollment changes and Android API 24/36 behavior require native tests.
- Keys are applied before schema reads; absent SQLCipher, wrong/missing key or identity/migration failure leaves files untouched and reports a recovery state. Never delete/recreate a failed store to make a test pass. Keystore invalidation/biometric changes can make a store inaccessible; never-uploaded work may be unrecoverable. Uninstall/phone loss does not magically back up offline drafts.
- Operational offline access is <=7 days; sensitive limit <=24 hours is implemented as a policy primitive, but sensitive screens/data are not delivered. Clock rollback requires online validation. Backgrounding locks the session and closes its keyed database. On reconnect use **Check current server access**; role changes purge confirmed scope and quarantine (retain) original pending evidence. Phase 4 will integrate reconnect triggering and recovery.
- The confirmed replica, overlays, immutable commands, dependencies, receipts, mappings, conflicts, leases, pack manifests and attachment job metadata are separate tables. Bound prepared writes and serialized `BEGIN IMMEDIATE` on the keyed connection provide the atomic local boundary. This avoids the SDK's separate unkeyed exclusive-transaction connection. Authoritative money remains decimal text; previews never post money.
- Android cloud backup/device-transfer exclusions cover normal and device-protected private storage. No app credential/body logging is added. No attachment bytes exist yet; their encryption/upload is Phase 9. Sign-out disables offline unlock, clears bound refresh and attempts server blacklist without deleting original-user keys/files/outbox. Offline server logout cannot be promised; revoke the device online if required.

## Android acceptance checklist (partially executed)

On an API 36 emulator, API 24 device/emulator and representative physical phone, record model/OS/build/version, dates, commands and results in the checkpoint:

1. Sign in to the owned synthetic server as worker; verify current user/capabilities. Switch to viewer and verify capture disabled and worker cache/queue inaccessible. Switch API/deployment and verify separate store. Reuse the original server/device to recover retained original-user work.
2. Configure PIN/strong biometric lock. Exercise cancellation, biometric enrollment change/key loss and unauthorized device state. Close the app, enable airplane mode, relaunch/unlock within the window. Test expiry/clock rollback and reauthenticate without resetting files.
3. More → **Lock session & open native storage checks** (or **Development: native storage checks** on the locked sign-in screen) → **Run SQLCipher storage probe**. The separate development route keeps the user session locked during Android PIN prompts; it is unavailable in release builds. This tests a new synthetic DB only: cipher version, correct-key reopen, wrong/unkeyed-reader rejection, encrypted header, FK behavior, atomic injected failure, migration preservation and exclusive lease. Approve the two private device-unlock prompts. Success removes only its synthetic probe. Failed probes remain for inspection.
4. On the same development-only locked screen → **Prepare retained process-death probe**. Force-stop the development app with `adb shell am force-stop com.farmmanagement.mobile.dev`, relaunch, reopen the locked test screen, then **Verify retained process-death probe**. Repeat with reboot. Separately verify cached user unlock offline after process death. Verification requires the scratch-store marker, retains user stores, and removes only the verified synthetic scratch store. Export only this synthetic fixture through debug `run-as` if separately checking rejection by a standard plain-SQLite reader.
5. Inject constrained native storage/failed migration, confirm neither half-save and previous queue survive. Confirm concurrent refresh, rotation-response loss and revoked/role-downgraded reconnect on the device. Host tests cover these algorithms but not OS behavior.
6. Inspect backup rules, private DB/WAL files and logs for no secrets/finance/payroll data. Test 320dp width, Android large fonts, TalkBack labels/focus, keyboard/form errors and 48dp controls. Do not infer accessibility from TypeScript success.

Do not activate production sync or begin Phase 4 acceptance until Phase 3 native gates pass. Today/Record deliberately show unavailable data/features, not invented zeroes, FCR, profit or successful sync.
