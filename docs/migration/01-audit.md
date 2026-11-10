# 1. Audit of the existing application

Measured on `main` at `deefe6f6f` (2026-11-09). Counts come from the code and
from a fresh database built by the application's own migrations and demo seed;
nothing here was read from production.

## 1.1 Shape

One Django 5.2 project (Python 3.13) that renders its own pages. There is no
separate frontend application.

| Layer | What it is |
|---|---|
| Pages | Server-rendered Django templates (about 920), HTMX for partial updates, Alpine.js for local state, Tailwind 4 compiled to committed CSS, ApexCharts, FullCalendar, Leaflet |
| HTTP API | Django REST Framework under `/api/*`, a port of an earlier NestJS backend. JSON envelope `{data, page, pageSize, total, totalPages}`. Used by the pages' own scripts and by the Capacitor shell |
| Realtime | Server-sent events over ASGI (`apps/realtime`), with a cross-process bus |
| Background work | One scheduler process (`manage.py runscheduler`, django-apscheduler) and a transactional outbox (`apps/outbox`) |
| Mobile today | A Capacitor shell in `mobile/` wrapping the web app, with native push (APNs, FCM) |
| Process model | Gunicorn with Uvicorn workers (ASGI); a pre-deploy migration job; a scheduler worker |

56 Django apps, roughly 460,000 lines of Python outside migrations and tests.
The largest: `frontend` (86k, the page views), `planning` (42k), `core` (39k),
`analytics` (32k), `hr` (23k), `activities` (20k).

## 1.2 Database

PostgreSQL 16, one database, one schema. 439 migration files produce 366
tables. Table names are explicit (`db_table`), snake case, singular
(`school`, `user`, `fund_request`).

Conventions the new backend must respect:

- **Primary keys are 30-character string CUIDs**, generated in application
  code (`apps/core/cuid.py`). No sequences, no UUID columns.
- **Soft delete**: `deleted_at` on most domain tables. A soft-deleted row
  means "should never have existed", not "ended".
- **Timestamps**: `created_at`, `updated_at` as `timestamptz`. Time zone
  `Africa/Nairobi` (UTC+3, no daylight saving).
- **Many relationships are plain id columns, not foreign keys**
  (`school.cluster_id`, `school.account_owner_id`,
  `staff_school_assignment.school_id`). Integrity is held by application code
  and health checks. A new backend gets no help from the database here.
- **Choice values are strings with no database constraint** (`school_type`,
  `operational_status`, role names). The vocabulary lives in Python enums.
- **Roles are a text array** on `user.roles`, with one `active_role`.
- Migrations run only in a dedicated pre-deploy job (`migrate_locked`), never
  at web start-up. Two migrations call live application code (activities 0057
  and 0058).

## 1.3 Identity, roles and authorization

- Custom user model (`user` table), email sign-in, bcrypt password hashes.
- Two session mechanisms over one backend: Django sessions for the pages, and
  for the API an **HS256 access token** (15 minutes, claims `sub` and
  `activeRole`) with a rotating, hashed, reuse-detecting refresh token
  (7 days, `refresh_token` table).
- One authentication backend enforces lockout for every sign-in path. MFA by
  challenge code; invitations; password reset; idle timeout.
- **15 roles** (`apps/core/rbac.py`): CCEO, Program Lead, CountryDirector,
  RegionalVicePresident, RegionalProgramLead, ImpactAssessment, Accountant,
  HumanResources, ProjectCoordinator, PartnerAdmin, PartnerFieldOfficer,
  BusinessTransformationOfficer, MfiPartnerAdmin, MfiLoanOfficer, Admin.
- **Permissions are a static matrix in code**, role to permission keys
  (`ROLE_PERMISSIONS`). The `permission` and `role_permission` tables are a
  seeded mirror, not the source.
- **Data scope is resolved per request** (`apps/core/scoping.py`, 1,600
  lines): own schools, supervised team, temporary coverage, region reach,
  country reach bounded by the staff profile's country, project and partner
  portfolios, and acting appointments that swap the permission set for a
  month. Several rules were set by the owner on specific dates and are
  recorded in comments beside the code.

This is the highest-risk area to reimplement. See 1.10.

## 1.4 Domain data

| Domain | Main tables |
|---|---|
| Schools | `school`, `school_closure`, `school_ownership_transfer`, `district_portfolio_transfer`, `school_change_log`, import and data-quality tables |
| Geography | `region`, `district`, `sub_county`, `parish` |
| Clusters | `cluster`, `school_cluster_membership`, `cluster_service_district`, `cluster_score_setting` |
| Staff | `staff_profile`, `staff_school_assignment`, `staff_supervisor_assignment`, `staff_geography_assignment`, `staff_support_capacity`, `acting_assignment` |
| Planning and activities | `monthly_plan`, `monthly_plan_activity`, activity records with closure, timeline, snapshot and IA verification tables, `training_ceiling`, `core_plan`, `core_activity_slot` |
| SSA | `ssa_record`, `ssa_score`, `ssa_recommendation`, import batches. One SSA per school per financial year |
| Partners | `partner`, `partner_assignment`, `partner_activity_allowance`, `partner_member`, `partner_invoice` |
| Projects | `project`, `project_school_assignment`, `project_staff_assignment`, `project_partner_assignment` |
| Money | `cost_catalogue`, `cost_setting`, `activity_cost_snapshot`, `fund_request`, `weekly_fund_request`, `advance_request`, `disbursement`, `accountability_record`, `reimbursement_claim`, `finance_audit_log` |
| Targets | `target_setting`, `monthly_personal_target`, `target_achievement_ledger` |
| Audit | `audit_log` (hash chain, `audit_chain_checkpoint`), `domain_event_log`, `assignment_audit` |

**Stable identifiers** that must never be re-issued: record ids (CUID),
Edify School ID (`school.school_id`, unique), Salesforce account id
(`school.salesforce_account_id`, typed in by hand; there is no Salesforce
integration), activity ids, Salesforce visit and training ids entered at
completion.

**Financial year**: 1 October to 30 September, labelled by the calendar year
it ends in (`apps/core/fy.py`). Quarters Q1 Oct–Dec to Q4 Jul–Sep. A date is
read on its calendar day in `Africa/Nairobi`; the year turns at 21:00 UTC on
30 September. The Work Plan opens on the next financial year once planning for
it is open. Boundary tests pin this behaviour.

## 1.5 Evidence and files

`evidence_record` holds metadata and a generated storage key; the bytes live
in a private bucket (DigitalOcean Spaces through `django-storages`) in
production and on local disk in development. Downloads are authorised and
streamed by the application; nothing is public. Uploads are virus-scanned
(ClamAV client) and PDFs get a rendition. Organisational documents
(`document_asset`, versions, audiences, acknowledgements) use the same private
store.

## 1.6 Notifications

`notification` rows with per-channel delivery records
(`notification_delivery`) and per-person preferences. Channels: in-app,
email (Resend), web push (VAPID), native push direct to APNs and FCM, SMS for
money alerts. Sent through the outbox so a failed provider does not fail the
request.

## 1.7 Deployment

DigitalOcean App Platform, from `.do/app.yaml`:

- `migrate` pre-deploy job, `web` service, `scheduler` worker, all built from
  `main`, with deploy-on-push off. The **Deploy** workflow releases `main`
  only after CI succeeds on it.
- Managed PostgreSQL cluster `edify-production-db`; private Spaces bucket.
- A staging app spec exists (`.do/staging.yaml`, branch `staging`, its own
  database and cache clusters).
- `production_preflight` runs before the web and scheduler processes start.

Because Deploy and CI are tied to `main`, nothing pushed to the migration
branch can deploy.

## 1.8 Tests and baseline

| Suite | Size | Where it runs |
|---|---|---|
| Django tests | about 960 test files, roughly 12,900 test functions | CI, four workers, more than an hour |
| Browser journeys (Playwright) | 64 specs, against a demo-seeded database | CI, two shards, plus a nightly browser matrix |
| UI state tests (Node) | `tests/js` | CI |
| Static checks | ruff, ruff format, missing-migration check, bandit, pip-audit, npm audit, zizmor, CodeQL, Trivy on the image | CI |

**Baseline for this branch**: `main` at `deefe6f6f` passed all four required
checks and was deployed. The Django suite was not re-run locally for this
assignment (it takes over an hour and a parallel run hangs on this machine);
its result is taken from CI on the baseline commit. What was run locally is
listed in [05-environments-and-staging.md](05-environments-and-staging.md).

## 1.9 Performance, as already measured

From the project's own forensic audit (October 2026):

- Opening a page was dominated by the browser: 84–89% of main-thread time was
  style recalculation. The servers were idle (web at or under 25% CPU).
- Saving a schedule was dominated by the server: a reschedule ran 457 SQL
  statements in 2.4 s; a cluster bulk save 990–3,576 statements in 5.6–18.9 s,
  because each school re-costs the whole day.
- With many people online, live-region re-reads turned each save into several
  full-page renders.

What this means for the migration: a native app removes the browser cost
entirely, and the save path is where a Go implementation can help, but only if
it batches the costing. Porting the per-school pipeline line for line would
keep the cost.

## 1.10 Migration risks

| # | Risk | Why it matters | Mitigation in the plan |
|---|---|---|---|
| 1 | Authorization rules diverge between the two backends | 1,600 lines of scope rules plus a permission matrix, changed by owner decision almost weekly | Go serves a strict subset first; a parity test compares both backends for every account in CI; the rules move one domain at a time |
| 2 | Business rules change on `main` while they are being ported | `main` took 316 pull requests in about ten weeks | Port from pinned commits; parity tests fail when `main` changes a ported rule; merge `main` into the branch on a schedule |
| 3 | Integrity lives in application code, not the database | Plain id columns, unconstrained choices | Go writes go through one module per table, with the same checks, and are compared against the existing application's results |
| 4 | Two writers on one database | Lost updates, counters and cost snapshots out of step | No dual writes. A table has one writer at a time; ownership moves by explicit, approved cutover |
| 5 | The audit hash chain breaks | Each `audit_log` row hashes the one before | One process appends to the chain until the chain's cutover; Go reproduces `stable_stringify` byte for byte, proven against existing rows |
| 6 | Financial-year and time-zone edge cases | Local-day arithmetic at the year boundary | The boundary tests are ported first, as a shared test vector file |
| 7 | Money is computed differently | Day rates, shared days, night-away rules, snapshots | Money moves last, after a period of shadow comparison on restored data |
| 8 | Schema drift under the gateway | Existing migrations keep landing | The schema contract test runs against the schema built by the migrations at each commit |
| 9 | Mobile app and web app disagree | Two clients, one truth | Neither client holds rules; both read the same backend answers |
| 10 | Server-rendered pages have no API | Most page logic is in view code, not behind `/api` | The plan budgets for extracting each rule from its view before porting it |
