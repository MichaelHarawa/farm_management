# Profit First scope review

Reviewed 18 September 2026 against the working repository and the supplied proposal. This is a source-code review and implementation brief, not a runtime audit. No application changes or database operations were performed.

## Findings and duplication risks

| Requested capability | Evidence in current code | Implementation decision |
|---|---|---|
| Income and payment history | `SalePayment`, `collections.py`, receivables payment APIs and `/finance/receivables` | Use posted customer receipts as the cash-allocation input. Do not create a second sales receipt ledger. Add detail-window interaction. |
| Expenses and payments | `Expenditure`, `SharedExpense`, `FundingAllocation`, `expenditures.py`, payroll and labour services | Extend classifications and links. Preserve the distinction between recognition of a cost and payment of that cost. |
| Owner contributions | `FundingSourceType.OWNER_CAPITAL`, `FundingReceipt`, funding-mix and revenue-utilization reports | Receipts already exist. Add explicit owner attribution, separate owner-capital totals, and cumulative reporting. Do not record an additional contribution transaction for the same receipt. |
| Cost per survived bird | `_build_batch_profitability()` calculates production cost divided by sold bird units plus remaining live birds | Expose the existing basis clearly as cost per survived bird, with additive API aliases if useful. Do not divide by remaining birds alone. |
| Batch cost allocations | `CostAllocation`, `allocations.py`, bird-day and management-overhead calculations | These allocate costs to production batches. Profit First needs a separate cash earmarking workflow, with unambiguous names. |
| Cash accounts and general ledger | `ChartOfAccount`, `CashOrBankAccount`, `JournalEntry`, `JournalLine`, `ledger.py` | Reuse financial posting infrastructure where an actual accounting event occurs. Virtual earmarking must not create income, expense, or duplicate cash. |
| Period locks and final results | `AccountingPeriod`, `BatchProfitabilitySnapshot`, `PeriodReportSnapshot` | Preserve existing closure and snapshot semantics; do not regenerate historical results silently. |
| Reserves | `AssetReplacementPlan`, `ReplacementReserveTransaction` | Existing reserves concern asset replacement. Reuse suitable mechanisms without treating all replacement reserves as emergency cash or counting the same cash twice. |
| Debt | Loan funding source, loan-liability chart account, debt-service funding classification | Foundations only: a creditor register, terms, principal/interest split, schedules and projections are additional work. |
| Customer profitability | `Sales.buyer_name`, buyer type, sales revenue and batch costs | No stable customer master was found in the inspected models. Add a backward-compatible customer link and explicit cost attribution before presenting reliable customer rankings. |
| Deferred income | `ExpenseRecognitionSchedule` and `/prepaid-recognition` | This is prepaid **expense** recognition, not customer deferred revenue. Add a receipt-linked deferred-income schedule; do not repurpose this model. |
| Dashboard and warnings | `reporting.py`, `warnings.py`, finance dashboard, report pages | Extend the existing Finance area and warning patterns, with a focused Profit First workspace. |
| Audit | Journal/reversal metadata, finance integrity audit report, account-administration audit events | Existing `services/audit.py` is an integrity checker, not a complete finance action-event ledger. Add the missing finance action history without misusing user-administration events. |
| CSV exports and UI | Shared `DataTable` CSV export, shared `Dialog`, Finance UI components | Reuse presentation patterns; provide authorized full-result exports for paginated financial reports. |
| Tenancy | Inspected user and finance models are farm-wide; no organization/tenant entity was found | Use farm-level settings. Do not invent organization IDs or claim tenant isolation. Multi-tenant conversion is a separate architectural project. |
| Currency | Finance formatter uses MWK; `DollarReferenceMixin` captures USD reference values | Keep MWK and reference-rate behavior. USD reference capture is not full multi-currency settlement accounting. |
| Scheduling | Management commands exist; no scheduler dependency appears in the dependency manifests | Add idempotent due-work commands and setup instructions where needed. Do not claim jobs or notifications are running merely because configuration fields exist. |

## Decisions for the four additional requests

1. **Cost per survived bird:** interpret this as production cost per bird that survived mortality, including birds already sold. Reuse valid bird sales plus remaining live birds, including existing flock-adjustment rules. Show production cost as the numerator; retain existing fully loaded and break-even metrics separately. If the user later wants fully loaded cost per survivor, add a separately labelled metric.
2. **Payment details:** a click on an individual payment-history entry opens a read-only detail dialog. Cover customer collections, expenditure payment history, and payroll payment history using their existing data. Split funding rows for one payment should reconcile within the dialog.
3. **Owner contribution:** distinguish cash introduced to the farm, cash attributed or designated to a batch, and owner cash actually used for batch expenditure. Show per-batch and cumulative totals. Summing the full value of one shared receipt into every batch would overstate contributions.
4. **Customer contribution:** use exactly `Revenue - Direct Delivery Cost - Support Cost - Rework Cost - Acquisition Cost`. Subcontractor costs belong within the applicable category and must not become a sixth deduction. Show missing-cost coverage instead of reporting unknown costs as zero.

## Recommended delivery order

1. Add the survival-cost label/API mapping, payment details, and owner-contribution reports using existing ledgers.
2. Add customer identity and contribution attribution.
3. Add Profit First settings, receipt classification, cash buckets, allocation runs, controls and reporting.
4. Add deferred releases, distributions, reserves, debt planning, expense review, alerts and exports.

This order preserves the broader proposal while making dependencies explicit. `CODEX_FINANCE_PHASE_PROMPTS.md` splits it into seven bounded implementation tasks with review checkpoints. `CODEX_PROFIT_FIRST_IMPLEMENTATION_PROMPT.md` is their shared specification. Each launch prompt implements only its selected phase. The roadmap explicitly excludes a multi-tenant rewrite, full foreign-currency accounting, bank integrations, and automatic historical GL activation.

## Source map

- Backend stack: `requirements.txt` (Django 6.0.6, DRF 3.17.1); frontend: `frontend/package.json` (Next.js 16.2.10, React 19.2.4, TypeScript, Tailwind 4).
- Finance models, serializers, views, permissions and API registration: `backend/apps/finance/`.
- Calculation and ledger integration: `backend/apps/finance/services/{profitability,collections,expenditures,salary_payments,ledger,reporting,allocations,audit}.py`.
- Population rules: `backend/apps/poultry/services/batch_lifecycle.py`.
- Existing report and workflow tests: `backend/apps/finance/tests/`; poultry regressions: `backend/apps/poultry/tests.py`.
- Finance pages: `frontend/src/app/finance/`; poultry batch details: `frontend/src/features/poultry/components/BatchDetailView.tsx`.
- UI and request helpers: `frontend/src/components/ui/`, `frontend/src/features/finance/`, `frontend/src/lib/`, and the finance API proxy.
- Design constraints: `frontend/AGENTS.md`, `docs/FINANCE_ARCHITECTURE.md`, `docs/FINANCE_DATA_MIGRATION.md`, `docs/FINANCE_USER_GUIDE.md`.

The repository has substantial finance implementation beyond the generic proposal's assumptions. Model names alone do not prove every transaction is journal-posted end to end: verify actual posting paths before extending them. Existing documentation explicitly keeps historical GL activation subject to reconciliation and approved opening balances.
