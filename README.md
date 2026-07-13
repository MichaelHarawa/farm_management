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

## Project Structure

```text
backend/
  apps/
    accounts/
    inventory/
    poultry/
  config/
  manage.py

frontend/
  src/
    app/
    features/
      poultry/
    lib/

docker/
  docker-compose.yml
  Dockerfile
```

## Current Notes

- Poultry is the only live operating module.
- Crops and Goats are represented on the landing page as future modules.
- The frontend uses a themed executive layout with cream, navy, and gold styling.
- The batch detail workspace is designed around summary cards and tabbed operational views rather than placing every form and table into one long page.
- Input cost, sales, mortality, and feed usage creation are routed through local Next.js API routes before being forwarded to the Django API.
