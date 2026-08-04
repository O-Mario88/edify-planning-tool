# DigitalOcean App Platform — how to change this app safely

**Never apply `app.yaml` — or any hand-written spec — directly to production.**

`doctl apps update --spec` replaces the *entire* spec. Anything the file omits
or spells differently is not merged, it is overwritten. On 2026-08-04 the
committed `app.yaml` had drifted far enough from the running app that applying
it would have:

| Committed | Live | What applying it does |
|---|---|---|
| 20 secrets as `REPLACE_ME_…` | real `EV[1:…]` values | `prod.py` rejects the placeholders and the container **refuses to boot** |
| `databases: [db]` | `dev-db-315277` | `${db.DATABASE_URL}` stops resolving; risks detaching the live database |
| `services: [web]` | `edify-planning-tool` | component destroyed and recreated |
| `name: edify-planning-tool` | `edify-planning-app` | renames the app |

None of that announces itself in a diff you have not taken. The spec had never
been applied since the app was created, which is why nobody noticed.

## The safe procedure

Always start from what is actually running:

```bash
APP=dacdc3eb-0ebe-4b47-bea2-88fe1155347b

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

## What is actually running

Recorded 2026-08-04 after the spec repair. Treat as documentation, not as input:

- app `edify-planning-app`, region `fra`
- service `edify-planning-tool` — 1 × `apps-s-1vcpu-2gb`, port 8000,
  health check `GET /api/health/ready`
- worker `scheduler` — 1 × `apps-s-1vcpu-1gb`, `python manage.py runscheduler`,
  `ENABLE_BACKGROUND_JOBS=true`
- database `dev-db-315277` (PG, **development tier — no automated failover**)
- env is set at **app level**, so both components inherit it; the worker
  overrides only `ENABLE_BACKGROUND_JOBS`, `RUN_MIGRATIONS`, `RUN_SEED`
- `RUN_MIGRATIONS=true` on the web service: migrations run on **container
  boot**, not in a pre-deploy job. That makes `instance_count: 1` load-bearing
  — two web instances would migrate concurrently against one database.

## Known gaps, deliberately not changed here

- **No log retention** (`log_destinations` unset). A superseded deployment's
  logs are unrecoverable, so an incident can only be diagnosed while it is
  still happening.
- **No outbound email** (`EMAIL_PROVIDER` / `RESEND_API_KEY` unset), so
  `MailerService` falls back to the console provider, which withholds the body
  in production. Invitations and password resets are generated and silently
  discarded. Onboard via Admin → user → *reset password* instead, which sets a
  temporary password and forces a change at next sign-in.
- **Development-tier database** — no automated failover.
- Domains still have `www` PRIMARY and the apex ALIAS. The application-level
  `CANONICAL_HOST` redirect makes the apex canonical to users regardless, so
  this is cosmetic in App Platform's own routing.
