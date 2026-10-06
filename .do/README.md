# DigitalOcean App Platform — production operations

**Never apply `app.yaml` — or any hand-written spec — directly to production.**

`doctl apps update --spec` replaces the *entire* spec. Anything the file omits
or spells differently is not merged, it is overwritten. The committed
`app.yaml` contains placeholders instead of production secrets, so applying it
directly makes the production safety checks refuse to boot.

## The safe procedure

Always start from what is actually running:

```bash
APP=fcd3a30a-9687-4c23-ad76-d54345d4bcfa

doctl apps spec get $APP > /tmp/live.yaml   # 1. export reality
cp /tmp/live.yaml /tmp/proposed.yaml        # 2. edit the copy
$EDITOR /tmp/proposed.yaml
scripts/do_spec_diff.py /tmp/live.yaml /tmp/proposed.yaml   # 3. read EVERY line
doctl apps update $APP --spec /tmp/proposed.yaml            # 4. apply
```

Step 3 is the one that matters. The diff script prints every leaf that differs
and nothing else, so "3 differences" means three — not three that you noticed.

## Secrets

Live secret values are `EV[1:…]`, encrypted and decryptable only by this app.
They are deliberately **not** committed here: an exported spec round-trips them
fine, but a git repository is the wrong place for secret-shaped material even
when it is encrypted. Export the live spec when you need them; never retype
them.

## What is provisioned

Rebuilt and verified in the DigitalOcean control panel on 2026-09-08; the web
service, database and pool were upsized there on 2026-09-29. This is
evidence, not an input spec; export the live spec again before every change.

- app `edify-production`, id `fcd3a30a-9687-4c23-ad76-d54345d4bcfa`, region
  `fra1`
- service `edify-planning-tool` — 1 × `apps-s-2vcpu-4gb` ($50/month; 2 shared
  vCPUs, 4 GB), autoscale off, health check `GET /api/health/ready`,
  `WEB_CONCURRENCY=4` Gunicorn workers, `WEB_MAX_CONCURRENT_REQUESTS=10`
- worker `scheduler` — 1 × `apps-s-1vcpu-0.5gb` ($5/month),
  `python manage.py runscheduler`
- pre-deploy job `migrate` — `python manage.py migrate_locked --noinput`; it is
  billed only for the seconds it runs
- managed PostgreSQL 16 cluster `edify-production-db`, id
  `63eb66af-dbc5-490f-bae6-885525c15718`, one Basic primary with 2 vCPU, 4 GB
  RAM, 60 GiB storage and a 97-connection limit ($60.90/month), bound to the
  app as `db`; PgBouncer pool `edify_web` (transaction mode, size 40)
- private Spaces bucket `edify-production-private-fra` in `fra1` ($5/month)
- `edifyplanning.app` is PRIMARY and `www.edifyplanning.app` is an ALIAS; DNS
  remains at GoDaddy, with `www` targeting
  `edify-production-jct7s.ondigitalocean.app`

The recurring total is **$120.90/month before tax** (it was $35.15 before the
2026-09-29 upsize). Do not add a standby,
staging app, managed cache, dedicated egress IP, or paid log destination without
an explicit budget increase.

**Scaling precondition:** keep migrations in the dedicated pre-deploy job and
keep `RUN_MIGRATIONS=false` on every web replica. Do not re-enable migration on
web-container startup when changing instance counts.

## Current operational decisions

### Web connection pooling (2026-09-20)

The production database has 97 server connections (22 before the 2026-09-29
upsize). The `edify_web` transaction pool targets `defaultdb`, retains the
connecting user's privileges, and is capped at 40 server connections (was 10).
This uses the existing managed cluster.

Enable it on **the web component only** with `DB_USE_PGBOUNCER=true`,
`DB_POOL_NAME=edify_web`, and `DB_POOL_PORT=25061`. The existing managed
`DATABASE_URL` binding retains its host, credentials and TLS configuration;
only the database/pool name and port are overridden. Set
`WEB_MAX_CONCURRENT_REQUESTS` explicitly (10 since 2026-09-29, 6 before) so
enabling pooling does not also double application concurrency. Keep
`WEB_CONCURRENCY × WEB_MAX_CONCURRENT_REQUESTS` at or under the pool size:
4 × 10 = 40. Keep `DB_CONN_MAX_AGE=0` for ASGI.

The runtime role's defaults in `defaultdb` must retain `statement_timeout=30s`,
`lock_timeout=10s`, and `idle_in_transaction_session_timeout=60s`, because
PgBouncer rejects libpq startup options. Readiness checks verify these are set.
Pooled connections disable server-side cursors and automatic prepared
statements. Scheduler and migration jobs retain direct connections.

Rollback: set `DB_USE_PGBOUNCER=false` on the web component and redeploy.
The original database binding remains untouched, so the pool overrides are
ignored and requests use the direct connection again. Keep the request bound.

Redis is still not provisioned under the existing budget. Pooling does not
resolve the separate per-process cache limitation.

- **No paid log destination or managed cache is attached.** The single web
  process uses the production LocMemCache fallback; database-backed sessions,
  account lockout, and scheduler locks remain durable.
- **No outbound email** (`EMAIL_PROVIDER` / `RESEND_API_KEY` unset), so
  `MailerService` falls back to the console provider, which withholds the body
  in production. Invitations and password resets are generated and silently
  discarded. Onboard via Admin → user → *reset password* instead, which sets a
  temporary password and forces a change at next sign-in. The product owner
  explicitly accepted this interim operating model on 2026-08-28.
- **The database is intentionally single-node.** Managed backups remain
  available, but there is no automatic-promotion standby at this budget.
- **The apex is canonical.** `CANONICAL_HOST=edifyplanning.app` redirects the
  `www` alias while preserving the path and query string.

## Prepared on 2026-10-05, not applied

From the performance audit (`docs/performance-forensic-audit-2026-10-05.md`,
F6, F7, F13 and the open-database finding). Read from the control panel that
day; nothing was changed there. Each step stands alone and has its own way
back. Do one at a time, in a quiet hour, and after each look at
`https://edifyplanning.app/api/health/ready` and the Runtime Logs before the
next. Steps 1 and 2 can be done in either order, provided step 2 adds both
of its entries at once: with the app alone in the list, moving it onto the
private network afterwards would lock it out; with the private range alone,
the app as it connects today would be locked out at once.

What the control panel showed:

- the app is in no VPC (Networking > Private Network offers "Connect to a
  VPC"); app-level `DATABASE_URL` is `${db.DATABASE_URL}`, the public address,
  and the web, scheduler and migrate components all read it;
- the database cluster is in VPC `default-fra1` (10.114.0.0/20, FRA1), whose
  only resource is the cluster itself;
- Network Access on the cluster: "your database is open to all incoming
  connections";
- the web component carries `DB_USE_PGBOUNCER=true`, `DB_POOL_NAME=edify_web`,
  `DB_POOL_PORT=25061`, `DB_CONN_MAX_AGE=0`, `WEB_CONCURRENCY=4`,
  `WEB_MAX_CONCURRENT_REQUESTS=10`.

### 1. Database traffic on the private network (F13)

About 2 ms of every statement is the public round trip: 140 ms on a
68-statement page, 0.9 s on a reschedule.

**Done on 2026-10-06.** The app was connected to `default-fra1` at 03:36
(private IP 10.114.0.2) and `DATABASE_URL` was changed at 08:49. Database
traffic is on the private network: Databases > edify-production-db > Logs &
Queries > Current Connections shows the app arriving from 10.114.0.2, where
it used to show a public address (the web service's own connections show
127.0.0.1 there, before and after: they come through the pool).

The first deploy with the new value failed and DigitalOcean rolled back by
itself with no downtime; the next deploy, 29 minutes later with nothing
changed, went through. The `migrate` job's first connection had timed out
after the 5 seconds `DB_CONNECT_TIMEOUT_S` allows (`psycopg.errors.
ConnectionTimeout`, raised from Django's start-up checks). Why that one
attempt found no route is not known. If a deploy fails that way again, run
it again; `DB_CONNECT_TIMEOUT_S=30` on the `migrate` job alone gives its
first connection longer. While a failed deploy stands, the control panel
says the live deployment and the app spec are out of sync, and every push
is deployed with the spec as edited.

1. Apps > edify-production > Networking > Private Network > **Edit network** >
   Connect app to VPC network > `default-fra1` > Save. The app redeploys. It
   still uses the public address, so nothing else has changed yet.
2. Check the site and readiness.
3. Settings > App-Level Environment Variables > Edit: change `DATABASE_URL`
   from `${db.DATABASE_URL}` to `${db.DATABASE_PRIVATE_URL}` > Save. The app
   redeploys. The web component's pool overrides keep working: they change
   only the database name and the port.
4. Check: readiness answers `"db": "up"`; the `edify.perf` lines in the
   Runtime Logs show well under 1 ms of database time per statement on small
   pages (about 2 ms before); the scheduler's next job runs; the next deploy's
   migrate job connects.

Way back: put `${db.DATABASE_URL}` back in step 3. Edit network > disconnect
undoes step 1. `DATABASE_PRIVATE_URL` exists only while the app and the
cluster are in the same VPC, so undo step 3 before step 1. A deploy that
cannot reach its database fails its health check and is not put in service:
the version that was running keeps running.

### 2. Only the app may connect to the database (trusted sources)

1. Databases > edify-production-db > Network Access > **Add Trusted Sources**.
   In the one dialog add both of these before pressing Add:
   - the app: Quick select > Apps > `edify-production` (how it connects
     today, over the public address);
   - the private network: `10.114.0.0/20` (how it connects once step 1 is
     done. DigitalOcean: an app connecting through a VPC must have its VPC
     address among the trusted sources. The whole range, so a redeploy that
     moves the app's private address cannot lock it out; nothing else lives
     in that VPC).
   Add your own address (My current IP address) only if you connect to the
   database from your own machine, and remove it when you no longer do.
2. At once: readiness answers `"db": "up"`, a page opens, the scheduler's log
   shows its next job.

Way back: remove every trusted source; the cluster is open again immediately.
From here nothing outside the list can open a connection to the database,
whatever password it holds.

### 3. A pool of open connections in each web process (F6)

Each request opens a TLS connection to the `edify_web` pool and signs in
before its first query: 40-50 ms of every request. `DB_APP_POOL` keeps a
bounded set open in each process instead (`config/settings/base.py`).
Rehearsed on 2026-10-05 behind a local PgBouncer in transaction mode, four
workers of ten: 100 users with 3-12 s between clicks and then with 0.2-1 s,
no errors, no request waiting for a connection, at most 11 connections out
in one process, PgBouncer's client connections down from 53 to 44.

1. Deploy a build that has it (it needs `psycopg-pool`, in
   `requirements/base.txt`).
2. On the **web component only**: add `DB_APP_POOL=true`. Leave
   `DB_CONN_MAX_AGE=0` and `WEB_MAX_CONCURRENT_REQUESTS=10` as they are: the
   pool is sized from that bound (10 + 2 a process) and refuses to boot with a
   lifetime or without a bound. The scheduler and the migrate job keep their
   direct connections.
3. Check: readiness now carries `"db_pool": {"open": …, "idle": …, "max": 12,
   "waiting": 0}`; `waiting` stays 0. Expected, not yet measured in
   production: `/api/health/ready` answers within about 10 ms of
   `/api/health/live`, where they are 40-50 ms apart today.

Way back: remove `DB_APP_POOL` from the web component and redeploy. On a
direct connection the variable is ignored and a boot warning says so.

### 4. One cache for the four web processes (F7)

Not provisioned: it is a budget decision. A single-node managed Valkey
(Redis-compatible) starts at $15.00 a month, which would make the recurring
total $135.90. The code already uses it when `REDIS_URL` is set, and the
`redis` client is installed.

Rehearsed on 2026-10-06 against a local Valkey 9.1: the cache, session,
throttle and health tests pass against the real server, four workers report
`"cache": "up"`, all 61 audited pages are clean, and a full crawl leaves
6.5 MB in it. **Deploy `fix/pages-survive-cache-outage` first.** Without it,
whenever the cache is unreachable the Country Director's dashboard and
Analytics answer 500 and a schedule save is answered with an error after it
has saved (audit report, section 21.2). A single node has no standby, so it
will be unreachable now and then.

What changes once it is on, by design: the four web processes share cached
figures; sessions are read from the cache first; and the sign-in limit of
ten a minute from one address becomes ten, where each process counts its
own ten today (`RATE_LIMIT_LOGIN_PER_MIN` raises it for an office behind
one address).

1. Create a Valkey cluster in FRA1, in VPC `default-fra1`, 1 GiB single
   node. Set its eviction policy to `allkeys-lru`: it is a cache, and one
   that refuses writes when full is worse than one that forgets.
2. Attach it to the app and set `REDIS_URL` at app level to its private
   connection string (`${<component>.DATABASE_PRIVATE_URL}` once it is a
   component of the app), so the web service and the scheduler both read
   it: the scheduler's jobs rebuild snapshots that the web processes
   serve, and can only hand them over through a cache both can see.
3. Give the cache cluster the same two trusted sources as the database: it
   has a list of its own.
4. Check: readiness answers `"cache": "up"` and `"status": "ok"`. If it
   still says `"unshared"`, the boot log's "Cache unavailable (…)" line names
   the reason (a TLS or address problem); the app keeps working on its
   per-process cache meanwhile.

Way back: remove `REDIS_URL`; each process falls back to its own cache, as
now, and says so in the log.

## Authenticated production smoke

The authenticated route crawl is GET-only after login, but login itself updates
session/account metadata. It must use approved isolated synthetic accounts; do
not point demo accounts or real staff credentials at it.

1. Copy `docs/production-smoke-accounts.example.json` outside the repository
   and replace each placeholder email with its approved synthetic account.
2. Export each password through the environment-variable name referenced by
   that account. Do not add passwords to the JSON file or command line.
3. Run the deliberately verbose approval gate:

   ```bash
   EDIFY_E2E_BASE_URL=https://edifyplanning.app \
   EDIFY_PRODUCTION_SMOKE_MODE=read-only-authenticated \
   EDIFY_E2E_ACCOUNTS_FILE=/absolute/path/to/approved-production-smoke-accounts.json \
   npm run test:e2e:production-auth
   ```

The runner refuses partial role matrices, unknown role mappings, passwords in
the manifest, missing password variables, and accounts blocked on a required
agreement. It never accepts an agreement in production. Passing proves that
every permitted argument-free page opened for all 14 roles; it does not prove
mutation workflows or isolated third-party side effects.
