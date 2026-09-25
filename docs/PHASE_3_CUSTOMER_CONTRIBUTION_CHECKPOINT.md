# Phase 3 checkpoint: batch selling economics and payroll advances

Revised on 25 September 2026 after management replaced customer-specific contribution entry with sale-level selling costs. This checkpoint stops before Phase 4 / Profit First allocation work.

## Delivered

- Every poultry sale can carry any number of transport, packaging, commission, market-fee, or other selling-cost rows. Each row has its own amount and optional note.
- The active sale workflow no longer asks for a stable customer record. The original buyer name remains on the sale and continues to support receivables follow-up.
- Sale-specific costs flow into batch selling cost, total attributed cost, fully loaded net position, and the batch-performance dashboard without becoming production input cost.
- The Finance landing page is batch-first: choose one, several, or all batches and compare mortality, production cost, selling cost, gross profit, fully loaded net profit, funding sources, and break-even selling prices.
- The funding chart separates own-batch sales, other-batch sales, owner capital, other cash sources, and unpaid/unassigned cost.
- The sales trend starts at flock day 28. Earlier sales remain in revenue and profit totals but are excluded from the chart.
- Payroll has explicit **Record advance** and **Pay remaining salary** actions. Both select one or more cash sources, reduce the employee's remaining salary, and preserve reversal/audit history.
- Batch feed reporting provides evidence-based sell-by guidance, projected extra feed/bags, avoidable feed cost, weighted historical selling price, and projected net/loss. Missing evidence is shown instead of invented.

## Accounting boundaries

- **Gross profit** = recognized sales revenue minus direct and allocated production cost.
- **Net position** = gross profit minus selling, administration, finance, tax, and other attributed management costs.
- **Sale-specific cost** is the incremental cost of completing that sale; it is not tied to a customer master and is counted once.
- **Break-even per survived bird** = all attributed batch costs divided by birds sold plus birds remaining. The separate remaining-bird price estimate recovers the outstanding gap from birds still available for sale.
- A salary advance is a payroll payment kind, not an additional salary expense. It reduces both the payroll balance and the selected funding-source balance.

## Compatibility and migrations

- `finance.0026_customer_customercostattribution_and_more` and `poultry.0033_sales_customer` remain applied so existing linked data is not destroyed. Their pages and selectors are no longer part of the active workflow.
- `finance.0027_payrollpayment_payment_kind` distinguishes advance and salary payments and treats existing rows as salary payments.
- `poultry.0034_salesellingcost` adds the child ledger for sale-specific costs.

Rollback is forward-only: reverse incorrect financial activity through its controlled workflow. Do not unapply migrations after new payments or sale costs exist.

## Verification

- Django system check: passed.
- Migration drift check: no changes detected.
- Poultry and Finance tests: 108 passed.
- Frontend TypeScript check and production build: passed.
- Frontend ESLint: no errors; four existing `AddBatchDialog.tsx` warnings remain.
- Live dashboard service evaluated successfully for three batches and 22 sales-trend points.

The live finance audit still reports the inherited reconciliation queue: one unlinked and one void-linked operational cost, 52 unfunded or partly funded historical expenditures, one possible duplicate economic event, 32 legacy period-lock violations, and source events awaiting approved general-ledger backfill. This phase does not guess, delete, or rewrite those historical records.
