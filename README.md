# Farm Management System

A modern, full-stack farm operations platform for tracking production, costs, revenue, and profitability across farm modules. The system separates **operational tracking** (poultry batches, mortality, feed, vaccinations) from **management accounting** (profitability, allocations, cash flow, depreciation, and period reporting).

Currently, the **Poultry** module is fully operational. A rich **Finance** module provides employee management, payroll, ad-hoc labour, consumables, fixed assets with depreciation, shared expense allocation, and batch-level profitability reporting. Crops and Goats are planned future modules shown as placeholders.

**Live at**:
- Frontend: http://localhost:3000
- Backend API: http://localhost:7070/api/v1/
- API docs: http://localhost:7070/api/v1/docs/
- Django Admin: http://localhost:7070/admin/

---

## Table of Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Prerequisites & Dependencies](#prerequisites--dependencies)
- [Getting Started](#getting-started)
  - [Local Development (Backend)](#local-development-backend)
  - [Local Development (Frontend)](#local-development-frontend)
  - [Docker (Recommended for Backend + DB)](#docker-recommended-for-backend--db)
- [Configuration](#configuration)
- [Usage Guide](#usage-guide)
- [API Overview](#api-overview)
- [Financial & Accounting Model](#financial--accounting-model)
- [Testing & Quality Checks](#testing--quality-checks)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Project Overview

The Farm Management System enables precise operational control and transparent financial reporting for small-to-medium farms. 

Core principles:
- **Separation of concerns**: Operational records (sales, mortality, feed, input costs) feed into authoritative accounting calculations performed in the backend.
- **Provisional vs Final**: Active/selling batches show provisional results; closed batches have immutable final snapshots.
- **Auditability**: All shared costs, payroll, depreciation, and allocations are stored as explicit rows (`CostAllocation`) rather than ad-hoc redistribution.
- **Cash vs Profit distinction**: Revenue utilization (where batch cash was spent) is tracked separately from profitability.

The system currently focuses on poultry production with integrated farm-wide finance.

---

## Key Features

### Poultry Module
- Batch registration, status lifecycle (booked → planned → delivered → active → selling → closed)
- Input costs, sales (with payment tracking and balances), mortality, feed usage, vaccinations
- Automatic live-bird reconciliation and closure rules
- Growth tracking with Ross 308 / Cobb 500 target curves + severity alerts
- Flock dashboard with filters, status pie, bars for birds by type, sales, mortality, feed

### Finance & Accounting Module
- Employee profiles linked to system users with salary splits (production / admin / selling)
- Accounting periods with open/recalculate/close workflow
- Payroll generation and bird-day allocation
- Ad-hoc labour, shared expenses, consumable lots + usage recognition
- Fixed assets, categories, straight-line and units-of-production depreciation
- Asset maintenance, replacement reserves, impairment, disposal
- Batch profitability reports (revenue, direct costs, allocated costs, gross/net profit, provisional/final)
- Monthly farm profitability, receivables, warnings
- Cost allocation engine using bird-days (or other drivers) with exact reconciliation

### Cross-cutting
- JWT + cookie-based auth with role-based permissions
- Decimal-precise money handling (no floats)
- USD reference capture for inflation/purchasing power analysis
- Comprehensive OpenAPI docs (drf-spectacular)

---

## Architecture

- **Backend**: Django 6 + Django REST Framework (DRF) + drf-spectacular. Services encapsulate complex calculations (profitability, allocations, depreciation). Models use `Decimal` for all monetary fields.
- **Frontend**: Next.js 16 (App Router) + React 19 + TypeScript. Server Components fetch initial data; client components handle forms and interactivity via proxy API routes (`/api/...`).
- **Auth**: Django issues JWTs; Next.js BFF manages secure HttpOnly cookies and session refresh.
- **Database**: PostgreSQL. Row-level locking + database transactions protect against concurrent overselling / over-allocation.
- **Deployment**: Docker Compose for backend + Postgres (dev). Frontend runs via `npm run dev` or production build.

Data flows:
1. Operational events (sales, mortality, feed, costs) recorded via poultry APIs.
2. Finance services compute direct + allocated costs using stored allocation rows.
3. Reports and batch detail pages consume authoritative snapshots / live calculations.

---

## Technology Stack

**Backend**
- Python 3.12+
- Django 6.0
- Django REST Framework + drf-spectacular (OpenAPI)
- PostgreSQL + psycopg2
- python-decouple, django-environ

**Frontend**
- Next.js 16 (App Router)
- React 19, TypeScript
- Tailwind CSS 4
- React Hook Form + Zod
- Axios / fetch
- lucide-react icons
- @tanstack/react-table (some tables)

**Dev / Ops**
- Docker + docker-compose
- PowerShell / bash scripts for local runs
- ESLint, TypeScript compiler, Next build
- Django `check`, `test`, migrations

---

## Prerequisites & Dependencies

**Backend**
- Python 3.12+
- PostgreSQL (local or via Docker)
- `pip install -r requirements.txt`

**Frontend**
- Node.js 20+ (LTS recommended)
- npm (or yarn/pnpm/bun)

**Docker (optional but recommended)**
- Docker Desktop / Docker Engine + Compose v2

Full pinned dependencies are in:
- `requirements.txt` (backend)
- `frontend/package.json` (frontend)

---

## Getting Started

### Local Development (Backend)

```powershell
# From repo root
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# If using host Postgres (Docker exposes on 5437)
$env:POSTGRES_HOST='localhost'
$env:POSTGRES_PORT='5437'

python backend/manage.py migrate
python backend/manage.py runserver 0.0.0.0:7070
```

API will be available at http://localhost:7070

### Local Development (Frontend)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### Docker (Recommended for Backend + DB)

```powershell
docker compose -f docker/docker-compose.yml up --build
```

Starts:
- Django on http://localhost:7070 (auto-migrates on start)
- Postgres on host port 5437

Frontend still runs separately with `npm run dev` in `frontend/`.

---

## Configuration

Create a `.env` file in the repository root (loaded by both Django and Docker).

**Required (Database)**
```env
POSTGRES_DB=yourdb
POSTGRES_USER=youruser
POSTGRES_PASSWORD=yourpassword
POSTGRES_HOST=db          # or localhost when running outside Docker
POSTGRES_PORT=5432
```

**Django**
```env
DJANGO_SECRET_KEY=your-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
```

**Frontend**
```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:7070/api/v1
```

**Auth (optional tuning)**
```env
AUTH_IDLE_TIMEOUT_SECONDS=7200
AUTH_REFRESH_TOKEN_MAX_AGE_SECONDS=43200
```

Backend also supports `SECRET_KEY`, `DEBUG`, etc. via `python-decouple`.

---

## Usage Guide

1. Start backend + frontend (or Docker backend).
2. Create users/roles via Django admin or the employee creation flow.
3. Create an **Accounting Period** before recording payroll, labour, consumables, or depreciation.
4. Use `/poultry` to register batches and record daily operations.
5. Use `/finance` pages for:
   - Employees & salary splits
   - Payroll generation + allocation
   - Ad-hoc labour, expenses, consumables
   - Assets + depreciation runs
   - Batch and monthly profitability reports

See the in-app guides at `/poultry/guides` for step-by-step operational instructions.

---

## API Overview

- Interactive docs: http://localhost:7070/api/v1/docs/
- OpenAPI schema: http://localhost:7070/api/v1/schema/

Major groups:
- `poultry-management/` — batches + input_costs, sales, mortality, feed_usage, drugs_vaccine, weight_samples
- `finance/` — employees, accounting-periods, payroll, ad-hoc-labour, expenses, consumables, assets, reports
- `auth/` — login, logout, session, refresh

All monetary values use `Decimal` (serialized as strings or numbers with proper precision). Lists are paginated where appropriate.

Proxy routes under `/api/poultry/...` and `/api/finance/...` in the Next.js app forward authenticated requests.

---

## Financial & Accounting Model

The system distinguishes:
- **Revenue & Cash**: `recognized_revenue`, `cash_collected`, receivables.
- **Profitability**: Direct costs + allocated operating costs + depreciation → gross and net profit. Active batches are provisional.
- **Allocation**: Bird-day (or other driver) based `CostAllocation` rows for shared costs. Exact remainder reconciliation is enforced.
- **Cash vs Accounting**: Consumable lots stay in inventory until usage is recognized. Capital items are capitalized and depreciated.

Full details and worked examples are documented in the current root README (sections on Bird-Day Allocation, Consumables, Assets, Payroll, etc.) and the batch/monthly finance reports.

---

## Testing & Quality Checks

**Frontend**
```powershell
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

**Backend**
```powershell
cd backend
python manage.py check
python manage.py test
python manage.py test apps.finance.tests
```

Always run migrations after model changes and verify that existing batch totals and finance snapshots remain correct.

---

## Project Structure

```
.
├── backend/
│   ├── apps/
│   │   ├── accounts/     # Users, roles, auth
│   │   ├── poultry/      # Batches, sales, costs, mortality, feed, growth
│   │   ├── finance/      # Employees, payroll, assets, consumables, allocations, reports
│   │   └── inventory/
│   ├── config/           # Django settings, urls
│   └── manage.py
├── frontend/
│   ├── src/app/          # Next.js App Router pages + API routes (BFF)
│   ├── src/features/     # poultry/ and finance/ domain logic & UI
│   └── ...
├── docker/
│   ├── docker-compose.yml
│   └── Dockerfile
├── docs/
└── requirements.txt
```

---

## Contributing

1. Fork the repository and create a feature branch.
2. Follow existing code style and patterns (Django services for calculations, server components for initial data, client-safe mutations via proxy routes).
3. Add or update tests for any financial or allocation logic.
4. Run full lint, typecheck, build, and test suites before submitting a PR.
5. Document new API endpoints in the OpenAPI schema (they appear automatically via drf-spectacular).
6. For finance changes, include migration notes and example calculations in the PR description.

Please keep profit/cash distinctions clear and preserve backward compatibility for existing batch reports.

---

## License

This project is currently unlicensed / internal. Add an appropriate open-source license if you intend to publish.

---

**For the most up-to-date operational and accounting details, also consult the in-app help (`/poultry/guides`) and the existing detailed sections in this README (Poultry Data Model, Management Accounting Definitions, Integrated Finance User Manual, Bird-Day Allocation, etc.).**
