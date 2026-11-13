# 5. Environments, staging, CI and branch protection

## 5.1 Environments

| | Development | Automated test | Staging / UAT | Production |
|---|---|---|---|---|
| Database | local, built by migrations + demo seed | local or CI container, name ends `_test` | its own managed cluster, sanitised restore or seed | existing cluster, untouched |
| Gateway role | `edify_gateway` (read-only) | same, created per run | same, required by the start-up check | not deployed |
| Secrets | generated locally | throwaway literals | staging secret store | never used here |
| `EDIFY_ENV` | `development` | `test` | `staging` | refused by the build |
| App build | `development` | n/a | `staging` | refused by the app |

## 5.2 Development setup

Prerequisites: Go 1.27, Node 24, Python 3.13, PostgreSQL 16.

```bash
# 1. A database of your own, with the existing schema and synthetic data.
createdb edify_gorn_dev
cat > .env <<EOF
DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev
DJANGO_SETTINGS_MODULE=config.settings.dev
SECRET_KEY=$(openssl rand -hex 40)
FIELD_ENCRYPTION_KEY=$(openssl rand -hex 32)
ENABLE_BACKGROUND_JOBS=false
EOF
echo "JWT_SECRET=$(grep ^SECRET_KEY= .env | cut -d= -f2)" >> .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed --demo

# 2. The gateway's read-only role.
EDIFY_ENV=development \
EDIFY_ADMIN_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev \
  platform/deploy/db/apply-roles.sh

# 3. The analytics worker.
cd platform/workers/analytics
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
PYTHONPATH=gen .venv/bin/python -m edify_analytics.server

# 4. The gateway (EDIFY_JWT_SECRET must equal JWT_SECRET in .env).
cd platform/backend
EDIFY_ENV=development \
EDIFY_DATABASE_URL=postgresql://edify_gateway@localhost:5432/edify_gorn_dev \
EDIFY_JWT_SECRET=<the JWT_SECRET from .env> \
EDIFY_ANALYTICS_ADDR=127.0.0.1:50061 \
  go run ./cmd/gateway

# 5. The existing application, as the identity system for sign-in.
.venv/bin/python manage.py runserver 8000

# 6. The app.
cd platform/mobile && npm ci
EXPO_PUBLIC_EDIFY_ENV=development \
EXPO_PUBLIC_EDIFY_GATEWAY_URL=http://localhost:8090 \
EXPO_PUBLIC_EDIFY_IDENTITY_URL=http://localhost:8000 \
  npx expo start
```

Running it on each platform (all three were exercised on 2026-11-10 with the
seeded demo account: sign-in, Home, School Directory, paging):

- **iPhone simulator**: `xcrun simctl openurl booted exp://127.0.0.1:8082`
  (Expo Go). `localhost` is the Mac.
- **Android emulator**: `localhost` is the emulator itself, so forward the
  ports first, then open the same URL in Expo Go:
  `adb reverse tcp:8090 tcp:8090 && adb reverse tcp:8000 tcp:8000 && adb reverse tcp:8082 tcp:8082`
- **Browser**: open `http://localhost:8082`. The gateway must allow that
  origin (`EDIFY_CORS_ALLOWED_ORIGINS=http://localhost:8082`) and the existing
  application must too (`CORS_ORIGINS=http://localhost:8082`). The web build
  keeps tokens in memory only.

Do not start Expo with `CI=1`: it turns off file watching and the server keeps
serving the bundle it started with.

These runs use Expo Go. They prove the app's code on both operating systems;
they are not signed store builds, which come from EAS.

Checks, from `platform/`:

```bash
make proto-lint proto-check     # contracts
make backend-vet backend-test   # Go unit tests
EDIFY_TEST_ADMIN_DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \
  go -C backend test -tags integration ./internal/integration/
make worker-test mobile-test
../.venv/bin/python tools/parity/school_parity.py   # gateway must be running
```

## 5.3 Staging deployment

Nothing below has been carried out. It is the procedure to follow once a
staging environment is approved.

**Infrastructure** (separate from production in every respect):

Rewritten 2026-11-13 for what the gateway now is: it writes (sign-in,
accounts, teams, acting leadership, the Loan and Cluster Leader portals, and
the seven visit and training saves behind `EDIFY_GO_SAVES`), it forwards every
page it does not build to the existing application's feed
(`apps.mobile_feed`), and its saves call the existing application's pricing
and group check. None of that existed when the first version of this section
was written.

**What exists today.** A staging app for the existing application,
`edify-staging-fra`, was built from `.do/staging.yaml` on 2026-08-28 with its
own PostgreSQL and Valkey clusters (`edify-staging-pg-fra`,
`edify-staging-cache-fra`) and a Spaces key scoped to a staging bucket
([docs/release-validation-2026-08-28/11](../release-validation-2026-08-28/11-rollout-infrastructure-closure.md)).
On 2026-11-13 its host (`edify-staging-fra-gzbvn.ondigitalocean.app`) no
longer resolved, and the `staging` branch has not moved since 2026-08-29, so
the app has been taken down. Whether its two clusters still exist, and are
still billed, shows only in the DigitalOcean console. Nothing below reuses
them: they are the release-candidate staging for `main`.

**Shape.** Two App Platform apps on one new database cluster, all in `fra`:

| App | Spec | Components | Branch |
|---|---|---|---|
| `edify-migration-staging-fra` | [`.do/migration-staging.yaml`](../../.do/migration-staging.yaml) | the existing application: `migrate` (pre-deploy job), `web`, `scheduler` | `feature/edify-go-rn-migration` |
| `edify-migration-gateway-staging-fra` | [`.do/migration-gateway-staging.yaml`](../../.do/migration-gateway-staging.yaml) | `gateway` (public), `analytics` (internal port 50061, no route) | `feature/edify-go-rn-migration` |
| database cluster `edify-migration-staging-pg-fra` | created by hand | PostgreSQL 16, smallest size | |

Why these choices:

- **The migration branch, not `staging`.** The app's feed, the group check
  and the pricing door exist only on the migration branch, and the branch adds
  Django migrations, so its database must not be one `main` migrates.
- **Two apps.** The mobile app takes the gateway as a bare host (a path is
  refused by `platform/mobile/src/config/environment.ts`), and an app has one
  domain routed by path, with Django on `/`.
- **Production's shape, smallest sizes.** One web instance, no cache cluster,
  one scheduler, as `.do/app.yaml`, so what staging proves holds for
  production; the smallest instance and database sizes, because it carries
  demo data and testers, not load. Load testing stays with the August staging
  shape.
- **Seeded, never cloned.** `seed --demo`; no real school, staff or money
  record leaves production. A sanitised restore is a later, separate decision.
- **No object storage.** `SPACES_*` are unset, so nothing on staging can reach
  production's bucket. Uploads fail on staging (the inherited production
  settings keep Spaces on); boot and `/api/health/ready` do not probe storage.
  Evidence (M8) needs a staging bucket and key first (the August staging key
  is one candidate).
- **The Next.js web app is not in it yet.** It needs its own host for the same
  reason as the gateway; it is added when its pages are worth testing.

**Procedure**, in this order. Steps 1, 2, 3 and 6 are DigitalOcean console
work for the owner; the database steps need a machine with `psql` and Go
whose address is in the cluster's trusted sources.

1. **Cluster.** DO console → Databases → Create → PostgreSQL 16, region
   Frankfurt, the smallest size, name `edify-migration-staging-pg-fra`.
2. **Part 1.** Apps → Create → from the spec
   (`doctl apps create --spec .do/migration-staging.yaml`). Before the first
   deploy, set its five secrets in the environment editor, each fresh:
   `SECRET_KEY` and `JWT_SECRET` (`openssl rand -hex 40`),
   `FIELD_ENCRYPTION_KEY` and `EDIFY_INTERNAL_KEY` (`openssl rand -hex 32`),
   `SUPER_ADMIN_PASSWORD`. Keep the last four to hand for part 2.
3. **Seed.** When part 1 is green, from the `web` component's console:
   `python manage.py stamp_environment --to staging` (type `STAMP staging`),
   then `python manage.py seed --demo`.
4. **Database roles and Go's own schemas**, with the cluster's `doadmin`
   connection string from its page (`sslmode=require`):

   ```bash
   ADMIN_URL='postgresql://doadmin:<password>@<host>:25060/defaultdb?sslmode=require'
   EDIFY_ENV=staging EDIFY_ADMIN_DATABASE_URL="$ADMIN_URL" platform/deploy/db/apply-roles.sh
   GATEWAY_PASSWORD=$(openssl rand -hex 24)
   psql "$ADMIN_URL" -c "ALTER ROLE edify_gateway PASSWORD '$GATEWAY_PASSWORD'"
   cd platform/backend
   EDIFY_ENV=staging EDIFY_DB_ALLOWED_HOSTS=<host> EDIFY_MIGRATE_DATABASE_URL="$ADMIN_URL" \
     go run ./cmd/schemactl migrate --schema=school_loans --confirm-database=defaultdb
   EDIFY_ENV=staging EDIFY_DB_ALLOWED_HOSTS=<host> EDIFY_MIGRATE_DATABASE_URL="$ADMIN_URL" \
     go run ./cmd/clusterctl migrate --confirm-database=defaultdb
   ```

   Then take the machine's address out of the cluster's trusted sources.
5. **Gateway connection string**:
   `postgresql://edify_gateway:<GATEWAY_PASSWORD>@<host>:25060/defaultdb?sslmode=require`,
   with the same `<host>` the cluster's page shows (the gateway checks it
   against `EDIFY_DB_ALLOWED_HOSTS`, which the spec binds to `${db.HOSTNAME}`).
6. **Part 2.** `doctl apps create --spec .do/migration-gateway-staging.yaml`,
   then its five secrets: `EDIFY_DATABASE_URL` (step 5), `EDIFY_JWT_SECRET`,
   `EDIFY_FIELD_ENCRYPTION_KEY` and `EDIFY_INTERNAL_KEY` (part 1's values),
   and `EDIFY_EXISTING_APP_URL` (part 1's `https://…ondigitalocean.app`).
7. **App build.** An EAS `preview` build with `EXPO_PUBLIC_EDIFY_ENV=staging`,
   `EXPO_PUBLIC_EDIFY_GATEWAY_URL` = part 2's URL and
   `EXPO_PUBLIC_EDIFY_IDENTITY_URL` = part 1's, to testers through TestFlight
   and an internal Android track.

Deploys after that: neither spec deploys on push and the Deploy workflow
releases `main` only. A new build of the branch is a **Deploy** in each app's
console (or `doctl apps create-deployment <app-id>`), part 1 before part 2,
and only from a commit whose Platform CI is green.

**The saves.** Part 2 turns on all seven proved saves (`schedule_visit`,
`reschedule_visit`, `cancel_visit`, `edit_visit`, `schedule_training_pair`,
`group_reschedule`, `group_cancel`). On staging that makes Go the writer of
those saves for the app's users while the web's users keep saving through
Django on the same tables: the two-writer state the production cutover (03,
§3.7) is meant to avoid, accepted here because staging holds demo data and is
where that cutover is rehearsed. Removing a name from `EDIFY_GO_SAVES` and
redeploying part 2 hands that save back.

**Not yet checked against DigitalOcean** (nothing was created to check it):
that a service with only `internal_ports` and no `http_port` passes App
Platform's validation, that `${analytics.PRIVATE_DOMAIN}` and `${db.HOSTNAME}`
resolve as written, and the monthly price, which the console shows before
each create.

**Before staging is called ready**:

- [ ] `/readyz` is green and a signed-in tester sees their own schools.
- [ ] The parity check passes against staging data.
- [ ] From a staging shell, a connection attempt to the production database
      host fails at the network.
- [ ] Mutual TLS, or the platform's private-network encryption, between the
      gateway and the worker.
- [ ] Trace export to a collector, and an alert on gateway error rate.
- [ ] Rate limiting in front of the gateway.

## 5.4 CI

`.github/workflows/platform-ci.yml`, on pushes to the migration branch and its
`feature/migration/**` sub-branches and on pull requests into the migration
branch. It has no deploy job and no secret.

| Job | Checks |
|---|---|
| Protocol Buffer contracts | lint, format, compatibility with the base commit, generated code matches |
| Go gateway | gofmt, tidy modules, vet, unit tests with the race detector, govulncheck |
| Gateway against the existing schema | builds the schema with the existing migrations and seed, runs the integration tests, runs the parity check against the existing API |
| Python analytics worker | ruff, format, tests, pip-audit |
| React Native app | type check, tests, expo-doctor, npm audit, JavaScript bundle for iOS and Android |
| Container images build | both images build and neither runs as root |
| Next.js web app | install, type check, lint, unit tests |

The workflow runs on GitHub. From its first runs until 2026-11-13 every push
of the migration branch failed it: first the React Native app and the Go
gateway's module tidiness (both fixed 2026-11-13), then the Go gateway's
`govulncheck`, which flagged GO-2026-6859 in Go 1.27.3's `net/http`. The
toolchain is now Go 1.27.4 in the workflow, both `go.mod` files and the
gateway image; run 43396618456 on `feature/migration/go-toolchain-1-27-4`
passed all seven jobs.

## 5.5 Branch protection

**Current state** (read from GitHub on 2026-11-09): `main` is protected with
four required checks, administrators included, force pushes and deletion off.
It requires no approving review. The migration branch is on GitHub and, as
read on 2026-11-13, has no protection. Applying the settings below requires
a pull request for every change, so it waits until the branch's own work
stops being merged into it directly.

**Required for `feature/edify-go-rn-migration`**, to apply once the branch is
pushed and the workflow has run once (GitHub only offers checks it has seen):

- Require a pull request before merging.
- Require status checks, with the seven Platform CI jobs above.
- Require branches to be up to date before merging.
- Include administrators.
- Block force pushes and deletion.

```bash
gh api -X PUT repos/O-Mario88/edify-planning-tool/branches/feature%2Fedify-go-rn-migration/protection \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Protocol Buffer contracts",
      "Go gateway",
      "Gateway against the existing schema",
      "Python analytics worker",
      "React Native app",
      "Container images build",
      "Next.js web app"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

**Recommended for `main`** while the migration is open, so the release gate is
held by the platform and not by convention:

- Require one approving review.
- A ruleset that blocks any pull request whose head is
  `feature/edify-go-rn-migration` or `feature/migration/**`, lifted only when
  the release gate in [04-migration-plan.md](04-migration-plan.md) is signed
  off.

Note: the repository is public. Nothing on this branch contains a secret, but
the branch's contents are readable by anyone once pushed.
