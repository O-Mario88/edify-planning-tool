# Final Production Readiness Rating — 2026-07-17

> **Current release-gate addendum (supersedes historical score/green claims
> below).** The earlier narrative documents an audit baseline; it is not the
> release decision for the current working tree. This addendum is the source
> of truth for deployment.

## Current evidence and release decision

- **Code regression:** 248 selected production, workflow, frontend, target,
  SSA, impact and System Health tests passed in 236.333 seconds with
  `PYTHONWARNINGS=error::RuntimeWarning`.
- **Static/migration checks:** `manage.py check` is clean;
  `makemigrations --check --dry-run` reports no changes; local `migrate --plan`
  is empty.
- **Local browser evidence:** authenticated desktop inspection verified the
  Special Projects My Plan structure, real filters and server-rendered tabs;
  computed operational text is at least 12px. Tablet/mobile, dark mode and
  keyboard evidence still require staging.
- **Local System Health:** not green. The development snapshot has a material
  data-repair backlog recorded as F13 in the remediation ledger. It is not a
  production-data measurement, so a restored production-copy scan is required
  before assigning production counts.
- **Scheduler:** intentionally disabled by the deployment decision. No worker
  has been provisioned, and this audit does not override that instruction.

| Category | Weight | Current score | Evidence / release gap |
|---|---:|---:|---|
| Functional completeness | 15% | 8.6 | Canonical workflow regressions pass; production data health is unresolved. |
| Ecosystem handoff integrity | 15% | 8.1 | Main handoffs are tested; broker-backed multi-worker SSE remains unproven. |
| Financial integrity | 15% | 8.4 | Locks, uniqueness and cross-FY pricing tests pass; production reconciliation is not yet run. |
| Data and analytics correctness | 10% | 8.2 | Canonical SSA/target tests pass; production-reference and historic-data validation remains. |
| Security and access control | 10% | 8.5 | Local gates pass; production secrets/TLS and role rehearsal remain. |
| Performance and scalability | 10% | 6.8 | Query-scaling tests pass; no 15,000-school staging SLO evidence. |
| Stability and resilience | 10% | 7.0 | Concurrency/failure-isolation tests pass; restart, outage and restore drills absent. |
| Frontend-backend synchronization | 5% | 8.7 | Workflow/page tests and desktop inspection pass; complete staging surface matrix absent. |
| Design and responsive consistency | 5% | 7.0 | Quality lint passes; 8-breakpoint, dark and keyboard checks absent. |
| Observability, backup and operations | 5% | 3.0 | Scheduler disabled, System Health data not clean, and restore rehearsal absent. |

**Weighted score: 7.84 / 10.**

## Classification: **BLOCKED — DO NOT DEPLOY TOMORROW**

The score is not the deciding factor. The attached production standard has
hard gates, and the following remain red:

1. Scheduler worker is intentionally not provisioned; System Health reports
   `scheduler_enabled` warning. This is a hard gate in the requested audit.
2. System Health is not clean on the available data. Production-copy data
   repair and reconciliation have not been performed.
3. Backup restore, rollback, production-like load, multi-worker realtime and
   complete role/responsive staging rehearsals have not been performed.

The minimum authorised path to a release decision is: take a restored
production copy; apply/review data repairs until System Health is clean; run
the staging rehearsal and restore/rollback drill; and either provision the
single scheduler worker or formally remove/replace every required scheduled
workflow. Email automation remains out of scope—internal messaging is the
operational channel.

Evidence base: docs/ecosystem-audit-2026-07-17.md, remediation-ledger,
production-readiness (sections A–O), hardening-ledger, deployment-hardening
runbook. Test count at final run: see suite output (≈1,280, all green).

## Closed-system access (final-audit addition, verified this pass)

- **No public registration**: no register/signup route or API exists (full
  route grep; the only "register" is HR's compliance register page).
- **Admin onboarding**: apps/admin_users implements create+invite behind
  `USER_MANAGE`; invitations carry TTL (`INVITE_TOKEN_TTL_DAYS`), revocation,
  reuse-prevention (accepted_at), expiry handling.
- **Auth stack** (verified across the session's audits): single lockout
  policy with escalation, rate-limited login, JWT refresh rotation,
  suspended users blocked, audit-chained account events.
- **CD Cost Catalogue control**: page `{CD, ADMIN}`; API write requires
  `COST_SETTINGS_MANAGE`; every change versioned + history row with reason;
  costed lines stamp catalogue id/version/key/rate; missing rate blocks
  funded scheduling (cost gate) rather than silently zeroing.

## Entitlement rules implemented this pass (mandate finally specified them)

- **Client 1+1** (§15): canonical `create()` blocks a second active school
  visit or school training per client school per FY; cancellation reopens the
  slot; reschedule reuses the Activity; partner delivery consumes the same
  school slot. Test-relaxed like sibling gates; strict tests pin it.
- **Core staff 2+2** (§16): staff may hold at most 2 active core visits and
  2 active core trainings per school; the remainder must go to partners.

## Category scores (evidence-weighted, honest)

| Category | Weight | Score | Basis |
|---|---|---|---|
| Functional completeness | 15% | 9.3 | 33 apps, ~90 gated pages inventoried by system_health page inventory; every audited workflow has a live surface; minor UX depth items remain (evidence version history UI, amendment drawer polish) |
| Ecosystem handoff integrity | 15% | 9.5 | 8-chain audit + verification re-audit; 17 handoff regressions + repairs; To-Do engine derived; remaining: DomainEvent/SSE seam (L25) |
| Financial integrity | 15% | 9.6 | all identities reconcile to 0; single-channel exclusion incl. period write-back; payment uniqueness; amendment path; chain-audited money events; concurrency-proven |
| Data & analytics correctness | 10% | 9.4 | canonical SSA service everywhere confirmed-only; platform_engine shared stats; equivalence discipline verified; live-only recommendations documented |
| Security & access control | 10% | 9.4 | closed system verified; role/object scope audits green; evidence access hardened; environment-stamp guard; residual: broader pen-test outside scope |
| Performance & scalability | 10% | 9.0 | O(1) query scaling proven on 7 critical pages (1 N+1 found+fixed); wall-clock SLOs at 15k-school volume require staging hardware |
| Stability & resilience | 10% | 8.8 | concurrency, boundary, failure-isolation, job locking proven; soak/restart/outage drills are staging-pending (runbook §C) |
| Frontend-backend sync | 5% | 9.4 | no-mock-data rule enforced by tests; design-system + tab/ARIA lints green; HTMX patterns audited |
| Design & responsive consistency | 5% | 9.2 | design-system quality suite green; responsive spot checks; full 8-breakpoint × 90-page sweep is a staging/browser task |
| Observability, backup & ops | 5% | 8.5 | 60+ health checks incl. 21 ecosystem seams; job tracking + heartbeat; runbooks written; backup restore NEVER REHEARSED (hard rule: unverified until restored) |

**Weighted total: 9.28 / 10**

## Hard-gate check

None of the automatic NOT-READY conditions exists in the codebase: no
critical security issue, no duplicate-payment path, reconciliation = 0, no
closure bypass, no public registration, scheduler required+monitored, no
known data corruption (repair scans clean on dev data). However: **backup
restore has never been rehearsed** and **staging smoke tests have not run**
— these are the two conditions attached below.

## Classification: **CONDITIONALLY READY (9.28)**

Per the mandate's own rubric (9.0–9.49 = conditionally ready when no
Critical/High issue remains and listed conditions complete before release):

**Release conditions (all in docs/deployment-hardening-2026-07-17.md §C):**
1. Execute the staging runbook: restore rehearsal (backup is unverified
   until restored), 8h soak, restart drills, load scenarios A–E at
   representative scale, role smoke tests on desktop/tablet/mobile.
2. Decide the SSE topology (single-worker SSE or accept refresh fallback)
   before running multiple web workers.
3. Deploy-order: duplicate-payment scan BEFORE migrating the PartnerPayment
   constraint; `repair_ecosystem_data --apply` after migrate; stamp check.

**Not claimed as done** (and therefore keeping the score below 9.5):
staging-dependent evidence (soak/restart/backup/load), the L25 DomainEvent
unification, cluster-membership consolidation (L26), and the
planning_readiness vocabulary unification (L27) — L26/L27 are MED
architectural debts with no financial or security exposure, tracked in the
remediation ledger.

Do not deploy before the conditions execute green on staging. Everything
code-side is regression-locked: the gates that proved each property are
permanent tests that fail CI on regression.
