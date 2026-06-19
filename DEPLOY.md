# Deploying the Edify Planning & Monitoring Tool

Two services — `edify-api` (NestJS + Prisma + Postgres) and `edify-web`
(Next.js) — orchestrated by `docker-compose.yml`.

**Source repositories** — each service deploys from its own GitHub repo:

| Service     | GitHub repo                                          |
| ----------- | ---------------------------------------------------- |
| `edify-api` | https://github.com/O-Mario88/edify-api               |
| `edify-web` | https://github.com/O-Mario88/edify-planning-tool     |

Locally they live side by side under `Edify Planning Tool/` (siblings), which is
what `docker-compose.yml`'s `./edify-api` / `./edify-web` build contexts expect.

## Quick start (single host, Docker Compose)

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD and a strong JWT_SECRET.
#   openssl rand -base64 48   # JWT_SECRET

# First boot — build images, run DB migrations (automatic), seed demo data once:
RUN_SEED=true docker compose up --build

# After the first run, set RUN_SEED=false in .env (or omit) and:
docker compose up -d
```

- Web → http://localhost:3000  ·  API → http://localhost:4000/api
- The API container applies `prisma migrate deploy` on every boot
  (`docker-entrypoint.sh`) and waits for a healthy Postgres.
- Health probes: API `GET /api/health`, Web `GET /api/health`.

## Production checklist

- **Secrets**: strong `JWT_SECRET` (≥16 chars, not `change-me`); rotate
  `POSTGRES_PASSWORD`. The API refuses to boot in production with a weak secret
  or with `ENABLE_MOCK_DATA`/`ENABLE_DEV_ENDPOINTS` true (env.validation rails).
- **CORS**: set `CORS_ORIGINS` to the web app's real public URL(s),
  comma-separated.
- **Database**: for managed Postgres (Neon/Supabase/RDS), point the API's
  `DATABASE_URL` at it instead of the bundled `db` service and drop `db` from
  the compose file. Take regular backups of the `edify_pgdata` volume.
- **TLS**: terminate HTTPS at a reverse proxy / load balancer in front of `web`
  (and `api` if exposed). Keep the API private and only reachable from `web`
  where possible.
- **Optional adapters** (web `.env.example`): S3 evidence storage, Resend email,
  Twilio SMS, Sentry, Upstash Redis. Each falls back to a dev stub when unset —
  configure them for production.

## Deploying on Railway

> **Architecture this runbook assumes — read first.** `edify-web` is a
> **single-origin backend-for-frontend (BFF)**, NOT a split-origin SPA. The
> browser only ever talks to `edify-web`; every `/api/*` route in
> `edify-web/src/app/api` is a Next.js proxy that calls `edify-api`
> **server-side** over private networking. Consequences that drive the config
> below:
>
> - The browser **never** calls `edify-api` directly. There is **no public API
>   domain**, **no CORS**, and **no cross-subdomain cookies**. `edify-api` stays
>   private on Railway's internal network.
> - `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_API_BASE_URL` are **not read by any
>   code** — don't set them. The web reaches the API via the server-only
>   `EDIFY_API_URL`. The CSP (`next.config.ts`) pins `connect-src 'self'`, so a
>   browser→API call would be blocked anyway.
> - The session cookie lives on `edify-web` only (signed with
>   `EDIFY_SESSION_SECRET`). `edify-api` auth is **JWT bearer**, minted
>   server-side by the bridge — no API cookies.
>
> Railway builds each service from its `Dockerfile`, connecting **edify-api** to
> the [`O-Mario88/edify-api`](https://github.com/O-Mario88/edify-api) repo and
> **edify-web** to the
> [`O-Mario88/edify-planning-tool`](https://github.com/O-Mario88/edify-planning-tool)
> repo (each service's **root directory = its repo root**, since each repo holds a
> single service). Use Railway's **managed Postgres** plugin (no bundled `db`
> service needed).

### Project topology

One Railway project, three required services (+ two optional):

| Service        | GitHub repo (root dir)            | Public domain?         | Role                                  |
| -------------- | --------------------------------- | ---------------------- | ------------------------------------- |
| **Postgres**   | plugin                            | no                     | database (provides `DATABASE_URL`)    |
| **edify-api**  | `O-Mario88/edify-api`             | **no — private only**  | NestJS API + Prisma; owns the data DB |
| **edify-web**  | `O-Mario88/edify-planning-tool`   | **yes — the only one** | Next.js BFF the users hit             |
| Redis          | plugin                            | no                     | *optional* — only if you enable jobs  |
| Worker / Cron  | `O-Mario88/edify-api`             | no                     | *optional* — only if you enable jobs  |

Redis + Worker are **not needed for launch**: `ENABLE_BACKGROUND_JOBS=false` is
the default and nothing requires `REDIS_URL`. Add them later if you turn jobs on.

### 1 — Postgres

Add the Postgres plugin. Railway exposes its connection string as
`${{Postgres.DATABASE_URL}}` for reference from other services.

### 2 — edify-api  (PRIVATE service, repo `O-Mario88/edify-api`)

Do **not** attach a public domain. Variables:

```
NODE_ENV=production
PORT=4000                       # pin it — the web service references :4000 internally
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET=<openssl rand -base64 48>     # ≥16 chars, must NOT contain "change-me"/"dev-only"
JWT_EXPIRES_IN=12h
AUTHZ_MODE=enforce              # prod boot fails on any other value
ENABLE_MOCK_DATA=false          # prod boot fails if true
ENABLE_DEV_ENDPOINTS=false      # prod boot fails if true
DEMO_LOGIN_PASSWORD=<strong>    # MUST equal edify-web's DEMO_LOGIN_PASSWORD (see §3)
EVIDENCE_STORAGE_DIR=/data/evidence
RUN_SEED=true                   # FIRST deploy only — seeds 700 schools, then remove it
```

- **Do NOT set `CORS_ORIGINS`.** The browser never calls the API; with it unset,
  `main.ts` disables CORS in production (correct). Setting it is harmless but
  pointless.
- **Volume**: attach a Railway volume mounted at **`/data`** so
  `/data/evidence` survives redeploys (prod env-validation rejects an ephemeral
  evidence dir).
- **Migrations auto-run on every boot** via `docker-entrypoint.sh`
  (`prisma migrate deploy`, idempotent). No separate release command needed.
- **First deploy**: set `RUN_SEED=true`, deploy, confirm the seed log, then
  **remove `RUN_SEED`** and redeploy so it never reseeds.
- **Private-networking check**: the web service will call
  `http://edify-api.railway.internal:4000/api`. If that fails to connect,
  confirm Nest binds all interfaces (Railway's internal network is IPv6) — if
  needed, change `app.listen(port)` to `app.listen(port, '::')` in `main.ts`.

### 3 — edify-web  (PUBLIC service, repo `O-Mario88/edify-planning-tool`)

This is the only service with a domain. Variables:

```
NODE_ENV=production
EDIFY_USE_BACKEND=true
EDIFY_API_URL=http://edify-api.railway.internal:4000/api    # PRIVATE, server-side only
EDIFY_SESSION_SECRET=<openssl rand -hex 32>                 # login 503s for everyone if unset
SUPER_ADMIN_EMAIL=domario@edify.org
SUPER_ADMIN_PASSWORD=<strong>                               # the always-on super-admin login
DEMO_LOGIN_PASSWORD=<same value as edify-api §2>            # bridge uses it to auth into edify-api
NEXT_PUBLIC_USE_MOCK_DATA=false
```

- **Do NOT set `DATABASE_URL` on the web service.** In this hybrid, data is
  proxied to `edify-api`; setting `DATABASE_URL` flips `edify-web` into its own
  Prisma mode (a *second*, divergent copy of the data) and would require running
  the web `db:migrate && db:seed` step. Leave it unset to stay in proxy mode.
- **Do NOT set** `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_API_BASE_URL`,
  `NEXT_PUBLIC_APP_URL`, `APP_URL`, or any `COOKIE_*` — none are read.
- `DEMO_LOGIN_PASSWORD` **must match** the API's: the server-side bridge logs
  the role-mapped backend account in with it (`src/lib/api/backend.ts`). Mismatch
  → every proxied data call 401s.
- Auth note: the user store is **in-memory** — only the env-gated super-admin
  persists across redeploys. DB-backed multi-user login is the not-yet-merged
  `security/identity-platform` work; see "Completing the consolidation" below.

### 4 — Domains

```
edifyplanning.app        → edify-web          (apex; Railway issues the cert)
www.edifyplanning.app    → 301 → edifyplanning.app
api.edifyplanning.app    → DO NOT CREATE      (edify-api is private)
```

Add the apex + `www` to the **edify-web** service (Settings → Networking →
Custom Domain) and create the CNAME/ALIAS + verification records Railway shows.
Redirect `www` → apex at your DNS/registrar (or a Railway redirect rule).

### 5 — Deploy order & smoke test

```
1. Postgres up
2. Deploy edify-api with RUN_SEED=true  → watch logs: migrate deploy + seed
3. Remove RUN_SEED, redeploy edify-api  → healthy on /api/health (private)
4. Deploy edify-web                       → healthy on /api/health (public)
5. Attach edifyplanning.app to edify-web, wait for cert
6. GET https://edifyplanning.app/api/health        → 200
7. Log in as the super-admin                        → session set
8. Open a dashboard (e.g. /director)                → live data (proves the bridge)
9. Upload + download one evidence file              → proves the API volume
```

Both `railway.json` files already set `healthcheckPath: /api/health` — Railway
won't route traffic to an unhealthy release.

### Heads-up: Fly vs Railway drift

`edify-api/fly.toml` still exists and you did a live **Fly** deploy recently.
Pick one platform as the source of truth; running both invites config rot
(e.g. region, volume, and secret settings silently diverging). If Railway wins,
delete or archive `fly.toml`.

### Completing the consolidation (later, optional)

If you finish retiring `edify-api` (reimplementing the remaining proxied
surfaces on `edify-web`'s own 57-model Prisma), the topology collapses to **one
public service**: drop `edify-api`, give `edify-web` a `DATABASE_URL`, run its
`db:migrate && db:seed` as a Railway pre-deploy command, and drop
`EDIFY_USE_BACKEND`/`EDIFY_API_URL`. Not required for launch.

## Building images individually

```bash
docker build -t edify-api ./edify-api
docker build -t edify-web ./edify-web
```

## Running migrations manually

```bash
docker compose run --rm api npx prisma migrate deploy
```

## CI gate (recommended)

- API: `npm ci && npm run typecheck && npm run build`
- Web: `npm ci && npm run ci`  (typecheck + lint + tests) `&& npm run build`
