# Vercel deployment

The root `vercel.json` configures a Vercel Services deployment with the Next.js
frontend at `/` and Django API at `/api/v1`. The frontend calls Django through a
private service binding for its server-side API routes.

## Vercel project setup

1. Connect the repository to a Vercel project and set its framework preset to
   **Services**.
2. Provision a hosted PostgreSQL database, such as a Neon database from the
   Vercel Marketplace, and connect it to the project.
3. Add these production environment variables:
   - `DATABASE_URL`: the hosted PostgreSQL connection string, with SSL enabled.
   - `DJANGO_SECRET_KEY`: a new, private Django secret key.
   - `JWT_SIGNING_KEY`: a separate, new secret used to sign access tokens.
   - `DJANGO_DEBUG`: `False`.
   - `DJANGO_ALLOWED_HOSTS`: the exact Vercel production hostname, plus any
     custom hostname, comma-separated and without `https://`.
4. Deploy. The backend reads the private URL supplied by the service binding;
   do not set `BACKEND_SERVICE_URL` manually.

## First deployment

The hosted database is independent of the local development database and starts
empty. Apply Django migrations to it before signing in, then create an initial
administrator account. Existing farm records and users are not copied
automatically.

Keep the database connection string and both signing keys in Vercel environment
settings. Do not commit them to the repository.
