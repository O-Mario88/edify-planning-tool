# Release Readiness Assessment — 2026-08-25

**Verdict: NO-GO for a 2026-08-26 production rollout.**

Baseline commit `e13dce8`. Audit run from a source-only container with PostgreSQL 16,
no Redis, no Docker daemon, and no access to the production environment.

This is not a judgement that the platform is poor. It is a well-engineered system with
unusually honest internal controls, and the audit found several defences better than
most production codebases carry. The No-Go rests on three things that a deadline cannot
convert into evidence:

1. **Nine mandated gates cannot produce evidence from any source-only audit** — backup
   restoration, rollback rehearsal, deployment rehearsal and production smoke among
   them. The mandate's own rule is that Not Tested is never Green.
2. **Confirmed defects that the mandate lists as stop-the-line**, including false
   achievement credit on cancelled work and a leadership dashboard reporting a
   fabricated percentage.
3. **A capability the release scope requires does not exist**: offline field operation.

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
| Readiness honesty | live probe, Redis genuinely down | **FAIL** (RC-001) |
| E2E journey census | repository census at HEAD | **FAIL** — 1 of 22 |
| 50,000-school scale | `test_load_scale` @ 50k | **NOT ESTABLISHED** — see below |
| Seed-command safety | code audit of the only hard-delete path | **PASS — three guards** |

Suite size at HEAD: **425 test files; the runner collected and ran 5,721 tests.**

### The scale gate result must be read carefully

Run at `EDIFY_SCALE_SCHOOLS=50000 EDIFY_SCALE_GROWTH=10000`: **21 tests, 1 failure.**

The structural property held — scale-invariance passed on every surface, meaning query
counts do not move as the estate grows, which is the stronger claim. The failure was the
latency objective:

```
/dashboard p95=900ms  > 800ms
/todos     p95=1408ms > 800ms
/analytics p95=1631ms > 1500ms
```

**This is not evidence of a performance regression.** The run took place with nine audit
workstreams running tests concurrently: load average 8.90 on 4 CPUs, roughly 2.2×
oversubscription. `docs/audit-2026-08/02-scale.md` says the right thing about its own
numbers — "laptop wall time under `manage.py test` is not production wall time" — and the
same caveat applies with more force here.

The honest status is **NOT ESTABLISHED**: it must be re-run on a quiet machine before the
release. It may well pass. It cannot be claimed as passing on this evidence.

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

**Fixed and committed during this audit** (each with a regression test proven to fail
before the fix and pass after):

| ID | Sev | Finding | Commit |
| --- | --- | --- | --- |
| SEC-01 | P1 | A Programme Lead could seize ownership of a supervised CCEO's school through the edit drawer, moving its planning, target and budget scope onto themselves | `56fa8c6` |
| FIN-01 | P0 | The cost-snapshot lock had drifted two statuses behind the canonical money-moved set, so rescheduling could CASCADE-delete a disbursed advance | `00cdfd8` |
| TGT-02 | P1 | Cancelled or deferred work kept its verified achievement credit | `8f8c5b3` |
| — | P3 | The partner role-bridge failed **open** when its flag was missing | `804bd5b` |

**Open and release-blocking:**

| ID | Sev | Finding |
| --- | --- | --- |
| INTG-01 | P0 | No Salesforce, NetSuite or MFI transport exists. "Confirm Salesforce" validates a regex and local uniqueness — nothing contacts Salesforce |
| DEP-01 | P0 | The repository's two records of the live application contradict each other; the committed spec was never applied |
| DEP-03 | P0 | No restore from a production backup has ever been performed; no backup schedule or PITR is configured anywhere |
| DEP-02 | P0 | Migrations may run on web-container boot with no advisory lock, making `instance_count: 1` load-bearing |
| INTG-05 | P1 | "Partner Payments Pending" counts `completed`/`closed` work that carries **no IA verification** as verified-and-payable |
| D2 | P1 | Approving leave grants the absent person's portfolio, supervisee scope and approval authority to a cover who **explicitly declined**, silently rewriting `Declined` to `Approved` |
| CONFLICT-001 | P1 | CD dashboard reports 200% where the PL correctly reports 0% — a product decision, not a patch |
| FE-01 | P1 | Offline field operation does not exist |
| TGT-01 | P1 | Rate/ratio milestones can be allocated with no denominator, scoring 0% forever |
| TGT-03 | P1 | Unique-school milestones double-count a school reached in two months |
| FIN-02 | P1 | `reimburse()` accepts any integer — no bounds, no sign check — and the invariant is verified only *after* payout, with no reversal path |
| FIN-03 | P1 | Admin and Country Director can move partner money despite not holding `payment.act`; the service performs no role check at any layer |
| D8 | P1 | Measuring impact removes a school from the champion engine — the act that qualifies a school disqualifies it |
| D5 | P1 | `CorePlan.assessment_completed` cannot become non-zero by any reachable route, so `core_assessment_missing` is permanently critical for every core school |
| INTG-02 | P1 | Nothing alerts when a scheduled job stops; detection requires a human to open a page |
| INTG-03 | P1 | Six live paths insert notifications without a `source_event_type`, so those notices can never auto-close and escalate to urgent |
| INTG-04 | P1 | 18 registered metrics name a service callable that does not exist |
| RC-003 | P1 | 1 of 22 mandated end-to-end journeys has a real test |
| DEP-05/06/07 | P1 | No log retention, no error tracker, two alert rules, no named incident owner |
| INT-01 | P1 | Zero DB CHECK constraints on money columns outside `business_transformation` |
| INT-02 | P1 | "One active assignment" is app-level only; no DB constraint |
| RC-001 | P2 | Readiness reports healthy while Redis is down |
| GAP-02 | P2 | IA cannot edit Master Priority rows (approved extension unmet) |
| FE-02 | P2 | KPI headline limit enforced at 6, not the stated 4; 14 surfaces over-feed a truncating tray |
| D3/D6/D7 | P2 | API leave decisions notify nobody; package closure is a status nothing writes; correctly-completed core slots trip two health ratchets forever |
| RC-002 | P3 | `AUTHZ_MODE` is vestigial but named in the security posture dashboard |

---

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

Four commits, each with a regression test verified to fail before and pass after:

- `804bd5b` — the partner role-bridge now fails closed when its flag is absent.
- `56fa8c6` — the school edit drawer asks the ownership question before it writes.
- `8f8c5b3` — cancelling or deferring work withdraws its milestone credit.
- `00cdfd8` — the cost-snapshot lock reads the canonical money-moved set, and its test
  parametrises over that constant so the drift cannot recur.

A note on method, because it changed an outcome: the first draft of the FIN-01 test
asserted a bare `BadRequest` and **passed against the unfixed code** — `reschedule`
refuses on the scheduling policy long before it reaches the lock. It was only by running
the test against the reverted guard that the tautology showed up. Every regression test
here was checked that way.
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
