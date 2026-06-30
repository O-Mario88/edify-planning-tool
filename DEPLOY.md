# Deploying the Edify Planning & Monitoring Tool

The Edify Planning & Monitoring Tool is a unified **Django + HTMX + Alpine.js** monolith. It runs on a single server, managing both frontend views and backend API routes.

## Local Quick Start (Docker Compose)

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and configure:
   - `POSTGRES_PASSWORD` (set a strong password)
   - `JWT_SECRET` (generate using `openssl rand -base64 48`)
   - `SUPER_ADMIN_PASSWORD` (for the primary admin account)
3. Build and launch:
   ```bash
   RUN_SEED=true docker compose up --build
   ```
   - Serving on: http://localhost:4000
   - Seed data: Setting `RUN_SEED=true` runs the initial migrations and seeds reference/demo data. Subsequent runs should omit `RUN_SEED` or set it to `false`.

---

## Deploying on Railway

Deploying is extremely simple since there is only **one web application** to run.

### Project Topology

1. **Postgres** (Railway's managed Postgres plugin)
2. **web** (Django monolith) - builds from repository root `/`, exposed via a custom domain.

### 1 — Postgres
Add the Postgres plugin to your project. Railway will expose its connection string as `${{Postgres.DATABASE_URL}}`.

### 2 — web (Django application)
Add a web service connected to your repository.
Configure it with a public domain, and specify these environment variables:

```
NODE_ENV=production
DJANGO_SETTINGS_MODULE=config.settings.prod
PORT=4000
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET=<strong-secret-key>
JWT_EXPIRES_IN=12h
AUTHZ_MODE=enforce              # Fail-closed auth enforcement
ENABLE_MOCK_DATA=false          # Safety gates check
ENABLE_DEV_ENDPOINTS=false      # Safety gates check
DEMO_LOGIN_PASSWORD=<strong>    # Initial password for seeded demo accounts
SUPER_ADMIN_EMAIL=domario@edify.org
SUPER_ADMIN_PASSWORD=<strong>   # Primary administrator password
EVIDENCE_STORAGE_DIR=/data/evidence
RUN_SEED=true                   # First deploy only, then remove
```

- **Volume:** Attach a Railway volume mounted at `/data` to ensure evidence files stored at `/data/evidence` survive restarts.
- **Port:** Expose port `4000` to public traffic.

---

## Standalone Commands (Local Python Virtual Environment)

If running without Docker:

```bash
# Create and activate python virtual environment
python -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements/dev.txt

# Run migrations & seed database
python manage.py migrate
python manage.py seed --demo

# Run development server
python manage.py runserver 4000
```
