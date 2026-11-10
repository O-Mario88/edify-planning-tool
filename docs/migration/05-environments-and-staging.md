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

1. A staging PostgreSQL cluster. The existing `.do/staging.yaml` already
   names one (`edify-staging-pg-fra`); the new services use it, never the
   production cluster.
2. The existing application deployed to staging from its `staging` branch, as
   today. It is staging's identity system and it runs staging's migrations.
3. Two new components on the same private network:
   - `edify-gateway` from `platform/backend/Dockerfile`, public over HTTPS.
   - `edify-analytics` from `platform/workers/analytics/Dockerfile`, internal
     only, no public route.

**Database role**, run once by an operator with the staging owner credentials:

```bash
EDIFY_ENV=staging EDIFY_ADMIN_DATABASE_URL=<staging owner URL> \
  platform/deploy/db/apply-roles.sh
psql <staging owner URL> -c "ALTER ROLE edify_gateway PASSWORD '<generated>'"
```

**Gateway configuration** (staging secret store):

| Variable | Value |
|---|---|
| `EDIFY_ENV` | `staging` |
| `EDIFY_DATABASE_URL` | staging cluster, user `edify_gateway`, `sslmode=require` |
| `EDIFY_DB_ALLOWED_HOSTS` | the staging cluster's hostname, exactly |
| `EDIFY_DB_PRODUCTION_MARKERS` | the production cluster's hostname |
| `EDIFY_JWT_SECRET` | staging's `JWT_SECRET` (not production's) |
| `EDIFY_ANALYTICS_ADDR` | the worker's internal address |
| `EDIFY_HTTP_ADDR` | `0.0.0.0:8090` |

The gateway refuses to start in staging if the host is not the listed one, the
connection is not TLS, the role is a superuser, or the role can write to the
existing tables. Health check path: `/readyz`.

**Worker configuration**: `EDIFY_ANALYTICS_ADDR=0.0.0.0:50061` and nothing
else. It refuses to start if given database settings.

**App**: an EAS `preview` build with `EXPO_PUBLIC_EDIFY_ENV=staging` and the
staging URLs, distributed to testers through TestFlight and an internal
Android track.

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

The workflow has not yet run on GitHub. Each of its commands was run locally
except the two image builds (no Docker on the development machine) and
`zizmor` on the workflow file.

## 5.5 Branch protection

**Current state** (read from GitHub on 2026-11-09): `main` is protected with
four required checks, administrators included, force pushes and deletion off.
It requires no approving review. The migration branch does not exist on
GitHub yet and has no protection.

**Required for `feature/edify-go-rn-migration`**, to apply once the branch is
pushed and the workflow has run once (GitHub only offers checks it has seen):

- Require a pull request before merging.
- Require status checks, with the six Platform CI jobs above.
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
      "Container images build"
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
