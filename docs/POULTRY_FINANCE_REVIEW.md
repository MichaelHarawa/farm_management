# Poultry finance handling review

Date reviewed: 21 August 2026

## Reporting basis

The application's batch report is a lifecycle **management-cost report**. It is useful for flock decisions, but it is not, by itself, a statutory biological-asset valuation or a complete whole-farm income statement.

Malawi's reporting framework depends on the entity category. Public-interest entities use full IFRS, while ICAM has introduced a separate FRS for non-public-interest entities. The application must therefore not claim automatic IFRS compliance without a configured entity policy and an accountant's review.

## Authoritative design principles

- [IAS 41 Agriculture](https://www.ifrs.org/issued-standards/list-of-standards/ias-41-agriculture/) treats living birds as biological assets and, under full IFRS, generally measures them at fair value less costs to sell, with changes in profit or loss.
- [IAS 2 Inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/) includes purchase and conversion costs, requires a consistent cost formula, and recognizes inventory cost as expense when the related inventory is sold or lost.
- [IFRS 15 Revenue](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/) separates recognition of earned revenue from cash collection.
- [IAS 7 Cash Flows](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows/) keeps cash movement separate from accrual profit and classifies operating, investing, and financing flows.
- [USDA ERS farm financial ratios](https://ers.usda.gov/data-products/farm-income-and-wealth-statistics/documentation-for-the-farm-sector-financial-ratios) groups farm analysis into profitability, efficiency, liquidity, and solvency measures.
- [Penn State poultry enterprise budgeting](https://extension.psu.edu/enterprise-budgeting-for-small-poultry-flocks) identifies mortality and variable costs such as feed, bedding, repairs, packaging, interest, and labour as material flock economics.

## Controls already present

- Sales, mortality, inputs, feed, and vaccination records are linked to a poultry batch.
- Cancelled sales are excluded from operational and finance totals.
- Sale lifecycle checks prevent overselling.
- Direct flock costs and shared production costs are distinguished.
- Shared costs use stored, reconciling allocation rows rather than being redistributed only among batches selected for a report.
- Active-batch results are provisional; closed batches become final only after period-close allocation reconciliation creates an immutable snapshot.
- Revenue, cash collected, and receivables are shown separately.
- Consumable purchases and usage recognition, asset depreciation, accounting periods, and period locks are available.

## Changes made from this review

- Added a strict single- and multi-batch lifecycle analysis endpoint and user interface.
- Portfolio currency amounts are summed on the server using decimal arithmetic.
- Portfolio margins, collection rate, mortality rate, and per-bird measures are recalculated from combined numerators and denominators; per-batch percentages are never averaged.
- Selected batches retain their original stored share of farm overhead.
- Added explicit report-basis warnings for provisional flocks, unallocated central costs, and missing IAS 41 fair-value data.
- Added batch selection to direct labour and consumable usage entry, and optional direct attribution for production or selling expenses.
- Added batch identity to the corresponding finance registers.
- Included administration and selling labour/consumable scopes in monthly profit, and included directly assigned or revenue-allocated selling consumables in batch contribution.
- Moved final batch snapshot creation to accounting-period close, after allocations are regenerated. Period reopening retires the prior final snapshot and unlocks period records so a corrected close creates a new auditable version.
- Legacy final snapshots that are not linked to an accounting period are excluded from authoritative final profit and produce a dashboard warning until their period is reopened and reclosed.
- Blocked ordinary poultry and finance postings while a closed batch has a final snapshot. Reopening its accounting period retires that snapshot and opens a controlled window for batch-cost corrections; bird sales, mortality, feed, and vaccination events remain physically locked.
- Corrected crossed frontend API readers for assets and depreciation entries.

## Priority follow-up work requiring schema changes

1. **Receipt ledger and receivable ageing.** Replace the single mutable sale `amount_paid` with dated, immutable payments, refunds, and credit notes. Add due dates, credit terms, ageing buckets, and expected-credit-loss allowances. Until then, monthly cash received follows the sale date rather than the actual later receipt date.
2. **Consumption-based flock inventory.** Route feed, medicine, vaccines, litter, and packaging through purchase lots and stock movements. Charge a batch when stock is issued or consumed, not when it is purchased. This prevents unused inventory from being expensed and prevents duplicate entry between poultry inputs and finance consumables.
3. **Historical monthly snapshots.** Batch-close profitability is now snapshotted and versioned through period reopen/close. The monthly report still needs its own frozen COGS, WIP, bird-balance, and allocation snapshot so a historical month cannot change when an active flock later closes.
4. **Biological-asset policy and valuation.** Configure the entity's reporting framework. Where required, record period-end bird fair value, price source/date, costs to sell, and physical- versus price-change movements. Keep this separate from the management-cost report.
5. **Complete whole-farm profit and cash flow.** Allocate administration only under a documented policy, preserve an unallocated central-cost view, and add supplier-payment events so partial payments, investing flows, and financing flows reconcile to cash accounts.
6. **Poultry output inventory.** Where material, record eggs, dressed birds, and manure as output/harvest inventory before sale and assign product-specific processing cost.

The batch-analysis screen deliberately labels the current result as lifecycle management cost and uses “contribution after selling costs” in the interface instead of presenting the existing zero-administration field as true fully loaded or net profit.
