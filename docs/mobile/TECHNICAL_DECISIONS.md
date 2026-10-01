# Phase 1 — technical and deployment decisions

Decision date: 1 October 2026. Accepted for implementation planning. Native build verification belongs to Phase 3. Installed backend/frontend versions were inspected and baseline checks run; no mobile dependencies were installed and no device build has been claimed.

## Toolchain selected for the Android project

| Component | Selected baseline | Evidence / implementation rule |
|---|---|---|
| Expo | **57.0.26** | Stable SDK 57; npm metadata exists; inspected `expo-template-default@sdk-57` 57.0.28 recommends `~57.0.26` |
| React Native | **0.86.3** | SDK 57 template pins this patch; includes the documented Hermes fixes |
| React | **19.2.3** | SDK 57 template and official SDK compatibility table |
| Node / npm | **24.20.0 / 11.19.0** | Installed and used for frontend baseline; RN 0.86.3 engine accepts Node >=24.3 in its 24.x range |
| Expo Router | **57.0.24** | SDK 57 template recommends this compatible patch; conventional Stack/Tabs, no experimental routing APIs |
| expo-sqlite | **57.0.3** | SDK 57 SQLite documentation recommends `~57.0.3`; enable SQLCipher native plugin |
| expo-secure-store | SDK 57-compatible patch via `expo install` | npm confirmed 57.0.0 exists; resolve SDK-supported patch and save exact version in Phase 3 lockfile before build |
| expo-dev-client | SDK 57 compatible, documentation range `~57.0.19` | Native debug client; Phase 3 resolves exact compatible patch and locks it |
| React Hook Form / Zod / decimal.js | **7.81.0 / 4.4.3 / 10.6.0** | npm metadata checked; use typed native controls/resolver; decimal.js only for previews, server posts money |
| TypeScript / lint / Jest | SDK 57 template-compatible versions, exact lockfile in Phase 3 | No shared frontend dependency upgrades; `jest-expo`/React Native Testing Library compatibility must pass before adding tests |
| JDK | **17 LTS** for Android Gradle | Follow RN environment guidance; this workstation currently has JDK 21.0.12.1, so install/select 17 for mobile without changing other projects |
| Android | min SDK **24** (Android 7), compile/target **36** | Official SDK 57 compatibility table; test API 24 and 36; actual pilot fleet remains to be recorded |
| Gradle / AGP / Kotlin / NDK / Build Tools | Use SDK 57 generated template and its Gradle wrapper | Record exact generated versions in Phase 3 checkpoint. Do not independently upgrade native components or invent a prebuilt wrapper version |

SDK 57 is the selected release rather than an unpinned “latest” dependency. The official [Expo compatibility table](https://docs.expo.dev/versions/latest/) maps SDK 57 to RN 0.86, React 19.2.3, Node >=22.13, Android 7+ and compile/target 36. The [SDK 57 release notes](https://expo.dev/changelog/sdk-57) identify 0.86.3/Hermes fixes; the [React Native environment guide](https://reactnative.dev/docs/set-up-your-environment) supplies JDK/Android setup. These establish a supported toolchain, not evidence of a compiled app.

Use a separate `mobile/package-lock.json`, exact direct versions, and `npm ci`. Let `npx.cmd expo install --check` and Expo Doctor confirm the generated SDK dependencies. If implementation begins much later, record an explicit ADR/version change before moving off this baseline. Compatible auxiliary patch resolution is a Phase 3 task; the inspected template's complete dependency list must not be treated as authorization to add every optional UI package.

## Native encrypted persistence

Use `expo-sqlite` with explicit, versioned SQL migrations. A confirmed replica, pending overlay, outbox entry and dependency edges are separate tables; local draft/outbox save uses one exclusive write transaction. Keep decimal values as TEXT and counters as integers. Use bound statements for user data. Schema migration, interrupted bootstrap and sign-out preserve pending/unknown outcomes.

Native config must contain:

```json
{
  "expo": {
    "plugins": [
      "expo-router",
      "expo-secure-store",
      ["expo-sqlite", {"useSQLCipher": true}],
      ["expo-build-properties", {"android": {"minSdkVersion": 24, "compileSdkVersion": 36, "targetSdkVersion": 36}}]
    ]
  }
}
```

This is a configuration example, not a scaffold. Do **not** copy an `android.useSQLCipher=false` override from the documentation example. Native prebuild/compilation is required; Expo Go cannot prove encrypted storage. Open the database, apply the securely generated key before any schema reads, check `PRAGMA cipher_version`, then run migrations. Persist the per-user/deployment database key in SecureStore. Test that reopening succeeds with the right key, fails with a wrong key and a plain SQLite reader cannot read the file. Never log or hard-code the key. [SDK 57 SQLite documentation](https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/).

Use a hardware-backed application secret where the platform supports it, app/device unlock, backup exclusions for private database/attachments and original-user queue ownership. If a biometric policy prevents a background worker from obtaining a key, defer to foreground. Encrypted attachment bytes need their own file encryption implementation in Phase 9; a private sandbox path alone is not encrypted evidence.

## Native app structure and UI decisions

- Expo Router under `mobile/app/`; TypeScript repositories under `mobile/src/`. The template may offer `src/app/`; normalize once and document it rather than keeping two route roots.
- Native Stack plus Today/Batches/Record/Sync/More tabs; accessible native form components and a small cream/navy/gold token system. Use regular labelled buttons; no chart library is required for the first operational slice.
- React Hook Form + Zod for typed forms; decimal.js for labelled previews. JSONSchema/OpenAPI validation defines the server boundary; schema library differences must not redefine money/date semantics.
- SQLite drives screen reads. A network cache may fetch online reports but cannot become the offline datastore. A small in-memory context/store handles UI preferences only; persist sync state in SQLite.
- `expo-network` as connectivity trigger, `expo-crypto` for UUIDs/secure random, `expo-secure-store` for secrets, `expo-background-task` + task manager for later best-effort background execution. Install SDK-compatible modules through Expo and lock them.
- Generated/typed Django client calls public Bearer-authenticated API directly. Do not reuse Next.js cookie proxy helpers, DOM components or frontend server environment variables.

## Runnable Windows Android build plan

Prerequisites for Phase 3: install Android Studio/SDK platform 36, compatible SDK tools/NDK, JDK 17; set project-scoped JAVA_HOME and ANDROID_HOME; allow the official npm/Maven/Google dependency sources under the organization's network policy. Android SDK was absent at the standard local path during discovery. A direct Expo package archive download was blocked by the organization's access policy, although npm metadata lookups worked. Package installation and native build remain unverified until ordinary permitted dependency access works; do not bypass that restriction.

From the repository, Phase 3 will create the real project and preserve a selected SDK template. After its package/config files are implemented:

```text
cd mobile
npm.cmd ci
npx.cmd expo install --check
npx.cmd expo-doctor
npx.cmd expo prebuild --platform android
npm.cmd run android
npm.cmd run lint
npm.cmd run typecheck
npm.cmd test -- --runInBand
cd android
.\gradlew.bat assembleDebug
```

The `android` script must invoke `expo run:android`, not an Expo Go launcher. SDK 57 prebuild may regenerate native directories; keep native configuration in config plugins and review the diff before rerunning it on a modified native tree. The debug APK must be installed on an API 36 emulator, then a representative physical Android phone. Release APK/AAB and signing are Phase 10. No signing keys or paid build account are needed for discovery. [Expo local builds](https://docs.expo.dev/guides/local-app-development/), [Expo development client](https://docs.expo.dev/versions/v57.0.0/sdk/dev-client/).

## Deployment and development feasibility

| Concern | Verified state / selected decision | Gate |
|---|---|---|
| Django | Python 3.14.5, Django 6.0.6, DRF 3.17.1, SimpleJWT 5.5.1, psycopg2 2.9.12, drf-spectacular 0.30.0 installed | Existing backend stays; new adapter app in Phase 2 |
| PostgreSQL | Docker `farm_postgres_db`, PostgreSQL 16.14; host `127.0.0.1:5437` → container 5432 | Local role can CREATE schema/database; empty test DB migrations applied during baseline. Hosted migration-role privileges remain unverified |
| Development Django | Docker backend published at port 7070; DB hostname `db` works in Docker only | Host checks override POSTGRES_HOST/PORT in process, not `.env` |
| Emulator API | `http://10.0.2.2:7070/api/v1` | Device localhost is not desktop localhost. Add emulator host to development ALLOWED_HOSTS and debug-only network policy in Phase 3 |
| Physical phone | Reachable LAN address with server bind/firewall/ALLOWED_HOSTS, or HTTPS staging | No verified LAN phone/hostname supplied; record concrete reachability in 3 |
| Hosted public HTTPS | `vercel.json` routes `/api/v1/*` to Django; web private binding is separate | Public HTTPS host, Bearer forwarding, WAF/body/time limits and certificate must be checked on staging before phone rollout. No deployment was made |
| Attachment storage | No configured durable private storage/upload subsystem found | Phase 9 selects private S3-compatible/object storage and short-lived authorized uploads; no serverless local files. Provider/region/account remains an operational setting |
| Scheduler | No Celery/continuous worker configured; sync request-driven | No scheduler required in 2–8. Retention cleanup via explicitly invoked management command; later scheduled run needs actual hosting plan |
| Long work | Bootstrap frozen pages persisted in Postgres; no memory-only queues | Each first-phase bootstrap <=100,000 rows, short snapshot transaction. If profile exceeds budget, fail explicitly or add asynchronous snapshot job architecture before scaling |

Native requests are not browser CORS requests. Do not add wildcard CORS to solve phone reachability. Production API configuration is public and can go in the native bundle; JWT signing keys/database/storage credentials cannot.

Initial budgets: JSON push <=1 MiB, <=50 operations, <=20 dependencies/operation; pull <=500 records and <=1 MiB/page; immutable entity payload <=16 KiB; transaction group <=10,000 changes/16 MiB staged total (including a conservative 1 KiB metadata reserve/change); scan <=5,000 change rows/request. Phase 2 additionally bounds a snapshot to 100,000 scanned rows, 32 MiB canonical entity bytes, a 20-second build window and four unexpired snapshots/user (resume does not consume a new slot). Fragment-descriptor counts/bytes are bounded even when all changes are hidden. PostgreSQL lock timeout is 5 seconds, per-statement timeout 20 seconds; push stops starting new commands after a 20-second request budget. These are safety limits, not proof that the 100,000-row performance target or public hosting plan can run within them. Reduce packs or implement tested asynchronous snapshot infrastructure before expanding limits. Aim for <=5 seconds server processing/request, and finish a command before 20 seconds. These are application budgets to measure, not claims about the deployment's configured maximum duration. Client timeout 30 seconds retains unknown outcomes. Exceeding a group/snapshot limit rolls back/fails with a named error; it never silently omits data. Attachments <=10 MiB go outside JSON.

## Security/product defaults

Selected defaults: initial online login/bootstrap; 7-day operational cached access, 24-hour sensitive finance/payroll cached access; current 15-minute/7-day JWT lifetimes; bootstrap TTL 24h; stream/tombstone retention 90d; retain compact operation deduplication records indefinitely for v1; support current and previous app protocol during rollout. Enforce server time/clock rollback policy and expose cached cutoff. Pending receipts never become spendable confirmed cash.

Development package suggestion: `com.farmmanagement.mobile.dev`; release package/app name, actual fleet, private-storage provider and production hostname remain configurable pilot/distribution choices. They do not block Phase 2 backend work. Keep reporting policy `MANAGEMENT_COST_V1`, server financial authority, owner-source privacy and existing historical reconciliation queue. Do not introduce a new valuation, proration or tax policy through mobile.

## Decision status and phase entry

The sync identity, envelope, first command, entity projections, ordering and capability policy are finalized in [SYNC_CONTRACT.md](SYNC_CONTRACT.md), [COMMAND_CATALOG.md](COMMAND_CATALOG.md) and [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md). [The checkpoint](checkpoints/PHASE_01.md) records actual tests and inherited exceptions. Phase 2 can implement its mortality slice without solving unrelated historical finance; money commands remain disabled until their later gates pass. Phase 3 additionally requires the native prerequisites above and the completed Phase 2 API.
