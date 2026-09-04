# Finance architecture

## Scope and accounting boundary

The application keeps operational source documents (sales, receipts, expenditures, payroll, consumable usage, assets and poultry records) separate from accounting records. `JournalEntry` and `JournalLine` provide an append-only double-entry layer. `FundingSource` answers **where cash came from**; `CostAllocation` answers **which batch bears a cost**. These dimensions must never be inferred from one another.

The current reporting policy is `MANAGEMENT_COST_V1`. It uses weighted-average inventory costing, bird-days for administration/production allocation, and revenue share for selling, finance and recorded tax. This is internal management accounting, not an automatic IFRS, tax, or IAS 41 conclusion.

Design references are the IFRS Foundation summaries for [IAS 2 Inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/), [IAS 7 Statement of Cash Flows](https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows.html/) and [IAS 41 Agriculture](https://www.ifrs.org/issued-standards/list-of-standards/ias-41-agriculture/). IAS 2 permits FIFO or weighted average for interchangeable inventory, and IAS 7 supports operating/investing/financing classification. IAS 41 ordinarily uses fair value less costs to sell for biological assets, which this management-cost report deliberately does not implement.

## Core controls

- Every journal is tied to an accounting period, source model, source identifier and unique idempotency key.
- `post_journal` requires exact Decimal debit/credit equality and a configured chart account.
- Posted lines and journals cannot be edited or deleted. Corrections use a linked reversal.
- Closed periods reject ordinary postings. Reopening is an audited action and a later close creates a new snapshot version.
- Closed period reports are stored in immutable `PeriodReportSnapshot` rows. `snapshot_closed_period_reports` safely identifies legacy closed periods that still need their first snapshot.
- Batch final snapshots are separate from period financial-statement snapshots.

## Seeded chart of accounts

The chart includes cash (1000), receivables (1100), inventory (1200), poultry WIP (1300), fixed assets and accumulated depreciation (1500/1590), supplier/payroll/statutory/loan liabilities (2000/2100/2110/2200), equity and drawings (3000/3100), revenue (4000), direct production/payroll/overhead costs (5000/5100/5200), selling/admin/depreciation (6000/6100/6200), finance cost and tax (7000/7100).

## Posting templates

| Event | Debit | Credit |
|---|---|---|
| Sale | Receivables | Revenue |
| Customer receipt | Cash/bank | Receivables |
| Operating expenditure on credit | Expense/WIP | Supplier payable |
| Supplier payment | Supplier payable | Cash/bank |
| Payroll generation | Production/selling/admin expense | Payroll and statutory liabilities |
| Salary/statutory payment | Relevant liability | Cash/bank |
| Inventory purchase | Inventory | Payable or cash |
| Inventory issue to batch | Batch WIP/direct cost | Inventory |
| Asset acquisition | Fixed asset | Payable or cash |
| Depreciation | Depreciation expense | Accumulated depreciation |
| Impairment | Impairment expense | Asset/impairment allowance |
| Asset disposal | Cash and accumulated depreciation, plus loss if any | Asset cost, plus gain if any |
| Owner capital / borrowing | Cash | Equity / loan liability |
| Owner withdrawal / loan repayment | Drawings / loan liability | Cash |

`backfill_general_ledger` currently previews historical sale, receipt, expenditure, payment, payroll and depreciation journals. It is dry-run by default. Do not activate the ledger as the statutory source of truth until its preview, opening balances, and exception queue are approved.

## Reporting

“Period Reports & Close” separates accrual P&L, dated cash movement, receivables roll-forward, balance-sheet measures, ageing and comparisons. Open periods are labelled MTD/provisional. Collection rate uses receipts matched to that period’s sales cohort, while “cash received this period” uses receipt dates. Consequently September can contain MWK 505,500 receipts but a cohort collection rate of 78.95%, not 1,330.26%.

Batch reports remain lifecycle management-cost reports. They show actual-to-date and forecast-at-completion separately and expose the allocation period, driver, numerator, denominator, percentage and calculation version. Selection never recalculates a batch’s denominator from only the selected subset.

## Operational modules delivered in priorities 5–9

- Casual labour uses draft, approval, posting, payment and reversal states. Posting creates one payable and balanced journal; dated payments use the expenditure funding workflow and synchronize labour status.
- Inventory has item/base-unit masters, conversions, locations, lots, immutable stock movements, weighted-average receipt/issue accounting, and low-stock/expiry signals. Movement classifications cover receipt, issue, return, transfer, waste, expiry and adjustment.
- Assets expose acquisition/capitalized-cost, depreciation, usage, maintenance, replacement, impairment, transfer/custodian and disposal history. Financial basis fields lock once depreciation exists.
- Finance navigation is reduced to eight decision areas. The dashboard emphasizes cash, MTD/YTD results, collections, liabilities, stock, assets, WIP, forecasts, warnings and close readiness.
- Revenue summaries, spending transactions, cross-batch financing, receivables and expenditures use bounded server pagination. Aggregated endpoints replace the former request-per-batch pattern.
- Technical Administration is separate from Finance. Admin-only controls create system users, assign roles, activate/deactivate accounts, set temporary reset passwords, optionally link employees, show last login, record immutable audit history and preserve the last active administrator.

## Remaining policy-controlled work

Effective-dated compensation and payroll proration remain Priority 4 work. Inventory movement screens beyond receipt/issue and advanced prospective asset-estimate changes can be extended from the new ledgers. Switching statutory statements fully to the GL still requires approved historical backfill, opening balances and qualified-accountant approval.
