# Deploying Edify Planning Tool to Railway

This guide covers everything needed to deploy the Django + DRF backend to
Railway. The app runs as a single service (Daphne ASGI — serves HTTP, the
realtime SSE layer, and the APScheduler background jobs from one process).

---

## Architecture (what Railway runs)

- **One service** (the `edify-api` Dockerfile at the repo root).
- **Runtime:** Daphne (ASGI) on `$PORT` (Railway injects this).
- **Database:** Railway Postgres (provisioned separately; referenced via `DATABASE_URL`).
- **Static files:** WhiteNoise (`CompressedManifestStaticFilesStorage`) — collected at build time, served from the container. No CDN required.
- **Migrations:** Applied automatically on every deploy by `docker-entrypoint.sh` (before the server starts). Safe for a single replica.
- **Persistent volume:** `/data/evidence` — required for uploaded evidence files to survive redeploy.

---

## Step 1 — Create the Railway project

1. **New Project → Deploy from GitHub repo** (select this repo).
2. Railway detects the `Dockerfile` and `railway.json` automatically.
3. **Add a Postgres database:** `+ Add → Database → PostgreSQL`. Railway provisions it and exposes `DATABASE_URL`.

---

## Step 2 — Set environment variables

In the **service** (not the database), set these under **Variables**.

### Required — app will refuse to boot without these (fail-closed)

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | **Reference the Postgres variable.** Railway interpolates this. Do **not** hardcode the connection string — it rotates. |
| `JWT_SECRET` | (random, ≥ 16 chars) | Used for both Django `SECRET_KEY` and JWT signing. **Must not contain** `change-me` or `dev-only`. Generate with `openssl rand -hex 32`. |
| `SUPER_ADMIN_PASSWORD` | (strong password) | Login password for the bootstrap super-admin account. |
| `SUPER_ADMIN_EMAIL` | `admin@yourdomain.org` | Email for the super-admin account. |
| `ALLOWED_HOSTS` | `edify.up.railway.app,yourdomain.com` | Comma-separated. Railway's `*.up.railway.app` domain + any custom domain. `localhost`/`127.0.0.1` are added automatically for health probes. |
| `EVIDENCE_STORAGE_DIR` | `/data/evidence` | **Must start with `/`** (absolute path). Mount a persistent volume here (Step 3). |
| `AUTHZ_MODE` | `enforce` | Must be `enforce` (not `shadow`). |
| `ENABLE_MOCK_DATA` | `false` | |
| `ENABLE_DEV_ENDPOINTS` | `false` | |
| `ENABLE_DEV_SEED` | `false` | |
| `ENABLE_DEV_IMPORTS` | `false` | |
| `PARTNER_ROLE_BRIDGE` | `false` | |

### Optional but recommended

| Variable | Default | Notes |
|---|---|---|
| `CORS_ORIGINS` | — | Comma-separated allowed origins for API access. Set to your frontend domain(s). |
| `RUN_SEED` | `false` | Set to `true` **only on first deploy** to load reference data (cost catalogue, etc.). Set back to `false` immediately after. |
| `REDIS_URL` | (none → LocMem cache) | Add Railway Redis if you scale beyond 1 replica. LocMem is fine for single-replica. |
| `SECURE_SSL_REDIRECT` | `true` | Keep `true` — Railway terminates TLS. |
| `SESSION_COOKIE_SECURE` | `true` | Keep `true`. |
| `CSRF_COOKIE_SECURE` | `true` | Keep `true`. |
| `EMAIL_PROVIDER` | `console` | Set to `resend` + `RESEND_API_KEY` for real email. `console` prints to logs (dev only). |
| `ENABLE_BACKGROUND_JOBS` | `true` | APScheduler (cleanup, reminders). |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | JWT access token lifetime. |
| `REFRESH_TOKEN_TTL_DAYS` | `7` | JWT refresh token lifetime. |

> **Note on `JWT_EXPIRES_IN`:** this variable is **not read** by the code. Use `ACCESS_TOKEN_TTL_MINUTES` and `REFRESH_TOKEN_TTL_DAYS` instead.

---

## Step 3 — Add a persistent volume

Evidence files must survive container restarts.

1. Service → **Settings → Volumes → Add Volume**.
2. **Mount path:** `/data/evidence`
3. This path **must match** `EVIDENCE_STORAGE_DIR`.

---

## Step 4 — Configure networking

- **Port:** Railway reads `$PORT` from the env (set in the Dockerfile). The app listens on `$PORT`. No manual port config needed.
- **Health check:** `railway.json` sets `healthcheckPath: /api/health`. Railway probes `GET /api/health` (returns DB status).
- **Custom domain:** Settings → Networking → Generate Domain (for `*.up.railway.app`) or add your own domain. Add the domain to `ALLOWED_HOSTS`.

---

## Step 5 — Deploy

1. **Trigger a deploy** (push to `main`, or click Deploy in the dashboard).
2. Watch the **Deploy Logs**. You should see:
   ```
   ▶ Applying Django migrations...
   ▶ Starting edify-api (Django + DRF)...
   ```
3. The health check (`/api/health`) must return 200 for the deploy to be marked healthy.
4. If `RUN_SEED=true`: reference data loads after migrations. **Set it back to `false`** and redeploy.

---

## Post-deploy verification

Once the service is live, verify the critical path:

```bash
# 1. Health check (should return {"status":"healthy",...})
curl https://YOUR-DOMAIN/api/health

# 2. Login page loads (should return 200 + HTML)
curl -I https://YOUR-DOMAIN/login

# 3. Unauthenticated dashboard redirects to login
curl -I https://YOUR-DOMAIN/dashboard   # → 302 to /login?next=/dashboard
```

Then in a browser:
- Log in as the super-admin (`SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`).
- Switch roles (top-right avatar) and confirm each role's dashboard renders.
- Visit `/admin-panel` → confirm it loads.
- Visit `/api/health` → confirm `"db":"ok"`.

---

## How migrations work on Railway

- `docker-entrypoint.sh` runs `python manage.py migrate --noinput` **on every container start**, before the server boots.
- This is safe for a **single replica**. If you scale to multiple replicas, the concurrent `migrate` can race. For multi-replica, run migrations as a separate Railway **crashed/exit-job** step instead (remove `migrate` from the entrypoint and add a pre-deploy command).
- If a migration fails, the container exits (fail-fast). Railway's `restartPolicyMaxRetries: 5` will retry a few times then stop — check the logs for the SQL error.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Container crash-loops on boot | Missing/invalid env var. prod.py prints the exact list of violations at startup. | Read the deploy logs for the "Production environment is not safe" block; set every listed variable. |
| `ALLOWED_HOSTS` error | Domain not in `ALLOWED_HOSTS`. | Add your Railway domain + custom domain. `localhost` is auto-added. |
| Login page has no CSS | Static files not collected (shouldn't happen — build step collects them). | Check the build logs for the `collectstatic` step; it must succeed (no `|| true`). |
| Cookies don't persist / CSRF fails | `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` set to `false` over HTTPS. | Leave these at their default `true`. Railway terminates TLS; secure cookies work. |
| 500 on `/accounts` or other pages | Possible view error. | Check runtime logs; run `python manage.py test` locally to reproduce. |
| Health check fails | DB connection refused or `/api/health` returning 503. | Verify `DATABASE_URL` references the Postgres variable correctly. |

---

## Local production-mode smoke test

Before deploying, verify the prod config boots and collects static:

```bash
# Set the required vars (use dummy values for local smoke test)
export $(grep -v '^#' .env | xargs)  # or set manually
export DJANGO_SETTINGS_MODULE=config.settings.prod
export JWT_SECRET="local-prod-test-secret-strong-enough"
export AUTHZ_MODE=enforce
export EVIDENCE_STORAGE_DIR=/tmp/evidence
export SUPER_ADMIN_PASSWORD=test-pass
export ALLOWED_HOSTS=localhost

python manage.py check           # → "System check identified no issues"
python manage.py collectstatic   # → "N static files copied"
python manage.py migrate         # → apply any pending migrations
python manage.py test            # → 234 tests pass
```

---

## Rollback

Railway keeps previous deploys. To roll back:
1. Service → **Deployments**.
2. Click the previous healthy deployment → **Redeploy**.

Because migrations run on boot, a rollback to a pre-migration deploy is safe **only if** the new migrations were backward-compatible (no destructive schema changes). The migrations in this repo are additive (new tables/columns, choice-list updates) — safe to roll back over.

---

## What's intentionally NOT in this deploy

- **No Celery / separate worker.** Background jobs run via APScheduler in the same Daphne process. Fine for current scale; add a worker if job volume grows.
- **No CDN.** WhiteNoise serves static files from the container with gzip/brotli compression. Add a CDN only if static latency matters for your region.
- **No Redis.** LocMem cache is used. Add Railway Redis + set `REDIS_URL` if you scale beyond 1 replica (cache must be shared).
- **LibreOffice** is installed in the image for the optional DOCX→PDF evidence rendition. It adds ~600MB to the image. If you don't use that feature, remove `libreoffice` from the Dockerfile to shrink the image.
