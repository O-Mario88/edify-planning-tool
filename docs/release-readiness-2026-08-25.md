# Release Readiness Assessment — 2026-08-25

**Verdict: NO-GO for a 2026-08-26 production rollout.**

Baseline commit `e13dce8`. Audit run from a source-only container with PostgreSQL 16,
no Redis, no Docker daemon, and no access to the production environment.

This is not a judgement that the platform is poor. It is a well-engineered system with
unusually honest internal controls, and the audit found several defences better than most
production codebases carry.

**Eighteen findings were fixed in this audit**, including two P0s — a rescheduling path
that could CASCADE-delete a disbursed advance, and migrations that could run concurrently
with no lock. Every fix carries a regression test verified to fail before it and pass
after. §4 lists them.

What remains is no longer a list of defects nobody has looked at. The No-Go now rests on
three things a deadline cannot convert into evidence:

1. **Nine mandated gates cannot produce evidence from any source-only audit** — backup
   restoration, rollback rehearsal, deployment rehearsal and production smoke among them.
   No restore from a production backup has ever been performed. The mandate's own rule is
   that Not Tested is never Green.
2. **Two questions need the product owner, not an engineer.** Whether the Country
   Director's dashboard or the Programme Lead's is the truthful one (CONFLICT-001, where
   both fix directions break tests encoding the other behaviour), and whether Salesforce
   reconciliation stays a manually typed reference.
3. **Two capabilities the release scope names were never built**: offline field
   operation, and IA editing of Master Priority rows.

None of the three is closable by more code review. Each needs an environment, a decision,
or a work programme.

---

## 1. Gates executed in this audit

Everything in this table was run, not inferred.

| Gate | Command | Result |
| --- | --- | --- |
| Ruff lint | `ruff check .` | **PASS** |
| Ruff format | `ruff format --check .` | **PASS** (1,492 files) |
| Migration drift | `makemigrations --check --dry-run` | **PASS** — no changes detected |
| Production boot gate | `manage.py check --deploy` (prod settings) | **PASS — fails closed** |
| CSS bundle reproducibility | `npm run build:css` + `git diff --exit-code` | **PASS** — byte-for-byte |
| Design-system / mobile contracts | 101 contract tests | **PASS** |
| Full test suite | `manage.py test --parallel 4` | **PASS** — 5,900 tests, 0 failures, 0 skips |
| 50,000-school scale | `test_load_scale` @ 50k, quiet machine | **PASS** — 21 tests |
| Readiness honesty | live probe, Redis genuinely down | **FAIL** (RC-001) |
| E2E journey census | `test_release_journey_census` | **FAIL** — 1 of 22, 2 unbuildable |
| Container vulnerability scan | Trivy, in CI | **FAIL** — pre-existing; see below |
| Branch CI on the fixed tree | GitHub Actions, head `922e3a1` | **PASS** on every job this branch owns |
| Seed-command safety | code audit of the only hard-delete path | **PASS — three guards** |

CI on the branch head runs five jobs. Four pass — Django lint and test suite, CodeQL,
`Analyze python`, `Analyze javascript-typescript`. The fifth, Security Scans, fails at one
step, `Scan the image`, and that failure is not this branch's: the same workflow on `main`
at `e13dce8` — this PR's exact baseline — fails at the same step while its Django suite
passes. The findings are OS-package CVEs in the base image (`util-linux` and `mount`,
CVE-2026-53612 through -53615), none carrying a fixed version, and nothing in this
branch's diff touches the Dockerfile or dependency pins. It is a base-image refresh, not a
code fix, and it is counted as a blocker on the rollout rather than on this branch.

Suite size at HEAD: **425 test files; the runner collected and ran 5,900 tests.** The run
on the fixed tree is clean — `OK (skipped=0, expected failures=1)` in 1,006s. The single
expected failure is CONFLICT-001 below, quarantined deliberately and documented at the
test.

### Both skips were hiding something, and this report first said otherwise

An earlier draft of this section disposed of the run's two skips as "conditional on data
the dev database does not hold" — which is what the skip messages implied, and which was
not checked. Running the suite at `-v 2` to name them found that neither was benign, and
that the sentence dismissing them was exactly the false-green reasoning the mandate
forbids. Both are now closed and the suite skips nothing.

**`test_the_cost_does_not_grow_with_the_number_of_program_leads`** measured the growth,
saw it, and called `skipTest` on itself with the measurement in the message. A test that
detects a regression and then declines to fail reports green over an open defect for as
long as it exists. The defect was real: `_pl_cceos` was memoised per Programme Lead, so
each additional one cost three more queries on every Country Director surface that walks
the list. Measured on `/todos`: **82 queries at three Programme Leads and 112 at
eighteen**. Batching the resolution onto the scope object makes it **69 at both**. The
test now measures the request rather than calling the service directly — the distinction
mattered, because outside a request `apps.core.request_cache` is deliberately inert, so
the direct path pays a per-user re-read that no page load pays, and the test could not
tell that policy apart from a regression. Verified by reverting the fix: 82 → 112, failed;
restored, passes.

**`test_monthly_fund_plans_are_counted_not_just_weekly_advances`** asserted that the FY
money totals exceed the weekly-advance totals whenever a monthly plan exists. That was
true when the totals summed both snapshots, and D1 moved them to the `AdvanceRequest`
ledger precisely because that addition counted a cost line requested through both channels
twice. Under the ledger the assertion asks for the double-count back. It skipped whenever
the database held no monthly plan, which was always, so nothing ever caught it going
stale. Removed, with the rule it named left where it is genuinely exercised
(`test_audit_funding_channels.test_fy_totals_count_the_shared_cost_line_once`, which seeds
both channels).

### The scale gate needed two runs, and the first one would have been a false alarm

Run at `EDIFY_SCALE_SCHOOLS=50000 EDIFY_SCALE_GROWTH=10000`. Measured p95 at 50,000
schools on a quiet machine, every surface inside its objective:

```
/dashboard=508ms  /my-plan=95ms   /schools=451ms      /todos=227ms
/analytics=825ms  /settings=28ms  /notifications=44ms /system-health=12ms
```

Scale-invariance also held on every surface — query counts do not move as the estate
grows, which is the stronger claim than any single latency figure.

The first run of this gate **failed** its latency objective (`/dashboard` 900ms,
`/todos` 1408ms, `/analytics` 1631ms) because it executed while nine audit workstreams
were running tests concurrently: load average 8.90 on 4 CPUs. Reporting that as a
performance regression would have been wrong by a factor of up to six. It is recorded here
because the lesson generalises — `docs/audit-2026-08/02-scale.md` makes the same point
about its own figures, and a latency number is only evidence if you know what else the
machine was doing.

### The production boot gate is a strength worth naming

`config/settings/prod.py` refuses to start without `AUTHZ_MODE=enforce`, the five
`SPACES_*` values, `SUPER_ADMIN_PASSWORD` and a valid `FIELD_ENCRYPTION_KEY`. A
misconfigured production deploy fails loudly at boot instead of silently serving with
uploads going nowhere. Verified by running it.

### The seed command cannot destroy production

`_purge_operational()` runs `Activity.objects.all().delete()`, which would CASCADE
through evidence, verification records, Salesforce references and cost lines
(`apps/evidence/models.py:16`, `apps/activities/models.py:631,653`). It is reachable
only under `--demo`, behind three independent guards — including one that asks the
**database** for its own environment stamp and refuses if it says `production`,
"regardless of what this process believes it is"
(`apps/core/management/commands/seed.py:143-154`). That defends the case that actually
happens: a local shell whose `DATABASE_URL` points at the live database. This is
better than most systems manage.

---

## 2. What this environment could not verify

| Gate | Blocker |
| --- | --- |
| Backup restoration tested (§35) | No managed-Postgres access |
| Rollback rehearsal (§43) | No deploy target or prior image |
| Deployment rehearsal (§39) | No deploy target |
| Production smoke test, 27 steps (§42) | Proxy denies edifyplanning.app |
| Live integration failure/recovery (§30) | No Salesforce / NetSuite / MFI endpoints |
| Real-device mobile (§33) | Emulation only |
| Observed 15-minute field objective (§34) | Requires time studies with real users |
| Production monitoring + incident owner (§44) | Requires the live stack |
| Load/concurrency at production scale (§34) | No load generator against production |

Nine gates. Under §6.4 none may be marked Green, however good the code is. A real Go
decision requires a staging environment and the deployment path; it cannot be issued
from a source-only audit.

---

## 3. Prior audit evidence has expired

The repository contains a rigorous internal audit at `docs/audit-2026-08/`, dated
2026-08-16, which recorded honest gate statuses (1 of 16 journeys, offline not
assessed, backup restore not assessed, 50 of 68 metrics disagreeing).

Since that baseline: **52 commits, 647 files changed, 122,538 insertions, 19,532
deletions.** Route count has moved from the 952 that audit walked to **1,028** at HEAD
— 76 routes it never saw.

Its PASS verdicts — including "all 952 routes walked; no unguarded state-changing
endpoint" — describe a codebase that no longer exists. They cannot be carried into this
release candidate without re-verification, and re-verification of that scope did not
happen in this audit either.

---

## 4. Release-blocking findings

Full detail, including the workstream reports, follows in §6.

### Fixed in this audit

Eighteen findings were fixed here, each with a regression test verified to fail before
the fix and pass after. Where a test initially passed against the unfixed code it was
rewritten, not accepted.

| Sev | ID | Finding |
| --- | --- | --- |
| P0 | FIN-01 | The cost-snapshot lock had drifted two statuses behind `MONEY_MOVED_ADVANCE_STATUSES`, so rescheduling could CASCADE-delete a **disbursed** advance |
| P0 | DEP-02 | Migrations could run concurrently with no lock, making `instance_count: 1` load-bearing |
| P1 | SEC-01 | The school edit drawer gated its write on the READ helper, letting a Programme Lead take ownership of a supervised CCEO's school |
| P1 | INTG-05 | "Partner Payments Pending" counted `completed`/`closed` work carrying no IA verification as verified-and-payable |
| P1 | D2 | Approving leave granted the absent person's portfolio, supervisee scope and approval authority to a cover who had **declined** |
| P1 | FIN-03 | Two partner-payment paths had no `payment.act` gate and the service checked nothing at any layer |
| P1 | FIN-02 | `reimburse()` took any amount unvalidated; the settlement identity was checked only after payout, with no reversal |
| P1 | TGT-02 | Cancelling or deferring work left its verified achievement credit standing |
| P1 | TGT-01 | Ratio milestones were allocated without the denominator their arithmetic needs, and scored 0% for ever |
| P1 | TGT-03 | Annual "unique schools" figures summed per-month distinct counts, double-counting a school reached twice |
| P1 | D8 | The follow-up SSA that qualifies a champion candidate set a status that hid its plan from the scorer |
| P1 | INTG-02 | Nothing pushed when a scheduled job failed or stopped |
| P1 | INTG-03 | Six paths wrote notifications with no `source_event_type`, so they could never auto-close and were promoted to urgent |
| P1 | INTG-04 | 18 registered metrics named service callables that do not exist |
| P1 | INT-01/02, INTG-07 | No DB CHECK constraints on money outside one app; no uniqueness on the NetSuite id gating finance clearance |
| P2 | RC-001 | Readiness answered `{"status": "ok"}` with Redis genuinely down |
| P2 | SEC-02 | `can_update` claimed every write resolved through it; nothing called it, which is how SEC-01 survived a green suite |
| P2 | D3/D4 | API leave decisions notified nobody; accepting coverage claimed a notification it never sent |
| P2 | D6/D7 | Core slots completed through the real path carried neither evidence nor Salesforce id, so two blockers alarmed for ever |
| P2 | ISSUE-007 | Two tests skipped themselves rather than fail, so the suite reported green over an open N+1 and a stale assertion. See below |
| P3 | — | The partner role-bridge failed **open** when its flag was absent |

**The shape most of these share.** One definition, written out in several places, where a
copy drifted: the money-moved status set, the rate-measurement set, the school-write rule,
the metric service pointer, the notification writer. In each case the fix names the
definition once and makes the copies read it, and three guards were added so the drift
cannot recur — the cost-snapshot test parametrises over its constant, the metric registry
resolves every service path, and a scanner fails on a raw `Notification.objects.create`
outside the notifications app.

**The eighteenth has a different shape, and a worse one.** ISSUE-007 was not a drifted
copy but a test that measured a regression and then chose not to fail — and a second that
had quietly outlived the rule it asserted. Neither was hidden: both printed their reason
in the run. What hid them was that a skip reads as a pass in every summary line anyone
looks at, including the one in this report's first draft. A defect a test declines to
report is worse than one no test covers, because the second is visibly absent from the
coverage and the first is not. The suite now skips nothing, which makes any future skip
a signal rather than noise.

### Still open

Nothing below is now a defect nobody has looked at. Each is either infrastructure this
audit cannot reach, a build, or a decision that is not engineering's to take.

| Sev | ID | Finding | Why it is still open |
| --- | --- | --- | --- |
| P0 | DEP-03 | No restore from a production backup has ever been performed | Needs the managed database. The rehearsal harness exists and is rigorous |
| P0 | DEP-01 | The repository's two records of the live app contradict each other | Needs `doctl apps spec get` against the live app |
| P0 | INTG-01 | No Salesforce, NetSuite or MFI transport exists | Needs credentials, or a scope decision that reconciliation stays manual |
| P1 | CONFLICT-001 | CD dashboard reports 200% where the PL correctly reports 0% | **Product decision.** Both fix directions break tests encoding the other behaviour |
| P1 | FE-01 | Offline field operation does not exist | A build: IndexedDB queue, replay, server-side idempotency keys |
| P1 | RC-003 | 1 of 22 mandated end-to-end journeys has a real test | 21 journey tests is a work programme, not a fix. The 22 are now enumerated and the count machine-checked — see below |
| P1 | DEP-05/06/07 | No log retention, no error tracker, two alert rules, no named incident owner | Configuration and an org decision. The scheduler half is now fixed |
| P1 | D5 | `CorePlan.assessment_completed` is unreachable by any route | Needs a catalogue item and a scheduling route — a workflow, not a patch |
| P2 | GAP-02 | IA cannot edit Master Priority rows | An approved extension that was never built |
| P2 | FE-02 | KPI headline limit enforced at 6, not the stated 4 | Needs the owner to say which number is the rule |
| P2 | D6 (closure) | "Package Complete" is a status nothing writes | Inventing the closure workflow is a product decision |
| P3 | RC-002 | `AUTHZ_MODE` is vestigial but named in the posture dashboard | Cosmetic; object-level authz is enforced unconditionally |

### The journey census is now a test, not a sentence

"1 of 22" was a claim with the twenty-two enumerated nowhere and the number checkable by
nobody — the same shape as a skipped test reporting green. The mandate's twenty-two
journeys and their steps now live in `apps/core/tests/release_journeys.py`, each either
pointing at the single test that walks it end to end or saying plainly that nothing does,
and `test_release_journey_census` holds that manifest to reality: a pointer at a test that
does not exist fails by name, and the covered count is pinned so coverage cannot be
claimed or lost without a deliberate edit that the assessment must be updated alongside.
Verified against both drift modes by introducing each and watching it fail.

The census also caught its first error immediately. The one real journey test documented
itself as "Journey 1" while walking Journey 3 — Plan, Cost, Schedule, Fund request,
Approval, Disbursement, Start, Evidence, PL review, IA verification, Accountability,
Closure. Journey 1 is Priority to verified performance, an entirely different spine. A
census built from docstrings would have recorded the wrong journey as covered.

Two of the twenty-two cannot be covered by any test at present, and the manifest says so
rather than counting them as merely unwritten:

- **Journey 20, Offline field activity** — FE-01. There is no IndexedDB queue, no replay
  and no server-side idempotency key, so there is no behaviour to walk.
- **Journey 21, Integration outage** — INTG-01. There is no outward transport, so
  "external system fails" and "retry succeeds" have nothing to exercise.

That leaves **19 journeys that are unwritten rather than unbuildable**, which is a work
programme with a known shape rather than an open question.

## 5. Path to a defensible Go

1. **Product-owner decision on CONFLICT-001.** It is a conflict, not a bug — both fix
   directions break tests encoding the opposite behaviour. Engineering cannot resolve it.
2. **Fix and regression-test the three achievement P1s** (TGT-01/02/03).
3. **Amend the release scope or build the offline client.** The honest options are to
   ship as "installable, online-only PWA" or to build the IndexedDB queue, replay and
   server-side idempotency keys. It is a build, not a patch.
4. **Stand up a production-equivalent staging environment** and run the nine gates
   above, including a real restore and a real rollback rehearsal.
5. **Walk the mandated journeys end to end** — or accept, in writing, which of them ship
   unproven.
6. **Re-run the full pipeline on the release candidate**, including the container scan
   currently failing on `main`.

---

## 6. Workstream findings

### 6.1 Deployment and operations

The single most important finding of the whole audit is that **the repository does not
know what is deployed.**

- **DEP-01 · P0 ·** `.do/app.yaml` carries a "DO NOT APPLY THIS FILE TO THE RUNNING APP"
  banner, and `.do/README.md:17` states the spec "had never been applied since the app was
  created". Worse, the repository's two records of the live application contradict each
  other: `.do/README.md:45-57` describes app `edify-planning-app` with **1** web instance,
  a **dev-tier** database and no Redis; `docs/live-production-audit-2026-08-09.md:3-33`
  describes a *different* app, `edify-planning-fra`, with **2** web instances, managed
  PostgreSQL 17 + Valkey, and a dedicated pre-deploy migration job. Both cannot be true,
  and nothing in a source-only audit can settle it.
- **DEP-02 · P0 ·** `.do/README.md:87-89` records `RUN_MIGRATIONS=true` on the *web*
  service — migrations run on container boot, making `instance_count: 1` load-bearing.
  There is no advisory lock around migrate (grep for `pg_advisory_lock` finds only two
  unrelated call sites). If the two-instance record is the accurate one, production has
  been running the exact configuration `DEPLOY.md` calls unsafe.
- **DEP-03 · P0 ·** `scripts/backup_restore_rehearsal.sh` is a genuinely rigorous
  round-trip (row-count parity, `django_migrations` parity, unvalidated-FK assertion, app
  smoke). But it defaults to the local database, no CI job invokes it, and every recorded
  run was against the local estate. No backup schedule, retention or PITR setting exists in
  any spec; the database is declared `production: false`; `DEPLOY.md:241` still lists
  "configure an independent backup/export process" as a to-do. **No restore from a
  production backup has ever been performed.**
- **DEP-05/06/07 · P1 ·** Nothing pushes an alert when the scheduler stops
  (`scheduler_health_check` exists and is invoked by no cron, workflow or monitor);
  observability is console logging with **no retention**, no error tracker, and two alert
  rules (`DEPLOYMENT_FAILED`, `DOMAIN_FAILED`); and no document maps the runbooks' roles
  ("Platform owner" ×7) to a named person or contact.
- **DEP-08 · P2 ·** `apps/audit/migrations/0006` widens `subject_id` from `varchar(30)` to
  `varchar(128)` precisely because longer values were being dropped. Reversing it issues
  `ALTER COLUMN TYPE varchar(30)`, which PostgreSQL **errors** on rather than truncating —
  so database rollback past this migration is unavailable for this release.

Credit where due: the runbooks are good operational writing, `scripts/rollback_rehearsal.sh`
asks exactly the right question ("does the previous release run against the current
schema?"), and runbook 7 answers the database-rollback question correctly. The gap is that
none of it has been rehearsed against production or staging for this commit.

### 6.2 External integrations — the largest scope gap

- **INTG-01 · P0 ·** There is **no HTTP transport for Salesforce, NetSuite or the Lending
  Partner feed anywhere in the codebase.** `apps/integrations/services.py:48-60`
  (`push_to_external`) is a single unconditional `raise IntegrationNotConfigured`, and so
  is `validate_external_reference` at `:63-71`. An outbound-HTTP sweep across `apps/` and
  `config/` finds only the SMS and email clients (independently verified).

  **This is a scope disagreement, not a hidden bug, and the distinction matters.** The
  seam is deliberate and documented — "Implementing this against the live APIs is the
  credentialed half of Phase 2c … Until then it refuses loudly rather than pretending."
  The platform is behaving exactly as its authors intended. The release blocker is that
  the mandate makes Salesforce confirmation a *gating* step in several core journeys
  (activity closure, partner-payment eligibility, loan confirmation), and what the
  platform actually gates on is a human-typed string. Either the roadmap item lands or the
  release scope says plainly that Salesforce reconciliation is manual and unverified.

  **What "Confirm Salesforce" does today: a human types a string, it is matched against a
  regex prefix (`TS-`/`SVE-`, or `Loan-<number>`), checked for local uniqueness, and
  stored. Nothing contacts Salesforce.** That locally-typed string is the gate on activity
  closure, IA partner confirmation, core-activity verification and partner-payment
  eligibility.

  The outbox around it is real and well-built — `SELECT … FOR UPDATE SKIP LOCKED` claims,
  crash reclaim counted as an attempt, deterministic backoff, dead-letter with Admin
  notification and a replay command. It simply has nothing to deliver to.
- **INTG-05 · P1 ·** Metric definitions still disagree materially with what the services
  compute. The most serious: **"Partner Payments Pending" folds on
  `("ia_verified","accountant_confirmed","completed","closed")`
  (`apps/planning/partner_oversight_service.py:47,753`) — `completed` and `closed` carry no
  IA verification.** The correct field is computed at `:552` and never read. Unverified
  partner work is presented to finance as verified-and-payable, against a spec that says
  "work Impact Assessment has verified".
- **INTG-04 · P1 ·** 18 registered metrics name a service callable that does not exist
  (3 dead dotted paths). The registry's own `check()` never resolves the path, so its 55
  tests pass while pointing at nothing.
- **INTG-03 · P1 ·** Notification centralisation is not true: six live paths insert
  `Notification` rows directly without a `source_event_type`, and `resolve_condition`
  filters on that field — so those notices **can never auto-close**, persist as permanent
  "Action Required", and are then promoted to urgent by the escalation job.
- **INTG-07 · P2 ·** `AdvanceRequest.accountability_netsuite_id` has no uniqueness
  constraint and no duplicate check; two advances can carry the same NetSuite expense ID.
  `finance_services.py:219-220` declares the rule and does not implement it.

Against that, database-level idempotency is genuinely strong: unique constraints exist on
outbox idempotency keys, activity Salesforce IDs (partial index), MFI loan references,
repayment transactions, partner payments and milestone credits. A replayed webhook cannot
create a duplicate credit, loan or payment.

### 6.3 Achievement and targets

The engine's architecture is sound: planned/phased/planned-output/verified are four
genuinely distinct concepts, credit creation is idempotent behind a
`(rule, activity)` unique constraint, partner work is correctly excluded from staff
achievement (with a non-tautological test), the five performance bands are correct at all
seven boundaries, and the zero-balance rule is enforced server-side in three places
including per-component reconciliation. `refresh_period_targets` is the only writer of
`actual_value` platform-wide; no manual override exists.

Three P1 defects sit inside that sound architecture:

- **TGT-02 · P1 ·** `_cancel_or_defer` (`apps/activities/services.py:~3940`) sets the new
  status and syncs money but never calls `reverse_activity_progress` — unlike the three
  other paths that do (`ia_return`, `ia_services`, `closure_services`). **Cancelling a
  verified activity leaves its achievement credit standing.** No test covered it. A fix is
  in progress in this audit.
- **TGT-01 · P1 ·** `ratio` is a user-selectable measurement type, but only `percentage`
  populates the numeric denominator, and no template anywhere offers a denominator input.
  Rate milestones allocated through the Strategic Priorities page therefore score **0%
  forever** — the guard that produces the repeated `has no denominator` log line is correct
  and deliberate; the defect is upstream, that nothing supplies what it needs.
- **TGT-03 · P1 ·** Annual and quarterly figures for unique-school milestones are summed
  from per-period distinct counts, so **a school reached in two months counts twice** in a
  figure whose name says "unique". Fourteen seeded milestones use these bases.

### 6.4 Frontend, mobile and offline

The design-system layer is strong: the CSS bundle reproduces byte-for-byte from source,
101 contract tests pass, the login page is overflow-free from 320px to 1280px, the token
layer is real and tested, only two raw hex values exist in all templates (both in contexts
where CSS custom properties genuinely do not work), and hover-revealed actions all carry
`focus-visible` fallbacks.

- **FE-01 · P1 ·** **Offline field operation does not exist.** The service worker caches
  only same-origin GETs under `/static/` and deliberately excludes anything
  session-bearing. Offline mutations are not queued — they are *cancelled*:
  `static/js/platform-status.js:82-87` calls `preventDefault()` and announces "This action
  was not sent because you are offline." There is no IndexedDB and no background sync
  anywhere in first-party JavaScript (independently verified). The only offline persistence
  is a `localStorage` draft of seven text fields on one page — no files, no photos. Of the
  four required capabilities (start activity, capture evidence, survive app close, sync
  without duplicates), three are absent and the fourth is partial and text-only.
- **FE-02 · P2 ·** The stated KPI rules are "operational 0–2, dashboard max 4, mobile max
  2". Mobile max 2 is correctly enforced. The dashboard limit is enforced **at 6**, not 4.
  The operational limit is not enforced at all — the inventory deliberately asserts there
  is no per-category limit. `docs/platform-kpi-inventory.json` reports 14 payload groups
  feeding more than six metrics into a six-slot tray that truncates, so metrics are being
  dropped with no UI affordance.

### 6.5 Approved product extensions

Nothing on the approved-extensions list is fully absent — a genuinely strong result across
16 items covering Business Transformation, loans and lending partners, the full HR suite,
Special Projects, SSA impact measurement and the partner workflow. Three are partial:

- **GAP-02 ·** IA **cannot** edit Master Priority rows. `_assert_master_author` requires
  Country Director, IA's RBAC block has no `STRATEGIC_PRIORITIES_EDIT` or
  `MILESTONES_DEFINE`, and a passing test pins the exclusion. There is no row-level
  create/edit/delete for priorities or milestones in any UI; the master arrives by import
  or seeding, and after publication cannot be amended at all. This sits at the head of the
  chain the release is meant to prove.
- **GAP-15 ·** Offline — see FE-01.
- **GAP-10 ·** "Send School to" builds the non-ownership ask correctly (notification,
  To-Do, audit, idempotent, auto-resolving) but the recipient is never chosen — it resolves
  to the school's existing assignee — and no temporary access grant exists outside a Leave
  record.

### 6.6 Security and access control

Object-level authorization **is** enforced, unconditionally, by purpose-built helpers at
35 call sites — and this was verified empirically, not assumed: the object-level denial
suite (27 tests, 79 subtests) passes while `AUTHZ_MODE` is `shadow`, proving enforcement
is not flag-dependent. Separation of duties holds: Admin is withheld `ia.verify`,
`payment.act` and `budget.approve` by the permission matrix, and two tests POST to the
real endpoints and assert the state did not move. Cross-tenant isolation holds for
partners and lending partners. `bandit` reports no issues across 329,364 lines;
`pip-audit --strict` reports no known vulnerabilities. Production hardening is thorough:
HSTS with preload, secure cookies, `X-Frame-Options: DENY`, a CSP, a 30-minute idle
timeout, weak-secret rejection at boot, and login throttling on both the DRF and HTML
doors. No key material is tracked in the repository.

Against that, one live privilege escalation was found and fixed (SEC-01 above), and one
structural reason it survived:

- **SEC-02 · P2 ·** `RolePermissionService.can_update` and `can_delete` — the functions the
  oversight regression contract tests — have **zero production callers**. The contract
  guards a function nothing calls, and its own docstring claims "the API, the HTMX
  endpoints and the bulk actions all resolve through this one function". They do not.
  That misleading contract is why a green suite coexisted with an open write path.
- **SEC-03 · P2 ·** Field-level encryption at rest is not implemented:
  `ENCRYPTED_FIELDS = ()`. NetSuite identifiers and partner payment metadata are
  plaintext. The posture dashboard is honest about it — it reports `encryptedFieldCount: 0`
  and the flag was deliberately renamed so it could not be misread — so this is a risk to
  accept with a named owner, not an unnoticed hole.
- **SEC-05 · P3 ·** The route/permission scanner covers 536 of 1,028 resolver entries (DRF
  is excluded by design and does carry `permission_classes`), and dedupes by bare function
  name, so a name collision across modules is skipped unchecked. Two collisions exist; all
  four views were verified guarded.

### 6.7 Data integrity

No P0. Every self-audit scanner passes — 190 tests, 1,592 subtests — and the checked-in
inventories were verified **not stale** (regenerated byte-identical to HEAD). No dead
surfaces, no inert controls, no unguarded page routes, no mock data reaching production,
and exactly one client-side business calculation, which is a documented waiver with a
ratchet test and an independent server-side recomputation.

Three of the five invariants the mandate names are protected at the database level —
duplicate Salesforce ID, duplicate MFI loan reference, and one credit per source, all
verified as live indexes in Postgres. Two are not:

- **INT-01 · P1 ·** `fund_requests`, `budget`, `targets` and `partners` declare **zero**
  CheckConstraints. Every amount is a bare `BigIntegerField`, so Postgres accepts a
  negative disbursement. `business_transformation` shows the pattern done properly with 35
  such constraints.
- **INT-02 · P1 ·** `TemporaryCoverageAssignment` and `PartnerAssignment` have no
  constraints at all. "One active assignment" rests entirely on a row lock in one code
  path; any other writer can create a second live assignment. The coverage model's own
  docstring notes that nothing ever writes `expired`, so every assignment reads `active`
  forever.
- **INT-03 · P2 ·** The referential-integrity gate reports clean — against a database with
  zero schools. `docs/verification-ledger-2026-07-21.md` still lists 3,220 orphan school
  references as OPEN, and no repair migration exists. Run the scanner against a production
  restore before the gate is claimed.
- **INT-04 · P2 ·** 45 routed surfaces have no automated test, 29 of them mutating
  `action` routes — including `/ia/verification/<id>/verify` and `/ia/verification/<id>/return`.

### 6.8 Previously documented defects — re-verified at HEAD

The internal audit of 2026-08-16 recorded eight defects. Re-checked against current code
with runtime reproductions: **one is fixed, seven are still present.**

`D1` (an escalated leave request could never be approved) was properly fixed, with a
regression test that passes. Still present: `D2` (P1, the declined-cover access grant),
`D5` (P1, the unreachable core assessment slot), `D8` (P1, impact measurement removing a
school from the champion engine), `D6` and `D7` (P2, package closure and the permanent
health-ratchet false positives), `D3` (P2, silent API leave decisions) and `D4` (P3, a
message claiming a notification that is never sent).

`D2` deserves emphasis. Declining coverage sets `coverage_status = "Declined"` but leaves
`covering_staff` populated; approval then branches on `covering_staff` alone, overwrites
the status back to `"Approved"`, and creates a live `TemporaryCoverageAssignment`. The
decliner receives the absent person's school portfolio, supervisee scope, **approval
authority**, and auto-attribution of their audit actions — while believing they are not
covering, and with the record no longer showing the refusal. One guard in `approve_request`
closes it.

## 7. What was fixed in this audit

Each carries a regression test verified to fail before the fix and pass after.

| Commit | Fix |
| --- | --- |
| `804bd5b` | The partner role-bridge fails closed when its flag is absent |
| `56fa8c6` | The school edit drawer asks the ownership question before it writes |
| `8f8c5b3` | Cancelling or deferring work withdraws its milestone credit |
| `00cdfd8` | The cost-snapshot lock reads the canonical money-moved set, and its test parametrises over that constant so the drift cannot recur |
| `31601f5` | Migrations serialise on an advisory lock instead of on `instance_count: 1` |
| `b2dd49d` | Leave cannot be approved onto a cover who declined it |
| `85b37d6` | Only IA-verified work counts as partner payment pending |
| `202aa78` | Readiness names the degraded dependency it was calling healthy |
| `5d599e3` | An unpayable reimbursement is refused, not discovered after payout |
| `4bdc817` | Partner money movement asks the permission matrix, not a role tuple |
| `6cb508a` | The scheduler pushes what it already knew about its own failures |
| `3e2a096` | The oversight contract answers with the rule writes actually enforce |
| `d996b62` | The metric registry follows the pointer it exists to enforce |
| `697b58f` | A school counts once a year where the basis says unique, not once a month |
| `50493d6` | A rate milestone gets the denominator its own arithmetic requires |
| `e66b3ce` | A leave decision is announced from the transition, not from one of its doors |
| `9964cb8` | A core plan is read by its lifecycle, not by one status in it |
| `d35c85e` | The database refuses the money and assignment states nothing else did |
| `bd33fac` | One notification writer is true, and a scanner guards against the seventh |
| `592ad83` | Every Programme Lead's CCEOs resolve in one read, and the two tests that skipped rather than fail now assert |

Supporting commits: `3859103`, `398bd6e` (KPI inventory regeneration), `47b908e` (a test
respelled for a case the new constraint makes impossible), `44f418d` (stale at-risk
notices resolved in one query), and `4aef402`, `120a66a`, `6750c71`, `036982e` (this
report).

A note on method, because it changed an outcome: the first draft of the FIN-01 test
asserted a bare `BadRequest` and **passed against the unfixed code** — `reschedule`
refuses on the scheduling policy long before it reaches the lock. It was only by running
the test against the reverted guard that the tautology showed up. Every regression test
here was checked that way — including the last one, where reverting the batch took the
measurement from 69 back to 112 and the test failed as it should.
## 7a. Deliverable coverage — what this audit did not produce

The mandate asks for twelve deliverables. Nine are in this document: the executive
assessment, defect register, journey report, financial reconciliation, target and
performance reconciliation, data-integrity report, security report, frontend and
responsive report, and the deployment and rollback report. The scale report is here with
its result recorded as not established rather than passed.

Two are **not** built, and saying so is part of the assessment:

- **The complete requirements traceability matrix (§11, §45.2).** Every approved
  requirement mapped to its role, page, API, service, model, permission, notification,
  metric, test and evidence. This audit prioritised the highest-risk domains and the
  platform's own invariants instead. The internal audit of 2026-08-16 also recorded this
  gate as NOT DONE, so it has now been deferred twice.
- **The exhaustive permission and scope matrix (§45.5)** covering every role against every
  page, action and record scope. What exists is the route/permission scanner (536 of 1,028
  resolver entries; DRF excluded by design) plus targeted denial suites. That found a live
  privilege escalation, which is evidence the coverage is worth completing rather than
  evidence it is sufficient.

Neither omission changes the verdict — the release is already blocked on evidence that
cannot be produced here — but both would have to exist before a Go could be called
complete on the mandate's own terms.

## 8. Release Requirements Conflict Register

## CONFLICT-001 · Leadership and the Programme Lead read different achievement percentages for the same team

| Field | Value |
| --- | --- |
| Conflict ID | CONFLICT-001 |
| Requirement source A | `CDAnalyticsService._weighted_achievement()` — weights against `active_target_areas()`, the whole `TargetArea` catalogue (`cd_analytics_service.py`, `areas = areas or active_target_areas()`) |
| Requirement source B | `PLTeamTargetsService.get_page()` — derives areas per user from the agreed annual performance review, and renders "No measurable team priorities agreed" when there are none |
| Current system behaviour | For a team with **no signed agreements**, the Country Director's dashboard pools 2 achieved over 1 target and reports **200%**, while that team's Programme Lead correctly sees "Not Assigned" and **0%** |
| Affected roles | Country Director, Regional Vice President (consumers of the inflated figure); Programme Lead, CCEO (the work being miscounted) |
| Affected workflow | Achievement → Performance → Leadership Decisions |
| Financial/data risk | Leadership reads a fabricated achievement figure. The mandate forbids exactly this: "No number may be fabricated", "Pages to calculate different values", "Leadership receives truthful, actionable intelligence" |
| Product-owner decision | **REQUIRED — NOT YET MADE** |
| Resolution | Blocked on the decision below |
| Test proving the resolution | `apps/analytics/test_target_formula_unification.py:214` `test_cd_pl_target_percentage_matches_pl_team_targets` — currently marked `@unittest.expectedFailure` |

### Why this is a conflict and not a bug to patch

The codebase states plainly that both fix directions were attempted and reverted,
because each breaks tests that deliberately encode the opposite behaviour:

- **PL falls back to the catalogue** → breaks 3 tests, including
  `test_global_target_catalogue_does_not_invent_team_priority_rows`, which pins the
  honest empty state and the no-fabricated-data rule.
- **CD adopts priority areas** → breaks 6 tests, including the four
  `test_target_percentage_consistent_q*` cases, whose fixtures assume catalogue-based
  CD maths.

The test's own docstring draws the conclusion: *"Choosing between them changes what
leadership reads off a dashboard, so it is a product decision rather than a patch."*

### Assessment

The engineering handling of this is exemplary — the defect is reproduced by a real
test, quarantined rather than deleted, documented with both attempted fixes, and the
marker is self-removing (unittest fails the run on an unexpected success, so whoever
fixes it is told to remove the marker).

But quarantine is not resolution. **This is an open P1 defect that the release cannot
carry**, because the surface it corrupts is the one the mandate names as the platform's
purpose: leadership receiving truthful intelligence. It requires the product owner to
decide which denominator is authoritative, before the release, not after.

**Recommended decision** (for the owner, not for engineering to take): source B is the
honest one. A target nobody assigned should not have work counted against it; the PL's
"Not Assigned" is the truthful state. That implies CD analytics should adopt the agreed
priority areas and the six catalogue-based CD fixtures should be re-based — a change
with a known, bounded test cost.
