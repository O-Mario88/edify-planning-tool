# Edify Planning — Railway Deployment Plan

> **STALE**: this document describes the retired NestJS+Next.js split-service
> architecture. The current deployment is a single Django monolith (see
> `Dockerfile` at the repo root). For the current, accurate deployment setup
> — including the background-job scheduler worker service — see
> `docs/scheduler-deployment.md`.

The production deployment target. One Railway project, two app services that stay
**independent** but present as **one product** to users. The frontend and backend
are separate so either can redeploy/scale/fail without taking the other down — the
contract between them is what matters, not co-location.

## Project & services

```
Railway Project: edify-planning-production

Services:
1. edify-web        → frontend (Next.js)
2. edify-api        → backend (NestJS + Prisma)
3. Postgres         → database
4. Redis            → sessions / rate limits / jobs (if used)
5. Worker/Cron      → optional background jobs
```

## Domains

```
https://edifyplanning.app        → edify-web
https://www.edifyplanning.app    → redirect to edifyplanning.app
https://api.edifyplanning.app    → edify-api
```

Railway custom domains require DNS records (CNAME / TXT verification); Railway
issues HTTPS certs once DNS is correct.

### Why separate (not "deployed together")
- `edify-web` can fail or redeploy without taking down the API.
- `edify-api` runs migrations, queues, auth, evidence, payments, analytics independently.
- Scale API and frontend independently.
- Secure backend routes properly; debug deploy issues faster.

The issue was never that they're separate — it's that they need a **clean contract**.

## Environment variables

### edify-web (Next.js)
```
APP_URL=https://edifyplanning.app
NEXT_PUBLIC_APP_URL=https://edifyplanning.app
NEXT_PUBLIC_API_URL=https://api.edifyplanning.app
```
Only `NEXT_PUBLIC_`-prefixed vars are exposed to the browser. **Secrets must NOT
use that prefix.** (Identity work also needs, as NON-public secrets: `EDIFY_SESSION_SECRET`,
`SUPER_ADMIN_PASSWORD`, `SECURITY_ENCRYPTION_KEY`, `DEMO_LOGIN_PASSWORD`.)

### edify-api (NestJS)
```
NODE_ENV=production
APP_URL=https://edifyplanning.app
API_URL=https://api.edifyplanning.app
ALLOWED_ORIGINS=https://edifyplanning.app,https://www.edifyplanning.app
COOKIE_DOMAIN=.edifyplanning.app
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
AUTHZ_MODE=enforce
JWT_SECRET=<32+ random hex>
DEMO_LOGIN_PASSWORD=<must match edify-web>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
EVIDENCE_STORAGE_DIR=/data/evidence
```
Cookie-based auth ⇒ the API must use **exact** CORS origins (never `*`) with credentials:
```
Access-Control-Allow-Origin: https://edifyplanning.app
Access-Control-Allow-Credentials: true
```

## Auth architecture (backend is the authority)

```
Browser
  ↓
edify-web (edifyplanning.app)
  ↓ API calls
edify-api (api.edifyplanning.app)
  ↓
Postgres / Redis / Evidence storage
```

`edify-api` is the authority for: login, social sign-in callback, MFA, roles,
permissions, sessions, user onboarding, audit logs, evidence access, finance workflows.
The frontend never decides auth/role access itself — it only renders what the
backend session/permissions allow.

## Railway wiring
1. Create one project: `edify-planning-production`.
2. Add service `edify-web` (frontend repo).
3. Add service `edify-api` (backend repo).
4. Add Postgres.
5. Add Redis (if sessions/queues/rate-limits/jobs are used).
6. Attach `edifyplanning.app` → `edify-web`.
7. Attach `api.edifyplanning.app` → `edify-api`.
8. Set `NEXT_PUBLIC_API_URL` in `edify-web`.
9. Set `ALLOWED_ORIGINS` in `edify-api`.
10. Run backend migrations **before** allowing frontend traffic.

Railway private networking (`SERVICE_NAME.railway.internal`, same project/env) is
available for backend↔worker / server-side proxy calls.

## Deployment order (every time)
```
1. Deploy edify-api
2. Run migrations
3. Run seed / role validation
4. Run health check
5. Deploy edify-web
6. Frontend smoke test
7. Test login
8. Test one protected API call
9. Test dashboard fetch
10. Test evidence upload/download
```
The backend must be healthy before the frontend points users to it.

## Health checks
**Backend:** `GET /health`, `/health/db`, `/health/auth`, `/health/storage`, `/health/version`
**Frontend:** `GET /`, `GET /login`, a frontend health/`api-health-proxy` page.

The frontend should show a controlled **"API unavailable"** state if `edify-api`
is down — never crash.

## Guardrails
- Don't merge the repos just to deploy.
- Don't put everything in one Railway service.
- Don't use frontend-only auth.
- Don't expose backend secrets with `NEXT_PUBLIC_` / `VITE_`.

Later (post-stability) you can proxy `/api/*` through the frontend so users only
ever see `edifyplanning.app`. For launch, the `api.edifyplanning.app` split is
cleaner, faster to debug, and safer.

---

## Implementation status (current code vs. this plan)
Honest gaps to close while wiring Railway (so the doc isn't aspirational):

- **Health endpoints:** edify-api currently exposes `GET /api/health` only. The
  `/health/db|auth|storage|version` sub-checks above need adding (small controllers).
- **Cross-subdomain auth:** today the FE↔API bridge is **server-side** (edify-web's
  `/api/*` routes proxy to edify-api with a JWT). The cookie-based, browser-direct
  cross-subdomain model (`COOKIE_DOMAIN=.edifyplanning.app`, CORS-with-credentials)
  is the target once the identity platform (branch `security/identity-platform`)
  is merged and the FE calls `api.edifyplanning.app` directly.
- **`ALLOWED_ORIGINS` in edify-api:** `main.ts` reads CORS origins from config —
  confirm it maps the `ALLOWED_ORIGINS` env (comma-split) before go-live.
- **Redis:** not yet wired (rate-limits are in-memory). Add `REDIS_URL` usage when
  multi-instance.
- **Seeding prod:** the prod seed withholds demo data unless `ALLOW_DEMO_SEED_IN_PROD=true`
  (see edify-api). A real launch onboards users via the Super Admin instead.
- **DEMO_LOGIN_PASSWORD must match** on both services (API hashes users with it; the
  web bridge logs in with it) — a mismatch = 502s.

## Background jobs / scheduler — open ops decision (2026-07 audit)

**This section reflects the current Django backend, not the NestJS/Next.js split
described above** — the codebase migrated to a single Django + DRF service
(`Dockerfile` builds one image, `CMD daphne -b 0.0.0.0 -p ${PORT:-4000}
config.asgi:application`; there is no separate `edify-web`/`edify-api` split or
`Worker/Cron` service actually provisioned in `railway.json` today).

**Status: `ENABLE_BACKGROUND_JOBS` is `False` everywhere, including production.**
- Read/set in `config/settings/base.py` (`ENABLE_BACKGROUND_JOBS = _truthy(os.environ.get("ENABLE_BACKGROUND_JOBS"), fallback=False)`).
  `config/settings/prod.py` does not override it — it falls through to the same
  `False` default unless an operator sets the env var.
- No deployment config sets it: not in `railway.json`, not in `Dockerfile`/
  `docker-entrypoint.sh`, not in `.env.example`.
- Effect: `apps/realtime/apps.py`'s `AppConfig.ready()` never registers the
  django-apscheduler jobs, and each job function in `apps/realtime/jobs.py`
  early-returns via `_enabled()` even if called directly. **None of the 4 jobs
  run automatically**: `weekly_fund_request_job`, `monthly_work_plan_job`,
  `notification_escalation_job`, `daily_digest_job`.
- Separately, two management commands are explicitly documented as
  cron-only-by-design and are **not** gated by `ENABLE_BACKGROUND_JOBS` at all —
  they simply have no scheduler calling them: `python manage.py
  send_pd_reminders` (`apps/professional_development/management/commands/
  send_pd_reminders.py`) and `python manage.py detect_field_debrief_insights`
  (`apps/debriefs/management/commands/detect_field_debrief_insights.py`).

**This needs a human/ops decision, not a code fix.** Turning this on requires an
actual process that stays alive to run a scheduler (or an external cron caller) —
that's an infrastructure choice, not something to flip silently in shared
production settings. Two viable options once decided:
1. Add a second Railway service (a "Worker" process, `CMD python manage.py
   runworker` equivalent or just a long-lived process with
   `ENABLE_BACKGROUND_JOBS=true` set) that runs the in-process apscheduler from
   `apps/realtime/apps.py`, **and** add a Railway Cron Job (or external cron)
   that calls `send_pd_reminders` and `detect_field_debrief_insights` daily.
2. Skip in-process apscheduler entirely and drive all 4 jobs + the 2 commands
   from Railway Cron Jobs / an external scheduler hitting `python manage.py
   <command>` directly (would need small wrapper commands for the 4
   apscheduler-only jobs, which currently only exist as importable functions,
   not management commands).

Until one of these is provisioned, weekly fund-request generation, monthly
work-plan envelope generation, notification escalation, daily digests, PD
reminders, and field-debrief recurring-issue detection are all **manual-only**
in production. See `apps/realtime/tests.py` for regression coverage of the
`ENABLE_BACKGROUND_JOBS` gate itself (so a future change can't silently start
these jobs without an explicit env flip).
