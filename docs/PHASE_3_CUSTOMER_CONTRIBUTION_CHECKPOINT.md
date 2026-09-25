# Phase 3 checkpoint: customer contribution

Completed on 24 September 2026. This checkpoint stops before Phase 4 / Profit First allocation work.

## Delivered

- Stable customer identities with explicit historical-sale linking, preserved sale-time buyer names, duplicate-name safety, and non-destructive deactivation.
- Customer selection in the poultry sale form without making identity mandatory for legacy records.
- Recognized-revenue contribution analysis with cash collected and receivables shown separately.
- One exact, visible formula with four non-overlapping cost categories: direct delivery, support, rework, and acquisition.
- Automatic sold production-cost attribution from the existing cost-per-survived-bird basis, calculated across the complete batch sale population before filters.
- Source-linked actual or estimated customer-cost attributions, canonical source caps, idempotency, append-only history, controlled reversals, and closed-period protection.
- Protection against attributing a batch-production source a second time after its automatic direct-delivery inclusion.
- Category coverage and incomplete-data warnings, customer concentration, product mix, system recommendations, management labels and decision notes.
- Searchable customer, historical-sale, and recognized-cost selectors; independent customer-result pagination; and complete filtered CSV export.
- A simplified finance landing page and navigation with four headline measures, short attention/task sections, and secondary detail collapsed until requested.
- Clickable dashboard warning for valid sales that are not yet linked to a stable customer.

## Reconciliation rule

`customer contribution = recognized revenue - direct delivery - support - rework - acquisition`

Posted receipts affect cash collected and receivables, not recognized revenue. Missing customer cost categories remain explicitly incomplete and are never silently converted into evidence of zero cost.

## Migration

- `finance.0026_customer_customercostattribution_and_more`
- `poultry.0033_sales_customer`

Both migrations are additive and applied successfully. Existing sales are not matched by buyer name and retain their historical `buyer_name` values.

## Verification

- `python backend/manage.py check`: passed.
- `python backend/manage.py makemigrations --check --dry-run`: no changes detected.
- Focused customer-contribution and poultry tests: 20 passed.
- Complete finance test suite: 91 passed.
- `python backend/manage.py finance_preflight`: passed; all migrations applied.
- Frontend ESLint: 0 errors; 4 pre-existing warnings in `AddBatchDialog.tsx`.
- Frontend TypeScript check: passed as part of the production build.
- Frontend production build: passed and includes `/finance/customers` and `/finance/customers/[id]`.
- `git diff --check`: passed; only Git line-ending notices were emitted.

The live finance audit still reports the inherited reconciliation queue: one unlinked and one void-linked operational cost, 52 unfunded or partly funded historical expenditures, one possible duplicate economic event, 32 legacy period-lock violations, and source events awaiting approved general-ledger backfill. Phase 3 does not guess, delete, or rewrite those historical records.

## Acceptance example

A customer with MWK 1,000,000 recognized revenue, MWK 600,000 direct delivery cost, MWK 50,000 support, MWK 20,000 rework, and MWK 30,000 acquisition cost reports MWK 300,000 contribution and a 30% contribution margin. If only MWK 400,000 has been collected, the same report separately shows MWK 600,000 receivable. This scenario is covered by the automated test suite.
