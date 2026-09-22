# Finance user guide

## Period reports

Open **Finance → Period Reports** and select a month. Open months show **MTD / provisional**. Review the accrual result separately from cash flow, then confirm:

- cash received is based on receipt date;
- cohort collection rate relates only to that month’s sales;
- the receivables roll-forward reaches closing receivables;
- opening cash plus operating, investing and financing movement equals closing cash;
- assets equal liabilities plus net assets under the displayed management-cost basis;
- close-readiness warnings have been addressed.

Closing creates immutable report and eligible batch snapshots. To correct a closed month, use the controlled reopen action with a reason, post reversals/replacements, recalculate, and close again. The former snapshot remains in history.

## Batch performance

Use **Finance → Batch Performance** for one batch or a combination. Each row retains its original whole-farm allocation share. Open **Review full finance breakdown** to see revenue, receipts, receivables, direct cost, production overhead, selling cost, administration, finance cost, recorded tax, management net position, active exposure, break-even measures and forecast-at-completion.

An active batch’s negative actual-to-date position is not labelled a final loss. Use the forecast and its basis for planning. “Net assets” belongs to the period balance sheet; it is not another name for batch profit.

**Cost per survived bird** uses all birds that survived mortality, whether already sold or still alive and unsold. It therefore does not jump merely because birds are sold. The figure shows **N/A** for a booked batch, a batch with no survivors, or an invalid flock balance that needs correction. Combined-batch views use a weighted calculation from the displayed production-cost numerator and survivor denominator, not an average of batch rates.

## Payment history

In **Receivables**, an expenditure detail page, or the payroll ledger, select any payment-history row to open its full audit detail. The window shows the payment amount, effective date, method/reference, who recorded it and when, its current/reversed status, and the linked buyer, payee, employee, batch or beneficiary where applicable. Expenditure payments split across funding sources also show every source line and a reconciliation total. Close the window with its close button, Escape, or the backdrop; keyboard focus returns to the selected history row.

Reversals remain visible in history. Do not overwrite the original row to correct a payment.

## Funding versus cost allocation

When recording or paying an expenditure:

- **Payment source** identifies the cash pool (batch collections, general farm cash, owner funds, loan, grant or other income).
- **Cost allocation** identifies the batch or farm function that benefited.

A batch can fund another batch’s cost without bearing that cost. Splitting payment sources does not change the cost allocation.

## Warning actions

Finance warnings are clickable. Open one to read the cause and recommended solution, then use its action link to reach the relevant sales, expenditure, payroll, inventory, period or poultry record. Do not clear a warning by changing an unrelated total.

## Operational controls

- Never edit a posted historical total to simulate a correction; reverse it and post a replacement.
- Record later customer cash as a receipt, not by changing the original sale date.
- Leave unpaid payroll as a liability until a dated payment exists.
- Use consumable lots/issues when purchased stock remains unused; direct poultry input costs are expensed when entered.
- Obtain accountant approval before treating this internal management report as statutory, tax, IFRS, or IAS 41 reporting.

## People, inventory and assets

Casual labour begins as a draft. Approve it, post the payable, then open the linked expenditure to record the dated payment and actual funding source. Do not mark labour paid manually. Inventory purchases enter a lot/location and increase stock; issuing a lot to a batch creates the batch charge and stock reduction once. Asset detail pages contain depreciation and lifecycle history plus controlled transfer, impairment and disposal actions.

## Technical administration

**Administration** is not a Finance submenu. It is restricted to administrators and manages login accounts only: create a system user, assign an access role, activate or deactivate access, review last login, and set a temporary password. An employee may exist without a login and a system user may exist without an employee record. The last active administrator cannot be deactivated or stripped of administrator access.

## Owner capital

Administrators and directors can open **Finance → Owner Capital**. First create a stable owner/contributor identity, then record the bank/cash receipt. A receipt may be designated across one or many batches immediately or later. Leave it unassigned when the intended batch is not yet known; do not create a second receipt merely to change the designation.

Owner-source balances and their use are sensitive. Farm managers and supervisors can record the underlying purchase as a payable, but an administrator or director must assign owner-capital cash to its payment. General farm cash, loan, grant and other-income sources continue to follow the ordinary finance permissions.

The workspace keeps three ideas separate:

- **Introduced** is actual owner cash received and is counted once.
- **Designated** is the intended batch use and does not move cash.
- **Actually spent** comes from posted expenditure or payroll payments that selected that owner's funding source.

Use **Return of Owner Capital** only when principal is genuinely repaid. Use **Owner Drawing**, **Owner Compensation**, or **Owner Profit Distribution** for their distinct purposes. These options are available when recording an expenditure. Reverse an incorrect designation or unused receipt with a reason; a receipt that has already funded posted spending cannot be reversed until the spending is corrected through its controlled reversal workflow.

Legacy owner-capital receipts with no reliable contributor appear under **Unknown legacy owner**. Do not rename or guess them from a description. Reconcile them against bank records and source documents before making an explicit controlled assignment.
