# Final Planning and Monitoring Workflow Audit — Deployment Gate

Audit date: 2026-07-29  
Audit baseline: `00e4989abb42eec5a406832026471ab76aba453f`  
Audit branch: `codex/final-planning-monitoring-audit`  
System criticality: Tier 1 / mission critical  
Recommendation: **NO-GO**

## A. Executive Summary

The code-level Planning and Monitoring ecosystem is materially safer than the
merged baseline: 18 direct view-owned state mutations were moved behind
canonical services; the second reimbursement ledger was retired; OpenAPI and
the `/api` prefix were repaired; production configuration now fails closed;
audit-chain appends serialize correctly; deterministic historical drift was
backed up and repaired; and responsive/accessibility defects on representative
field, Partner, Finance and IA surfaces were corrected.

Deployment is nevertheless **not approved**. The post-repair local data set has
18 genuine workflow-blocker categories, including evidence, IA/Finance ordering,
NetSuite, analytics, Partner visibility, visit batching and duplicate client
entitlements. Two critical local Admin Ops incidents are also unacknowledged.
The auditor has no live production/staging worker process or heartbeat to prove
that required jobs are operating. These are explicit hard-gate failures, not
documentation caveats.

No ambiguous business record was “fixed” by inference. A release owner must
resolve or formally adjudicate every row, prove the dedicated worker heartbeat,
acknowledge/investigate the incidents, rerun this matrix against the release
candidate and obtain a green System Health result.

## B. Current commit and environment

| Item | Evidence |
|---|---|
| Pre-audit merge | PR #18, merged to `main` as `00e4989abb42eec5a406832026471ab76aba453f`; required Django, security and CodeQL checks green |
| Audit implementation | `a3393e4e` (`audit planning and monitoring deployment gates`) |
| Audit working branch | `codex/final-planning-monitoring-audit` |
| Python / Django | Python 3.13.12 / Django 5.2.16 |
| Node / npm | Node 24.14.0 / npm 11.9.0 |
| Database | Local PostgreSQL 16.13; 203 applied migrations; database is explicitly demo-seeded and is not represented as production |
| Browser matrix | Chromium in-app browser; 1440, 1366, 1280, 1024, 768, 430, 390 and 360 px |
| Production configuration | `config.settings.prod` with ephemeral valid secrets, explicit host/origin and all development bridges disabled |
| External limitation | No authenticated production/staging environment, worker process, scheduler heartbeat, real object storage or deployment telemetry was available |

## C. Baseline test result

The first complete merged-baseline run executed 3,274 Django tests in 673.488
seconds with 0 failures, 0 errors and 2 skips. The current audit tree collects
3,286 tests. Targeted repair suites are green, including 92 frontend/Finance
tests, 51 Finance/closure tests, OpenAPI/deployment/health contracts, the
eight-thread audit-chain test and repair idempotency.

The repaired current tree then ran 3,286 Django tests in 705.024 seconds with
0 failures, 0 errors and 2 skips. The final repeated matrix is recorded in
section AM. A passing test suite does not override the red data and
live-operations gates.

## D. Remediation ledger

The live issue record is
`docs/final-planning-monitoring-remediation-ledger-2026-07-29.md`. It records
the expected and reproduced behavior, root cause, affected roles and systems,
backend/frontend/data repair, verification level and closure evidence for
PMG-001 through PMG-013. PMG-013 remains at **System Health Red**.

## E. Architecture and source-of-truth map

| Domain handoff | Authoritative persistence | Canonical logic / boundary | Required invariant |
|---|---|---|---|
| School identity and classification | `schools.School` | School services + object scope | One live school identity; no unresolved references |
| Cluster membership | `School.cluster_id`; assignment table is a compatibility projection | Cluster services | One active canonical cluster pointer and matching projection |
| SSA and recommendation | SSA records plus persisted recommendation snapshots | SSA services; `PlanningRecommendationService` | Current-FY status and recommendation agree |
| Planning and scheduling | `activities.Activity` | Planning services delegate Activity creation/transitions | One Activity; entitlement and slot guards enforced |
| Costing | `CostCatalogue`/`CostSetting` → `ActivityScheduleCostLine` | Budget costing service | Persisted cost snapshot, period and total agree |
| My Plan | Scoped Activity query, not a second work ledger | My Plan services/shared active-status contract | Same status as PostgreSQL; terminal work excluded |
| Weekly funding | `WeeklyFundRequestLine` linked to the original schedule cost line | Weekly/fund-request services | One live claim per cost line; UGX totals trace to work |
| Monthly/quarterly/annual budget | Persisted roll-ups from schedule/fund-request lines | Monthly country-budget and reconciliation services | Aggregates reconcile to their source lines |
| Staff execution | Activity plus attendance/evidence | Activity transition service | Legal transition, scoped principal, atomic side effects |
| Partner execution | Activity plus Partner assignment/payment | Partner and Activity services | Assigned Partner is visible; responsible staff monitors |
| Evidence | `EvidenceRecord` plus protected storage object | Evidence service | Metadata and file both exist; quarantine/authorization enforced |
| IA and Salesforce | Activity, Salesforce reference, IA timeline/checklist | IA certification/return services | Unique valid ID; evidence and attendance gates precede certification |
| Advance/accountability/reimbursement | `AdvanceRequest` and its cost line | Advance/accountability services | State-guarded, locked, idempotent; no second reimbursement ledger |
| Partner payment | Canonical Partner payment record | `PartnerPaymentService` | IA-verified work paid once |
| Closure | Activity closure checklist/snapshot/analytics record | `ActivityClosureService` | Evidence, IA, Finance, NetSuite and analytics guards satisfied |
| Targets/performance | Target achievement derived from eligible Activity | Target services | Credit once and only after eligible completion |
| Audit | Append-only audit chain | Audit service under PostgreSQL advisory lock | Every concurrent event retained; hash chain continuous |

Views validate requests and render responses. They no longer own workflow state
assignments: all five hard-zero production-readiness scanners report 0,
including raw workflow mutation, mock runtime data, client-side business maths,
dead controls and unguarded page routes.

## F. Role and scope results

RBAC is centralized in `apps/core/rbac.py`; object and geography/team scope is
resolved in `apps/core/scoping.py`. Production configuration forces
`AUTHZ_MODE=enforce`, disables the Partner role bridge and disables development
seed/import/mock switches. Permission-route audit and the release scanner share
one implementation and both report 0 unguarded routes.

Role tests cover Admin’s read-only business boundary, CD/RVP country and region
scope, PL team scope, CCEO ownership, Partner assignment scope, IA verification,
Accountant Finance authority and HR/Admin account operations. The browser audit
used CCEO, Partner, Accountant and IA accounts. No unauthorized record leak was
observed or introduced. Live production identity-to-Partner links remain part
of the external data gate; the local health report finds 100 invisible Partner
work items.

## G. Planning entry-gate results

Planning readiness is derived by `PlanningReadinessService` from the School,
current-FY SSA state, classification and required assignment context. Tests
cover rejection of ineligible schools and role/object scope. UI and API
transitions reach canonical services.

Code contract: **pass**. Data gate: **fail** because 672 schools are unclustered,
138 districts lack primary/secondary classification and 12 client
school/FY/support-type entitlement slots have duplicate active Activities.

## H. SSA Recommendation results

Recommendation calculation and display use Planning recommendation services;
active Core plans persist a recommendation snapshot so the result does not
change silently beneath approved planning. The repair command found and
restored 103 missing snapshots plus 2 stale SSA readiness stamps. Repeat apply
and dry-run report 0.

Code and deterministic-history contract: **pass**. Production recommendation
reconciliation must still be rerun on the production backup and live candidate.

## I. Client School workflow

Client support scheduling flows through Planning into the canonical Activity
service and the one-per-school/FY/support-type entitlement guard. Concurrent and
duplicate-planning tests cover the first/second scheduling boundary.

Code contract: **pass**. Historical gate: **fail** because 12 duplicate active
entitlement slots need owner adjudication; deleting or cancelling one by guess
would change service delivery and funding.

## J. Core School workflow

Core Activity slots, persisted Core plan counters and recommendation snapshots
are the controlling records. Creation, reservation, activity creation and cost
snapshot are atomic. Repair dry-runs now report 0 stale counters and 0 missing
Core recommendation sets.

Code/deterministic-history contract: **pass**. End-to-end production sampling
remains required after the ambiguous blocker set is cleared.

## K. Cluster workflow

`School.cluster_id` is authoritative; the assignment relation is explicitly a
compatibility projection. Cluster planning delegates activity creation and
costing to shared services. The one deterministic legacy cluster-meeting key
was renamed only after catalogue/rate/amount equivalence was proven; repeat
repair reports 0.

Data gate: **fail** because 672 schools have no cluster and one cluster Activity
has no cluster link. Those assignments are business-owned.

## L. Special Project workflow

Project-school membership and Project activities use the shared Activity,
costing, My Plan, funding and closure paths rather than a separate execution
ledger. Scope and authenticated workflow tests pass.

Data gate: **fail** because 25 Project schools have no current-FY Project
Activity. The auditor cannot determine whether each is missing work, deferred
or intentionally excluded.

## M. Staff scheduling

Staff scheduling atomically creates/updates Activity and its cost snapshot,
checks leave and scheduling rules, and exposes the result through My Plan.
Rescheduling moves both work and money to the correct week and is rollback
tested.

Data gate: **fail** because 381 historical staff school visits are not linked to
a Daily Visit Batch and one below-target batch lacks its required reason.

## N. Partner assignment and scheduling

Assignment and scheduling use Partner and Activity services with object scope,
staff-monitor ownership and Partner visibility. Partner mobile surfaces were
audited at all eight widths.

Data gate: **fail**: 2 assigned items await Partner scheduling, 100 work items
are invisible to any Partner and 210 Partner Activities have no staff monitor.

## O. Cost Catalogue

CD-managed Cost Catalogue/Settings are the rate source. The costing service
persists schedule-time snapshots; funding and budget readers sum those lines
rather than recalculating mutable current rates. Cost-preview and write paths
share the resolver.

Health shows 0 period drift, 0 split-week cost lines and 0 double-funded budget
lines. Valid zero-cost historical Activities are no longer falsely treated as
missing lines. Code and current reconciliation: **pass**.

## P. Daily Visit Batch costing

Batch costing is part of the same Activity/cost-line model, with target/reason
rules represented in persisted batch data. No second calculation was added.

Code contract: **pass**. Historical gate: **fail** for the 381 unbatched visits
and one under-target batch without a reason.

## Q. Automatic budgeting

Activity scheduling writes `ActivityScheduleCostLine` records in the same
transaction. Failure-injection tests prove a costing crash leaves no orphan
Activity; cost snapshots become immutable once funding owns them. All current
deterministic repair/reconciliation counts are 0.

Result: **pass at code/reconciliation level**; production-data rerun required.

## R. Weekly Fund Requests

Weekly requests select persisted schedule cost lines, preserve source-line
identity and guard one live request claim per line. Approval/disbursement
services lock and state-check records. Tests cover approval routing, retry,
period movement and double-funding health.

Result: **pass at code level**; live financial sampling and UGX reconciliation
remain mandatory on the release environment.

## S. Monthly, Quarterly and Annual Budgets

Monthly country budgets and higher roll-ups derive from persisted lower-level
lines through country-budget and reconciliation services. Approval uses
canonical transitions. Static client-side totals are prohibited by the scanner,
which reports 0.

Result: **pass at code level**. Production-like staging reconciliation was not
available, so this hard external evidence remains open.

## T. Rescheduling and amendments

Reschedule locks the Activity, enforces legal timing/state rules and moves its
cost snapshot with it. Approved/funded changes use the amendment path rather
than rewriting the funded source. Failure-injection and “money moves with work”
regressions pass.

Result: **pass**.

## U. My Plan

My Plan is a scoped projection of canonical Activities, not another task table.
System Health now consumes the same terminal-status exclusion contract, removing
the false “missing from My Plan” classification for completed work.

Result: **pass at code/UI level**. Two Partner-assigned items correctly remain a
health blocker until they are scheduled into visible Partner work.

## V. Staff execution

Start, attendance, completion and review use Activity transition services with
state, permission and evidence guards. Direct state assignments in views were
eliminated and the scanner is held at 0 by a synthetic positive test.

Data gate: **fail** because 200 completed Activities lack accepted evidence.

## W. Partner execution

Partner work surfaces use the same Activity state and assignment records.
Partner Today, Schools, Activities and Evidence were usable without page
overflow at all audited widths; the mobile navigation traps focus, hides
background content, closes on Escape and returns focus.

Data gate: **fail** for the 100 invisible and 210 unmonitored historical Partner
items.

## X. Evidence and PDF preview

Evidence is represented by metadata plus an authorized storage object. Health
checks resolve every URI against the evidence store; malformed or absent files
block closure. Evidence validation, quarantine and preview/export tests are
present.

Data/storage gate: **fail** because one EvidenceRecord points to a missing file,
and no production object-storage probe was available.

## Y. Salesforce and IA

Salesforce identifiers are normalized, format-checked and uniquely reserved.
IA certification validates evidence, attendance, SSA requirements and duplicate
risk; return/certify actions use canonical services. Race errors now render
honest 404/409 responses instead of 500 or a fabricated method error.

Data gate: **fail** because 43 Activities show Accounts clearance before IA.

## Z. Accountability and NetSuite

Advance accountability uses the canonical `AdvanceRequest` state machine.
Submission, approval, return, reimbursement and receipt are locked and
state-guarded. NetSuite ID is a closure prerequisite.

Data gate: **fail** because one submitted/cleared accountability lacks a
NetSuite code and 78 closed Activities lack a NetSuite ID.

## AA. Returns and reimbursements

The legacy `ReimbursementClaim` create/pay methods now fail closed, its old
routes redirect to the canonical Disbursement Dashboard and the dead batch
reimbursement tab/export was removed. Local legacy-claim count is 0.
Overspend reimbursement remains inside `AdvanceRequest`, including receipt
confirmation; it cannot directly close an Activity.

Result: **pass at code and local-history level**.

## AB. Partner payments

Partner payment uses one canonical service, is limited to IA-verified work and
is state/idempotency guarded. Responsive Finance tables use one DOM control set
that becomes card-like below XL; action buttons remain on-screen.

Result: **pass at code/UI level**. Production duplicate-payment reconciliation
must be repeated against the release data.

## AC. Activity closure

`ActivityClosureService` is the only closure authority. Eligibility evaluates
evidence, review/IA, Finance clearance, NetSuite and required analytics
projection. The legacy reimbursement bypass was removed.

Data gate: **fail**: 78 closed Activities have no analytics publish record, 78
lack NetSuite ID, and other evidence/ordering blockers invalidate “all closed
Activities are compliant.”

## AD. Target and performance handoff

Target achievement is derived by target services from eligible Activity status
and evidence rules; reopen/correction behavior retains or removes credit through
explicit services. No frontend arithmetic is accepted by the hard-zero scanner.

Code contract: **pass**. Historical closure defects mean production performance
figures cannot yet be certified.

## AE. Monitoring and analytics

Role analytics services read canonical operational records and published
analytics projections. KPI/static-mock scanners and inventory tests guard
against hardcoded values. At 15,000 schools, observed local response times were:
dashboard 241 ms, My Plan 55 ms, School Directory 173 ms, To-Dos 105 ms,
notifications 16 ms, settings 12 ms, analytics 772 ms and System Health 9 ms.

Data gate: **fail** because 78 closed Activities are missing from the analytics
projection; leadership reporting is therefore not yet complete.

## AF. Notifications and To-Dos

Transition services own downstream notifications and action items; views no
longer write transition state directly. Scheduler-owned notification,
reconciliation, target sync and maintenance work is monitored by background
automation health.

Code registration/tests: **pass**. Live operations: **fail/unproven** because
the local web process correctly has background jobs disabled and no dedicated
production worker heartbeat was available.

## AG. Frontend-backend synchronization

HTMX responses are server-derived and API pages now share a valid, boundary-safe
contract. The school page’s duplicate input/drawer IDs were removed. Finance
responsive layouts reuse the same row and action controls, avoiding divergent
desktop/mobile state. All hard-zero frontend scanners are 0.

Result: **pass on audited surfaces**. There is no configured automated
Playwright/visual-regression suite; browser evidence is manual and targeted.

## AH. Performance and planning-time reduction

The system carries School, scope, SSA, recommendation, rate, fiscal period,
owner and roll-up context so planners enter only decision data. Planning
benchmark tests enforce the five intended human touchpoints and reject new
unsanctioned required fields. Server pagination and bounded-table inventory are
tested. The 15,000-school benchmark stayed below 600 ms for all sampled routes.

Result: **pass in the local benchmark**. A production-like load/stress
environment was unavailable; capacity approval remains an operational follow-up
but is not used to excuse the red hard gates.

## AI. Concurrency

Database uniqueness, `select_for_update`, legal-state checks and transactional
services protect scheduling, funding, disbursement, payment and closure.
Audit append now obtains a transaction-scoped PostgreSQL advisory lock before
reading the tail, including when the chain is empty. An eight-thread test
retains all eight distinct events with contiguous sequence and a valid chain.

Result: **pass for configured concurrency tests**.

## AJ. Failure and recovery

Failure-injection tests cover rollback of Activity/cost creation, rescheduling,
funding and downstream side effects. A backup/restore rehearsal produced a
3,013,999-byte PostgreSQL dump and restored 228 table row counts exactly, with
203 migrations, 250 validated foreign keys, the environment stamp, eight
authenticated route probes and audit-chain integrity preserved.

The production image was built from the final working tree. Docker's initial
signal-handling warning exposed a shell-form server command; the command now
uses JSON form and `exec`s Daphne after runtime `PORT` expansion, so rolling
deploy SIGTERM/SIGINT reaches the server process. The repeat image build is
warning-free. The local production-smoke instructions were also corrected to
include every fail-closed secret/bridge setting and the current pytest runner.

Backup artifact:
`.backup-rehearsal/edify_pm-20260729T144158Z.dump`.

Restore rehearsal: **pass**. Post-commit rollback rehearsal: **pass**. The
pre-audit release `00e4989a` served the schema left by `a3393e4e`; sequences
advanced, eight authenticated smoke routes returned HTTP 200 and the audit hash
chain remained intact. Live infrastructure recovery evidence remains a final
release prerequisite.

## AK. Historical data repairs

Before mutation, the local database was backed up to
`.backup-rehearsal/pre-final-planning-monitoring-repair-2026-07-29.dump`.
`repair_ecosystem_data --apply` repaired:

- 2 stale SSA readiness stamps;
- 103 active Core plans missing persisted recommendation sets;
- 1 legacy cluster-meeting cost key whose catalogue/rate/amount identity was
  deterministic.

The second apply and subsequent dry-run report 0 in every repair category.
Referential-integrity dry-run reports 0. The command now writes audit events for
applied historical transitions. The remaining 18 categories are deliberately
untouched because their correct outcome requires business context.

## AL. System Health

Code-level health:

- hard-zero production scanners: 0 / 0 / 0 / 0 / 0;
- unguarded routes: 0;
- audit chain: clean;
- cost-line period drift: 0;
- split-week cost lines: 0;
- double-funded budget lines: 0;
- deterministic and referential repair dry-runs: 0.

Release health: **red**. Workflow health lists 18 blocker categories. Background
automation warns that the local process has jobs disabled, as expected for the
web role. Admin Ops reports two critical incidents open and unacknowledged for
more than 60 minutes. A green production worker heartbeat was not supplied.

## AM. Tests

| Gate | Current evidence | Result |
|---|---|---|
| Django check | 0 issues | Pass |
| Migration drift / plan | No changes; no pending operations | Pass |
| Ruff lint / format | 0 findings; 1,026 files formatted | Pass |
| Pytest collection | 3,286 tests; one Django 6 deprecation warning | Pass |
| Fresh Django suite | 3,286 tests in 705.024s; 0 failures/errors; 2 skips | Pass |
| First `--keepdb` suite | 3,286 tests in 709.639s; 0 failures/errors; 2 skips; database preserved | Pass |
| Second `--keepdb` suite | 3,286 tests in 724.734s; 0 failures/errors; 2 skips; same databases reused and preserved | Pass |
| Instrumented full pytest | 3,284 passed, 2 skipped, 34 warnings and 2,342 subtests in 3,070.58s; 0 failures/errors | Pass |
| Coverage | 88% across 82,809 statements; 627 files at 100% | Pass |
| OpenAPI | `spectacular --validate --fail-on-warn`: 0 warnings | Pass |
| API/HTMX integration | Included in Django suite and targeted contracts | Pass subject to full-suite result |
| Browser responsive/accessibility | 21 representative pages, 4 roles, 8 widths; repaired findings retested | Pass on audited matrix |
| Automated Playwright/a11y/visual regression | No configured repository suites found | Not configured; not misreported as pass |
| npm audit | 0 vulnerabilities | Pass |
| pip-audit | No known vulnerabilities | Pass |
| Bandit | 0 medium/high findings; low findings retained for normal review | Pass release threshold |
| Tailwind production build | Completed | Pass |
| collectstatic | 337 files collected/unmodified on final run | Pass |
| Production `check --deploy` | 0 issues with valid ephemeral settings | Pass |
| Compose configuration | Valid; web and worker require encryption key | Pass |
| Container build | `edify-planning:audit-20260729` built from the final tree; 0 Docker warnings after exec-safe Daphne command repair | Pass |
| Backup/restore | Counts, FKs, routes, stamp and audit chain preserved | Pass |
| Release rollback rehearsal | `00e4989a` served `a3393e4e` schema; 8/8 routes, sequences and audit chain passed | Pass |
| System Health | 18 workflow categories + 2 unacknowledged critical incidents | **Fail** |
| Live scheduler/staging | No production worker/staging access | **Unproven / Fail hard gate** |

`mypy` is not configured or installed; no type-check result is invented.
Manual browser coverage does not replace a future committed automated
Playwright/accessibility/visual-regression suite.

The instrumented suite's 34 non-failing warnings are retained as explicit
engineering debt: one Django 6 `CheckConstraint.check` deprecation, four
memcached-key portability warnings from route-crawl fixtures, 28 naive-datetime
warnings from HR performance fixtures and one naive-datetime warning from the
load-scale fixture. None was suppressed to make this gate appear cleaner.

## AN. Deployment recommendation

**NO-GO. Do not deploy this candidate.**

Approval requires all of the following evidence on the exact release commit:

1. Every System Health workflow blocker is 0, or a documented exception is
   approved by the accountable business and risk owners without violating a
   hard invariant.
2. The two critical incidents are acknowledged, investigated and either
   resolved or attached to an approved incident-managed release decision.
3. A dedicated production-like worker runs with
   `ENABLE_BACKGROUND_JOBS=true`; the web process runs it as false; heartbeat
   and required job freshness are green.
4. Production-backup repair dry-runs, financial/target/analytics
   reconciliations and authenticated role smoke tests are attached.
5. The final repeated suites, coverage, container build, rollback rehearsal and
   CI checks are green on the exact commit.

Passing code gates is necessary but not sufficient when workflow truth,
financial ordering, evidence completeness and monitoring remain red.

## AO. Remaining issues

Material remaining issues are:

1. 672 schools without a cluster.
2. 2 Partner-assigned Activities awaiting schedule/visibility in My Plan.
3. 200 completed Activities without accepted evidence.
4. 43 Activities showing Accounts clearance before IA verification.
5. 78 closed Activities without NetSuite ID.
6. 78 closed Activities without analytics publication.
7. 1 EvidenceRecord whose file is missing.
8. 1 training without participant count.
9. 1 staff candidate awaiting Admin profile setup.
10. 100 Partner work items invisible because Partner assignment/user linkage is
    absent.
11. 210 Partner Activities without a responsible staff monitor.
12. 1 cluster Activity without a cluster.
13. 25 Project schools without current-FY Project activity.
14. 381 staff school visits without a Daily Visit Batch.
15. 1 below-target Daily Visit Batch without a recorded reason.
16. 138 districts without primary/secondary classification.
17. 1 submitted/cleared accountability without NetSuite code.
18. 12 duplicate active client entitlement slots.
19. 2 critical Admin Ops incidents unacknowledged for more than 60 minutes.
20. Dedicated production worker/scheduler heartbeat and production-like staging
    evidence unavailable.
21. Automated Playwright, accessibility and visual-regression suites are not
    configured; current evidence is a targeted manual browser matrix.

Therefore “remaining issues: none” would be false, and the absolute deployment
gate is not satisfied.
