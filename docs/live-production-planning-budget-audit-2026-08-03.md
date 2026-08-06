# Live Production Planning-to-Budget Audit — 2026-08-03

## Decision

**NO-GO / NOT CERTIFIED.** The live site is reachable and its public liveness
and readiness probes are green, but the absolute completion gate is not met.
The current session has only a Program Lead account and no production database,
DigitalOcean control-plane, worker, scheduler, log, or staging access. FY2026
contains no representative scheduled/funded activities visible to this account,
so the required live financial lineage and UGX 0 reconciliations cannot be
proven without creating prohibited fake production records.

Evidence classifications in this document are deliberately limited to:

- **LIVE PRODUCTION VERIFIED** — observed on `https://www.edifyplanning.app`.
- **SOURCE/REGRESSION VERIFIED** — fixed and tested locally, not deployed.
- **NOT VERIFIED** — unavailable with the current role or infrastructure access.

## Live release evidence

| Evidence | Result | Classification |
|---|---|---|
| Canonical URL | `https://www.edifyplanning.app` | LIVE PRODUCTION VERIFIED |
| Commit | `d9d50adf24c40454d372663d4b19155cba0807f8` | LIVE PRODUCTION VERIFIED |
| Release identifier | `unknown` | LIVE PRODUCTION VERIFIED defect |
| Build timestamp | `2026-08-03T03:45:36+00:00` | LIVE PRODUCTION VERIFIED |
| Static manifest hash | `f5b29e60f2158ff0` | LIVE PRODUCTION VERIFIED |
| Main CSS asset | `css/main.066141049b07.css` | LIVE PRODUCTION VERIFIED |
| Liveness | HTTP 200, `{"status":"ok"}` | LIVE PRODUCTION VERIFIED |
| Readiness | HTTP 200, `{"status":"ok","db":"up"}` | LIVE PRODUCTION VERIFIED |
| Browser console | No warnings or errors during audited PL routes | LIVE PRODUCTION VERIFIED |
| GitHub CI for deployed commit | Required Django job failed at Ruff formatting; tests never ran | LIVE PRODUCTION VERIFIED release-control defect |
| Image digest / instance inventory | unavailable | NOT VERIFIED |
| Migration state | unavailable | NOT VERIFIED |
| Worker and scheduler release | unavailable | NOT VERIFIED |
| Production logs | unavailable | NOT VERIFIED |

Low-rate samples (five sequential requests; seconds):

| Route | Status | Samples | Median |
|---|---:|---|---:|
| `/api/health/live` | 200 | 0.695, 0.452, 0.432, 0.411, 0.427 | 0.427 |
| `/api/health/ready` | 200 | 0.814, 0.520, 0.668, 0.545, 0.542 | 0.545 |
| `/api/health/build` | 200 | 0.712, 0.475, 0.481, 0.534, 0.597 | 0.534 |
| `/reset-password` | 404 | 0.636, 0.537, 0.494, 0.504, 0.504 | 0.504 |

## Live Program Lead browser audit

Authenticated principal: Denis O'Mario (`domario@edify.org`), active role
Program Lead.

| Route | Live result | Classification |
|---|---|---|
| `/dashboard` | FY2026 dashboard renders; 2 CCEOs, 2,171 schools, zero activities/targets/approvals/funding | LIVE PRODUCTION VERIFIED |
| `/planning` | 101 client schools in scope; schedule drawer opens and shows SSA intelligence and governed form fields | LIVE PRODUCTION VERIFIED |
| `/my-plan` | zero week/month/quarter/FY activities | LIVE PRODUCTION VERIFIED |
| `/work-plan` | zero activities; plan-derived budget UGX 0 | LIVE PRODUCTION VERIFIED |
| `/fund-requests/weekly` | zero source activities; UGX 0 | LIVE PRODUCTION VERIFIED |
| `/budgets/monthly` | redirects to `/accounts/monthly-request/`; activity cost plan renders | LIVE PRODUCTION VERIFIED |
| `/fund-approvals` | empty queue; page renders | LIVE PRODUCTION VERIFIED |
| `/country-budget`, `/cost-settings`, `/system-health` | role-gated back to Program Lead dashboard | LIVE PRODUCTION VERIFIED authorization; feature state NOT VERIFIED |

The Planning page reported 3 schools ready for support, 0 scheduled, 0 cost
blocked, 107 requiring data cleanup, 2,061 not grouped in a cluster, and 176
core package gaps. An ABAKO JUNIOR SCHOOL schedule drawer showed its latest
confirmed SSA and weakest interventions. No mutation was submitted.

## Remediation ledger

### PROD-AUTH-001 — Password reset email target returns 404

- Severity: High
- Feature / URL: Password Reset, `/reset-password?token=…`
- Role: public/reset recipient
- Expected: token validation page with a CSRF-protected password form
- Actual live behavior: HTTP 404, title `Not Found`, body “The requested resource was not found on this server.”
- Screenshot: captured in the browser audit task before remediation
- Browser trace / console: direct navigation; no console error
- Production API / DB / logs: not applicable / NOT VERIFIED / NOT VERIFIED
- Production release: `d9d50adf…`, manifest `f5b29e60f2158ff0`
- Root cause: reset emails already point at `/reset-password`, while the deployed frontend exposes only the JSON API reset endpoint
- Affected code: accounts reset service, frontend auth routes/views, login JS/CSS, reset template
- Financial / Planning impact: none directly; operational account recovery is blocked
- Fix: added a same-origin HTML route, token validation, CSRF-protected POST, row-locked single-use reset, and browser form behavior
- Tests: invalid, expired, reused, mismatched, CSRF, and successful-reset cases
- Current status: **Regression Tested** (not deployed)
- Live closure evidence: pending; production still returns 404

### PROD-REL-001 — Release identifier is unknown

- Severity: High
- Feature / URL: Release provenance, `/api/health/build`
- Expected: immutable commit and release identifier for every serving process
- Actual live behavior: commit is exact; `release` is `unknown`
- HTTP / cache: 200; `Cache-Control: no-store, max-age=0`; Cloudflare bypass
- Root cause: the image build correctly leaves unavailable Docker build args empty, but App Platform injected only `GIT_COMMIT` at runtime and the runtime provenance reader did not accept `RELEASE`
- Fix: runtime `RELEASE` fallback plus App Platform binding to the immutable source revision
- Tests: runtime fallback and image-value precedence contract
- Current status: **Regression Tested** (not deployed)
- Live closure evidence: pending; production still reports `unknown`

### PROD-REL-002 — Deployed commit has a failed required CI run

- Severity: High
- Feature: deployment governance
- Expected: required Django lint, migration, tests, CSS, security, and CodeQL gates pass before deployment
- Actual live behavior: production serves `d9d50adf…`; GitHub CI run `30782505104` failed because Ruff would reformat `apps/activities/services.py` and migration `0035`; the migration check, tests, and CSS gate were skipped. Security and CodeQL passed.
- Root cause: production auto-deploy is not gated on successful CI completion, and branch protection is not enforced for administrators
- Fix completed: formatted both files; full current-tree Ruff format/check now passes
- Remaining fix: make deployment consume a successful immutable CI artifact instead of rebuilding every main push independently
- Current status: **Regression Tested** for formatting; deployment-control change NOT VERIFIED

### PROD-PLAN-001 — Field Debrief acceptance bypasses Planning

- Severity: Critical
- Feature: Field Debrief recommendation acceptance
- Expected: accepted operational follow-up enters the canonical Planning gate, remains cost-free until scheduled, enforces scope and entitlement, and creates an audit event
- Actual deployed code path: directly creates `Activity`; an existing contract test explicitly listed this as an allowed operational bypass
- Live mutation: not executed because the prompt prohibits fake production work and no responsible business owner selected a genuine debrief
- Classification: production artifact presence confirmed by commit; behavior **NOT VERIFIED** on production data
- Root cause: the earlier path bypassed scope, client visit entitlement, duplicate prevention, Planning provenance, and canonical audit behavior
- Fix: route acceptance through `activities.services.create`; resolve internal/external School identities; enforce PL/CD/Admin authority, target scope, entitlement, cluster and partner preconditions; preserve the planned date; create no cost line before scheduling; audit as `activity.planned`; keep recommendation update atomic
- Tests: single Activity creation chokepoint, planning-source stamp, zero pre-schedule cost lines, owner identity, entitlement refusal and rollback, actor/date audit evidence, notification preservation
- Current status: **Regression Tested** (not deployed)

### PROD-PLAN-002 — System Health does not hard-fail missing Planning provenance

- Severity: Critical
- Feature: System Health / Work Plan integrity
- Expected: any live Activity without `planning_source` makes System Health red
- Actual deployed code path: excludes `planned` rows and reports other unstamped live rows as a warning, allowing the aggregate health result to remain green
- Live System Health page: NOT VERIFIED with the Program Lead role
- Root cause: provenance was treated as a late scheduling warning rather than the governing creation invariant
- Fix: include planned drafts and scheduled work in the check; classify any non-zero count as fail/critical
- Test: a live cost-free planned Activity without provenance makes `healthy=false`
- Current status: **Regression Tested** (not deployed)

## Automated evidence

- 148 targeted planning, costing, funding, roll-up, debrief, provenance, and password-reset tests: PASS
- 132 core planning-to-budget integrity tests before the Field Debrief change: PASS
- Ruff check: PASS
- Ruff format check: PASS
- `makemigrations --check --dry-run`: PASS, no changes
- Django system check: PASS
- Local dirty-tree image build: PASS; non-root runtime user `edify`, runtime import PASS, image digest `sha256:f03dc61b8229704cd7b4c294df69b60ace55f520a11478aa6670388f09700b37`, static manifest `34bebcb38e48cdd5`
- Production-settings deploy check against the developer `.env`: intentionally fails closed because local values are not production secrets; this is not evidence about live environment values

The local image is **not an approved deployment artifact**. The shared
workspace contains unrelated uncommitted changes and a pre-existing unfinished
cherry-pick on `main`; changing or completing that operation would risk the
owner's work. A clean candidate branch/commit must be produced after that Git
operation is resolved, then rebuilt so the artifact maps to one exact commit.

## Required evidence still unavailable

The following must remain NOT VERIFIED and block certification:

- Country Director, CCEO, partner, Project Coordinator, Accountant, IA and RVP role journeys
- an owner-approved genuine live activity across Planning → cost snapshot → My Plan → Work Plan → funding request → monthly/quarter/annual budget → approval/disbursement/accountability/NetSuite/closure
- read-only PostgreSQL lineage and all UGX 0 reconciliation queries
- production System Health finance checks
- DigitalOcean application spec, environment flags, image digests, instance count, migration job, scheduler/worker identity and logs
- isolated production clone destructive, concurrency, rollback and scale scenarios
- staging deployment and promotion of the exact immutable artifact
- post-deploy live screenshots, database verification and monitoring

## Next production gate

Do not merge or deploy this work as a certified release until a staging target,
DigitalOcean read/deploy access, production read-only database access, and the
remaining role accounts are available. After those are supplied, run the clone
scenarios, merge only after required checks pass, promote the same artifact,
and repeat this ledger against the new `/api/health/build` identity.
