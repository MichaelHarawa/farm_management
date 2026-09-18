# Phased implementation prompts

Use one prompt at a time in this repository. The review and shared specification are already saved under `docs/`. Each phase must inspect the current code again so that earlier work is reused rather than rebuilt. These prompts request implementation; the review task itself did not change application code.

| Phase | Deliverable | Prerequisite |
|---|---|---|
| 1 | Cost per survived bird and payment-history detail windows | Existing repository |
| 2 | Owner contributions per batch and cumulative across batches | Phase 1 recommended |
| 3 | Customer identity and customer contribution analysis | Phase 1 recommended |
| 4 | Profit First settings, allocation runs and enforceable cash controls | Phases 1–3 |
| 5 | Deferred cash, distributions and reserve management | Phase 4 |
| 6 | Debt management and expense review | Phase 4; Phase 5 recommended |
| 7 | Consolidated assessment, dashboards, alerts and reports | Phases 1–6 |

Phases 2 and 3 do not mathematically depend on each other, but sequential delivery makes integration and review easier. Each phase includes its own permissions, audit, UI, tests and documentation; Phase 7 is consolidation, not the first point where those controls are added. Full multi-tenancy, foreign-currency settlement accounting, bank connections and historical statutory-ledger activation remain outside scope.

## Phase 1 — survival cost and payment details

```text
Implement Phase 1 only in the current Farm Management repository.

Read docs/PROFIT_FIRST_SCOPE_REVIEW.md and docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md. Apply shared sections 1–2 and 8–10, then implement A1 and A2 from section 3. Inspect current instructions and code first; reuse anything already completed.

Deliver:
1. Cost per survived bird using existing total_production_cost divided by valid bird units sold plus remaining live birds. Reuse the existing saleable-bird calculation, preserve old APIs, final snapshots and weighted portfolio aggregation, and distinguish survivor percentage from remaining-bird availability.
2. A read-only detail dialog when one payment-history row/entry is clicked, covering customer collections, expenditure payments and payroll payments. Reuse the shared Dialog and existing payment records. Show split funding for the selected payment without duplicate payroll/expenditure totals. Enforce existing and sensitive-field access, keyboard usability and safe nested action behavior.

Do not implement owner-contribution tracking or Profit First yet. Do not create a new payment ledger. Add relevant backend tests and UI checks, run available lint/type/build checks, update documentation, and summarize results. Stop after this phase is complete and reviewable.
```

Checkpoint: the 1,000 received / 50 deaths / 600 sold / 350 remaining example yields 950 survivors and MWK 2,000 per survivor on MWK 1,900,000 production cost. Clicking each supported payment entry opens the correct details without causing a mutation.

## Phase 2 — owner contributions

```text
Implement Phase 2 only in the current Farm Management repository.

Read docs/PROFIT_FIRST_SCOPE_REVIEW.md and docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md. Apply shared sections 1–2 and 8–10 and the relevant access/audit rules in section 7. Implement A3 in section 3. Inspect and preserve earlier phase changes.

Extend existing OWNER_CAPITAL FundingSource, FundingReceipt, FundingAllocation and batch funding-mix reports. Add stable owner identity and receipt-to-batch designation only where needed; do not create another cash contribution ledger.

Show owner cash introduced, designated per batch, actually spent for each batch, remaining funds and explicitly classified withdrawals/returns. Provide per-owner/per-batch reports and cumulative totals with opening balances, dated movements and closing balances. Prevent counting shared receipts multiple times. Reconcile source/batch rounding before filters. Treat owner cash as equity funding, not sales, profit or Owner's Pay. Preserve unknown historical identities and distinguish unknown attribution from zero contribution.

Connect authorized UI, APIs, audit, additive migrations and tests. Verify one MWK 1,000,000 receipt split 600,000/400,000 across two batches still totals 1,000,000; spending 300,000/200,000 leaves 500,000. Test reversals, filters, pagination and cumulative history. Document what changed and verification results, then stop at this phase's checkpoint.
```

Checkpoint: receipt totals, batch designations, batch spending and cumulative reports reconcile without creating money or rewriting existing transactions.

## Phase 3 — customer contribution

```text
Implement Phase 3 only in the current Farm Management repository.

Read docs/PROFIT_FIRST_SCOPE_REVIEW.md and docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md. Apply shared sections 1–2 and 8–10 plus relevant access/audit/reporting rules. Implement section 4 (Phase B). Reinspect existing customer/sale models and reuse earlier implementation where present.

Use exactly:
Customer Contribution = Revenue - Direct Delivery Cost - Support Cost - Rework Cost - Acquisition Cost.

Add a minimal stable customer identity and backward-compatible nullable Sales link if still absent. Preserve buyer_name and historical records; do not merge customers by name automatically. Add source-linked and documented estimated cost attribution with caps and clear coverage status. Include attributable production/delivery/subcontractor cost once, in the appropriate category; do not add a separate subcontractor deduction. Use recognized sales revenue and show cash collected separately.

Deliver customer/product-type breakdowns, contribution/margin, actual-versus-estimated coverage, review labels/actions, drill-down and authorized CSV export. Retain unsold birds' cost share and prevent re-attributing linked duplicate cost records. Missing costs must be visible, not silently zero.

Test the specified 1,000,000 - 600,000 - 50,000 - 20,000 - 30,000 = 300,000 example, attribution limits, identity ambiguity, partial payments and permissions. Complete UI, migrations, tests and docs, report verification, and stop. Do not start Profit First allocation runs in this phase.
```

Checkpoint: contribution is traceable to revenue and four non-overlapping cost categories, with unresolved/estimated coverage visible.

## Phase 4 — Profit First core

```text
Implement Phase 4 only in the current Farm Management repository.

Read docs/PROFIT_FIRST_SCOPE_REVIEW.md, docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md and prior phase documentation. Implement section 5 (Phase C), applying shared sections 1–2 and 8–10 plus the necessary access, audit, warning and report requirements from section 7 now.

Deliver disabled-by-default farm-level effective-dated settings, onboarding with authoritative previews, virtual cash buckets, source-linked receipt classification, Real Revenue calculation, allocation consumption, allocation-run preview/approval/posting/reversal and basic bucket/run reports. Distinguish virtual earmarking from cost allocation, funding origin and real GL movements. Keep MWK and existing financial definitions.

Use existing posted receipts; do not create duplicate income. Exclude owner capital/loans/internal transfers, handle partial receipts, and reconcile a cutover so historical cash already spent or included in opening balances cannot be allocated again. Deferred cash may be explicitly held and excluded now; scheduled releases belong to Phase 5.

Integrate bucket consumption and protection into ALL existing payment paths when enabled. Enforce backend access, immutable finance audit events, period locks, exact Decimal rounding, receipt-consumption constraints, idempotency payload checking and transactional concurrency controls. Approval must become invalid after a material draft change. New earmarks must not increase total cash or affect accounting profit.

Complete usable settings/run/bucket UI and relevant tests, including concurrent posting, source reversal dependencies, insufficient funds, protected-fund bypass attempts and feature-disabled regressions. Do not activate/backfill the historical GL or add tenancy. Update setup/cutover/rollback documentation and provide verification results. Stop before deferred schedules, distributions and advanced debt workflows.
```

Checkpoint: the 5/30/15/50 allocation example reconciles, and neither simultaneous posting nor an existing payment endpoint can overspend protected cash.

## Phase 5 — deferred cash, distributions and reserves

```text
Implement Phase 5 only in the current Farm Management repository.

Read docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md and confirm Phase 4 is present and verified. Implement section 6's Deferred receipts / Drip and Profit distributions and reserves subsections. Apply shared controls, access, audit, migrations and verification requirements; reuse Phase 4 cash buckets and movements.

Deliver receipt-linked deferred schedules and idempotent releases; do not repurpose prepaid EXPENSE recognition. Add dry-run/due-work management commands and deployment instructions if no scheduler exists. Scheduled releases must not allocate the original receipt twice or imply formal accounting recognition automatically.

Add approved profit-distribution events/statements and linked actual payments, protected retained reserves, optional debt earmarking, and ownership splits only from explicitly entered ownership percentages. Owner contributions do not establish ownership. Debt settlement integration can reuse Phase 6 once delivered; do not fake repayments now.

Add emergency reserve targets/months, gap, movement, access rules and replenishment plans while preserving separate asset replacement reserves and avoiding double counting. Enforce available cash, permissions, confirmations/reasons and reversals.

Verify 120,000 released as twelve 10,000 slices, rerun safety, cancellations/refunds, distribution limits, zero-expense reserve coverage and protected funds. Complete UI/reports, tests, docs and checks, then stop at this checkpoint.
```

Checkpoint: deferred releases reconcile to the receipt, and approved distributions cannot consume protected or unavailable funds.

## Phase 6 — debt and expense review

```text
Implement Phase 6 only in the current Farm Management repository.

Read docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md and earlier implementation notes. Implement section 6's Debt and Expense review subsections, with all relevant shared controls, permissions, audit and verification.

Extend existing loan funding and expenditure/payment records with a creditor/debt register, terms, drawdown/repayment links, principal-versus-interest/fee separation, history and estimated snowball/avalanche/custom-order comparisons. Show assumptions and relevant debt terms; do not automatically execute repayment recommendations. Integrate existing debt buckets/distribution earmarks without duplicating cash movements.

Extend existing expenditures with essential/recurring/discretionary and other specified review classifications, review actions and estimated/realized savings. Reuse customer attribution from Phase 3 where relevant. Do not create another expense system or claim subscription usage data exists. Add documented trends and duplicate candidates, not automated cancellations.

Complete authorized screens, reports, migration handling, calculations and tests for principal/interest, projections, attribution and financial regressions. Report verification and limitations, then stop before the final reporting consolidation.
```

Checkpoint: loans reconcile to cash drawdowns/repayments, interest remains distinct from principal, and expense review does not recognize costs a second time.

## Phase 7 — assessment, reporting and final integration

```text
Implement Phase 7 only in the current Farm Management repository.

Read docs/CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md and the delivery notes for Phases 1–6. Implement remaining section 7 assessment/dashboard/trends/alerts/reporting requirements and complete sections 8–9 cross-feature verification. First identify what prior phases already deliver and extend it; do not rebuild their screens, ledgers or audit stream.

Deliver the completed-12-month Instant Assessment, consolidated Profit First dashboard, documented metric/date bases, configurable meaningful in-app alerts, filtered reports and complete authorized CSV exports. Cover owner contributions, customer contribution, allocations, bucket movements, reserves, tax earmarks, distributions, debt, expenses, deferred releases and action history. Expose incomplete data and do not portray earmarked cash as accounting profit or tax liability.

Audit the role/field/export permission matrix and aggregate data leakage. Add idempotent due-reminder commands only where needed; do not claim a scheduler or external notifications are running without deployment. Verify responsive/accessibility behavior, export safety, pagination, query performance, historical as-of reporting and all existing finance/poultry workflows.

Run available full backend tests, migration checks, frontend lint/type/build and configured UI checks. Document failures honestly. Update user/architecture/migration/operations documentation and deliver an implemented/remaining matrix for the complete roadmap with manual verification and screenshots where possible. Do not include excluded multi-tenancy, foreign-currency accounting, bank integrations or automatic statutory GL activation.
```

Checkpoint: the complete roadmap is accounted for, financial totals reconcile between screens and exports, and any unfinished capability is explicitly recorded rather than implied to work.
