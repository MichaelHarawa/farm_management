# Farm Management System

Farm Management System is a Django + Next.js application for tracking farm production by module. The current live module is Poultry, with Crops and Goats represented as planned module workspaces.

## Current System Scope

The system currently supports:

- A module landing workspace at `http://localhost:3000`
- A poultry batch register at `http://localhost:3000/poultry`
- A poultry batch detail workspace at `http://localhost:3000/poultry/batches/[id]`
- Backend API documentation at `http://localhost:7070/api/v1/docs/`
- Django admin at `http://localhost:7070/admin/`

## Live Modules

### Poultry

The Poultry module is the active production workspace. It supports:

- Batch registration and listing
- Batch detail review
- Input cost recording
- Sales and collection recording
- Flock movement summaries
- Cost summaries by category
- Sales collection summaries
- Net position and gross position calculations in the frontend
- Operational readouts for quantity, maturity timing, sales, input costs, mortality, feed usage, and balances

### Planned Modules

The landing page also displays future workspaces:

- Crops: season planning workspace
- Goats: herd activity workspace

These modules are currently UI placeholders and do not yet have backend models or routes.

## Frontend Operations

The frontend lives in `frontend/` and is built with Next.js, React, TypeScript, Tailwind CSS, React Hook Form, Zod, Axios/fetch, and lucide-react icons.

Current frontend routes:

| Route | Purpose |
| --- | --- |
| `/` | Executive module landing page with Poultry, Crops, and Goats module cards |
| `/poultry` | Poultry production command view and batch portfolio table |
| `/poultry/batches/[id]` | Batch detail workspace with overview, flock, costs, sales, mortality, and feed usage views |
| `/api/poultry/batches/[id]/input-costs` | Next.js server route that proxies input cost creation to Django |
| `/api/poultry/batches/[id]/sales` | Next.js server route that proxies sale creation to Django |
| `/api/poultry/batches/[id]/mortality` | Next.js server route that proxies mortality creation to Django |
| `/api/poultry/batches/[id]/feed-usage` | Next.js server route that proxies feed usage creation to Django |

Current frontend poultry features:

- Reads poultry batches from the Django API.
- Displays a batch portfolio table with flock size, placement date, maturity date, status, and a view icon under `Readout`.
- Opens detailed batch workspaces from the register.
- Displays batch production information, current birds, sold birds, mortality, input cost totals, sales totals, feed usage, cash collected, outstanding balances, and net position.
- Records input costs through a form with purchase date, item, category, package count, package size, unit measurement, and cost per unit.
- Records sales through a form with sale date, product type, quantity sold, unit price, buyer details, payment status, payment method, amount paid, balance, seller, and notes.
- Records mortality through a form with mortality date, quantity dead, age in days, suspected cause, description, action taken, and reporter name.
- Records feed usage through a form with flock age, feeding dates, feed type, source, quantity, unit, current bird count, notes, and reporter name.
- Records vaccinations and drugs with administration date, vaccine type, conditional other-vaccine name, quantity, notes, reporter name, and an auto-calculated timely status.
- Recalculates available live birds as initial birds less sold birds and recorded mortality.

### Finance And Profitability

The Finance module adds workforce management, payroll snapshots, cost allocation,
batch profitability, monthly profitability, receivables, and business-intelligence
warnings. Backend services perform the authoritative financial calculations with
`Decimal`; frontend pages format and display returned values.

Current frontend finance routes:

| Route | Purpose |
| --- | --- |
| `/finance` | Dashboard for active batch exposure, closed-batch profit, receivables, and warnings |
| `/finance/employees` | Create linked system users and employee profiles; review salary allocation splits |
| `/finance/payroll` | Generate payroll snapshots, recalculate allocations, and close periods |
| `/finance/labour` | Record ad-hoc labour payments by cost scope |
| `/finance/expenses` | Record shared, admin, selling, finance, capital, tax, and other expenses |
| `/finance/monthly` | Monthly farm profitability report |
| `/finance/batches/[id]` | Batch profitability report |

The frontend expects `NEXT_PUBLIC_API_BASE_URL` to point to the Django API version root. For local development this is typically:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:7070/api/v1
```

## Backend Operations

The backend lives in `backend/` and is built with Django, Django REST Framework, drf-spectacular, PostgreSQL, and django-environ.

Current backend API root:

```text
http://localhost:7070/api/v1/
```

Current poultry API base:

```text
http://localhost:7070/api/v1/poultry-management
```

Current backend routes:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health/` | Health check |
| `GET` | `/api/v1/docs/` | Swagger API documentation |
| `GET` | `/api/v1/schema/` | OpenAPI schema |
| `GET` | `/api/v1/poultry-management` | List poultry batches |
| `POST` | `/api/v1/poultry-management` | Create a poultry batch |
| `GET` | `/api/v1/poultry-management/{id}` | Retrieve one poultry batch |
| `GET` | `/api/v1/poultry-management/{id}/input_costs` | List input costs for a batch |
| `POST` | `/api/v1/poultry-management/{id}/input_costs` | Create an input cost for a batch |
| `GET` | `/api/v1/poultry-management/{id}/feed_input_costs` | List feed-related input costs filtered by category |
| `GET` | `/api/v1/poultry-management/{id}/sales` | List sales for a batch |
| `POST` | `/api/v1/poultry-management/{id}/sales` | Create a sale for a batch |
| `GET` | `/api/v1/poultry-management/{id}/mortality` | List mortality records for a batch |
| `POST` | `/api/v1/poultry-management/{id}/mortality` | Create a mortality record for a batch |
| `GET` | `/api/v1/poultry-management/{id}/feed_usage` | List feed usage records for a batch |
| `POST` | `/api/v1/poultry-management/{id}/feed_usage` | Create a feed usage record for a batch |
| `GET` | `/api/v1/poultry-management/{id}/drugs_vaccine` | List vaccination and drug records for a batch |
| `POST` | `/api/v1/poultry-management/{id}/drugs_vaccine` | Create a vaccination or drug record for a batch |

Current finance API routes:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET/POST` | `/api/v1/finance/employees` | List or create employee profiles and linked system users |
| `GET/PATCH` | `/api/v1/finance/employees/{id}` | Retrieve or edit employee details |
| `POST` | `/api/v1/finance/employees/{id}/activate` | Activate employee and linked user |
| `POST` | `/api/v1/finance/employees/{id}/deactivate` | Deactivate employee and linked user |
| `GET/POST` | `/api/v1/finance/accounting-periods` | List or create accounting periods |
| `POST` | `/api/v1/finance/accounting-periods/{id}/generate-payroll` | Generate monthly permanent-employee payroll snapshots |
| `POST` | `/api/v1/finance/accounting-periods/{id}/recalculate` | Recalculate bird-day snapshots and unlocked allocations |
| `POST` | `/api/v1/finance/accounting-periods/{id}/close` | Close a period and lock allocations |
| `GET/POST` | `/api/v1/finance/payroll-entries` | Manage payroll entries |
| `GET/POST` | `/api/v1/finance/ad-hoc-labour` | Manage temporary and ad-hoc labour payments |
| `GET/POST` | `/api/v1/finance/expenses` | Manage shared expenses |
| `GET` | `/api/v1/finance/reports/monthly?period=YYYY-MM` | Monthly profitability report |
| `GET` | `/api/v1/finance/reports/batches/{batch_id}` | Batch profitability report |
| `GET` | `/api/v1/finance/dashboard` | Dashboard indicators and warnings |
| `GET` | `/api/v1/finance/receivables` | Open customer receivables |

## Poultry Data Model

### Batch

Tracks a poultry production cycle.

Important fields:

- `batch_id`: generated as `BATCH-YYYYMMDD-0001`
- `bird_type`: broilers, layers, local, kloilers, or mikolongwe
- `source`: `proto`, `central_poultry`, or `other`
- `source_other`: manually entered source name when `source` is `other`
- `entry_date`
- `expected_maturity_date`
- `quantity`
- `created_at`
- `updated_at`

### Input Costs

Tracks costs attached to a batch.

Important fields:

- `item`
- `category`
- `quantity`
- `unit`
- `unit_measurement`
- `unit_cost`
- `purchase_date`
- `notes`

The frontend calculates estimated totals from:

```text
quantity * unit * unit_cost
```

The backend exposes the same calculation as `direct_input_total`.

### Sales

Tracks sales and collections attached to a batch.

Important fields:

- `sale_id`: generated as `SALE-YYYYMMDD-0001`
- `sale_date`
- `product_type`: live chicken, dressed chicken, eggs, or manure
- `quantity_sold`
- `unit_price`
- `buyer_name`
- `buyer_type`
- `payment_status`
- `payment_method`
- `amount_paid`
- `balance`
- `sold_by_name`
- `notes`

Sales integrity rules:

- `sale_total = quantity_sold * unit_price`
- `balance = sale_total - amount_paid`
- `PAID`, `PARTIAL`, and `UNPAID` are normalized from payment amount and balance
- `CANCELLED` sales are excluded from revenue, birds sold, cash collected, receivables, and closure
- only live chicken and dressed chicken reduce the live-bird balance
- eggs and manure generate revenue without reducing live birds

Batch closure uses:

```text
remaining_live_birds =
  initial_batch_quantity
  - valid_bird_units_sold
  - recorded_mortality
```

A batch closes automatically only when `remaining_live_birds == 0`. Sale and
mortality creation use database transactions and row locking to prevent
overselling.

## Management Accounting Definitions

Batch revenue is the sum of valid non-cancelled sales linked to the batch,
including eggs and manure revenue. Customer cash collected is valid sales
`amount_paid`. Accounts receivable is valid sales `balance`.

Direct batch cost is input costs plus batch-direct temporary labour plus directly
assigned production expenses. Allocated production cost is permanent production
payroll, shared production temporary labour, and shared production overhead
allocated through auditable `CostAllocation` rows.

```text
total_production_cost = direct_batch_cost + allocated_production_cost
batch_gross_profit = batch_revenue - total_production_cost
fully_loaded_batch_profit =
  batch_gross_profit
  - directly attributable selling costs
  - separately disclosed administration allocation
```

Administration is displayed separately and is not hidden inside production cost.
Gross margin, fully loaded margin, mortality rate, and collection rate return
`null` when the denominator is zero.

Active and selling batches are labelled `PROVISIONAL`:

```text
provisional_saleable_birds =
  valid_bird_units_already_sold + remaining_live_birds

provisional_cost_per_saleable_bird =
  accumulated_production_cost / provisional_saleable_birds
```

Closed batches are labelled `FINAL`; their final profitability snapshot is
created once and protected from casual overwrite.

Monthly profitability separates profitability, cash movement, receivables, and
active-batch work in progress. Cash flow is not presented as net profit.

## Bird-Day Allocation

Shared production payroll, shared production labour, and shared production
overhead use bird-days by default. For each day in an accounting period:

```text
daily_average_live_birds =
  (opening_live_birds + closing_live_birds) / 2

daily_bird_days = daily_average_live_birds
```

Mortality and valid bird sales apply to closing balance on their transaction
date. Cancelled sales are excluded.

Worked example:

| Batch | Average live birds | Active days | Bird-days |
| --- | ---: | ---: | ---: |
| A | 180 | 30 | 5,400 |
| B | 250 | 20 | 5,000 |

For MWK 600,000 of shared production salary:

```text
Batch A = 600,000 * 5,400 / 10,400 = 311,538.46
Batch B = 600,000 * 5,000 / 10,400 = 288,461.54
```

Rounded allocations reconcile exactly to the source amount with a deterministic
remainder rule.

## Payroll, Labour, Expenses, And Permissions

Permanent employees are represented by `EmployeeProfile`, linked one-to-one to
the existing `accounts.User`. Roles remain the existing user-role system.
Employee allocation percentages must total 100%.

Payroll entries are monthly snapshots, so historical reports do not change when
an employee's current salary changes later.

Ad-hoc labour scopes:

- `BATCH_DIRECT`: assigned fully to one batch
- `SHARED_PRODUCTION`: allocated by bird-days
- `FARM_ADMINISTRATION`: monthly operating expense, not batch production cost
- `SELLING_AND_DISTRIBUTION`: assigned directly when possible, otherwise revenue share

Shared expenses separate production, administration, selling, finance, capital,
tax, and other scopes. Capital expenditure is isolated from ordinary operating
expense totals.

Finance permissions use existing roles:

- `admin`, `director`, and `farm_manager`: manage finance data and close periods
- `farm_supervisor`: record operational finance data but cannot close periods
- `stake_holder`: read-only report and dashboard access

### Mortality

Tracks bird mortality events.

Important fields:

- `mortality_date`
- `quantity_dead`
- `age_in_days`
- `suspected_cause`
- `description`
- `action_taken`
- `reported_by_name`

### Feed Usage

Tracks feed given to a batch.

Important fields:

- `initial_age`
- `feeding_start_date`
- `feeding_end_date`
- `feed_type`
- `feed_source`
- `quantity_given`
- `unit_of_measurement`
- `current_number_of_birds`
- `notes`
- `reported_by_name`

### Drugs And Vaccination

Tracks vaccine and drug administration against the batch care schedule.

Important fields:

- `vaccination_date`
- `drug_vaccination_type`: hitchner, gumbolo, lasota, or other
- `other_drug_vaccination`: only used when type is other
- `quantity`
- `description`
- `timely_status`: calculated by the frontend against the expected schedule
- `reported_by_name`

Default schedule:

- Hitchner: 7 days after chick arrival
- Gumbolo: 14 days after chick arrival
- Lasota: 21 days after chick arrival

## Local Development

### Backend

From the repository root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python backend/manage.py migrate
python backend/manage.py runserver 0.0.0.0:7070
```

When running Django commands from the Windows host while Docker exposes Postgres
on `localhost:5437`, override the Docker-only database host:

```powershell
$env:POSTGRES_HOST='localhost'
$env:POSTGRES_PORT='5437'
```

### Frontend

From `frontend/`:

```powershell
npm.cmd install
npm.cmd run dev
```

Open:

```text
http://localhost:3000
```

### Docker Backend and Database

The `docker/docker-compose.yml` file can run the Django backend and PostgreSQL database:

```powershell
docker compose -f docker/docker-compose.yml up --build
```

This starts:

- Django backend on `http://localhost:7070`
- PostgreSQL exposed on host port `5437`

## Environment Variables

The backend reads environment settings from `.env`.

Required database variables include:

```env
POSTGRES_DB=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_HOST=
POSTGRES_PORT=
```

Common Django variables include:

```env
DJANGO_SECRET_KEY=
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
```

The frontend requires:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:7070/api/v1
```

## Quality Checks

Frontend checks:

```powershell
cd frontend
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd run build
```

Backend checks:

```powershell
python backend/manage.py check
python backend/manage.py test
```

Finance-focused backend tests:

```powershell
python backend/manage.py test apps.finance.tests
```

Manual finance smoke test:

1. Create an accounting period through Django admin or `POST /api/v1/finance/accounting-periods`.
2. Open `/finance/employees` and create an employee with salary, allocation split, and role.
3. Open `/finance/payroll`, generate payroll, recalculate allocations, and close the period when ready.
4. Record ad-hoc labour in `/finance/labour`.
5. Record shared expenses in `/finance/expenses`.
6. Create poultry mortality and valid bird sales until a batch reaches zero remaining birds.
7. Review `/finance/batches/{batch_id}` for provisional or final profitability.
8. Review `/finance/monthly` for profitability, cash movement, receivables, WIP, and warnings.
9. Log out and confirm finance pages redirect through the existing auth flow.
10. Sign in as a stakeholder and confirm write actions are rejected by the backend.

## Project Structure

```text
backend/
  apps/
    accounts/
    inventory/
    poultry/
    finance/
  config/
  manage.py

frontend/
  src/
    app/
    features/
      poultry/
      finance/
    lib/

docker/
  docker-compose.yml
  Dockerfile
```

## Current Notes

- Poultry and Finance are the live operating modules.
- Crops and Goats are represented on the landing page as future modules.
- The frontend uses a themed executive layout with cream, navy, and gold styling.
- The batch detail workspace is designed around summary cards and tabbed operational views rather than placing every form and table into one long page.
- Input cost, sales, mortality, feed usage, and finance mutations are routed through local Next.js API routes before being forwarded to the Django API.
