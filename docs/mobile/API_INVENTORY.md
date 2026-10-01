# Phase 1 — verified API and writer inventory

Verified 1 October 2026 against the working repository and the local PostgreSQL 16 farm database. This is discovery evidence, not a statement that mobile endpoints exist. Exact resolved methods, view/action names, configured permission classes, pagination classes and model field types are in [api-baseline.json](evidence/api-baseline.json). There are 230 resolved API method/path pairs, including schema/docs; DRF's root/format aliases are excluded. Inherited OpenAPI annotations are incomplete, so the resolved routes and source are the inventory authority.

## Conventions and reuse status

`P` means `/api/v1/poultry-management`; `F` means `/api/v1/finance`; `A` means `/api/v1/auth`. `{id}` is the existing server primary key, **not** the proposed sync UUID. Poultry/finance routers omit trailing slashes, except the poultry collection is `P/`. The administration router uses trailing slashes. Never redirect a mobile POST to correct its slash.

Method groups used below expand exactly as follows:

- `CR`: collection GET/POST; detail GET.
- `CRU`: collection GET/POST; detail GET/PUT/PATCH.
- `CRUD`: collection GET/POST; detail GET/PUT/PATCH/DELETE.
- `R`: collection and detail GET.

`AUTH` currently means any authenticated account. `FR/FW/FM/FC/OWNER/ADMIN` are the source-defined role groups in [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md); safe reads normally use FR and writes FW unless noted. Default DRF pagination and filter backends are **not configured**. A `filterset_fields` attribute alone does not implement filtering. Plain ModelViewSet routes are exposed even where deletion or direct update is inappropriate for a mobile workflow.

Reuse classifications: **reuse** means the named service is a useful domain boundary but still needs mobile authorization, receipt/hash and stream wrapping; **extract** means a view/serializer directly writes or a composite lacks an outer transaction; **gate** means financial/permission/dated-invariant work must pass before enabling the command. Every proposed mobile command is currently unavailable.

## Authentication and account API

| Existing route / methods | Permission and current behavior | Mobile use / phase |
|---|---|---|
| `POST A/login` | Public; FarmTokenObtainPairSerializer; username/password, JWT pair and user summary | Initial login; device-bound token exchange added in 2; UI 3 |
| `POST A/refresh` | Public token possession; rotating refresh/blacklist | Extend device-bound validation in 2; serialize refresh in 3–4 |
| `POST A/verify` | Public token possession; signature/expiry | Verification is not current capability/device authorization |
| `GET A/me` | AUTH; CurrentUserSerializer | Own identity; no bulk user replication |
| `POST A/logout` | Public refresh-token blacklist; 204 | Online logout, preserve original user's locked outbox; 3–4 |
| `A/administration/users/` CRU | ADMIN; SystemUserSerializer; create/update are atomic with AccountAuditEvent; user UUID; no pagination | Online `accounts.user.create/update`; 8 |
| `GET A/administration/users/{id}/history/` | ADMIN; audit events, unbounded list | Online audit history; 8 |
| `POST A/administration/users/{id}/reset-password/` | ADMIN; atomic password set + audit; `temporary_password` min 8; no email invitation service | Online `accounts.user.reset_password`; 8. Keep credentials out of sync payload logs |
| `GET /api/v1/schema/`, `GET /api/v1/docs/` | Public schema/docs; annotation gaps logged in baseline | Phase 2 explicitly annotates the new API, not a generated guess |

JWT: 15-minute access, 7-day refresh, rotation/blacklist enabled, `UPDATE_LAST_LOGIN=False`. Current `JWTAuthentication` has no device registry or mobile token claims. User.roles is a many-to-many table; employee association is optional. The REST last-admin safeguard counts active admins but is not serialized across concurrent demotions; employee routes can also mutate linked accounts. These are implementation prerequisites for administration, not proof of complete controls.

## Poultry API

All actions below currently use AUTH, except forecast assumptions. They do not enforce operational roles or batch assignments. GET child lists are unpaginated.

| Route / methods | Service / transaction / effects | Proposed mobile action, mode, phase |
|---|---|---|
| `P/` GET/POST, `P/{id}` GET | BatchSerializer direct save, then `recalculate_batch_status`; create has no encompassing atomic wrapper; Batch.save allocates human reference in a nested atomic sequence operation | `poultry.batch.book`; pending capture after extraction; 5 |
| `GET P/dashboard` | `poultry.services.dashboard.poultry_dashboard`; computed flock/feed/growth indicators | Cached dated operational summary; 8 |
| `POST P/{id}/mark-delivered` | Direct Batch save; no row lock/outer atomic | `poultry.batch.mark_delivered`; pending capture, revision/chronology checks; 5 |
| `POST P/{id}/confirm-delivery` | Direct Batch save then status recalculation; entry/maturity timestamps, quantity | `poultry.batch.confirm_delivery`; pending capture; extract locked service; 5 |
| `PATCH P/{id}/forecast-assumptions` | FinancePermission FW; direct serializer update, financial forecast fields | `poultry.batch.set_forecast`; online, expected revision; 8 |
| `P/{id}/mortality` GET/POST | `create_mortality_with_lifecycle`; atomic Batch lock, Mortality create, non-negative total check, status save and **bulk FeedUsage population updates**; no journal | `poultry.mortality.record`; first pending command in 2/4 |
| `P/{id}/feed_usage` GET/POST | `record_feed_usage`; atomic Batch lock and dated flock check; integer source quantity; no inventory issue or journal | `poultry.feed.record`; pending, stock-linked composite needs new boundary; 5/6 |
| `GET P/{id}/feed-metrics` | `feed_summary`, calculated denominators and quantities | Downloaded summary or full dated event pack; 5/8 |
| `GET P/{id}/sell-by-recommendation` | `sell_by_recommendation`, price/feed evidence with missing-input status | Finance projection only; current AUTH exposes price/cost information; 8 |
| `POST P/{id}/recalculate-feed-metrics` | `recalculate_feed_event_populations`; per-row QuerySet.update, no top-level atomic/stream boundary | Online supervisor+ maintenance command; 5 |
| `P/{id}/flock-adjustments` GET/POST | `create_flock_adjustment`; atomic Batch lock, approved adjustment immediately; current endpoint treats any authenticated actor as approver | Offline **proposal**, online supervisor+ approval; `poultry.flock.adjust`; 5 |
| `P/{id}/drugs_vaccine` GET/POST | Direct serializer save after current lifecycle check; no atomic lock/stock link | `poultry.treatment.record`; extract; pending capture; 5/6 |
| `P/{id}/weight_samples` GET/POST | Direct serializer save after lifecycle check; GET returns samples plus growth series/status/strain | `poultry.weight.record`; extract; pending capture; 5 |
| `P/{id}/sales` GET/POST | `create_sale_with_lifecycle`; atomic Batch lock, Sales+SaleSellingCost[], initial SalePayment, source creation and feed recalculation; no sale/receipt `post_journal` call in this service chain | `poultry.sale.record`; one sale+costs+initial receipt composite; finance writer capability, gated; 6 |
| `P/{id}/input_costs` GET/POST | `create_batch_cost_transaction`; expenditure/posting/funding/cost projection boundary; existing wrapper allows specified closed-batch corrections in an open period; AUTH is too broad | `finance.batch_cost.record`; pending evidence; gate finance permission, date locks and once-only projection; 6 |
| `GET P/{id}/feed_input_costs` | Filtered `batch_cost_records`, no separate financial event | Authorized cached cost read, not worker pack; 6 |

MortalitySerializer currently accepts client `age_in_days` and requires `reported_by_name`; the design example originally omitted both. The mobile contract now derives age and includes the reporter. Lifecycle creation checks total flock but does not alone prove every later dated balance/closed-period invariant; Phase 2 adds these checks before enabling mortality.

## Finance registers and actions

All base/detail method groups are exact router exposures; a detail `DELETE` in this table is an inherited route, **not** permission to delete a posted record in mobile.

| Register / base methods | Permission / service and boundary | Cash, cost, journal effect / mobile phase |
|---|---|---|
| `F/employees` CRU; POST `{id}/activate`, `/deactivate` | FR/FW; EmployeeProfileSerializer atomic create/update; activation views directly save profile and optional User | No money event; proposed profile edits online, 7. Remove account/role fields from mobile employee adapter |
| `F/salary-adjustments` CR; filter `employee` | FR/FW; `record_salary_adjustment` atomic employee lock; effective **accounting period**, not arbitrary mid-month date | Updates future base rate; preserves generated payroll; online managerial command, 7 |
| `F/accounting-periods` CRUD | FR/FW generic serializer; status/reopen metadata writable on generic routes | Unsafe generic status route for mobile; use explicit online close/reopen, 8 |
| POST `F/accounting-periods/{id}/generate-payroll` | FM; `generate_payroll_for_period` atomic get-or-create, salary snapshots + payable/expenditure + deduction liability | Generation is not payment; GL coverage must be proven; online 7 |
| POST `{period}/recalculate` | FM; `regenerate_allocations_for_period`, deletes/rebuilds unlocked allocations and bird-day snapshots | Reporting allocations; no second source expense; online 8 |
| POST `{period}/close`, `/reopen` | FC; outer atomic; status/save, bulk locks/unlocks, Batch finalization updates and report snapshots | Locked report versions; need row locking, idempotency and all-writer coverage; online 8 |
| POST `{period}/generate-depreciation`, `/allocate-depreciation` | FM; depreciation/allocation services; second combines calls without a view-wide transaction | Asset cost recognition, not cash; online 7–8, gate journal/replay coverage |
| `F/payroll-entries` CRUD; POST `{id}/allocate-costs`, `/record-payment`, `/reverse-payment` | FR/FW; create/update serializer then deduction liability/salary expense; explicit allocation/payment services atomic | PayrollPayment + funding split + compatibility summaries; `advance`/`salary` share salary liability; online 7. Generic create/update needs outer atomic; no separate payroll-approval endpoint |
| `F/ad-hoc-labour` CRUD; POST `{id}/approve`, `/post`, `/pay`, `/reverse` | FR/FW including approvals/reversals today; `labour` services atomic with row locks | Post creates one expenditure/payable+journal; pay uses expenditure funding; pending draft/evidence, online approval/post/reverse, 7 |
| `F/work-logs` CRUD | FR/FW; direct serializer writes | Operational time evidence, no payment; worker-specific projection/authorization requires explicit Phase 7 adapter; pending 7 |
| `F/expenses` CRUD | FR/FW; save then `project_shared_expense`; no encompassing view atomic | Compatibility source + expenditure projection; never post both as expenses; pending capture after gated composite, 6 |
| `F/expenditures` CRUD | FR/FW; drafts only update/delete guard; collection pagination 10 default, max 100; manual `search/status/payment_status` filtering | Draft itself no confirmed cash; `finance.expenditure.create/update`, 6 |
| POST `F/expenditures/{id}/post` | FW; owner-source use restricted OWNER; `post_expenditure` atomic, cost/funding rows and derived poultry projection | Cash funding + beneficiary cost; no direct GL call in ordinary post boundary; gate before mobile posting, 6 |
| POST `{expenditure}/record-payment`, `/assign-funding` | FW, OWNER if using owner cash; `record_expenditure_payment` atomic | Dated FundingAllocation split; historical assignment distinct from source cost; pending permitted payments after concurrency/date tests, 6 |
| POST `{expenditure}/void` | FW, OWNER for protected source; `reverse_expenditure` atomic | Controlled reversal/replacement; online 6 |
| GET `F/expenditures/payables`, `/reconciliation-report` | FR; custom unpaginated result rather than list paginator | Cached authoritative liabilities/exceptions with coverage; 6/8 |
| `F/funding-sources` CRUD | FR/FW; OWNER for owner source; source list custom pagination 20 default/max 100, balances calculated before page; `search/source_type/batch/include_empty` | Cash source dimension, not beneficiary; masters online, read snapshot 6 |
| `F/funding-receipts` CR; POST `{id}/reverse` | FR/FW; source visibility excludes owner for non-OWNER; generic save for non-owner; reversal uses atomic `reverse_funding_receipt` | Cash-in; batch sources forbidden here, owner receipts require owner workflow; pending non-owner evidence after gate, 6 |
| `F/owners` CRU | OWNER on reads/writes; atomic user-independent identity changes + FinanceActionEvent | No cash; online master action 6/8 |
| POST `F/owner-contributions` | OWNER; atomic `record_owner_contribution`, fingerprint/idempotency | Exactly one FundingReceipt; designation does not add cash; pending capture after gate, 6 |
| `F/owner-designations` R; POST `for-receipt/{receipt_id}`, `{id}/reverse` | OWNER; atomic owner designation services | Intended use, no cost/cash; online controlled revision/action 6 |
| `F/action-events` R | OWNER; pagination 20/max 100 | Immutable privileged audit; online 8 |
| `F/consumable-items`, `F/inventory-locations` CRUD | FR/FW; direct serializer masters; UnitConversion exists in models but has no dedicated REST/editor workflow | Online masters; conversion management is a named Phase 6 prerequisite, not an existing endpoint; pending receipt/issue reference cached lookups, 6 |
| `F/consumable-lots` CRUD | FR/FW; **create** atomic `record_consumable_receipt`; update/delete inherited generic | Receipt adds StockMovement + inventory/payable journal; does not itself establish full supplier cash/payment boundary; gate financial lifecycle, 6 |
| `F/consumable-usages` CR | FR/FW; atomic `record_consumable_usage` with lot lock, period check | Issue decreases lot, one movement/journal and batch/admin cost; pending, 6 |
| `F/stock-movements` R | FR; unpaginated; filterset declaration inactive without backend | Immutable stock read, 6. Only receipt/issue services exist; returns/transfers/waste/expiry/adjustment handlers missing |
| `F/prepaid-recognition` CRUD | FR/FW; direct serializer with open-period validation | Recognition not new cash; online controlled recognition, 6/8 |
| `F/asset-categories` CRUD | FR/FW; direct master writes | Online master 7 |
| `F/assets` CRUD; POST `from-expense` | FR/FW; from-expense FM; direct asset save followed by lifecycle/link service, no outer view transaction | Capitalized cost not operating expense; online acquisition/correction, gate source/journal completeness, 7 |
| `F/assets/{id}/usage`, `/maintenance`, `/replacement-plan`, `/reserve-transactions` GET/POST | FR/FW; direct serializers; replacement-plan upsert | Usage/notes offline evidence; maintenance cost must link one expenditure; plan/reserve online financial action, 7 |
| POST `F/assets/{id}/impair`, `/dispose`, `/transfer` | Impair/dispose FM; transfer FW; atomic services, but no `post_journal` call for impairment/disposal | Financial adjustment + event; period/locking/journal/idempotency gates; online 7 |
| GET `F/assets/{id}/history`, `/depreciation-schedule`, `/recovery` | FR; unbounded event lists, calculated recovery | Cached dated detail; 7–8 |
| `F/asset-usage` CRUD | FR/FW; direct serializer | Evidence needs service/revision/period lock; pending create only, 7 |
| `F/asset-depreciation` R | FR; service-generated values | Cached dated history; online generation only, 7 |
| `F/reserve-transactions` CRUD | FR/FW; direct serializer | Reserve is not automatically a bank transfer/cash event; gate semantics, online 7 |
| `F/bird-day-snapshots`, `F/allocations`, `F/expenditure-categories` R | FR; computed/read-only; no pagination | Download authorized report/reference projections; 6/8 |

## Finance reports and receipts

| Exact route / methods | Domain service / shape | Mobile contract |
|---|---|---|
| `GET F/reports/monthly` | `resolve_period`, `monthly_profitability_report`; period selector; report snapshot/open provisional | Authorized dated report cache, 8 |
| `GET F/reports/batches`, `GET F/reports/batches/{batch_id}` | `batch_portfolio_report` / `batch_profitability`; repeated `batch` IDs; stored allocation denominator preserved | Dated server authority, selection/coverage; 8 |
| `GET F/dashboard` | `dashboard_indicators`; FR, not general-worker dashboard | Role-projected dated finance indicators; 8 |
| `GET F/receivables` | `receivables_report`, manual bounded pagination | Cached open receivable pack; 6 |
| `GET/POST F/receivables/{sale_id}/payments` | List unpaginated; `record_sale_payment` atomic sale lock, dated SalePayment and Sales summary update; same key checks sale but **not full amount/date payload** | `finance.sale_receipt.record`; durable full-hash adapter needed; pending, 6 |
| `POST F/payments/{payment_id}/reverse` | `reverse_sale_payment`; sale/source locks, cash-consumed check, ledger status/summary | Online `finance.sale_receipt.reverse`; 6 |
| `GET F/reports/revenue-utilization` | Aggregated batch-page response; search/order/size; service computes batch sums | Cached summary pages with total coverage, 8 |
| `GET F/reports/batches/{batch_id}/revenue-utilization` | Transactions materialized then paginated: page 20/max100, `transaction_page` metadata | Paginate drill-down separately, not whole history in summary; 8 |
| `GET F/reports/cross-batch-financing` | Aggregated source/cost bearer report, paginated nested details | Never interpret funding batch as cost bearer, 8 |
| `GET F/reports/batch-funding-mix`, `GET F/reports/batches/{batch_id}/funding-mix` | Funding reports; list uses manual page response | Preserve source visibility and pending-vs-confirmed distinction, 8 |
| `GET F/reports/owner-contributions` | OWNER; nested batch/receipt/timeline pages; export mode; **GET appends FinanceActionEvent** | Private report cache, 8; snapshot uses pure report service; read-audit is explicit, not a business replica mutation |

Retained legacy API, outside active mobile UI: `F/customers` CRU + POST `{id}/review`; `F/customer-cost-attributions` CR + POST `{id}/reverse`; GET `customer-cost-sources`, `customer-unlinked-sales`, `reports/customer-contributions`; POST `customer-sale-links/{sale_id}`. FR/FW; customer-contribution services have their own fingerprint/atomic boundaries. Preserve these endpoints/data, but do not add obsolete customer screens. The baseline's date-sensitive failed test belongs here.

## IDs, exact values and dates

User.id is UUID; Asset.id is UUID. The generated model-field inventory records every other PK rather than assuming all finance identifiers are UUIDs. Batch/Mortality/FeedUsage/Sales are integer PKs. Existing batch/sale/expense/receipt display references are server sequences; never create their official form on a phone. The selected sync identity is **SyncEntity mapping**, detailed in the finalized contract.

DRF model DecimalFields normally render strings. Some report responses use `json_safe`; poultry feed summaries return Decimal through Response without that conversion, which DRF's JSON encoder can render as numbers. The sync projection must explicitly stringify decimal values and server-PK text. Money scale is 2; quantity/rate scales come from the model/command schema, never binary float. Existing UTC settings remain. Batch entry/maturity, mortality, sale, sale-payment, funding-receipt and feeding events use DateTimeFields. Batch booking/estimated arrival and accounting-period/expense/payroll/inventory/asset dates use DateFields where recorded by the model inventory. Mobile captures farm local intent and explicit UTC instants, not a global timezone rewrite.

## Phase 2 published set and complete writer checklist

Phase 2 publishes only `poultry.batch`, `poultry.mortality`, and `poultry.feed_usage` operational projections. Batch includes authoritative aggregate flock counts and cutoff; sales and adjustments remain **server-side dependency sources**, not price-bearing worker replicas. All financial payloads/commands remain disabled. This set is intentionally larger than one Mortality row because the reused mortality service also changes batch status and feed-population fields.

| Entity/dependency | Current writer paths | Required Phase 2 coverage before enablement |
|---|---|---|
| Batch fields / display IDs | REST create, mark/confirm delivery, forecast PATCH; Batch.save/next_batch_id; `recalculate_batch_status`; lifecycle sale/mortality; `profitability.create_final_snapshot`; period close/reopen QuerySet.update | Acquire stream before domain locks in shared service boundary; publish allowed Batch projection and membership in same transaction; protected financial fields never serialized |
| Batch derived flock counts | Mortality create/edit/delete; Sales create/edit/delete/cancel/status summary; FlockAdjustment creation/reversal; arrival/quantity edits | Refresh Batch projection even when Batch.status does not change. SalesAdmin and related service calls count as writers; do not subscribe only to Batch.save |
| Mortality | `create_mortality_with_lifecycle`; MortalityAdmin create/change/delete; direct ORM/test fixtures; batch cascade deletion | Stream-aware model/service mutation guard; route admin writes/deletions through validated boundary, immutable tombstone on supported removal; direct unsafe bulk updates forbidden |
| FeedUsage | `record_feed_usage`; `recalculate_feed_event_populations` QuerySet.update from mortality/sale/flock/recalculate REST; FeedUsageAdmin changes/deletes; Batch cascade | Replace covered bulk update path with explicit locked publication; one transaction group includes all recalculated rows; prevent untracked bulk operations |
| Related admin/cascade | BatchAdmin, SalesAdmin, MortalityAdmin, FeedUsageAdmin; default ModelAdmin save/delete/bulk delete; not service-aware today | Cover save_model/delete_model/delete_queryset and inline/cascade behavior; block unsupported bypasses rather than declaring coverage from signals |
| Period close/finalization | finance views bulk Batch `profitability_finalized_at` writes; profitability final snapshot saves | Stream-before-domain transaction around these writers even while their finance data is not replicated; avoid lock inversion |
| Account/role visibility | SystemUserViewSet, EmployeeProfileSerializer create/update roles/link, employee activate/deactivate, UserAdmin, RoleAdmin, user.roles M2M | Current capability recheck each request and deterministic scope hash; reject old cursors on scope change; prevent worker finance/account escalation on affected paths |
| Commands / imports / scripts | Finance audit/preflight read only; snapshot_closed_period_reports, reconciliation/backfill commands write other models and may call finalization; `integrations/`, docs review scripts; historical RunPython migrations | Inspect touched entity/service dependencies before enabling. Historical migrations seed identity afterward; future controlled imports reset epoch. No poultry mutation management command or runtime signal receiver found in source search |
| Privileged raw SQL | Database operator/manual edits cannot be intercepted by Django signals | Explicit maintenance mode + reseed/epoch reset, outside normal sync guarantee |

For later phases the same checklist extends to every registered finance/inventory/people/asset model. Known bulk paths: allocations deletes/rebuilds; ledger JournalLine.bulk_create and reversal update; PayrollPaymentFunding.bulk_create; SalaryPayment/Expenditure summary QuerySet.update; OwnerReceiptDesignation reversal update; period lock/unlock QuerySet.update. Default finance admin bypasses many service boundaries. Receipt tables, stream changes and accounting effects must share a single outer transaction.

## Reuse blockers and precise next action

| Finding | Required gate | Phase |
|---|---|---|
| Broad poultry AUTH permits stakeholder/worker sales, costs and approvals; employee serializer accepts role/account fields for finance writers | Central capability + explicit field allowlists across affected ordinary REST and sync; no new real-user grants | 2, 7–8 |
| Mortality lifecycle validates total balance; FeedUsage recalculation clamps dated negative balance to zero | Validate event chronology and every affected dated flock balance before commit; return review conflict, never clamp invalid history as acceptance | 2 |
| Several generic finance writes, approvals and deletes lack precise action controls | Keep corresponding mobile commands unavailable until service/replay/period gates pass | 6–8 |
| Sale/receipt/expenditure/payroll/asset posting paths do not all create GL journals today; local GL has zero journals | Financial workflows need targeted posting completeness proof. Historical backfill remains a separate approved activity | 6–8 |
| Inventory enum has more movement types than implemented handlers; feed/treatment are not integrated with stock issues | Add typed tested movement/composite services before offering those actions | 5–6 |
| Salary adjusts by period, no arbitrary effective-date compensation/proration or explicit approval state | Reuse verified period workflow; broader policy is a named prerequisite, not invented UI | 7 |
| OpenAPI has missing response/request annotations, ambiguous enums and operation IDs | Add explicit new sync schemas; extend affected existing annotations before client generation | 2 onward |

Feature/command phase coverage is in [FEATURE_TRACEABILITY.md](FEATURE_TRACEABILITY.md), command schemas in [COMMAND_CATALOG.md](COMMAND_CATALOG.md), and baseline evidence/known failures in [the Phase 1 checkpoint](checkpoints/PHASE_01.md).
