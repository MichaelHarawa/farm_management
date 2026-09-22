# Phase 2 checkpoint: owner contributions

Completed on 19 September 2026. This checkpoint intentionally stops before Phase 3 / Profit First allocation work.

## Delivered

- Stable owner/contributor identities, separate from login accounts.
- One authoritative cash receipt for each contribution, with retry-safe idempotency.
- Reversible receipt-to-batch designations that describe intended use without duplicating cash or expense.
- Exact attribution of actual owner-funded expenditure and payroll payments across the complete batch-beneficiary set.
- Separate classifications for return of capital, drawing, owner compensation and profit distribution.
- Per-owner, per-batch and cumulative reporting with opening balance, in-period movement and closing balance.
- Owner, multi-batch and date filters; independent pagination of batch, receipt and timeline detail; and full-filtered CSV export.
- Explicit **Unknown legacy owner** reporting. No historical identity is inferred from source descriptions.
- Administrator/Director access controls and an append-only audit trail for sensitive owner-capital actions.
- Owner-capital and other non-sales funding shown separately in funding-mix and revenue-use views.

## Reconciliation rule

`remaining owner cash = posted owner receipts - owner-funded expenditure payments - owner-funded payroll payments`

`net contributed capital = posted owner receipts - explicit returns of owner capital`

Drawings, compensation and profit distributions remain separately classified. Batch filters affect the attribution analysis, not the reconciled owner cash ledger total.

## Migration

`finance.0025_ownerreceiptdesignation_and_more` is additive and applied successfully. It does not delete, merge or recalculate historical receipts, expenditures or allocations. Existing owner-capital sources remain assigned to **Unknown legacy owner** until source documents support an explicit administrative correction.

## Verification

- `python backend/manage.py check`: passed.
- `python backend/manage.py makemigrations --check --dry-run`: no changes detected.
- Focused owner-capital/expenditure/payroll tests: 25 passed.
- Complete finance test suite: 84 passed.
- `python backend/manage.py finance_preflight`: passed; all migrations applied.
- Frontend ESLint: 0 errors; 4 pre-existing warnings in `AddBatchDialog.tsx`.
- Frontend TypeScript check: passed.
- Frontend production build: passed and includes `/finance/owner-capital`.
- `git diff --check`: passed; only Git line-ending notices were emitted.

The finance audit still reports the pre-existing historical reconciliation queue (unlinked/void operational costs, partially funded historical expenditures, legacy period-lock flags and pending GL backfill). It also flags one possible duplicate economic-event candidate for manual review. Phase 2 does not guess or mutate those historical records.

## Acceptance example

A MWK 1,000,000 contribution designated MWK 600,000 to Batch A and MWK 400,000 to Batch B, with actual owner-funded use of MWK 300,000 and MWK 200,000 respectively, reports:

- cash introduced: MWK 1,000,000;
- designated: MWK 1,000,000;
- actually spent: MWK 500,000;
- remaining owner cash: MWK 500,000.

This scenario is covered by the automated owner-capital test suite.
