# edify-api (Django + DRF)

The Edify Planning & Monitoring backend, rebuilt in **Django 5 + Django REST
Framework** (replacing the previous NestJS + Prisma backend). The School
Directory is the source of truth; ~200 endpoints across 33 domain apps; JWT
access + rotating refresh tokens; a 38-key RBAC permission matrix with
data-access scope resolution; a tamper-evident audit hash-chain; realtime SSE;
and 7 background jobs (weekly fund requests, monthly work plans, notification
escalation, daily digest, target-ledger sync, PD reminders, and recurring
field-debrief issue detection — see `apps/realtime/registry.py`).

## Stack

- **Python 3.13**, Django 5.2, DRF 3.16, `drf-spectacular` (OpenAPI at `/api/docs`)
- **PostgreSQL** (psycopg 3) — the legacy ran Postgres via Prisma
- **JWT** (`PyJWT`) access tokens (15m) + rotating revocable refresh (7d, SHA-256 hashed)
- **bcrypt** password hashing (parity with the legacy bcryptjs cost 12)
- **django-apscheduler** — in-process background jobs (parity with the NestJS `@Cron` worker)
- **daphne** (ASGI) — required for the realtime SSE stream + scheduler
- **cryptography** — AES-256-GCM field-level encryption
- **LibreOffice** (optional, headless) — evidence DOCX→PDF rendition

## Quick start

```bash
cd edify-api
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements/dev.txt

# Postgres must be running. Configure via DATABASE_URL or POSTGRES_* env vars:
export DATABASE_URL="postgresql://edify:edify@localhost:5432/edify_pm"
export JWT_SECRET="dev-secret-12345678"   # ≥16 chars in prod
export NODE_ENV=development
export PORT=4000

python manage.py migrate
python manage.py seed                    # REFERENCE DATA ONLY (permissions). Safe on every deploy.
# Local development only — demo accounts + sample data (refuses production):
python manage.py seed --demo             # demo users + geography + 700 schools/SSA/partners
python manage.py runserver               # or: daphne -b 0.0.0.0 -p 4000 config.asgi:application
```

> **CORE RULE: the database is the only runtime source of truth.** Production
> must never contain demo/mock data. `seed` alone seeds only the RBAC permission
> matrix; `seed --demo` is local-only and refuses to run in production. Real
> operational data arrives through backend upload/admin workflows.

## Data source of truth — local vs production

**Local development:**
```bash
# Upload test data into the LOCAL database (never fabricated in code):
python manage.py seed --demo                # demo accounts + sample schools/SSA (local only)
python manage.py import_schools_local schools.csv    # CSV → School rows (tagged source=local_test_upload)
python manage.py import_ssa_local ssa.csv            # CSV → SSA records; updates readiness
python manage.py purge_local_test_data --yes         # remove local-test records (keeps reference data)
python manage.py audit_mock_data                    # scan for mock/demo leakage
```

**Production:**
- Deploys with **reference data only** (permissions). No demo schools/users/SSA.
- The dev-only commands (`seed --demo`, `import_*_local`, `purge_local_test_data`)
  **refuse to run in production**.
- Real data is uploaded through the backend API / admin / `ALLOW_PRODUCTION_IMPORTS`
  workflows after deployment.
- Production gates (`config/settings/prod.py`) fail-closed if `ENABLE_MOCK_DATA`,
  `ENABLE_DEV_SEED`, `ENABLE_DEV_IMPORTS`, or `PARTNER_ROLE_BRIDGE` are on.


The API is served at `http://localhost:4000/api` (global `/api` prefix, matching
the legacy contract). OpenAPI docs at `/api/docs` (non-production).

## Demo accounts (local development only — shared `DEMO_LOGIN_PASSWORD`, default `edify`)

Created by `seed --demo` (refuses production). Production creates real users
through the admin user-management workflow.

| Email | Role |
|---|---|
| `admin@edify.org` | Admin |
| `cd@edify.org` | CountryDirector |
| `ia@edify.org` | ImpactAssessment |
| `rvp@edify.org` | RegionalVicePresident |
| `accountant@edify.org` | ProgramAccountant |
| `hr@edify.org` | HumanResources |
| `coordinator@edify.org` | ProjectCoordinator |
| `partner@edify.org` | PartnerFieldOfficer |
| `pl1..4@edify.org` | CountryProgramLead |
| `cceo@edify.org`, `cceo1..19@edify.org` | CCEO |
| `domario@edify.org` | super-admin (password from `SUPER_ADMIN_PASSWORD` env only) |

## Browser tests (Playwright)

The journeys and the role route audit in `e2e/` run against a real server on a
demo-seeded database, the way CI runs them:

```bash
python manage.py migrate && python manage.py seed --demo
RATE_LIMIT_LOGIN_PER_MIN=1000 python manage.py runserver 127.0.0.1:8000 --noreload
npx playwright test --project=chromium-desktop           # or one spec: npx playwright test e2e/<name>.spec.js
```

- Every browser project depends on the `seeded-accounts` setup project, which
  signs each seeded account in once and clears its first-login agreements, so
  any spec, shard or project can run on its own. It runs in Chromium, and only
  against a server on this machine.
- Sign-in allows 10 attempts a minute per address. A browser run needs far more,
  so raise `RATE_LIMIT_LOGIN_PER_MIN` for the test server; otherwise the sign-in
  helper waits out each window.
- CI runs `chromium-desktop` (journeys and the authenticated route audit) in two
  shards on every push, each with its own database and server
  (`.github/workflows/browser-suite.yml`). Firefox, WebKit and the phone and
  tablet projects run nightly in **Browser Matrix**
  (`.github/workflows/browser-matrix.yml`), which can also be started by hand.

## Domain apps (`apps/`)

| App | Purpose |
|---|---|
| `core` | CUID/soft-delete bases, pagination envelope, request-context + exception middleware, RBAC matrix, ScopeService, FY/crypto/email/throttle |
| `accounts` | User, RBAC (Permission/RolePermission), StaffProfile, JWT auth |
| `geography` | Uganda admin hierarchy (Region→District→SubCounty→Parish→Village) |
| `schools` | School Directory (source of truth) + bulk upload + duplicates |
| `clusters` | School grouping, sub-county uniqueness, intelligence |
| `ssa` | School Self-Assessment upload, QA provenance, readiness recompute |
| `activities` | The 21-state field-work lifecycle |
| `budget` | Cost spine + the automatic costing engine |
| `partners` | Partner-org directory + self-service |
| `assignment` | Direct-support capacity + assignment policy |
| `evidence` | Secure multipart file pipeline (5-gate validation + DOCX→PDF) |
| `planning` | Plan authoring + scheduling + lifecycle |
| `fund_requests` | The Budget→Fund Request approval chain |
| `monthly_work_plan` | CD→RVP monthly budget routing |
| `core_schools` | Core/Champion pipeline (polymorphic slot actions) |
| `projects` | Special projects |
| `messaging` / `notifications` | In-app threads + per-user rail |
| `hr` / `debriefs` / `targets` / `reports` / `flags` / `pl_review` | Operations |
| `command_center` / `filters` / `search` / `my_plan` / `system_health` / `security` | Surfaces |
| `admin_users` | Account provisioning + invite lifecycle |
| `analytics` | Role-scoped summaries + SSA performance + correlation |
| `leadership` / `budget_intelligence` | The two decision engines |
| `audit` / `realtime` | Audit hash-chain + DomainEvent seam + SSE + jobs |

## Key contracts (must match the legacy)

- **`/api` global prefix**, no trailing slashes on routes (`/api/schools`, `/api/auth/login`)
- **`Paginated<T>` envelope**: `{data, page, pageSize, total, totalPages}`
- **Error envelope**: `{statusCode, correlationId, message}`
- **Validation leniency**: unknown JSON keys dropped (never 400), matching the legacy `whitelist:true`
- **Refresh-token rotation**: single-use (reuse → 401)
- **Login lockout** after `AUTH_MAX_FAILED_LOGINS` failures; **rate-limited** 10/min/IP
- **Production gates** (`config/settings/prod.py`): refuse to boot unless mock data,
  dev endpoints, and shadow authorization are off, the JWT secret is strong, and
  evidence storage is on a persistent absolute path.

## Docker

```bash
docker build -t edify-api ./edify-api
# Entry: migrate → optional seed (RUN_SEED=true) → daphne ASGI on :4000
```

## Management commands

- `python manage.py seed [--mock] [--reset]` — permissions + demo data
- `python manage.py spectacular --color --file schema.yml` — OpenAPI export
- `python manage.py makemigrations` / `migrate` — schema
