# Edify full production reliability audit — 2 August 2026

Status: **active audit; production remains a no-go for enterprise-grade certification**.

This document is the live remediation ledger and evidence record for the full
production reliability mandate. Production testing is deliberately
non-destructive. Load, chaos, restart, dependency-failure, restore and rollback
exercises are restricted to an isolated production-like staging environment.

## Baseline

| Item | Observed value |
|---|---|
| Repository | `O-Mario88/edify-planning-tool` |
| Branch | `main` |
| Source and deployed revision | `1d039ef581f19f2e4434d1e892272bf39ece505d` |
| Working tree at audit start | only pre-existing untracked `.deploy-verify/` |
| Local audit Python | 3.13.12 (`.venv`) |
| Production image Python | 3.13 |
| Django | 5.2.16 |
| PostgreSQL client / declared topology | 16.13 / PostgreSQL 16 |
| Node / npm | 24.14.0 / 11.9.0 |
| Production ASGI server | Daphne |
| Production static manifest | `631bdab11312fe34` |
| Canonical production URL | `https://www.edifyplanning.app` |
| Initial checks | Django check clean; no migration drift or pending plan; Ruff lint and format clean; dependency installation consistent |
| Route inventory | 469 routed product surfaces; 870 registered routes; 293 API routes; 11 roles |
| Card inventory | 557 titled cards across 197 templates; zero same-page duplicate titles; zero ambiguous titles |
| KPI inventory | 268 tiles across 36 modules and 222 distinct labels |

The platform is classified **Tier 2 — Business Critical**. Finance,
authorization, evidence, approval, workflow-transition and audit-chain paths
receive Tier-1-style correctness controls because their failure can create
financial loss, unauthorized action or irreconcilable records.

## Reliability remediation ledger

### PRF-001 — Production uses a development database

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** Production Readiness, Database Reliability, SRE, Security
- **Affected roles/features:** all users and every persistent workflow
- **Evidence:** DigitalOcean identifies `dev-db-315277` as a “Dev Database”,
  with 512 MB RAM, shared CPU and 1 GB disk, and explicitly states that it is
  not intended for production. The committed target specification also marks
  its database as `production: false`.
- **Impact / failure path:** capacity exhaustion, missing production database
  features, an unproven backup/restore posture, and a single database failure
  can interrupt or lose access to all planning, finance, evidence and audit
  data.
- **Target state:** managed PostgreSQL 16 with automated backups/PITR,
  documented RPO/RTO, capacity alerts, protected access and an isolated restore
  rehearsal.
- **Implementation:** requires an approved billable infrastructure change and
  a rehearsed dump/restore/cutover. No live conversion was attempted by this
  audit.
- **Verification:** restore into isolated staging; row, FK, sequence, audit
  chain, evidence-reference and critical-route smoke checks; measured RPO/RTO;
  cutover and rollback rehearsal.
- **Status:** **Root Cause Confirmed — release blocker**

### PRF-002 — Shared Redis/cache topology is absent

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** Reliability, Security, Performance, Architecture
- **Affected features:** rate limits, cached role/tenant/FY views, SSE and any
  future multi-instance deployment
- **Evidence:** every production boot logs `Redis unreachable at
  redis://127.0.0.1:6379/0` and falls back to per-process `LocMemCache`.
- **Impact / failure path:** cache state is not shared between processes;
  invalidation and IP rate limiting become instance-dependent; scaling can
  return inconsistent answers or multiply the permitted request rate.
- **Target state:** one managed Redis-compatible service shared by web and
  scheduler, with bounded connect/read timeouts, authentication/TLS, health
  telemetry and tested cache-loss degradation.
- **Implementation:** code already supports `REDIS_URL`; provisioning and
  binding are billable environment changes and were not performed without
  explicit approval.
- **Verification:** two-worker invalidation, throttle and SSE isolation tests;
  cache-unavailable staging test; zero production fallback warnings.
- **Status:** **Root Cause Confirmed — release blocker**

### PRF-003 — Live app topology drifted from the reviewed specification

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** DevSecOps, Production Readiness, Reliability
- **Evidence:** live web is 1 GB / 1 shared vCPU, port 8000, one container,
  migrations on web startup and no configured liveness check; the committed
  specification targets 2 GB, port 8080, a pre-deploy migration job,
  `RUN_MIGRATIONS=false` and `/api/health/ready`.
- **Impact / failure path:** concurrent replica boots can race migrations;
  configuration review does not describe the running system; the 1 GB process
  has less headroom for pandas/numpy/LibreOffice workloads; readiness behavior
  is not an enforced traffic gate.
- **Target state:** apply a reviewed App Spec with pre-deploy migrations,
  explicit readiness and liveness checks, 2 GB web capacity, immutable runtime
  configuration and drift detection.
- **Verification:** deployment logs show one pre-deploy migration and web
  migration skip; probes exercise the intended paths; release verifier, smoke
  suite, metrics and rollback threshold remain green.
- **Rollback:** revert the App Spec or redeploy the last known-good spec and
  artifact; never reverse a data migration without its own recovery plan.
- **Status:** **Root Cause Confirmed — release blocker**

### PRF-004 — Required scheduler process is not deployed

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** SRE, Architecture, Production Readiness, QA
- **Affected features:** weekly requests, monthly plans, escalation, digest,
  target sync, PD and performance-cycle reminders, recurring debrief detection
- **Evidence:** DigitalOcean lists only the web service and development
  database. The scheduler worker remains commented out in `.do/app.yaml`; web
  correctly keeps `ENABLE_BACKGROUND_JOBS=false`.
- **Impact / failure path:** time-dependent workflows silently become stale;
  overdue notifications, reconciliations and snapshots may never run.
- **Target state:** exactly one dedicated scheduler process with a database
  lock, heartbeat, last-run/last-success/next-run telemetry, timeouts,
  idempotency and an actionable alert/runbook.
- **Verification:** two-scheduler exclusion test, killed-mid-job recovery,
  database-unavailable behavior, boundary-date runs and live heartbeat.
- **Status:** **Root Cause Confirmed — release blocker**

### PRF-005 — Database access occurs during Django application initialization

- **Priority / confidence:** P2 Medium / high confidence
- **Pillars:** Architecture, Reliability, Deployment Safety
- **Evidence:** production startup emits Django’s `APPS_NOT_READY_WARNING_MSG`
  for database access during app initialization.
- **Impact / failure path:** imports can fail or delay before the process is
  ready, management commands inherit hidden database side effects, and startup
  ordering becomes coupled to database availability.
- **Target state:** no database query from settings import, module import or
  `AppConfig.ready()`; explicit post-migrate/reference-data and request/job
  boundaries own database access.
- **Verification:** production settings/application import with database
  unavailable does not query; startup log contains no warning; reference data
  and scheduler registrations remain intact.
- **Repair:** removed database work from both `CoreConfig.ready()` and
  `SystemHealthConfig.ready()`. Added the explicit fail-closed
  `production_preflight` management command and wired it into the container
  entrypoint before production Daphne/Gunicorn/scheduler processes.
- **Verification:** 56 focused boot/deployment/environment tests pass;
  production-mode `manage.py check --deploy` completes with RuntimeWarnings
  promoted to errors; the previous app-registry warning is absent.
- **Status:** **Backend Fixed — deployment pending**

### PRF-006 — Live observability is infrastructure-only and incomplete

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** Observability, Incident Response, Production Readiness
- **Evidence:** no component alert policies, no log-forwarding destination and
  no application-level log retention are configured. DigitalOcean exposes CPU,
  memory, restart, request-rate and latency charts, but no owned business/SLO
  alerts or runbook links.
- **Impact / failure path:** finance, scheduler, storage, audit-chain,
  reconciliation and queue failures can persist until a user reports them;
  short-lived container logs are insufficient for investigation.
- **Target state:** centralized protected logs, request/deployment correlation,
  critical-journey SLIs/SLOs, actionable alerts with owners and runbooks, and
  dashboards for finance reconciliation, scheduler, storage, audit chain and
  queue age.
- **Verification:** controlled staging alert exercises and live synthetic
  checks route to the named owner without exposing secrets or HR/evidence data.
- **Status:** **Root Cause Confirmed — release blocker**

### PRF-007 — Canonical generated inventories were stale

- **Priority / confidence:** P2 Medium / high confidence
- **Pillars:** QA, DevSecOps, Maintainability
- **Evidence:** regenerating the current route/card/KPI inventories changed the
  page JSON state map, card counts/templates and KPI source locations.
- **Repair:** regenerated `docs/platform-page-inventory.json`,
  `docs/platform-card-inventory.json` and
  `docs/platform-kpi-inventory.json` from revision `1d039ef`.
- **Verification:** page Markdown remains byte-identical; regenerated current
  inventory reports 469 routed surfaces, 557 titled cards and 268 KPI tiles.
- **Status:** **Backend Fixed — inventory regeneration verified**

### PRF-008 — Authenticated live feature/role matrix lacks safe credentials

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** QA, Security, Production Readiness
- **Evidence:** the configured local administrator credential was rejected by
  production. Later in the audit, a user-supplied browser session allowed a
  non-mutating Program Lead smoke across 18 representative journeys and three
  direct-URL denial probes. The remaining 10-role matrix still lacks dedicated
  production-safe accounts/sessions.
- **Impact:** anonymous reachability does not prove object scope, role scope,
  workflow handoffs, finance invariants, HTMX mutations or responsive behavior
  after authentication.
- **Target state:** dedicated non-billable test tenant/data and one controlled
  account per role in staging; production receives read-only synthetic accounts
  only if explicitly approved and technically constrained.
- **Verification:** browser and backend role matrix across desktop, tablet and
  mobile, including direct-URL denials and cross-scope object probes.
- **Status:** **Program Lead read-only evidence captured; remaining role matrix blocked**

### PRF-009 — Expected user input was logged as an unhandled server error

- **Priority / confidence:** P2 Medium / high confidence
- **Affected feature:** partner assignment and related planning mutations
- **Evidence:** a missing Activity Catalogue selection raised `ValueError`,
  producing an `ERROR` “Unhandled error during an action” even though the HTTP
  response was a user-facing 400.
- **Repair:** changed seven deliberate request-validation failures to the
  typed `BadRequest` exception and added an `assertNoLogs(..., ERROR)`
  regression for the reproduced partner-assignment path.
- **Verification:** the 15-test request-error suite passes; the final combined
  suite exercised the path without the previous unhandled-error log.
- **Status:** **Backend Fixed — deployment pending**

### PRF-010 — ASGI database connection exhaustion under modest concurrency

- **Priority / confidence:** P1 High / high confidence
- **Pillars:** Reliability, Performance, Database Safety
- **Evidence:** at 12 concurrent authenticated requests, 165 of 2,591 requests
  returned HTTP 500 (6.37%). PostgreSQL reported that remaining connection
  slots were reserved for superusers, and approximately 98 application
  connections remained idle. `CONN_MAX_AGE=60` retained one connection per
  ASGI sync thread.
- **Root cause:** persistent Django database connections were enabled for an
  ASGI-only deployment, contrary to Django's ASGI database guidance.
- **Repair:** set `CONN_MAX_AGE=0`; an external bounded pool is the appropriate
  future optimization. Added a regression assertion.
- **Verification:** the identical 12-user rerun produced 2,598/2,598 HTTP 200,
  43.12 requests/second and 338 ms p95, then zero retained application
  connections. The corrected feature-page target run and soak below also
  passed with zero errors.
- **Status:** **Backend Fixed — deployment pending**

### PRF-011 — Administrative analytics and System Health breach load budgets

- **Priority / confidence:** P2 Medium / high confidence
- **Evidence:** the corrected real-page four-user run had `/analytics` at
  2,071 ms p95 and `/system-health` at 1,802 ms p95 against 1,500 ms budgets.
  Sequential profiling observed 104 and 288 queries respectively.
- **Repair:** added 30-second read-only dashboard snapshots with bounded,
  fail-open stampede protection. Tests bypass caching; analytics exports remain
  uncached. Added shared Redis to the production-like Compose topology.
- **Verification:** corrected four-user rerun: analytics 149 ms p95, System
  Health 171 ms p95; 12-user target: 279/260 ms p95; three-minute target soak:
  333/336 ms p95. Cold rebuild maxima remain 2.1–4.1 seconds and are recorded,
  not hidden.
- **Status:** **Backend Fixed with measured cold-path residual — deployment pending**

### PRF-012 — Current shared worktree has an unrelated UI contract failure

- **Priority / confidence:** P1 High / high confidence
- **Evidence:** concurrent edits changed the page-hero CSS to a tonal surface,
  while `PageHeroSurfaceContractTest` still requires a transparent flat hero.
  The final combined run finished 3,705 tests with one failure at that exact
  assertion. Those files are outside this audit patch and were preserved.
- **Impact:** the shared worktree is not a releasable exact candidate and must
  not be pushed merely because this audit's focused tests pass.
- **Follow-up observed:** the concurrent UI owner updated the contract after
  the full run; its focused four-test suite then passed. Two of that work's
  Python files remained outside Ruff format and the moving shared tree did not
  receive another full clean run.
- **Target state:** finish formatting and run the exact candidate through a
  clean full suite.
- **Status:** **Focused regression fixed externally; exact-candidate gate still pending**

### PRF-013 — Live Program Lead operational state is materially unhealthy

- **Priority / confidence:** P1 High / high confidence for the displayed live
  state; business interpretation requires the accountable owners
- **Evidence:** the live Program Lead dashboard displays 2 CCEOs / 2,171
  schools, 0% team execution, 0/2 CCEOs on track, 0% Activity SF ID compliance,
  1,367 high-risk schools and an overload warning for 2 staff above 120%
  capacity. The live To-Do page shows 40 items: 4 analytics, 12 core-school, 8
  data-quality, 8 planning and 8 SSA actions.
- **Impact:** even with correct software behavior, the visible operational
  portfolio is not in an enterprise-ready green state; high-risk schools,
  workload imbalance, missing program evidence and queued data/planning work
  can make analytics and financial planning unreliable.
- **Target state:** named Program Lead/business owners triage the queue,
  validate whether zero-percent metrics are genuine or missing-data symptoms,
  rebalance workload and close/accept each high-risk exception with evidence.
- **Status:** **Live business/operations blocker — owner action required**

## Current live measurements

All samples were sequential and intentionally low-rate from Kampala through
Cloudflare; they are user-path measurements, not an origin load test.

| Route | Samples | HTTP result | p50 | p95 | p99 |
|---|---:|---|---:|---:|---:|
| `/api/health/live` | 20 | 20 × 200 | 529 ms | 610 ms | 610 ms |
| `/api/health/ready` | 20 | 20 × 200 | 596 ms | 1,063 ms | 1,063 ms |
| `/api/health/build` | 10 | 10 × 200 | 543 ms | 616 ms | 616 ms |
| `/` | 10 | 10 × 200 | 536 ms | 595 ms | 595 ms |
| `/login` | 10 | 10 × 200 | 551 ms | 807 ms | 807 ms |

The login route is at the 800 ms common-page p95 boundary, and readiness
exceeded it in this small sample. This does not identify the saturated resource
or prove capacity; representative staging load and origin telemetry remain
required.

An authenticated, read-only Program Lead browser smoke subsequently opened 18
representative journeys: Dashboard, Team Targets, My Plan, Planning, Schools,
Core Schools, Clusters, Partners, Projects, Work Plan, Weekly Fund Requests,
Fund Approvals, Program Lead Analytics, Policy Compliance, Performance Reviews,
To-Do, Notifications and Settings. Every route completed with the correct page
heading and scoped content. Direct navigation to Accountant, Admin user
management and System Health surfaces redirected back to the Program Lead
dashboard, confirming those three scope boundaries. No mutation or export was
triggered.

Single browser-navigation elapsed times were mostly 0.85–3.8 seconds; Program
Lead Analytics was a 7.39-second outlier. These are full browser navigations,
not server p95 samples, but the outlier corroborates the analytics performance
finding and must be remeasured after the dashboard-cache patch is deployed.

## Isolated recovery and performance evidence

These tests used the local production-shaped 16,274-school estate and a
two-worker Gunicorn/Uvicorn ASGI deployment. They do not claim DigitalOcean
hardware equivalence and did not send load or failures to production.

| Exercise | Result |
|---|---|
| Backup/restore | **Passed** — 16,935,094-byte custom dump; all 246 table counts identical; 241 migration rows; 290 validated FKs; sequences, eight authenticated pages and audit chain verified |
| Rollback | **Passed** — previous release `c39cacc9` served eight authenticated pages against schema from deployed `1d039ef5`; audit chain intact |
| Corrected baseline, 4 users / 60 s | **Passed** — 1,723 responses, 0 errors, 28.62 rps, 319 ms overall p95 |
| Corrected target, 12 users / 60 s | **Passed** — 2,599 responses, 0 errors, 43.07 rps, 567 ms p95, 885 ms p99 |
| Corrected target soak, 12 users / 180 s | **Passed** — 7,518 responses, 0 errors, 41.70 rps, 597 ms p95, 901 ms p99; zero retained DB connections; worker RSS stable |
| Stress, 24 users / 60 s | **Failed capacity objective** — 2,297 HTTP 200 plus 6 timeouts (0.261%); analytics 1,821 ms p95; System Health 3,049 ms p95 |

The verified safe tier for this isolated two-worker shape is 12 concurrent
administrative requests. Twenty-four is beyond the measured knee. Production
capacity remains uncertified until the managed database, shared Redis and
reviewed App Spec are deployed and the same test is repeated there.

Live headers include HSTS, CSP, frame denial, MIME sniffing protection, a
referrer policy and correlation IDs. Residual hardening debt remains: CSP
permits `unsafe-inline` and `unsafe-eval`, and HSTS is 30 days rather than the
usual long-lived preload posture.

DigitalOcean’s last-hour charts showed approximately 0.36–18.15% CPU,
1.43–25.45% memory and ingress request-rate below 0.89 requests/second during
deployment/sweeps. The chart’s p95 latency range included a 9.25-second point,
so averages alone cannot support an enterprise performance claim.

## Evidence log

| Evidence | Result |
|---|---|
| DigitalOcean deployment `bfa990b2-4799-4f60-99fd-3da3dfa5e88d` | Success; live revision `1d039ef` |
| `/api/health/live` | 200, `{"status":"ok"}` |
| `/api/health/ready` | 200, database up |
| `/api/health/build` | exact revision and manifest `631bdab11312fe34` |
| Production startup | migrations executed in web; Redis fallback; application-init DB warning; Daphne listening on port 8000 |
| Runtime log error filter | no `ERROR` result in the currently retained/visible window; this is not long-term log evidence |
| Anonymous route sweep from preceding exact-revision certification | 210 concrete page routes: 3 × 200, 196 × 302, 11 × 405, zero transport/5xx |
| Sign-in UI | semantic form; required email/password; correct email/password input types; invalid configured credential returns a generic error |
| Authenticated Program Lead live smoke | 18 representative pages rendered correct headings/content; 3 cross-role direct URLs redirected to the scoped dashboard; no mutations |
| Authenticated live performance signal | Program Lead Analytics single full navigation 7.39 s; other representative pages 0.85–3.8 s |
| Live operational portfolio | 1,367/2,171 schools flagged high risk; 2 staff over 120% capacity; 0% Activity SF ID compliance; 40 queued actions |
| Local checks | Django check, migration drift/plan and dependency consistency pass; Ruff lint/format passes for the audit-owned Python files, while two concurrent UI-work files remain outside the formatting gate |
| Initial exact-revision full suite | 3,688 tests in 718.806 s; **OK**, 2 skipped |
| Final combined shared-tree suite | 3,705 tests in 3,089.380 s; 1 unrelated concurrent UI contract failure, 2 skipped; audit-focused tests pass |
| Recovery rehearsal | backup/restore and previous-release rollback both passed |
| Concurrent performance | 4-user baseline, 12-user target and 3-minute soak passed; 24-user stress failed and defines the observed knee |
| Security/dependency gates | pip-audit, Bandit CI threshold, npm audit, Ruff, Django deploy checks and migration drift checks pass for the audit patch |

## Readiness decision

The running production service is reachable and its public artifact is exact,
but a development database, missing scheduler, absent shared cache, unreviewed
platform drift, incomplete observability, ten unverified authenticated role
matrices, a failed 24-user isolated stress tier, materially unhealthy live
portfolio indicators and a moving shared worktree without a clean final full
suite are hard gates. The isolated restore, rollback, 12-user load and soak
rehearsals are positive evidence, but they do not certify the undersized live
DigitalOcean database/runtime or replace a production-shaped staging gate.
Numeric scoring cannot override these hard gates.

**Not Approved**
