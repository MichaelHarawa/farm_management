# Mobile Phase 1 checkpoint — discovery and contracts

Completed **1 October 2026** in `C:\Users\MW50001541\Pictures\farm_management`.

## Completion decision

**Phase 1 is complete: discovery, initial contracts, capability policy, writer coverage plan, feature traceability and reproducible baseline are delivered.** A01 is evidenced for data preservation and the unchanged application/regression baseline, with inherited failures disclosed below. A02–A37 remain unimplemented. Phase 2 may begin locally with the concrete operational contract; no Android app, sync endpoint, migration or changed financial behavior is delivered by this phase.

Native compilation/encryption is not claimed. Missing Android SDK/JDK setup, package-download access, an actual public HTTPS hostname and hosted migration/storage settings are explicit later-phase prerequisites, not fabricated successful checks.

## Instructions and repository context reviewed

Read the Phase 1 prompt, shared mobile implementation instructions, Android design, sync contract, acceptance matrix and next-phase entry requirements. Inspected source authentication/roles, poultry/finance models, serializers, views, services, admin, migrations, command/bulk writers, deployment configuration and existing frontend workflows. Read applicable `frontend/AGENTS.md`, finance architecture/data-migration/deployment documentation and the latest finance checkpoint as reference; current source/database evidence takes precedence over old documents. Dump comments/data and historical plans were not treated as instructions.

The supplied `dump-farm_management-202609021136.sql` is an older reference, not today's baseline. It was neither edited nor restored. The configured local Docker database has later salary/selling-cost migrations and additional records. No historical reconciliation, ledger backfill, role grant, production deployment or broader finance roadmap was executed.

Initial Git state already contained a modified `.gitignore` and untracked `docs/mobile/` design pack. Those user changes were preserved. Some original pack files are excluded by the user's existing ignore rules; no ignore rules, commits or staging were changed. All Phase 1 edits stay under `docs/mobile/`; no application/domain/dependency configuration files were edited.

## Delivered files and contract decisions

| Artifact | Concrete result |
|---|---|
| [API_INVENTORY.md](../API_INVENTORY.md) | Existing method/path groups, permissions, services/transactions, IDs/dates/decimals/pagination, financial effects, gaps and all-writer checklist |
| [CAPABILITY_MATRIX.md](../CAPABILITY_MATRIX.md) | Six current roles versus selected mobile capabilities, online/queued modes, positive field projections and scope revision |
| [COMMAND_CATALOG.md](../COMMAND_CATALOG.md) | Explicit registry, exact mortality fields, hash/identity rules, reserved later commands, composite/dependency map |
| [push-v1.schema.json](../contracts/push-v1.schema.json) | Strict protocol/payload v1, mortality-only shape; no client-controlled age/actor/model writes |
| [mortality-record.example.json](../contracts/mortality-record.example.json) | Valid fictional UUID/date example, not a live submission |
| [SYNC_CONTRACT.md](../SYNC_CONTRACT.md) | Finalized initial routes/session, mapping/revisions, commit ordering, packs/paging/fragments, results/errors and retention |
| [TECHNICAL_DECISIONS.md](../TECHNICAL_DECISIONS.md) | Official compatibility sources, pinned Expo/RN baseline, native SQLCipher/build plan, deployment feasibility and configurable budgets |
| [FEATURE_TRACEABILITY.md](../FEATURE_TRACEABILITY.md) | Active workflow → phase → offline/online boundary → acceptance IDs; inherited missing features gated |
| [phase01_baseline.py](../tools/phase01_baseline.py) | Read-only snapshot/inventory/checks/schema modes, guarded disposable PostgreSQL tests, contract and document validation |
| Existing design/index/acceptance/Phase 2 prompt | Updated only to resolve source-backed contradictions and link verified Phase 1 outputs |

Protocol/schema: **1**. Identity: additive `SyncEntity` mapping preserving existing primary keys; revisions/stream counters and integer source IDs are strings on wire. Initial mutation candidate: **`poultry.mortality.record` only**, unavailable until Phase 2 tests pass. Initial operational published set: **Batch, Mortality, FeedUsage**. Sales/approved adjustments, admin/cascades and financial finalization are dependency writers for these projections. Mortality's recalculated feed populations and batch status publish atomically with its accepted receipt. Current dated-balance clamping is not proof of a safe command and must be validated before acceptance.

Existing broad poultry `IsAuthenticated` writes and employee-linked account/role mutation are identified permission gaps, not policies to copy into mobile. Phase 2 centralizes the affected operational permissions and device/session authentication; later sensitive commands remain disabled until corresponding ordinary REST bypasses/service gates are fixed. No user roles changed.

No database migrations were added. Current domain migration leaves are `accounts.0004_seed_system_roles`, `finance.0028_employeesalaryadjustment` and `poultry.0034_salesellingcost`; all current migration leaves are applied. The initial backend command does not require historical general-ledger activation. Money/stock/payroll/asset commands require their own later accounting and concurrency evidence.

## Verification and exact baseline outcomes

| Check | Outcome |
|---|---|
| Django system check | Passed, no issues |
| Migration drift | Passed, no changes detected |
| Finance preflight | Passed, all current required migrations applied |
| Isolated PostgreSQL full backend suite | **116 run; 115 passed, 1 inherited failure**, detailed below |
| Existing OpenAPI generation/validation | Valid OpenAPI 3.0.3; 139 paths / 166 components; inherited annotation errors/warnings mean it is not a complete native client contract |
| Frontend lint | Passed with 0 errors / 4 inherited `AddBatchDialog.tsx` warnings |
| Original-tree TypeScript/default Turbopack production build | Failed on pre-existing malformed `.next/dev/types/validator.ts:98` |
| Clean temporary source copy, webpack production build | Passed; 28 pages generated; independent of the existing `.next` cache |
| Clean temporary source copy, TypeScript | Passed |
| Initial mortality JSON contract | Schema/example passed; 12 malformed cases rejected, including invalid calendar date, unknown fields, unsafe IDs, duplicate dependencies and oversized request count |
| Before/after database comparison | **63 table fingerprints unchanged**, including domain sequences and User.roles; no unapplied migrations; finance audit unchanged |
| Pack integrity | Python tool compiles; 9 JSON files parse; 21 Markdown files / 63 local links and fenced blocks checked by the `verify` mode |

No manual browser acceptance or emulator/physical-phone test was performed: this phase changes documents/contracts only. Clean frontend checks establish a source build baseline, not Android correctness or a default Turbopack success.

### Backend inherited failure and test-database teardown

Failure: `apps.finance.tests.test_customer_contribution.CustomerContributionTests.test_documented_estimate_is_analytical_idempotent_and_reversible`, assertion at line 316: expected support cost `0.00`, actual `50.00`.

The test reverses an analytical attribution using `timezone.now()` but queries a hard-coded report cutoff of **30 September 2026**. On this run, reversal occurs on **1 October 2026**. Source report filtering includes a reversal later than the requested cutoff, so the historical `50.00` remains. This is an inherited date-sensitive test expectation; no mobile application code exists in this phase. The customer-master UI is superseded but retained API/tests must still be preserved. Do not claim all inherited backend tests pass or alter historical reporting policy to force this assertion green.

Suite run time: 42.554 seconds. It used fresh local PostgreSQL database **`test_mobile_phase01_b7b7e41a3354`**, never the configured farm database. Django initially failed teardown with `ObjectInUse` because two threaded-test connections remained. After the test process exited, read-only catalog checks confirmed zero remaining sessions. The exact newly created test database was then removed successfully; a final catalog query confirmed absence. Only disposable test data was deleted. Farm records were not removed.

Future reruns may encounter this inherited teardown behavior. Inspect the exact disposable database name and active sessions after the runner exits; never reuse/drop a pre-existing database or terminate connections to the farm database. The helper refuses remote database creation and refuses an existing requested test name. No `keepdb`, source restore or destructive fallback was used.

### Read-only financial baseline

[Before](../evidence/database-before.json) and [after](../evidence/database-after.json) contain counts and SHA-256 row fingerprints, migration leaves and full read-only finance audit; they do not contain user rows/passwords or connection credentials.

Selected preserved counts: 4 users / 6 roles / 3 user-role links; 3 batches / 47 sales / 69 sale payments / 27 mortality / 28 feed records / 96 input costs; 110 expenditures (107 posted) / 60 funding allocations / 10 funding receipts; 2 employees / 6 payroll entries / 6 payroll payments; 1 asset / 2 depreciation rows; 0 inventory lots/stock movements; 0 journal entries/lines. Complete counts, including allocations/snapshots and sequences, are in the evidence files.

Finance audit: **6 issue categories, 2 critical / 4 warning**, inherited and unchanged:

| Category | Current result |
|---|---|
| Unlinked operational cost | 1, MWK 15,000 |
| Void-linked operational cost | 1, MWK 18,000 |
| Unfunded/partly funded expenditures | 54, MWK 4,692,200 |
| Possible duplicate economic event | 1 |
| Period-lock violations | 32 |
| Source events pending approved general-ledger backfill | 223 |

Zero journals must not be presented as completed ledger accounting. These exceptions stay visible and are not corrected by mobile discovery.

## Reproduction

Use the repository virtual environment from the workspace root. Native `.env` defaults use Docker hostname `db`, which does not resolve on the host. The verified farm container publishes **5437**, not the unrelated local PostgreSQL at 5432. Set only process variables; do not edit `.env` or expose its password.

```powershell
$env:POSTGRES_HOST = '127.0.0.1'
$env:POSTGRES_PORT = '5437'
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py checks
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py tests
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py inventory
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py schema
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py snapshot
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py contracts
& .\venv\Scripts\python.exe docs/mobile/tools/phase01_baseline.py verify
```

Read modes enforce PostgreSQL repeatable-read/read-only transactions. Optional `--output docs/mobile/evidence/<name>.json` saves generated JSON only inside that evidence directory. Use new before/after filenames for future work; do not overwrite this checkpoint's historical evidence. Tests intentionally return nonzero for the disclosed inherited failure. `contracts` and `verify` need no database connection.

Original frontend commands, run from `frontend/`:

```powershell
npm.cmd run lint
npx.cmd --no-install tsc --noEmit
npm.cmd run build
```

For the clean-cache baseline, copied frontend source/config into a fresh temporary directory, excluding `.next`, `node_modules`, `.env.local`, `dev.log` and `tsconfig.tsbuildinfo`, and linked its `node_modules` to the already installed source dependencies. No dependencies were upgraded. Ran there:

```powershell
npm.cmd run build -- --webpack
npx.cmd --no-install tsc --noEmit
```

Temporary baseline directory: `C:\Users\MW50001541\AppData\Local\Temp\farm-mobile-phase01-web-3d75fc08512b45918f8af627eef64495`. It contains a **node_modules junction**; do not recursively delete through that junction when cleaning it. The source `.next` problem was not edited or deleted to make the original command look successful.

Machine evidence: [resolved API/models](../evidence/api-baseline.json), [schema summary](../evidence/schema-summary.json), [contract validation](../evidence/contract-validation.json), [baseline summary](../evidence/phase01-baseline-summary.json) and [pack/preservation verification](../evidence/verification.json).

## Infrastructure and next-phase entry

Selected compatible baseline: Expo **57.0.26**, RN **0.86.3**, React **19.2.3**, Router **57.0.24**, expo-sqlite **57.0.3** with SQLCipher native plugin; local Node **24.20.0**, npm **11.19.0**. Auxiliary compatible patches are resolved/locked in Phase 3. Official sources and native build steps are in Technical Decisions. This workstation has JDK 21, not the selected JDK 17; Android SDK was not present at the standard path. npm metadata worked, but an Expo archive download was denied by the organization's network policy. Do not bypass it or claim package installation/build success.

Local PostgreSQL 16.14 privileges support additive migrations/test database creation. Hosted privileges are unverified. Vercel configuration exposes `/api/v1` to Django but no deployed public HTTPS hostname was supplied/verified. Confirm actual Bearer forwarding/certificates/body/runtime limits on staging before phone use. Private attachment storage provider is not configured and is a Phase 9 prerequisite. Request-driven Phase 2 needs no continuous scheduler.

Next: [Phase 2 — Django sync foundation](../phases/PHASE_02_DJANGO_SYNC_FOUNDATION.md). Implement additive sync persistence, shared capabilities/device-bound JWT, explicit mortality adapter, transactional stream/writer coverage, frozen bootstrap and bounded push/pull/status. Its empty/restored disposable-database, concurrency, authorization, replay and ordering tests must pass before enabling the command. Use Phase 1 budgets/allowlists; do not scaffold mobile UI early or broaden into financial backfill. Android shell/encrypted storage begins in Phase 3 after the Phase 2 API and native prerequisites are ready.

Recovery for this phase: preserve the previous pack and revert only this phase's document/diagnostic-tool changes if necessary. No database rollback, migration reversal or user-role recovery is needed. Temporary test data was disposable; recorded farm baseline is unchanged.
