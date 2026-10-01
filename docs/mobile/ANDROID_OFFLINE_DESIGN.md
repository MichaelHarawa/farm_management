# Farm management Android application — design

Design date: 30 September 2026; Phase 1 decisions verified 1 October 2026. Status: finalized initial contracts and phased design; application implementation remains pending. [The Phase 1 checkpoint](checkpoints/PHASE_01.md) records source evidence, baseline tests and prerequisites.

## 1. Product outcome

A farm worker can open previously downloaded batches, record mortality, feed, treatment, weights and other permitted field work without internet, close the app, and retain the work. When internet returns, the application submits pending records and downloads changes made by other phones or the web application. Each entry shows whether it is only on this phone, awaiting review, rejected, or confirmed by Django.

Managers also use sales, receipts, expenditures, inventory, people, payroll, assets and finance reports. Sensitive approvals run against current server permissions. The app records business events; it does not execute bank transfers or mobile-money payments.

## 2. Existing system and reuse boundary

The repository inspected for this design has no `mobile/` React Native project or dedicated mobile synchronization API. Its existing mobile-friendly web UI is not an Android app with durable offline writes.

| Existing foundation | Evidence | Mobile treatment |
|---|---|---|
| Django 6, DRF and PostgreSQL | `backend/requirements.txt`, `backend/config/settings.py` | Retain; add an adapter around domain services |
| Next.js 16 / React 19 UI | `frontend/package.json` | Keep as a separate client; do not wrap it in a WebView |
| Public REST groups and OpenAPI | `backend/config/urls.py` | Reuse `/api/v1/auth/`, `/poultry-management/`, `/finance/` |
| JWT authentication | `backend/config/settings.py`, `apps/accounts/` | Mobile calls Django directly; web HttpOnly-cookie proxy is not the mobile auth mechanism |
| Users and roles | `backend/apps/accounts/models.py` | Reuse identity and explicit capabilities; employee and user remain distinct |
| Flock lifecycle, sales, feed and growth | `backend/apps/poultry/services/` | Reuse validation and server calculations |
| Finance services, journals and snapshots | `backend/apps/finance/services/`, `models.py` | Reuse posting/payment/allocation services; verify each actual posting path |
| Inventory item/lot/movement models | `backend/apps/finance/` | Extend the implemented finance inventory; `apps/inventory/models.py` is currently a stub |
| Sale-level selling costs and payroll advances | `docs/PHASE_3_CUSTOMER_CONTRIBUTION_CHECKPOINT.md`, current models/services | Include current sale economics and salary-payment workflow |
| Deployment structure | `vercel.json`, `docs/VERCEL_DEPLOYMENT.md` | Use a public HTTPS Django API route; keep requests bounded for hosted runtimes |

Most business primary keys are integers; user IDs and asset IDs are UUIDs. Preserve them. Phase 1 selected the `SyncEntity` mapping strategy in [SYNC_CONTRACT.md](SYNC_CONTRACT.md), without replacing primary keys or existing human-readable batch/sale references.

No multi-farm tenant boundary was found. The initial app targets the same single farm as the current backend. Partition phone data by backend deployment identity and user; do not invent tenant IDs and claim tenant security. Initial worker visibility is determined by capabilities, not an unimplemented batch-assignment model.

Existing finance documentation explicitly leaves historical ledger activation dependent on reconciliation. Documentation and model names are not proof that every source event already posts correctly. Phase 1 rechecked the source and current local database rather than restoring the older September dump. Salary changes now have period-effective history (`finance.0028`); arbitrary mid-month salary/proration and a distinct payroll approval flow are not implemented. The [API inventory](API_INVENTORY.md) identifies posting/permission gaps and their feature gates.

## 3. Architecture and technology

```text
Android React Native screens
            |
Local repositories + domain validation
            |
Encrypted SQLite: confirmed records + pending drafts + outbox + cursors
            |
Sync coordinator (foreground, reconnect, manual, best-effort background)
            | HTTPS / JWT / versioned commands and change pages
Django mobile-sync API -> shared authorization and domain services
            |
PostgreSQL: business records + operation receipts + change stream
            |
Existing Next.js web client uses the same domain services
```

Recommended stack:

| Concern | Decision |
|---|---|
| App | React Native + TypeScript, using Expo with native development builds and Expo Router |
| Local persistence | `expo-sqlite`, explicit SQL migrations, SQLCipher for persisted farm/finance data; SQLite repositories are authoritative for screen reads |
| Authentication secrets | `expo-secure-store` for refresh token and encryption-key material; short-lived access token in memory where practical |
| Synchronization | A small application-specific engine with SQLite outbox and Django command handlers; no additional cloud database |
| Connectivity | SDK-compatible network-state module as a trigger; API response remains the authority on reachability |
| Forms and math | Typed validation; compatible React Hook Form/Zod where useful; decimal strings and a tested decimal library for monetary previews |
| Charts | React Native/SVG charts selected after Android compatibility and accessibility checks; simple bars/lines with text equivalents |
| Testing | Django/PostgreSQL integration and concurrency tests; mobile unit/component tests and emulator/device end-to-end tests |
| Build | Local Android development/release builds; optional EAS Build. Paid cloud build services are not required by the design |

Phase 1 selected Expo 57.0.26 / React Native 0.86.3 / React 19.2.3, encrypted native `expo-sqlite`, JDK 17 and Android API 24–36. [Technical decisions](TECHNICAL_DECISIONS.md) give the verified compatibility sources, pinned dependencies, build commands and unresolved workstation/deployment prerequisites. Do not independently install the newest versions of every library. SQLCipher needs a native build rather than Expo Go; actual native encryption/build evidence belongs to Phase 3.

Proposed directories:

```text
mobile/
  app/                    # native routes and layouts
  src/components/         # native design system
  src/features/           # poultry, sales, finance, inventory, people, assets
  src/db/                 # encryption setup, migrations, repositories
  src/sync/               # outbox, coordinator, pull, conflict and recovery logic
  src/auth/               # native session, offline access, capabilities
  src/api/                # generated/validated contracts and transport
  src/test/               # fixtures and test support
backend/apps/mobile_sync/ # proposed app, added by Phase 2
docs/mobile/              # this pack, decisions, checkpoints, runbooks
```

No Next.js server modules, DOM components, cookies, Tailwind web components, or database credentials belong in the native bundle. Share platform-neutral schemas only where they are actually compatible; financial authority remains on Django.

## 4. Mobile interaction design

Use the farm's cream, navy and gold visual identity with native typography, strong contrast, labelled icons and Android-sized touch targets. Respect font scaling, screen readers and low-end phones. Large grids become compact cards and drill-downs; long registers use local pagination/search or virtualized lists.

Primary tabs: **Today**, **Batches**, **Record**, **Sync**, **More**. The centre Record action opens permitted quick-entry forms, not a blank dashboard.

| Area | Screen and decisions |
|---|---|
| Today | Live birds in selected downloaded batches, mortality, feed/growth coverage, collection follow-up if permitted; timestamps and missing-data states |
| Batches | Search, lifecycle/type filters, batch summary and tabs for flock, feed, health, growth, sales and costs |
| Record | Mortality, feed, treatment, weight, sale, receipt, expense, stock issue or work log according to capabilities |
| Sync | Last successful sync, queued count, per-record status, retry, sign-in required, dependency blocked, conflict review and data-pack download |
| Finance | Overview, receivables, expenses/payables, funding/owner contributions, inventory, people/payroll, assets, batch performance and period reports |
| Administration | Online user creation/editing/roles, account activation, password-reset workflow, audit trail and device revocation for administrators |
| Settings | Account, backend/environment label, offline access expiry, storage/download coverage, app version, privacy and help |

Quick-entry forms default to a selected batch and today's farm date, show units explicitly, retain drafts, and end with a clear saved-on-device confirmation. Physical cash received offline gets a provisional device reference; the official receipt is issued only after server acceptance. Never show a generic green success mark implying financial posting before acceptance.

Conflict screen: show the user's captured values, current permitted server values, reason, affected linked records, and safe choices. Choices include correct a rejected draft, retain for manager review, or explicitly discard an unsent draft. Accepted posted records use reversal/correction workflows. Do not offer overwrite for posted finance, stock or flock quantities.

Each money/report screen distinguishes **confirmed as of [server timestamp]** from **pending on this device**. Pending receipts do not increase confirmed spendable cash; pending sales do not become official revenue or final profitability. Operational previews may include pending events if the resulting count is labelled provisional. No feed-conversion ratio is shown without a supported weight-gain denominator.

## 5. Offline capability policy

Initial sign-in, device registration and first download require internet. Afterward the user can use the downloaded data pack within the configured offline-access window. Offline support is explicit for each action:

| Workflow | Offline behavior | On reconnect / online control |
|---|---|---|
| Batch register/history | Read downloaded records; capture new booking/delivery details as pending commands | Validate IDs, lifecycle and chronology; server assigns official references |
| Mortality, feed, treatment, weights | Durable offline capture | Validate current and dated bird balance, unit rules and duplicates; append once |
| Flock adjustment/correction | Save a proposed adjustment | Authorized online review/approval before it changes confirmed stock |
| Sale and sale-specific selling costs | Capture linked pending records | Single domain transaction validates available birds and cost accounting |
| Sale collection, purchase, expense, supplier payment, owner funds | Capture evidence and permitted posting intents; no confirmed cash effect | Recheck role, period, source balance, amount and duplicate reference; accepted once or review required |
| Stock receipt/issue/return/transfer/waste | Capture linked pending movement; show provisional availability | Validate stock under locks; post one inventory/cost event; conflicts remain visible |
| Employee and labour records | Authorized cached directory, work logs, casual-labour drafts | Employee identity changes/approval/posting and salary-history changes require online access |
| Payroll, advances and salary payments | Authorized cached summaries; offline evidence/draft capture where configured | Generation, approval and formal payment posting are online; advance reduces salary balance, not a second expense |
| Asset usage and maintenance | Capture readings, maintenance notes and documents | Validate against asset; financial capitalization/depreciation/impairment/disposal remain online |
| Reports and period close | Read downloaded dated reports; local estimates labelled provisional | Django refreshes authoritative results; close/reopen/reversal require current authorization |
| Users, roles, device revocation | No offline administration | Online only, audited |

An offline command is a request to record work already done, not a promise that all devices had enough stock/cash when disconnected. Two phones can both record selling the last birds. On sync the server must preserve both submissions, accept only valid postings, and route the other to review. Do not alter quantities, payment dates or periods to make it fit. Guaranteed offline reservations across devices would require a later stock-quota design and is outside this release.

Payroll or finance data is never downloaded just because a user can access poultry. Enforce field-level projection and role-based filtering in bootstrap, pull, direct APIs and command handlers.

## 6. Security and offline access

- Current JWT settings are 15-minute access and 7-day rotating/blacklisted refresh tokens. Preserve web behavior; implement mobile refresh as one serialized operation across foreground/background workers. If a rotated-token response is lost, require sign-in without erasing pending work.
- Proposed operational offline-access default: 7 days since successful server validation. Proposed sensitive finance/payroll cache access: 24 hours and only for specifically authorized roles. Make these configurable and visible; they are product defaults, not regulatory requirements.
- Cached capability data permits bounded local use only. Every upload and online action rechecks current active-user, device and role state. A remote revocation cannot instantly reach a disconnected phone; describe this limit honestly.
- Require device/app unlock, encrypt SQLite and private attachments, and exclude secrets and private cache from Android backup. Tokens do not belong in unencrypted AsyncStorage. [React Native security](https://reactnative.dev/docs/security), [Expo SecureStore](https://docs.expo.dev/versions/latest/sdk/securestore/).
- Clock rollback or uncertain offline expiry should require online verification, never extend access automatically. Store server time and elapsed-time evidence where available; do not claim this defeats a compromised device.
- Scope all local stores/queues to deployment + user. On sign-out, lock pending work for the original user; offer explicit discard only with a count and confirmation. A different user must not see or upload it. Reauthentication by the same authorized identity can recover it.
- Device revocation blocks server access and quarantines rejected work. Privileged recovery requires an audited process; never reattribute a former user's operation silently.
- Uninstall/clear-data or loss of a phone can destroy unsynced records. Add visible pending counts and a controlled encrypted recovery/export procedure; never claim an unuploaded draft is backed up.

## 7. Synchronization lifecycle

1. Sign in, register the device, read capabilities and protocol limits.
2. Download a consistent, authorized data pack into staging tables; activate only when complete.
3. Write every local draft and outbox item in one SQLite transaction.
4. On app launch/resume, network return or manual Sync, refresh authentication, verify access, pull current data, push dependency-ready commands, then pull their resulting changes.
5. Commit each pull page and its cursor together. Preserve pending overlays until their acknowledgments reconcile to canonical entities.
6. Use a persisted worker lease so foreground and background work cannot drain the same queue concurrently. Retry transient failures with bounded backoff; business conflicts need action.

Android background scheduling is best effort. Foreground/manual sync must work independently; a force-stopped or power-restricted app may not synchronize until opened again. Expo's Android background scheduling uses WorkManager and its periodic timing is inexact. [Expo BackgroundTask](https://docs.expo.dev/versions/latest/sdk/background-task/), [Android offline-first guidance](https://developer.android.com/topic/architecture/data-layer/offline-first).

The exact envelope, transaction boundaries, bootstrap and conflict rules are in [SYNC_CONTRACT.md](SYNC_CONTRACT.md).

## 8. Data packs, performance and hosting

Complete-release default download: active/mature/selling batches, upcoming booked/delivered batches, their required histories and lookup records, all permitted open receivables/payables needed for actions, and current/recent finance snapshots where authorized. **Phase 2 initially publishes only operational Batch/Mortality/FeedUsage**, as finalized in the sync contract; later feature phases add finance packs after their gates pass. Older closed batches and periods are explicit downloadable packs. Related history required for accurate denominators must be included or provided as authoritative aggregate baselines; never derive whole-farm totals from a partial page.

Display coverage: batch IDs/range, report cutoff, last successful download and missing packs. A network error must not become a false zero or empty register. Permission loss requires a scope reset/purge on reconnection, with protected handling of the original user's unsent work.

Proposed initial limits, adjustable after profiling: 50 commands per request, 1 MiB JSON push body, 500 changes per page, 100,000 total downloaded rows, 5,000 queued operations, 10 MiB per attachment. Warn before storage/queue limits; never evict pending work to make room. Bootstrap and push have explicit payload and time budgets suitable for the deployed runtime.

The physical phone needs a reachable API host. Android emulator host-loopback is normally `10.0.2.2`, while a physical phone uses a reachable LAN development address or HTTPS server. `localhost:7070` on the phone refers to the phone. Permit cleartext only in a narrowly scoped development configuration; release uses HTTPS. [Android emulator networking](https://developer.android.com/studio/run/emulator-networking).

Hosted files/snapshots/queues must be durable in PostgreSQL or private object storage, not process memory or a serverless local filesystem. Background workers or schedulers are introduced only with a real deployment plan; the first sync protocol is request-driven and does not require a continuously running task worker.

## 9. Completion and explicit boundaries

Completion means every in-scope workflow has a native screen or a documented, visible online action, every permitted field-capture workflow survives offline restarts and converges safely, web/mobile see the same confirmed records, and Phase 10 evidence passes.

Keep configurable reporting policy, batch management profit, cash balances, inventory value and net assets separate. Missing/reconciliation-dependent finance features must show the actual limitation. Existing historical exceptions from the earlier finance review are not authorization to edit production data during mobile implementation.

Product defaults to confirm during a pilot, without blocking the design: app name/package ID, device fleet and supported Android versions, offline window, sensitive-cache policy, required document sizes, historical packs, release distribution and production hostname. No financial data migration is authorized by this design pack.
