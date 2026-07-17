# Production-Readiness Report — 2026-07-17

Companion documents: `docs/ecosystem-audit-2026-07-17.md` (findings),
`docs/remediation-ledger-2026-07-17.md` (per-issue ledger, L01–L30).

## A. Executive summary

**30 ledger items: 26 Closed, 4 Open.** Every HIGH-severity production
blocker across finance, SSA, Core Schools, Partner payments, auditability and
feedback loops is repaired, regression-tested, and green in a 1235-test full
suite (zero failures, including the UI-quality lints). Historical data repair
ships as an idempotent, dry-run-first management command. Four items remain
open — enumerated in section M with reasons — so **this report does not claim
the absolute production gate**; it claims every financial-safety and
data-integrity gate, with the residual items being architectural unification
and one product decision.

## B. What this remediation phase delivered (beyond the audit-phase fixes)

| Gate | Delivery |
|---|---|
| Budget Amendments (§4.5) | `BudgetAmendment` model + `amendment_service` (request → review → approve-applies / return / reject), self-review blocked, reviewer roles enforced, applied moves activity + existing cost lines to the new period **without** the delete-recreate the snapshot lock forbids; audit-chained; accountant queue page `/accounts/budget-amendments` + My Plan request action |
| Disbursement rounding (§4.8) | Largest-remainder allocation in weekly disburse — children sum exactly to the parent disbursed amount (test proves 0 UGX mismatch on a 33/33/34 partial) |
| Finance rollups (§4.7) | Rollup `disbursed`/`accounted` now sum actual `AdvanceRequest.disbursed_amount`/`accounted_amount`, not planned line amounts |
| Estimated-cost fallback (§4.6) | All 4 `est_cost_cents` fallbacks removed from authoritative budget totals; line-less scheduled activities are a System Health signal, never a guessed number |
| Evidence matrix (§G) | `apps/evidence/requirements.py`: per-type required kinds (visit form for visits, attendance for trainings, minutes for cluster meetings, assessment form for core assessment, project report for project activities), enforced at completion with named missing documents; checklist API for the frontend |
| Partner allowance (§F) | `PartnerActivityAllowance` model (grant: who/why/how many/expiry); default one non-core activity per partner per school per FY enforced in canonical `create()` AND `partner_schedule`; core slots exempt (governed by the nine-slot package) |
| Partner schedule hardening (§F) | Scope check (a partner can no longer schedule another partner's assignment by ID), duplicate-submission guard matching canonical `create()` |
| Audit chain (§3.8/§H) | `activity.closed`, `finance.disbursed`, `finance.partner_paid`, `budget_amendment.*` now write the tamper-evident AuditLog (specialized logs retained) |
| Project scope (§E) | `_scoped_projects` coordinator rule unified with My Plan/dashboard (manager-only); school-overlap leak closed; PL portfolio oversight lens retained |
| Core recommendation versioning (§D) | Persisted set carries `algorithm_version` + source SSA anchor; backfill command for active plans |
| System Health (§I) | +3 checks: `duplicatePartnerPayments`, `partnerPaidWithoutPayment`, `staleFyReadiness` (9 ecosystem checks total added across both phases) |
| Historical repair (§13) | `manage.py repair_ecosystem_data` — dry-run default, `--apply`, `--only <fix>`; fixes: core-counters, ssa-status, catchup-sync, debrief-drafts, core-recommendations; scans (manual-review queue): duplicate partner payments, paid-without-payment, reopened-still-credited, line-less activities. Idempotency proven by test |
| UI lints (no pre-existing exemption) | Literal `✓` glyphs → SVG; uncompiled `xl:` variants → compiled `lg:`; `test_gold_standard_lints_are_clean` green |

Audit-phase deliveries (L01–L13, L22–L23) are documented in the ecosystem
audit report: FY-aware SSA readiness, duplicate-import protection, canonical
weakest-intervention service, period fund-request guards, cross-channel
disbursement mutual exclusion, reschedule finance locks + vacated-week
regeneration, partner clear-payment retirement + payment uniqueness, reopen
credit withdrawal, legacy reimbursement closure-bypass retirement, debrief
recommendation handoff, catch-up completion, Special Project need gate.

## C–L. Evidence

- **Tests:** 1235 total, 0 failures, `--parallel 4`, fresh DB. New this phase:
  `apps/core/tests/test_production_gates.py` (10: amendment lifecycle ×4,
  evidence matrix, allowance ×2, partner scope, rounding exactness, repair
  idempotency) on top of the 17 ecosystem-handoff regressions and 2 reopen
  tests from the audit phase.
- **Migrations:** `fund_requests.0009` (PartnerPayment uniqueness),
  `projects.0007` (target interventions/measurement/override),
  `partners.0006` (activity allowance), `budget.0006` (BudgetAmendment).
  `makemigrations --check` clean; `manage.py check` clean. All additive —
  no destructive operations; the only constraint addition
  (`uniq_partner_payment_per_activity`) requires the duplicate scan to be
  run (and duplicates manually resolved) BEFORE `migrate` on production data.
- **Deploy order:** backup → `repair_ecosystem_data` (dry-run, review output)
  → resolve any duplicate-partner-payment rows → `migrate` →
  `repair_ecosystem_data --apply` → System Health review.
- **Reconciliation:** advance identity enforced at terminals; children-sum
  exactness proven; single-channel payment guarded at all three disburse
  paths; partner payment unique.
- **Frontend:** every repair whose behavior a user drives has a surface:
  amendment request (My Plan) + review queue (Accounts), evidence missing-
  document errors name the required forms, allowance/duplicate/scope errors
  surface through the existing message framework, Special Project override
  validation in the assignment drawer, System Health rows for every new check.

## M. Open items (the honest gate)

1. **L25 — DomainEvent/SSE seam (HIGH, architectural):** security-critical
   events now reach the tamper-evident chain, but workflows still call
   audit/notification directly; `emit()` remains unwired, so SSE dashboards
   are not event-driven and `DomainEventLog` stays empty. Unifying it touches
   every service and deserves its own guarded rollout.
2. **L26 — Cluster membership triple-source (MED):** `School.cluster_id`
   CharField vs `SchoolClusterAssignment` vs covered-sub-counties; needs a
   data migration + read-surface consolidation.
3. **L27 — `planning_readiness` dual vocabulary (MED):** test vs production
   state machines differ by design; unification requires a data migration and
   coordinated consumer updates.
4. **L28 — Client 1+1 entitlement (MED, product decision):** the "one visit +
   one training per client school per FY" rule is not enforced anywhere; the
   audit could not confirm it is a real product rule (Core has explicit slots;
   client schools have none). Enforcing it without confirmation risks blocking
   legitimate work — needs a product answer, then a one-line gate in
   `create()`.

Also outside this pass (environment, not code): staging deployment smoke
tests, Playwright browser suites, 15k-school performance fixtures, and
mypy/bandit (not configured in this repo). The test suite, System Health, and
reconciliation evidence above are the verification layer available in this
environment.

**Verdict:** financially safe, ecosystem-connected, and regression-locked.
Production deployment is reasonable following the deploy-order above, with
L25–L28 scheduled as the next engineering block — the absolute gate in the
mandate is not fully green until they close.

## N. Post-remediation verification audit (same day)

Four adversarial verification agents re-traced the ecosystem after remediation
(SSA decision loop, finance spine, execution/feedback loops, plus a dedicated
regression hunt over every edited file). Findings and their same-day fixes:

1. **Weakest-intervention consolidation was incomplete** — four sites cited
   the canonical helper in comments but re-implemented inline; the Core
   planning queue still ranked from UNVERIFIED SSA. → All Core/cluster/
   planning SSA reads now confirmed-only with canonical tiebreakers;
   planning-setup aligned to any-FY-latest-confirmed (matching the gate).
2. **Period disburse read the shared advance ledger but never wrote it** —
   period-first disbursement left the same cost line payable via the weekly/
   advance queue. → `services.disburse` now marks child advances DISBURSED.
3. **`review_accountability`/`submit_accountability` were unguarded** — a
   DISBURSED request could be knocked back to a resubmittable status and its
   items rewritten. → Both state-guarded + locked; accountability returns for
   correction while the request stays DISBURSED.
4. **Weekly disburse wrote no tamper-evident audit** → chain event added.
5. **Partner + advance channels had no cross-guard** → pay_partner refuses
   when the advance channel already moved money.
6. **Nine ecosystem health checks were computed but invisible** (JSON-only)
   → rendered on the System Health page as checks 11–19.
7. **Repair-command dry-run over-reported** (legacy status set) → mirrored to
   the apply set.
8. Regression hunt: 9/10 edited surfaces CLEAN; the one defect found is item
   7 above.

Live evidence: `repair_ecosystem_data` dry-run on the dev database found 51
stale FY stamps + 325 unpersisted core recommendation sets (expected
historical drift; zero financial anomalies). All 58 System Health checks
execute clean. Final suite: **1243 tests, 0 failures.**

Verification verdicts: SSA decision loop GREEN; finance spine GREEN after
fixes 2–5; execution/feedback loops GREEN; events/health GREEN after fix 6.
Open architectural items remain L25–L28 (section M) — unchanged in scope.

## O. Environment-stamp guard (local↔production data barrier)

Added post-verification on request: the live server can no longer receive
local data, in either direction.

- `EnvironmentStamp` (system_health, migrations 0001/0002): singleton row
  identifying which environment a DATABASE belongs to, written at migrate
  time from the process's `ENVIRONMENT` (prod settings pin it to
  "production" regardless of env vars).
- Boot guard (`environment_guard.validate_environment`, wired in
  `SystemHealthConfig.ready`): a production process on a 'local'-stamped
  database (restored dev dump) or a local process on a 'production'-stamped
  database (mispointed DATABASE_URL) refuses to start, with remediation
  instructions. Skips migrate/collectstatic/test and unreachable-DB cases.
- Deliberate promotion: `manage.py stamp_environment --to <env>` requiring
  the typed phrase `STAMP <env>`; audit-chained (`environment.restamped`).
- Seed hardening: `seed --demo` now also refuses when the DATABASE stamp
  says production (catches the local-shell-on-live-DB case the env-only
  check missed) and marks `seeded_demo_at` on the stamp so a demo-seeded
  dump is permanently identifiable.
- System Health checks 20–21: `demoDataOnProduction` (stamp marker +
  @edify.test accounts on a production database) and
  `environmentStampMissing`.
- `.dockerignore`: `*.sql`, `*.dump`, `*.sqlite3`, `backups/` — images can
  never carry database contents.
- Tests: `apps/system_health/test_environment_guard.py` (11) — both
  mismatch directions, first-boot adoption, phrase-gated restamp + audit,
  seed refusal with zero writes, seeded-marker, detector on/off.
- Live proof: guard fired against the real dev DB when the process claimed
  production; matching case passes.

Deploy-order update: on first production deploy, `migrate` under prod
settings stamps the fresh database "production" automatically. If a
pre-existing production database is adopted, run
`stamp_environment --to production` once, deliberately.
