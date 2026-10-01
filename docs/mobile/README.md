# Android app: design and phased implementation prompts

Prepared 30 September 2026 for `C:\Users\MW50001541\Pictures\farm_management`.

This pack specifies a new React Native Android application that uses the existing Django backend and works offline. The Django sync foundation is now implemented; the native application is not yet built. The Next.js application continues to run alongside it.

Phases 1–2 completed on **1 October 2026**. Read [the Phase 1 checkpoint](checkpoints/PHASE_01.md) for the discovery baseline and [the Phase 2 checkpoint](checkpoints/PHASE_02.md) for implemented sync behavior, tests and inherited failures. Sync remains off/unmigrated on the original farm database. [The runbook](PHASE_02_RUNBOOK.md) covers staged migration, seeding, activation and recovery. The native Android app is Phase 3.

Phase 1 outputs: [API/writer inventory](API_INVENTORY.md), [capabilities and field visibility](CAPABILITY_MATRIX.md), [command catalog/dependencies](COMMAND_CATALOG.md), [technical decisions/build plan](TECHNICAL_DECISIONS.md), [feature traceability](FEATURE_TRACEABILITY.md), and [strict initial push schema](contracts/push-v1.schema.json). Baseline reproduction is in [tools/phase01_baseline.py](tools/phase01_baseline.py); saved evidence is linked from the checkpoint.

## Start here

1. Read [Android and offline design](ANDROID_OFFLINE_DESIGN.md) for the architecture, screens, scope, and offline rules.
2. Read [sync contract](SYNC_CONTRACT.md) for the proposed API, persistence, retries, and conflicts.
3. Read [shared implementation instructions](IMPLEMENTATION_RULES.md). These apply to every phase.
4. Run the phase prompts below in order. Each is a ready-to-use instruction file for an implementation AI. Complete its acceptance checks and checkpoint before starting the next phase.
5. Use the [acceptance matrix](ACCEPTANCE_MATRIX.md) to track the complete requirement, including failure scenarios.

Copy this launch prompt, changing only the phase filename:

```text
Work in C:\Users\MW50001541\Pictures\farm_management.
Implement docs/mobile/phases/PHASE_01_DISCOVERY_AND_CONTRACTS.md.
Read and follow docs/mobile/IMPLEMENTATION_RULES.md and the design/contract
documents referenced by that phase. Inspect the actual repository before editing.
Implement only this phase, complete its tests and checkpoint, and report the
concrete result. Preserve existing records and unrelated work. Do not claim a
phase is complete if its required acceptance checks have not passed.
```

## Delivery sequence

| Phase | Working result | Depends on |
|---|---|---|
| [1 — Discovery and contracts](phases/PHASE_01_DISCOVERY_AND_CONTRACTS.md) | Verified API/workflow inventory, capability matrix, scope and technical decisions | Existing repository |
| [2 — Django synchronization foundation](phases/PHASE_02_DJANGO_SYNC_FOUNDATION.md) | Secure device API, consistent bootstrap, durable push/pull and mortality command | 1 |
| [3 — Android shell and local storage](phases/PHASE_03_ANDROID_FOUNDATION.md) | Native app, authentication, encrypted SQLite, offline session and navigation | 1–2 |
| [4 — End-to-end offline synchronization](phases/PHASE_04_OFFLINE_SYNC_ENGINE.md) | Record mortality offline, restart, reconnect, and see one confirmed record on web/mobile | 2–3 |
| [5 — Daily poultry operations](phases/PHASE_05_POULTRY_OPERATIONS.md) | Batch and daily operations workflows, including offline capture and reconciliation | 4 |
| [6 — Sales, spending and inventory](phases/PHASE_06_SALES_CASH_INVENTORY.md) | Offline financial capture, controlled posting, stock issues and cash history | 5 |
| [7 — People, payroll and assets](phases/PHASE_07_PEOPLE_PAYROLL_ASSETS.md) | Workforce and asset workflows with online approval controls | 6 |
| [8 — Dashboards, reports and administration](phases/PHASE_08_REPORTING_AND_ADMIN.md) | Useful offline summaries, authoritative reports, period close and user/device management | 7 |
| [9 — Attachments and resilience](phases/PHASE_09_ATTACHMENTS_AND_HARDENING.md) | Receipt/photo queue, background sync, conflict recovery, performance and security validation | 8 |
| [10 — Android pilot and release](phases/PHASE_10_ANDROID_RELEASE.md) | Tested signed Android build, deployment/runbooks, user guide and release evidence | 9 |

Phases 1–4 establish a technical pilot. Phase 5 supports daily operational trials. Phase 6 adds financial capture only after its accounting and concurrency gates pass. Phase 10 is the complete Android release gate. A limited pilot is not full feature completion.

The phases have dependencies because reliable offline writes need backend safeguards before screens are rolled out. UI work may be prototyped earlier, but must not be presented as a working offline feature until the complete path is tested.

## Scope decisions

- Android first, React Native with TypeScript; Expo development builds are the recommended starting point.
- Django/PostgreSQL remains the shared authority. SQLite is the phone's durable working store.
- Routine field records can be saved without connectivity after an initial authenticated download.
- Financial entries can be captured offline as pending records. Approval, reversal, period closing, salary changes and account administration require an online authorization check.
- Existing poultry and finance workflows are in scope. Future crops/goats modules, bank/mobile-money integrations, full multi-tenancy and iOS release are not part of this implementation.
- Existing finance exceptions must remain visible. Mobile delivery must not silently repair historical accounting or activate an unreconciled general ledger.

The individual prompts require checkpoints under `docs/mobile/checkpoints/`. Phases 1–2 now have completed checkpoints. Phase 3 onward remains future implementation work; the design pack is not evidence that native behavior works.
