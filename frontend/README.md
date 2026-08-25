# Farm Management System — Frontend

This is the Next.js (App Router) frontend for the Farm Management System.

## Tech

- Next.js 16 + React 19 + TypeScript
- Tailwind CSS
- React Hook Form + Zod
- Axios / fetch
- lucide-react icons

## Getting Started

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

The frontend expects the backend at the URL configured via `NEXT_PUBLIC_API_BASE_URL` (see root `.env` and root `README.md`).

## Key Routes

- `/` — Module landing (Poultry, Crops placeholder, Goats placeholder)
- `/poultry` — Batch register + dashboard
- `/poultry/batches/[id]` — Full batch detail (overview, flock, costs, sales, mortality, feed, vaccination, growth)
- `/poultry/dashboard` — Aggregated flock visuals and filters
- `/poultry/guides` — Operational + Finance help (zero-knowledge guides)
- `/finance/*` — Employees, Payroll, Labour, Expenses, Consumables, Assets, Monthly, Batch profitability, etc.

## Development

```bash
npm run lint
npx tsc --noEmit
npm run build
```

See the **root `README.md`** for full installation, configuration, architecture, accounting model, and contribution guidelines.

## Authentication

The app uses a Next.js auth BFF that sets HttpOnly cookies. Login flow is at `/login`. Session refresh and idle timeout are configurable via environment variables.

## Important Notes

- Server Components fetch initial data directly from the Django API (using server-only authenticated fetch).
- Client components use proxy routes (`/api/poultry/...`, `/api/finance/...`) for mutations and live refresh.
- All monetary values are handled as `Decimal` on the backend and displayed consistently on the frontend.
