# Web bird stock taking

Open **Poultry → Batches → a batch → Stock taking**. The expected live birds
include received birds, approved flock adjustments, bird sales and mortality.
Enter the physical count, a reason for any difference, and optional count notes.
Supervisors, managers, directors and administrators can confirm counts.
Stakeholders can read the history.

Confirming a shortage creates one negative flock adjustment. Confirming a surplus
creates one positive adjustment. A matching count saves evidence without an
adjustment. The original expected count, physical count, difference, recorder and
server count time remain available in the history. Shortages are separate from
mortality. Existing flock calculations, availability checks, bird-day calculations
and profitability denominators use the resulting adjustment.

Count birds immediately before saving. Counts are recorded at the current server
time; there is no backdating workflow. If the expected balance changed while the
form was open, refresh and verify the physical count. The server locks the batch,
validates its lifecycle and accounting period, and saves the count and adjustment
in one transaction. Retrying the same request cannot apply the shortage twice.
Counts cannot be recorded on a pre-production, closed or finalized batch.

Stock taking does not add a second monetary expense for missing birds: costs
already incurred stay with the batch and are spread over fewer saleable birds.

## Sales costs

Sale-specific transport, packaging and other selling costs already contribute to
finance's `selling_cost`, `total_attributed_cost`, `fully_loaded_batch_profit`
and `management_net_position`. They are recognized whether paid or unpaid.
Gross production profit remains separate from profit after selling costs.

The poultry dashboard now includes those costs in the sale-date period's batch
costs, selling-and-distribution breakdown and profit chart. The batch overview's
fallback net position and full cost include them too. Cancelled sales and their
costs are excluded from those totals.

## Schema and validation

Migration: `poultry.0037_bird_stock_take`. Apply with
`python backend/manage.py migrate` using the deployment's normal environment.

The web API is `GET/POST /api/v1/poultry-management/{batch_id}/stock-takes`.
POST accepts a UUID `request_id`, `expected_live_birds`, `physical_count`, `reason`
and `notes`. Expected stock is always recomputed on the server; the submitted
value is a concurrency check. GET returns current expected birds and count history.
There are no edit or delete endpoints for physical-count evidence.

Validation: 158 poultry/finance regression tests passed on a disposable PostgreSQL
database, along with seven frontend checks and the production web build.
Regression coverage includes matched counts, shortages, surpluses, stale counts,
retries, concurrent counts on PostgreSQL, overselling after a shortage, lifecycle
and permission restrictions, and sale-cost reporting. No mobile screens or
offline command contracts are added.
