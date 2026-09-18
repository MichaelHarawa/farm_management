# Codex implementation prompt: extend Farm Management finance

Implement the selected phase below in this existing Farm Management repository. Complete that phase's backend, UI, migrations, tests and documentation. Do not rebuild the application or add parallel versions of capabilities that already exist. Use `docs/CODEX_FINANCE_PHASE_PROMPTS.md` for the phase launch prompts; this document is the shared specification, not a requirement to implement every phase in a single task. If no phase is selected, implement Phase 1 from that guide.

This prompt supersedes the generic Profit First proposal. Inspect the current checkout first: the reference points below were reviewed on 18 September 2026 and may evolve. Read `AGENTS.md` instructions, including `frontend/AGENTS.md`, and the relevant bundled Next.js guides before changing frontend code. Preserve unrelated working-tree changes and artifacts, including `backend.zip`.

## 1. Repository baseline and boundaries

- Backend: Django 6.0.6, Django REST Framework 3.17.1, PostgreSQL, JWT authentication. Follow existing model/serializer/view/service conventions and migrations.
- Frontend: Next.js 16.2.10 App Router, React 19.2.4, TypeScript, Tailwind 4, React Hook Form and Zod. Reuse server-fetch helpers, client API helpers, authenticated BFF proxies, shared UI and styling.
- Review `docs/PROFIT_FIRST_SCOPE_REVIEW.md`, `docs/FINANCE_ARCHITECTURE.md`, `docs/FINANCE_DATA_MIGRATION.md` and finance tests. Verify implementation rather than assuming all documented posting templates are wired.
- Finance is currently farm-wide, not multi-tenant. Add farm-level settings using an enforced single configuration scope. Reuse authenticated roles and backend permissions. Do not introduce partial tenant fields or claim organization isolation.
- Current operating currency is MWK; USD reference fields are purchasing-power references, not a multi-currency ledger. Retain that behavior. Display currency explicitly and reject unsupported settlement currencies. Do not relabel historical MWK values through an editable currency selector.
- Do not activate or backfill the historical general ledger automatically. Keep dry-run reconciliation and existing opening-balance controls.
- This is cash management alongside existing management accounting. It must not change the definition of accounting profit, tax expense, production cost or sales revenue.

Before editing, produce a brief implemented/partial/missing matrix and integration plan for the selected phase. Then continue implementing; do not stop at the plan. Work in the dependency order in the phase guide. The full scope remains the roadmap; complete and verify the selected phase, then stop at its review checkpoint. Do not silently implement subsequent phases or report them as delivered.

## 2. Reuse rules: prevent duplication

Use these existing sources of truth:

- `Sales` and `SalePayment` for sales and customer receipts; `services/collections.py` for payment/reversal behavior.
- `FundingSource`, `FundingReceipt` and `FundingAllocation` for funding origins, non-sales receipts, and expenditure funding.
- `Expenditure`, linked `InputCosts`, payroll, labour, shared expenses, inventory recognition and assets for cost records. Preserve existing deduplication and recognition rules.
- `CostAllocation` for attribution of costs to poultry batches; existing shared-cost drivers and allocation policies remain authoritative.
- `ChartOfAccount`, `CashOrBankAccount`, `JournalEntry`, `JournalLine` and `services/ledger.py` for applicable accounting events.
- `AccountingPeriod`, `BatchProfitabilitySnapshot` and `PeriodReportSnapshot` for locks and historical results.
- Existing Finance reports, warnings, navigation, `Dialog`, `DataTable` and formatting helpers.

Keep four concepts separate: funding origin, beneficiary cost allocation, Profit First cash earmarking, and accounting journal posting. Call the new workflow an **allocation run** in code and UI to distinguish it from a poultry production batch. Do not overload `CostAllocation`, `FundingAllocation` or `AllocationPolicy` with incompatible meanings.

Do not create duplicate sales, income receipts, expenses, payroll entries, cash balances or customer-payment history. New supporting models may reference existing records and store classifications, allocation consumption, cash movements, approvals and immutable snapshots.

## 3. Phase A: survival cost, payment details and owner contributions

### A1. Cost per survived bird

Extend the existing backend profitability calculation and its portfolio/detail/UI contracts:

`survived_birds = valid_bird_units_sold + remaining_live_birds`

`cost_per_survived_bird = total_production_cost / survived_birds`

- Reuse `calculate_bird_balance()` and `_build_batch_profitability()`; the existing `provisional_saleable_birds` and `provisional_cost_per_saleable_bird` already implement this basis for valid balances. Preserve old fields for compatibility and use one calculation, not a second competing formula.
- Count valid live/dressed bird sales only; cancelled sales and non-bird products do not enter the denominator. Honor actual quantity received, approved flock adjustments, mortality and existing lifecycle rules.
- Sold birds remain in this denominator. Do not use remaining live birds alone or booked quantity minus deaths without reconciling adjustments.
- Numerator is existing direct plus allocated production cost. Do not silently substitute total cash spending or fully loaded management cost. Retain other cost, final cost-per-sold-bird and break-even metrics separately.
- Zero survivors and pre-production batches display N/A, not zero/infinity. Flag invalid negative balances rather than hiding errors through the new metric.
- Active batches are provisional. For closed batches derive from the applicable immutable snapshot; extend future snapshot payloads if needed. Do not recalculate old final totals using today's costs.
- Portfolio metric is sum of eligible production costs divided by sum of eligible survivors, never an average of per-batch ratios. Show numerator, denominator and definition in contextual help on batch detail and Finance batch reports.
- Review the existing `survivalPercent` display, which currently uses remaining birds against original quantity; avoid presenting sales depletion as mortality. Keep remaining availability separately labelled if that value is still useful.

Acceptance example: 1,000 received, 50 deaths, 600 sold and 350 remaining gives 950 survivors. Production cost MWK 1,900,000 gives MWK 2,000 per survived bird. Selling the remaining 350 without further losses must not change the denominator.

### A2. Click a payment-history entry to show details

- Start with `frontend/src/app/finance/receivables/page.tsx`, expenditure detail at `frontend/src/app/finance/expenditures/[id]/page.tsx`, and `PayrollLedgerManager.tsx`.
- Reuse the shared `Dialog` and add a reusable typed payment-details component. Clicking a single history row/entry opens that payment's read-only details. Also provide a keyboard-accessible details button; avoid nested interactive controls.
- Display available identifiers, source sale/expenditure/payroll link, buyer/payee, poultry batch or beneficiaries, amount/currency, payment date, method, external reference, recorded/received by, notes, created timestamp, status and reversal details. Use N/A for fields not captured; do not fabricate metadata.
- For expenditure payments split across funding sources, use the existing `payment_group_key` to show the relevant payment's source lines and reconciled total. Handle legacy rows without a grouping key without merging unrelated payments. Do not count payroll-linked expenditure payments twice.
- Add a backend detail endpoint only if existing authorized response data is insufficient. Fetch by record identity with server-side permissions; do not expose salary or owner information through a generic endpoint.
- Preserve record-payment and reversal actions. Row clicks must not trigger reversal. Isolate nested button events. Include focus trapping/restoration, Escape/close, labelled headings, small-screen scrolling, loading and error states.

### A3. Owner contributions by batch and cumulatively across batches

Extend `FundingSourceType.OWNER_CAPITAL`, `FundingReceipt`, and `batch_expenditure_funding_mix()` rather than creating another cash-entry ledger.

- Add stable owner/contributor identity only as needed, referenced from owner-capital sources or receipts. An owner need not be a login user. Preserve existing descriptions and allow legacy owner identity to remain explicitly unknown; never infer ownership percentages from contributions.
- Show separately: owner cash introduced, amount assigned/designated to each batch, owner cash actually used for batch expenditures, remaining owner-source cash, owner withdrawals/returns, and net contributed capital where reliably known.
- For direct batch designation, use receipt-to-batch attribution rows referencing the existing receipt. Multiple batch shares plus unassigned amount must reconcile exactly to the receipt. Attribution does not create cash, recognize an expense, or mean the funds were spent.
- For actual batch use, extend the existing funding-mix join of owner-capital funding rows to expenditure cost shares. Use a deterministic cent-remainder rule across all beneficiaries before filtering, so a shared payment is not overstated or understated through independent rounding.
- Expose owner capital separately from the current `other_sources` umbrella without breaking existing response fields. Reuse existing funding-mix/revenue-usage pages and batch details where possible.
- Provide date range, owner and batch filters; per-batch totals; full filtered totals independent of pagination; and an ordered cumulative timeline with opening balance, period movements and closing balance. Use receipt date for cash introduced and payment date for cash used; explain the difference.
- Cumulative cash introduced counts each receipt once. Batch designations and actual spending are alternative views of that same cash, not additional contributions. Show unassigned and farm-wide use explicitly.
- Respect reversals, refund/return metadata and period cutoffs. Do not infer return of capital from every owner distribution: distinguish return of capital, drawings/compensation and profit distribution explicitly.
- Owner capital is equity funding, not sales revenue, Profit First eligible income, Owner's Pay, or a production expense. Do not derive capital balance as the negative of batch profit.

Acceptance example: one owner receipt of MWK 1,000,000 assigned 600,000 to batch A and 400,000 to batch B yields 1,000,000 cumulative contributions. If only 300,000 and 200,000 have been spent, show 500,000 used and 500,000 remaining; never show 2,000,000 introduced or treat all designated cash as spent.

## 4. Phase B: customer contribution

Implement this exact formula, superseding the extra standalone subcontractor deduction in the original proposal:

`Customer Contribution = Revenue - Direct Delivery Cost - Support Cost - Rework Cost - Acquisition Cost`

- Introduce a minimal stable customer model and nullable `Sales.customer` link if still absent. Keep `buyer_name`, buyer type and existing sale forms/APIs compatible. Provide explicit linking/review for historical sales; matching names alone must not automatically merge people or organizations. Preserve source identity/history through customer deactivation or controlled merges.
- Use recognized valid sales revenue for the selected customer and period; separately display cash collected and receivables. Do not use receipts as revenue in this report.
- Define the four cost buckets visibly. Direct Delivery Cost includes attributable production/product fulfillment and delivery/subcontractor costs. Support, Rework and Acquisition costs are distinct. Assign each cost share to one bucket only.
- Add source-linked attribution rows for recognized costs from existing expenditures, cost allocations, payroll/labour or other valid cost sources. Track amount, category, customer/sale/batch, date/period, basis, estimated/actual status, actor and reason. Cap attribution across customers at the available recognized source amount; prevent duplicate recognition across linked representations of the same cost.
- If exact attribution is unavailable, allow documented estimates/manual analytical allocations without manufacturing expense/payment records. Show estimates and unattributed cost coverage. Missing classifications are not automatically zero.
- Allocate batch production cost to sold units using the existing cost-per-saleable/survived-bird basis where appropriate; retain the share belonging to unsold birds. Document treatment of non-bird products and avoid adding the same production cost again through expenditure attribution.
- Show customer contribution amount, margin (N/A for zero revenue), breakdown, coverage, actual/estimated status, customer concentration and product-type breakdown. Product reporting must use existing poultry product types rather than invent service/project/timesheet modules.
- Support IDEAL, HEALTHY, REVIEW, UNPROFITABLE and STRATEGIC_EXCEPTION labels, notes and review actions. No automated customer termination. Provide drill-down and CSV export.

Acceptance example: revenue 1,000,000 minus delivery 600,000, support 50,000, rework 20,000 and acquisition 30,000 equals contribution 300,000 and margin 30%. A subcontractor cost included in the 600,000 is not subtracted again.

## 5. Phase C: Profit First core

### Configuration and cash buckets

- Add disabled-by-default farm-level settings with effective-dated immutable versions, allocation frequency/days, current and target percentages, optional fixed allocations, reserve averaging/target months, distribution and debt-repayment settings, approval policy and deterministic rounding policy.
- Support manual, weekly, fortnightly, twice monthly and monthly runs. Twice-monthly defaults may be 10th/25th. Document timezone, short-month and weekend behavior; do not assume an external holiday calendar exists.
- Core buckets: Income, Profit, Owner's Pay, Tax, Operating Expenses. Optional buckets: Materials, Subcontractors, Payroll, Sales Tax, Pass-through, Stocking, Major Equipment, Drip, Petty Cash, Emergency Reserve, Debt Repayment and Custom.
- Distinguish virtual cash buckets from physical cash/bank accounts and chart accounts. Reuse optional references to `CashOrBankAccount` and `ChartOfAccount`; do not store bank credentials. Balances must derive from an append-only movement ledger, with any cache reconciled transactionally.
- Store active/protected status, withdrawal approval, ordering and definitions. Source/funding provenance must remain traceable when cash is split across buckets.
- Avoid overlapping controls: tax percentage, reserve percentage and debt percentage must map to the appropriate allocation/distribution rule, not be applied twice.
- Provide onboarding/settings with a live server-calculated preview. Percentage allocations total 100% of their documented basis. For fixed allocations, subtract valid fixed amounts first and apply percentages to the remainder; prevent over-allocation and explain the sequence. Preserve input on validation errors.

### Eligible cash and Real Revenue

- Derive allocation candidates from posted `SalePayment` rows. Keep partial receipts separate; never allocate a whole unpaid sale. Other trading receipts are eligible only with explicit classification; owner capital, borrowing and internal transfers are excluded.
- Add source-linked classification for materials, subcontractors, sales tax, pass-through and deferred amounts without copying the original receipt into a second authoritative ledger.
- Show `Real Revenue = collected trading receipts - materials - subcontractors - sales tax - pass-through`, and a separate bridge for deferred cash excluded now and previously deferred cash released now. Each monetary slice belongs to one category only; the bridge must reconcile exactly.
- Do not automatically classify all poultry feed/chick purchases as Real Revenue deductions merely because they are production costs. Require an explicit, documented policy and avoid subtracting costs twice.
- Store allocation consumption at receipt/release-slice level with constraints preventing duplicate or excessive consumption. Classifications cannot exceed source cash. Unclassified historical items remain visible in a review queue.
- Cash already spent before enabling this feature is not available for allocation again. Establish a documented cutover, reconcile opening earmarked/unallocated balances to existing available funds, and exclude historical receipts already represented by the opening balance. Reject allocation that exceeds available unreserved cash, even when nominal eligible receipts are larger.

### Allocation runs and spending

- Persist period/date, source slices, effective configuration snapshot, gross cash, deductions, Real Revenue, lines, rounding, approvals, posting/reversal metadata and notes.
- Use DRAFT → CALCULATED → PENDING_APPROVAL → APPROVED → POSTED, with documented paths when approval is disabled and a controlled REVERSED state. Reject invalid transitions; edits invalidate prior calculation/approval.
- Preview included/excluded records, basis, percentages/fixed amounts, per-bucket opening/movement/closing balances, reasons and exact reconciliation. Zero/negative available Real Revenue cannot create a positive allocation; display an explanatory state.
- Posting and reversal must be atomic and idempotent, with consistent row locking, database uniqueness and safe concurrent-request handling. Same key with different payload must fail. Do not rely on a frontend button disable.
- Earmarking funds does not create sales revenue, an expense or extra cash. Record a GL transfer only when a real, appropriately mapped accounting movement occurs; use existing posting services and avoid duplicating source journals.
- Integrate actual supplier, payroll, owner, tax, debt and other payments with bucket consumption. Preserve existing funding-source checks and additionally prevent bypassing protected earmarks through legacy payment endpoints once enabled. Transfers between buckets conserve total cash.
- Protect posted records. Reversals create linked compensating movements. Source-payment reversal must be blocked or coordinated atomically if funds have been allocated/spent; never silently release or strand reserved cash. Inactive buckets, insufficient funds and closed periods must reject invalid actions.

## 6. Phase D: planning and supporting workflows

### Deferred receipts / Drip

Create receipt-linked deferred schedules with delivery period, release frequency, scheduled/released/remaining balances and audited prospective changes. `ExpenseRecognitionSchedule` is for expenses and must not be reused as revenue recognition. Release only eligible slices once, with deterministic rounding and transactional due-work processing. A 120,000 receipt over twelve months releases 10,000 monthly, never 120,000 plus the releases. Distinguish allocation eligibility from formal revenue-recognition accounting. Cancellation/refund/reversal must reconcile cash, released funds and future schedules.

### Profit distributions and reserves

Add configurable distribution events with protected reserve, distribution/debt-retention split, approvals, linked payment records and a statement. Ownership-based splitting is allowed only with explicitly recorded ownership percentages; contribution history does not establish ownership. Prevent distributions beyond available approved cash and preserve retained reserve. Owner pay/distributions must not automatically become production expense.

Reuse asset replacement reserve concepts where applicable, but distinguish replacement funds from general emergency reserves. Calculate reserve months as protected eligible cash divided by average monthly essential operating expense over a stated period; zero denominator is N/A. Show target, gap, coverage, movement, emergency-use rules, approval and replenishment plan. A cash amount cannot count toward multiple protected reserve totals simultaneously.

### Debt

Extend loan funding with a creditor/loan register, terms, original/current principal, rates, minimum payment/frequency, due dates, security/guarantee/penalties, priority, status and debt-freeze flag. Link drawdowns and repayments to existing receipt/payment records. Separate principal from interest/fees; debt-service classification alone is not sufficient. Add repayment history and snowball/avalanche/custom-order comparisons with extra-payment simulation, payoff estimates and interest assumptions. Explain relevant terms and label projections as estimates; do not auto-execute suggested repayments.

### Expense review

Extend existing expense/expenditure metadata with essential/discretionary, recurring, revenue-generating/productivity and review classifications, customer attribution, action (KEEP/CANCEL/RENEGOTIATE/REPLACE/REVIEW/INVESTIGATE), notes and estimated/realized savings. Avoid a competing expense model. Reuse existing dates, categories and payment state. Show increases and duplicate candidates only from available evidence; no claims about unused subscriptions without usage data. Essential safety/compliance/security/staffing costs require contextual review, not automatic cancellation recommendations.

## 7. Dashboard, assessment, alerts, reports and access

- Integrate a Profit First workspace into existing Finance navigation. Retain existing cash/profitability/report screens and add contextual links instead of duplicate dashboards for the same metric.
- Dashboard: collected trading cash, Real Revenue, current/target allocation, balances by bucket, owner's pay, tax earmark, operating cash, reserve coverage, debt, existing overdue receivables, next allocation date, compliance rate, variances and contribution trends. Define all denominators and date bases.
- Instant Assessment: user-selected completed 12-month window, cash basis stated explicitly, deductions/Real Revenue, actual bucket allocations/withdrawals, targets, percentage-point/amount variance and review direction. Distinguish allocated Profit cash from accounting profit and paid tax from tax reserves. Incomplete data must show insufficient coverage, not manufactured actuals.
- Reuse existing chart patterns; no charting library is declared in the current frontend dependencies. Use accessible responsive graphics/tables and text labels instead of assuming a library is installed.
- Filters: dates, poultry batch, customer, bucket and owner where relevant. Do not expose nonfunctional organization/project/currency selectors.
- Alerts: invalid settings, overdue allocation, insufficient operating cash versus commitments, reserve shortfall, protected withdrawal, duplicate allocation, negative customer contribution, material recurring-cost changes, debt-freeze breaches, unsupported owner-pay levels, deferred-release mismatch and customer concentration. Compare tax reserve to liability only when a reliable entered/recorded liability exists. Thresholds and review links must be explicit; deduplicate alerts.
- Add reports for assessment, runs, bucket balances/movements, targets, distributions, tax reserves, expense review, reserves, debt, customer/product contribution, deferred releases, owner contributions and finance action history.
- Reuse CSV conventions with decimal strings, currency, timezone/date/period and basis. Exports must respect permissions, include all filtered records rather than only the loaded page, and mitigate spreadsheet formula injection in text cells. PDF/Excel are optional, not prerequisites.
- Reuse existing roles: admin, director, farm_manager, farm_supervisor, stake_holder, general_worker. Define an explicit operation/field permission matrix. Default sensitive owner identity/contributions/pay, protected distributions, settings, approval/posting/reversal and debt management to admin/director; broader access must be explicit. Do not blindly inherit existing finance SAFE_METHOD permissions for sensitive data. Enforce checks in APIs/services, summaries, exports and UI. Preserve existing access for unrelated reports.
- Add an append-only finance action audit stream with actor, time, entity, operation, before/after or version references and reason. The existing finance integrity report and account-administration audit table are not substitutes. Audit changes, approvals, reversals, attribution, protected access and scheduled releases without leaking secrets into logs.
- If no scheduler/notification service exists, implement idempotent Django management commands for due releases/reminders with dry-run and setup instructions, and in-app alerts. Do not add an unrelated worker stack or claim external notifications are enabled. No automatic posting, payments or distributions merely because an allocation date is due.
- Show the cash-management/professional-advice disclaimer in settings/onboarding and a contextual distribution warning. Do not hard-code tax rates or jurisdiction-specific legal assumptions.

## 8. Migration, correctness and performance

- Use additive migrations with dependencies based on the current graph. Preserve old field/API contracts, receipts, identifiers and snapshots. Test upgrades from pre-feature data as well as a clean database.
- Backfill only reliable mappings. Leave ambiguous owner/customer identities, historical cost classifications, opening balances and incomplete GL coverage explicitly unresolved for review. No fabricated opening money, seed transactions or automatic matching solely by name.
- Disable Profit First by default; existing finance flows must behave as before until activated. Once activated, all spending paths must respect cash controls. Define safe deactivation with outstanding earmarks/deferred schedules, not a switch that bypasses protections.
- Use Decimal arithmetic and decimal strings for financial API values. Frontend Number conversion is for presentation only; authoritative previews/totals come from backend calculations. Deterministic cent allocation must reconcile across the entire eligible set before filters/pagination.
- Respect period locks for financial changes and preserve economic dates plus reversal dates for historical reporting. Test as-of reports across later reversals; do not erase a historical receipt simply because its current status is reversed.
- Keep backend calculations canonical. Add relevant indexes, aggregation/prefetch, bounded pagination and authorized filtered exports; avoid N+1 batch/customer queries.
- Document rollback constraints for posted new records. Schema rollback must never silently delete financial history; provide backup/reconciliation and feature-disable procedures rather than promising unconditional destructive reversal.

## 9. Verification and completion criteria

Add meaningful tests following existing Django test patterns. Cover:

1. Survivor denominator, sold versus remaining birds, mortality, adjustments, non-bird/cancelled sales, zero survivors, weighted portfolio results, and final snapshots.
2. Receipt versus designated versus spent owner capital, split beneficiaries, exact rounding, unknown owners, cumulative opening/movement/closing totals, pagination/filter independence, withdrawal classification and reversals.
3. Customer identity, exact contribution formula, no double subcontractor/production-cost deduction, partial receipts not changing recognized revenue, missing/estimated costs and source-attribution caps.
4. Payment detail identity, funding groups, permissions, reverse-button isolation and keyboard/mobile behavior.
5. Real Revenue classifications, partial receipts, deferred releases, refunds/reversals, duplicate consumption, retrospective entries, cutover balances and unsupported currencies.
6. Current/target percentages, fixed-first rules, effective dates, rounding, invalid/zero/negative bases, run transitions, changed approval inputs and inactive buckets.
7. PostgreSQL concurrent posting/payment/release attempts, idempotency payload mismatch, insufficient/protected funds, rollback on failure and reversal dependencies.
8. Distribution/reserve/debt formulas, principal/interest separation, missing data and due-work reruns.
9. Sensitive field/API/export access, source links, audit immutability, closed periods and historical snapshot/report preservation.
10. Regression coverage for poultry lifecycle, sales, collections, expenditures, payroll/labour, inventory, assets, cash-source balances and batch/farm profitability.

Run available checks with the repository's configured environment:

- `python backend/manage.py check`
- `python backend/manage.py makemigrations --check --dry-run`
- Django finance, poultry and accounts tests, then the full configured backend suite where practical.
- In `frontend`: `npm run lint`, `npx tsc --noEmit`, `npm run build`.
- Run configured formatting/UI/E2E checks if present. The current package manifest has no frontend test or formatter script: do not invent passing results. Add focused UI verification where needed and document manual browser checks if no runner exists.
- Validate fresh/upgrade migrations on a test database, not production; review query counts and posting concurrency on PostgreSQL.
- Manually verify all monetary examples in this prompt and the 1,000,000 Real Revenue allocation example: 5% Profit = 50,000; 30% Owner's Pay = 300,000; 15% Tax = 150,000; 50% Operating Expenses = 500,000.

Fix regressions caused by this work. Clearly distinguish unavailable checks and pre-existing failures. Do not remove or weaken tests to obtain a pass.

Update project documentation and contextual help with architecture, new schema/endpoints, formulas, role matrix, cutover/migration/rollback, due-job setup and manual verification. Finish with delivered capabilities, files changed, test/build results, migration details, calculation examples, remaining limitations and screenshots where supported. A feature is complete only when persisted data, authorized APIs, usable UI and relevant tests are connected; unfinished phases must remain explicitly listed.

## 10. Explicit scope exclusions

Do not build a multi-tenant architecture, general invoicing replacement, bank integration, full foreign-currency accounting, new project/timesheet/service business subsystem, or automatic historical statutory-ledger conversion. Do not replace existing poultry accounting policies with an unreviewed Profit First interpretation. These are outside this implementation, unlike the required phases above.

Proceed autonomously through the selected phase's authorized changes. Apply the shared correctness, access, audit, migration and verification requirements to that phase; do not defer its essential controls to a later phase. Resolve routine choices from the code and this prompt. Ask only for a blocking business decision that cannot be handled through a documented conservative default or explicit configuration.
