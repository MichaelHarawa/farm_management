# Phase 1 — feature-to-phase and acceptance traceability

Verified 1 October 2026. This table maps the current repository's active workflows and the user's Android/offline requirement. “Pending” means durable local evidence/intent followed by a server decision; it does not mean an approved financial entry. The API inventory identifies each existing route; the command catalog identifies the explicit adapter boundary.

| Requirement / current web workflow | Native delivery | Offline behavior / server gate | Acceptance IDs |
|---|---|---|---|
| Login, current account, refresh/logout, account isolation | 2 API; 3 UI/storage; 4 recovery | First login/download online; bounded cached access; retain original-user unknown outcomes | A03–A07, A15–A16, A28–A29 |
| Device registration/self-management, admin device revocation | 2 API; 8 administration UI | Online authorization, persisted device sessions checked on ordinary REST/refresh too | A03, A06, A16 |
| Batches register/booking/mark-delivered/confirm-arrival; web `/poultry` | 2 read projection; 5 workflows | Cache current/history pack; supervisor+ pending writes with UUID dependencies/revisions | A10, A13–A14, A17, A19, A35 |
| Mortality | 2 server command; 4 first complete offline slice | Pending append; age/date/flock/period validation; Batch+FeedUsage effects atomically published | A07–A14, A17–A19, A33–A35, A37 |
| Feed capture, feed/population metrics, feed source/cost read | 5; inventory integration 6 | Pending operational usage; financial cost projection restricted; stock-linked composite once | A10, A17, A19, A21, A26, A35 |
| Flock corrections and metric recalculation | 5 | Offline proposal only; online supervisor+ approval; dated history preserved | A03, A14, A17–A19 |
| Treatment/vaccination and growth/weight samples | 5; stock integration 6 | Pending observation; treatment stock effect once; no fabricated healthy/FCR result | A07, A17, A19, A21, A26 |
| Poultry live dashboard and guides; `/poultry/dashboard`, `/poultry/guides` | 5 operational screens; 8 dashboard | Dated local/confirmed indicators and static guidance, coverage/empty states | A24–A26 |
| Batch forecast assumptions and sell-by guidance | 8 | Cache permitted evidence/version; online forecast edits; never derive farm totals from partial history | A19, A24–A26 |
| Batch input costs and expenditure projection | 6 | Pending composite; finance permission/date lock; preserve legacy cost read without duplicate expense | A18–A21 |
| Sale with multiple incremental selling costs | 6 | Pending sale+children+initial receipt; one server transaction; no required customer master | A08–A10, A17–A20, A24 |
| Receivables/follow-up and dated sale receipt history; `/finance/receivables` | 6 | Cache open balance/evidence; pending collections; current balance/period/source controls | A08–A10, A18–A20, A24, A35 |
| Sale receipt reversal | 6 | Online fresh confirmation, durable outcome/status recovery | A03, A09, A18, A36 |
| Expenditure draft/post/update/pay/void/historical assign-funding; `/finance/expenditures` | 6 | Pending allowed draft/post/payment intents; posted updates forbidden; reconciliation/reversal online | A08–A10, A18–A21, A24, A36 |
| Shared expense compatibility register; `/finance/expenses` | 6 | Single source/expenditure projection; no duplicate cost/cash | A20–A21 |
| Funding sources, receipts, owner cash source privacy | 6 | Authorized cached source balance; pending cash receipt; source master/reversal online | A03, A08–A09, A19, A24 |
| Owner identity/contribution/designation/capital report; `/finance/owner-capital` | 6 capture; 8 report/master administration | Director/admin only; pending receipt, online identity/designation/reversal; cash and intended use separated | A03, A08–A10, A19, A24–A25, A36 |
| Inventory items/base units/conversions/locations and lot receipt | 6 | Cached operational lookups; masters online; conversion-management API/editor is missing and must be added; receipt pending after payable/journal boundary proof | A03, A10, A17, A19, A21 |
| Inventory issue/return/transfer/waste/expiry/adjustment, low-stock/expiry warnings; `/finance/consumables` | 6 | Pending typed events; adjustment posting/approval online; missing movement services completed before enabling | A08–A10, A17–A19, A21, A26 |
| Employee directory/detail/edit, optional user link; `/finance/employees` | 7 | Minimal authorized cache; employee edit online; account link/admin identity online separately | A03, A06, A16, A22 |
| Period-effective salary history/adjustment and payroll generation; `/finance/payroll` | 7 | Sensitive cache managerial only; generation/salary changes online; no claim of arbitrary mid-month proration | A03, A18–A19, A22 |
| Salary advance/payment/funding allocation/reversal/deduction liabilities | 7 | Offline evidence if configured; formal actions online with submitted-intent recovery; same wage liability | A08–A09, A19, A22, A24, A36 |
| Work logs and casual labour draft/approve/post/pay/reverse; `/finance/labour` | 7 | Own linked worker log or authorized draft pending; approval/post/pay/reversal online | A03, A08–A10, A18–A19, A22, A36 |
| Asset/category register/detail, acquisition/from-expense/additional capitalization | 7 | Authorized cache; financial creation/correction online after complete accounting controls | A03, A18–A19, A23, A36 |
| Asset usage/maintenance history/reminders | 7; documents 9 | Pending observations; linked financial expense separate and controlled | A07, A10, A23, A30 |
| Asset available-for-use/basis estimates/depreciation/impairment/transfer/disposal/history | 7 | Financial actions online; existing source limitations visible and remedied before enabling | A03, A18–A19, A23, A36 |
| Asset replacement plans/reserve transactions/recovery | 7 | Dated cached plan; online financial changes; reserve not assumed cash transfer | A19, A23–A25, A36 |
| Prepaid recognition/depreciation/cost allocation/bird-day regeneration | 6–8 | Cache authoritative values; controlled online action, no second source expense | A18–A19, A23, A25, A34, A36 |
| Batch and portfolio performance/funding mix; `/finance/batches` | 8 | Confirmed cutoff and pending evidence separate; selection-invariant allocations | A19, A24–A26, A34–A35 |
| Revenue utilization/spending/cross-batch financing; `/finance/revenue-usage` | 8 | Bounded list/detail download; local virtualization; no per-batch network loop | A24–A26, A34–A35, A37 |
| Finance overview/live metrics; `/finance` | 8 | Role-projected current/cached summary with decision indicators, freshness and missing-data states | A03, A24–A26 |
| Period reports & close/reopen/checklist; `/finance/monthly` | 8 | Dated immutable snapshots read offline; close/reopen online, recovery/idempotency and large groups | A18–A19, A24–A25, A34, A36 |
| User independent of employee, role assignment, activation, temporary-password reset, audit; `/administration` | 8 | Online admin only; preserve last active admin across concurrent/generic writers | A03, A16, A36 |
| Consistent bootstrap/pull/push, conflict UX, queue/manual/reconnect/foreground sync | 2 primitives; 4 engine; extend 5–8 | Atomic queues/revisions/cursors; hidden-page progress; no silent overwrite; preserve unknown effects | A07–A17, A33–A37 |
| Receipt/photos/private attachment upload and recovery | 9 | Protected local queue; resumable independent upload; checksum/access gates | A06, A15, A28–A30 |
| Doze/force-stop/reboot/flaky network/low storage/background worker overlap | 9 | Best-effort background; reliable foreground/manual; protected queues across restart/upgrade | A15, A27–A29 |
| Signed APK/AAB/pilot rollout/user/operator guide | 10 | Native emulator/physical-device evidence and install/upgrade tests | A31–A32 |

## Scope exclusions and inherited prerequisites

The customer master/contribution UI is superseded by sale-level costs and remains outside mobile navigation. Its retained backend data/API/tests are preserved. Future crops/goats, multi-tenancy, iOS distribution, bank/mobile-money execution, Profit First allocation roadmap and a fresh statutory reporting policy are not part of this delivery.

Some desired backend capabilities are incomplete: non-receipt/issue stock handlers, complete live GL posting coverage, prospective asset changes, explicit payroll approval and arbitrary effective-date salary/proration. Their feature phases must either implement a scoped tested service or leave the action visibly unavailable and mark the corresponding feature gate incomplete. Do not relabel inherited model fields as delivered workflows. Phase 1 does not backfill/repair the historical finance exception queue.

## Acceptance status after Phase 1

Only A01 has Phase 1 evidence: unchanged application/domain files; read-only before/after table fingerprints; safe disposable PostgreSQL test DB; backend checks, inherited test failure; frontend baseline and clean-copy build. See [checkpoints/PHASE_01.md](checkpoints/PHASE_01.md). A01 is verified for isolation/data preservation and documented regression baseline, not an assertion that all inherited tests pass. A02–A37 remain specified/unimplemented; no Android offline/build claims are made.

Phase 2 entry: use the finalized mortality JSON schema, mapping identity, operational entity projections and writer checklist. Add its migrations only to disposable/staging databases until verified. Its safe operational command is independent of historical finance backfill; all financial sync commands remain unavailable until their later gates pass.
