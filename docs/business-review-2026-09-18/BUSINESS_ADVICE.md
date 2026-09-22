# Farm business review — 18 September 2026

**Recommendation: stabilize unit margins and working capital before expanding.** Your completed flock was close to production break-even, but selling and administration costs pushed it into a loss. The next flock has materially worse mortality and a tight price/cost position. At the same time, customer credit and owner withdrawals are draining the cash needed to finish production.

There is a plausible improvement path; this small dataset does not establish that the business is unviable. It does establish that repeating the same prices, mortality and withdrawal pattern is risky.

## Basis and reliability

Source: `dump-farm_management-202609181126.sql`, reviewed as of its 18 September 2026 date. You confirmed that sales prices are **per bird** and that **all costs are captured**. Amounts below are MWK. I have not invented additional historical operating costs.

The backup contains three broiler batches, 40 sales, 46 customer-payment records, 99 expenditure records and four payroll entries. I extracted finance/poultry data without executing the backup SQL or restoring it into your live database. I reproduced the current application's batch report on an isolated local copy, then independently reconciled revenue, receipts, bird counts and production costs using decimal arithmetic.

These are management figures, not audited financial statements. There are no posted general-ledger journals, batch profitability snapshots or period-report snapshots in this backup. The completed flock is physically closed but its financial result is not locked. Existing management allocations are used, including administration by bird-days and selling payroll by period revenue. That policy places all recorded July/August selling payroll on the first flock; it is a management attribution, not proof that all that work served only that flock.

## 1. What the numbers actually say

To make the report readable, the flocks are named by their placement dates rather than their sometimes earlier booking-based batch IDs.

| Metric | Flock 1: placed 7 July | Flock 2: placed 4 August | Flock 3: placed 28 August |
|---|---:|---:|---:|
| Database batch ID | BATCH-20260712-0001 | BATCH-20260724-0001 | BATCH-20260824-0001 |
| Status | Sold out; financial close pending | Selling | Growing |
| Birds placed | 200 | 208 | 220 |
| Deaths recorded | 9 | 26 | 17 |
| Mortality | 4.50% | 12.50% | 7.73% |
| Birds sold | 191 | 68 | 0 |
| Birds remaining | 0 | 114 | 203 |
| Sales revenue | 3,584,500 | 1,262,500 | 0 |
| Customer cash collected | 3,584,500 | 365,500 | 0 |
| Customer balances outstanding | 0 | 897,000 | 0 |
| Recorded production cost | 3,539,755.80 | 3,403,558.21 | 1,552,644.05 |
| Production cost per survived bird | 18,532.75 | 18,700.87 | 7,648.49 |
| Recorded cost including attributed selling/admin | 3,795,840.10 | 3,431,062.06 | 1,557,055.90 |
| Sales less recorded attributed costs | **(211,340.10)** | (2,168,562.06) | (1,557,055.90) |

Parentheses indicate negative figures. The last two columns' negative positions are **not final flock losses**: their costs include birds still awaiting sale. Flock 3's low cost per survivor is also not its finishing cost.

Across all flocks, sales of 4,847,000 less attributed costs of 8,783,958.06 gives a negative lifecycle position of 3,936,958.06. Calling that entire amount a realized business loss would be misleading while **317 birds remain**. This comparison also does not value unsold birds as inventory or biological assets.

An additional 12,000 repair/pest-control expenditure is recorded but not carried into those batch totals because of its current beneficiary classification. The broader recorded cost base is therefore 8,795,958.06. This is a report-allocation discrepancy, not an invented missing cost.

## 2. Your completed flock explains the pricing problem

Flock 1's cost bridge is:

| Component | MWK |
|---|---:|
| Direct batch costs | 3,335,200.00 |
| Allocated production overhead, including production payroll/depreciation | 204,555.80 |
| Total production cost | **3,539,755.80** |
| Sales less production cost | **44,744.20 surplus** |
| Attributed selling cost | 180,000.00 |
| Attributed administration | 76,084.30 |
| Management result after these costs | **211,340.10 loss** |

You received an average **18,767 per bird**, against **18,533 production cost** and **19,874 cost including selling/admin**. That means roughly **234 production surplus** but **1,106 loss after overhead per sold bird**.

Most birds sold for 19,000. Charging 19,000 for every one of the 191 birds would still have left a **166,840 loss** at the same costs. Discounting contributed to the problem, but eliminating discounts alone would not have solved it.

### Price scenarios for the same 191 birds and the same recorded costs

| Average realized price per bird | Flock profit/(loss) | Margin on sales |
|---|---:|---:|
| Actual: 18,767 | (211,340) | -5.90% |
| 19,000 | (166,840) | -4.60% |
| 20,000 | 24,160 | 0.63% |
| 21,000 | 215,160 | 5.36% |
| 22,000 | 406,160 | 9.67% |
| 22,500 | 501,660 | 11.67% |

On this historical cost base, the mathematical price for a **10% sales margin is approximately 22,082**, and for 15% it is 23,381. Formula: cost per sold bird / (1 - target margin). These are cost-derived targets, **not verified Malawi market prices or guarantees of buyer acceptance**. Volume, bird size, delivery, credit and customer retention could change when prices change.

**Commercial action:** test a price that supports margin with real customer orders before placing the next flock. Offer clearly defined size grades even if you continue charging per bird. Quote pickup/cash and delivery/credit terms separately where justified by their costs. If customers will only pay 18,500–19,000, redesign the cost base or sales channel before increasing production.

At the actual average price, a 10% margin would require total cost of approximately **3,226,050** rather than 3,795,840: a reduction of **569,790**, around 15%. That is the improvement required for a meaningful return, not just survival at break-even.

## 3. Feed is the largest financial lever, but conversion efficiency is not yet measurable

Flock 1's feed-category charges total **2,459,000**, or **64.8% of its fully attributed cost** and **12,874 per sold bird**. This category includes some associated transport and mixing-related charges, so it is not a pure purchased-feed-only figure.

| Reduction in this cost pool, with output/other costs unchanged | Saving |
|---|---:|
| 5% | 122,950 |
| 10% | 245,900 |
| 15% | 368,850 |

A reduction of approximately **8.6%** in that pool would have erased the completed flock's loss, all else equal. A 10% reduction plus an average selling price of 20,000 would have produced approximately **270,060 profit**, or 7.1% margin. These are sensitivity calculations, not evidence that the savings are readily achievable.

**Do not implement this as a 10% reduction in feed offered.** Instead:

- Compare suppliers and feed strategies on total cost to produce a saleable bird of the agreed size, including delivery, wastage, mortality and selling age.
- Reconcile opening feed, purchases, feed issued to each flock, waste and closing stock in kilograms. Confirm whether purchases charged to a flock were actually consumed there or carried forward.
- Weigh representative birds regularly and at sale. Keep feeding and weight records sufficiently consistent to calculate feed conversion and identify when further feeding ceases to earn its cost.
- Have a qualified poultry nutritionist review any home-mixed ration and ingredient substitutions before making changes. The first flock has ingredient purchases and later purchased feed; this does not by itself establish which approach is cheaper or better.

The backup has **no weight samples**. Feed usage logs total 800 kg, 400 kg and 151 kg for the three flocks, but include overlapping periods, an entry of only 1 kg and a gap after 16 August for the first flock despite sales continuing into September. Purchase records sometimes use `kg` with quantities/prices that appear to describe bags. Consequently, I cannot calculate a defensible feed-conversion ratio or attribute the loss conclusively to inefficient feeding.

## 4. Mortality needs operational attention before expansion

Mortality progressed from **4.5%** to **12.5%**, with the youngest flock already at **7.73%**.

- Flock 2 recorded **nine deaths on 20 August**, with cold entered as the suspected cause.
- Flock 3 recorded **15 of its 17 deaths at recorded ages of seven days or less**. Notes mention weak chicks, care and poor feed.

Those notes are observations, not diagnoses or proof of supplier fault. Ask a poultry veterinarian or extension specialist to review the loss pattern, chick arrival condition, brooding, water access, feed handling, ventilation and biosecurity. Assign explicit daily and overnight responsibility and record the findings and corrective actions.

The business case is straightforward: dead birds absorb chick and rearing costs but produce no sales. As an illustration, reducing Flock 2 mortality to about 5% would mean roughly **16 additional saleable birds**, worth around **304,000 gross sales at 19,000**. That is not 304,000 extra profit: those birds would also consume feed and other resources, and the reduction is a planning scenario rather than a promised outcome.

This emphasis is consistent with [University of Georgia Extension's brooding guidance](https://fieldreport.caes.uga.edu/publications/B1287/environmental-factors-to-control-when-brooding-chicks/), which links poor early environmental conditions to mortality, poorer growth and poorer feed conversion. It supports examining management conditions; it does not diagnose these flocks.

Use an initial internal whole-cycle mortality ceiling of **5%**, improving on the later flocks and close to your first flock's result. Treat this as a management target to refine with your local poultry adviser, not a universal standard. A young flock already above that ceiling needs intervention now, not waiting for sale day.

## 5. What to do with the 114 birds currently being sold

Flock 2 has incurred **3,431,062.06** of attributed cost and recorded **1,262,500** in sales. Its remaining 114 birds therefore need to generate **2,168,562.06 plus future costs** to bring the flock to break-even, assuming all 114 survive and sell.

| Further cost from the backup date to final sale | Required average price for remaining 114 birds |
|---|---:|
| 0 | 19,022 |
| 150,000 | 20,338 |
| 300,000 | 21,654 |
| 500,000 | 23,408 |

Selling all 114 at 19,000 would still leave a loss of **2,562 before any additional costs**. At 20,000, only **111,438** would remain to cover future costs and profit.

Prepare a finish-and-sell plan immediately: remaining feed, delivery/selling expense, payroll/overhead to be attributed, realistic sale dates and expected receipts. Do not assume a sale price alone solves this flock's position.

There is an important distinction between planning the next flock and selling birds already raised. **Do not keep mature birds indefinitely merely to insist on recovering historical cost.** Compare the likely additional price from holding them with additional feed, care, mortality risk and delayed collection. A prompt sale can limit a loss even if it does not recover the entire flock cost. For the next placement, require a profitable forward budget before committing.

The first flock's recorded sales stretched from 16 August to 2 September, approximately ages 40–57 days. For birds sold at a fixed per-bird price, additional weight creates little extra revenue unless customers pay more for the larger size. Secure buyers before target market age and arrange clustered pickup dates. Do not impose a fixed sell-out age without considering actual weights, demand and health.

## 6. Cash discipline is as urgent as improving profit

### Customer credit

Flock 2 has collected only **365,500 of 1,262,500**, a **28.95% collection rate**. The **897,000 outstanding is across six sale records**. The stored due dates fall between **23 September and 2 October**: these balances were not yet overdue on the backup date.

Two entries on 18 September account for 666,000 of that outstanding amount, making cash exposure concentrated. Verify both deliveries and agree collection arrangements before offering more unsecured credit.

Actions:

- Confirm every outstanding amount and its due date now; plan cash around actual expected collection dates, not revenue recognition.
- Prefer payment on collection or a deposit covering the next committed production costs for new buyers.
- Set credit limits by buyer and stop further unsecured dispatch when an agreed limit is reached. Keep contracted terms for existing sales.
- Offer a cash discount only when the avoided financing/default/collection costs justify it within the margin. Do not discount reflexively when margins are already thin.

Collecting the 897,000 will improve cash, **not profit already recorded**.

### Owner funds and drawings

The backup records:

| Movement | MWK |
|---|---:|
| Owner-capital receipts | 1,483,000 |
| Owner withdrawals | 1,308,000 |
| Net recorded owner introduction before other uses | 175,000 |
| Loan funding receipts | 290,000 |

Owner withdrawals equal **33.1% of customer cash collected**. They do not belong in production costs and have been excluded from the operating-loss calculation above. They nevertheless remove cash needed to buy feed and support the remaining flocks. One withdrawal of 523,000 is described as temporary; if genuinely recoverable, document and schedule its return rather than count it as new sales income.

**Pause discretionary drawings until a rolling cash plan covers the existing flocks' feed, necessary care, payroll and debt commitments.** Maintain a separate business cash account and record any essential owner compensation explicitly. Profit First buckets can enforce discipline later, but allocating a percentage to profit cannot repair negative unit margins.

Recorded receipts of 5,723,000 less matched funding payments of 5,665,500 leave a **ledger residual of 57,500**. This is not a verified bank balance: **4,422,200 of historical expenditures has unassigned funding provenance**, and the backup contains no cash/bank-account records. Reconcile cash, mobile money, bank balances and historical owner funding before setting withdrawal or borrowing limits. Historical unassigned funding is not automatically an unpaid supplier debt.

## 7. Planning the youngest flock and the next placement

Flock 3 has 203 birds remaining and attributed costs of **1,557,055.90** to date. At 19,000 per bird with no further deaths, potential sales are **3,857,000**. To preserve a 10% margin, total cost would need to stay below **3,471,300**, leaving a future-cost allowance of **1,914,244.10**.

That allowance must cover all remaining feed, necessary care, selling/delivery and attributable overhead. It is a budget ceiling under stated assumptions, not a forecast of profit. Reduce expected saleable birds if further mortality is plausible. The database's price, future mortality and remaining-cost forecast inputs are currently blank.

Before approving another placement, require:

1. Expected saleable birds based on credible mortality assumptions, not simply chicks ordered.
2. Full finishing cost and realistic selling price by size/channel.
3. A positive downside case with lower selling price or worse survival, alongside the base case.
4. Buyer commitments and a sell-out plan.
5. Enough cash to finish the flock without depending on emergency borrowing or collections from buyers before their agreed due dates.

Do not scale simply to dilute overhead: increased volume helps only if the extra birds generate positive contribution after their additional costs and can be sold/collected on time. Review staffing and selling effort against useful output, but do not cut brooding supervision or essential care while early mortality is deteriorating.

## 8. Records to confirm before treating results as final

Your confirmation that all costs are captured addresses completeness. These checks concern accuracy, classification and timing:

- `SALE-20260918-0001` and `SALE-20260918-0002` each record 18 birds at 18,500 for the same named buyer on the same day, with different timestamps. Confirm they are two separate deliveries. They may be valid; do not remove one just because it looks similar.
- Expenditures 96 and 99 each record grower feed of 139,500 for Flock 3 on 16 September. Confirm two purchases against invoices and stock. If one is a duplicate it overstates that flock's cost; neither has been excluded in this review.
- Several feed/chick category labels include transport or medication. Clean categories for supplier and unit-cost analysis while preserving real costs.
- Reconcile the 12,000 unallocated repair/pest-control item and the existing 15,000 unlinked legacy input cost. The latter is already included once in the calculations above.
- Only July/August payroll and depreciation are generated in this backup. Include any September costs still to be incurred or allocated in forward budgets and period close; do not assume the current provisional cost is the final finishing cost.
- Finalize period/batch reports after reconciliation. Preserve original records and use documented corrections.

## 9. A practical 30-day turnaround plan

| When | Action | Evidence of completion |
|---|---|---|
| Next 48 hours | Count birds and feed; reconcile cash and the two possible duplicate pairs; pause discretionary drawings | Signed bird/stock/cash reconciliation and verified transactions |
| Next 48 hours | Agree the 114-bird finish-and-sell plan and confirm receivable dates | Written cost-to-finish budget and customer collection schedule |
| This week | Investigate early mortality with a poultry professional; formalize daily/overnight checks | Documented findings, named responsible person and corrective-action log |
| This week | Test cost-covering prices and cash/pickup terms with actual buyers | Confirmed orders or evidence of price resistance, not assumed demand |
| Within two weeks | Reconcile feed stock/usage; record weights; compare feed procurement options | Reliable cost per saleable bird and usable feed/weight records |
| Before another placement | Approve a full-cost budget, realistic margin and funded downside case | Go/no-go decision supported by cash and orders |
| Weekly | Review survival, realized price, forecast finishing cost, days to sell, receivables and cash | One-page management review with actions and owners |
| At flock/period close | Reconcile and lock results | Final batch result, correct allocations and matched funding |

My priority order is **protect the remaining birds, protect cash, improve selling economics, then expand only after demonstrating a repeatable margin**. Treat approximately 22,100 as a cost-derived 10% margin reference for the completed flock, or achieve the equivalent combination of better realized prices and genuine cost efficiency. Do not treat 20,000 as comfortably profitable: on that historical cost base it leaves less than 1% margin.

## Analysis files

- `application_batch_report.json`: application-derived report from the isolated copy, as of the backup date. It includes existing application warnings, some of which are generic/stale; this report's reconciliations take precedence over those generic statements.
- `business_metrics.json`: supporting source-record groupings and transaction review details.
- `analyze_dump.py`, `business_metrics.py`, `reproduce_reports.py`: local analysis scripts. The first expects the finance/poultry COPY extract in the system temporary directory.
- `verify_analysis.py`: independent decimal reconciliation checks; all checks passed.

No live database, application code, financial records or customer communications were changed.
