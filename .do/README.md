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

Rebuilt and verified in the DigitalOcean control panel on 2026-09-08. This is
evidence, not an input spec; export the live spec again before every change.

- app `edify-production`, id `fcd3a30a-9687-4c23-ad76-d54345d4bcfa`, region
  `fra1`
- service `edify-planning-tool` — 1 × `apps-s-1vcpu-1gb-fixed` ($10/month),
  health check `GET /api/health/ready`, one Gunicorn worker
- worker `scheduler` — 1 × `apps-s-1vcpu-0.5gb` ($5/month),
  `python manage.py runscheduler`
- pre-deploy job `migrate` — `python manage.py migrate_locked --noinput`; it is
  billed only for the seconds it runs
- managed PostgreSQL 16 cluster `edify-production-db`, id
  `63eb66af-dbc5-490f-bae6-885525c15718`, one 1-GiB primary with 10 GiB storage
  ($15.15/month), bound to the app as `db`
- private Spaces bucket `edify-production-private-fra` in `fra1` ($5/month)
- `edifyplanning.app` is PRIMARY and `www.edifyplanning.app` is an ALIAS; DNS
  remains at GoDaddy

The recurring total is **$35.15/month before tax**. Do not add a standby,
staging app, managed cache, dedicated egress IP, or paid log destination without
an explicit budget increase.

**Scaling precondition:** keep migrations in the dedicated pre-deploy job and
keep `RUN_MIGRATIONS=false` on every web replica. Do not re-enable migration on
web-container startup when changing instance counts.

## Current operational decisions

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
