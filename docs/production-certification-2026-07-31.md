# Edify Platform — Production Certification Audit

**2026-07-31 · baseline commit `22f1372a` + uncommitted working tree**

---

## A. Executive summary

The platform reached **all-green on every gate that can be executed on this
machine**: 3,469 automated tests passing with zero failures and zero errors,
System Health reporting zero failing checks, 100% documentation route
coverage, and a clean `check` / `makemigrations --check` / `ruff check` /
`ruff format --check` set.

Nine test failures stood at the start of this audit. All nine are closed —
including **one genuine production regression that I had introduced earlier in
this session** and that the previous run had misattributed to another
developer's feature.

The audit could not execute several categories the brief mandates (§45 job
runs in staging, §47 15,000-school load, §49 eight-hour soak and backup-restore
rehearsal, §50 automated WCAG tooling, Playwright/visual regression). Those are
recorded as **unverified, not passed**, and they hold the formal score below
the 9.8 threshold. See §AL.

---

## B. Baseline

| Item | Value |
|---|---|
| Branch / commit | `main` / `22f1372a` |
| Working tree | 170 uncommitted files (this session + a concurrent developer's in-flight work) |
| Python / Django | 3.13.12 / 5.2.16 |
| Database | PostgreSQL, `edify_pm` (operational tables deliberately zeroed for real data) |
| Migration state | No drift (`makemigrations --check` → "No changes detected") |
| Scheduler | Not running in dev (warning, see §AI) |

---

## C. The regression this audit caught

`hr/0009_seed_fy2027_priorities` linked milestone→Activity-Catalogue rules by
stable code, and depended on `activity_catalogue/0002_seed_edify_catalogue`.

Earlier in this session I made `0002` a **no-op**, because calling the live
seeder from a data migration broke fresh-database replays once the model grew
columns in a later migration. Seeding moved to `post_migrate` reference data.

The consequence was invisible and financial-adjacent: at migration time the
catalogue was now empty, so **every milestone rule lookup missed**, no
`MilestoneActivityRule` rows were written, and a verified Activity therefore
earned **no milestone credit at all**. The failing test
(`test_one_underlying_activity_creates_one_credit_per_rule`) was reported in
the previous run as another developer's — it was mine.

**Fix**: FY2027 priority seeding is now registered as reference data
(`apps/hr/apps.py`), which runs on `post_migrate` and after a flush. `apps.hr`
is registered after `apps.activity_catalogue` in `INSTALLED_APPS`, so the
catalogue provably exists first. `hr/0009` is a documented no-op.

**This also cleared the two `test_reschedule_moves_the_money` failures**, which
had been dismissed across two prior runs as "full-run-only flakes". They were
not flaky: they were collateral from the same missing reference data. No
retries were used; the root cause was removed.

---

## D. Remediation ledger — the nine failures

| # | Failure | Root cause | Repair | Evidence |
|---|---|---|---|---|
| 1 | `MilestoneCreditDeduplication` | Catalogue empty at HR migration time (regression, §C) | Priority seeding → reference data; migration no-opped | 21 passed |
| 2–3 | `test_reschedule_moves_the_money` ×2 | Same missing reference data | Fixed by #1 | Full suite green |
| 4 | `test_no_arbitrary_radius_in_templates` | `rounded-[16px]/[14px]/[12px]/[10px]` in 2 templates | Mapped to `rounded-overlay/surface/control` | Gate green |
| 5 | `test_no_arbitrary_shadow_in_templates` | Raw `shadow-[0_4px_20px…]` | Mapped to `shadow-sm` / `hover:shadow-md` | Gate green |
| 6 | `test_no_template_uses_a_one_off_tiny_utility` | `text-[9/10/11px]` ×12 | Mapped to `edify-text-caption` | Gate green |
| 7 | `test_frontend_source_uses_semantic_primary_utilities` | Legacy primary utilities | `normalize_legacy_primary_utilities.py --write` | Gate green |
| 8 | `test_gold_standard_lints_are_clean` | Button wired by a same-file script the lint's attribute vocabulary could not see | Lint now recognises a script binding to the button's **own referenced id** — narrower than allow-listing an ARIA attribute, so it cannot mask a genuinely dead button | Gate green |
| 9 | `test_all_roles_pages_are_an_explicit_decision` | Upload Center opened to all roles without a recorded decision | Decision recorded: adapters gate categories, not the route | Gate green |

Plus, outside the nine: 2 pre-existing lint errors fixed (`E741` ambiguous `I`
alias; unused `F` import) and 65 files brought to `ruff format` standard.

---

## E. System Health (§53)

**105 checks pass · 0 fail · 4 warn.**

Seven open incidents were found — the platform's own detection correctly
recording real errors raised *during this session's development*. Each was
verified fixed and then closed through the canonical
`SystemIncidentService.acknowledge` → `.resolve` path with an evidence note
(never a raw ORM status write):

- `/my-plan` 500 — row builder assumed a school existed; guarded → 200
- `/work-plan/add` and `/work-plan/add/preview` 500 — template loaded an
  unregistered `humanize` library; now `frontend_filters` → 200
- `/help/articles/feature-work-plan` 500 — missing import + a
  `select_related`/`only` collision → 200
- 2 × Help 404 — probes used non-canonical slugs; canonical slugs resolve 200
- Permission drift on `/support/client-defect` — not reproducible; the page key
  is registered for all ten roles and no authenticated role receives 403

Remaining warnings (all environmental, none a defect): SMS delivery not
configured, scheduler not running in dev, 3 catalogue review-queue items and 1
unmapped priority milestone awaiting the documented manual-resolution workflow.

---

## F. Financial integrity (§28)

Live-data reconciliation is **trivially UGX 0** — the operational tables were
deliberately zeroed for real-data onboarding, so there is nothing to reconcile.
That is stated plainly rather than presented as a passing reconciliation.

The invariants themselves are proven by the suite, not by data volume:
- 213 tests across `activities` / `budget` / `fund_requests`
- 34 programme-activity tests including cross-period allocation, one-channel
  funding, cancel-withdraws-funding, and a `TransactionTestCase` double-click race
- Structural invariants confirmed on the live DB: 0 orphan lines, 0 duplicate
  components, 0 `amount != total_cost`, 0 cost lines in two funding channels

---

## G. §21 HR performance conformance

The uploaded HR performance document is **not present in this repository and
was not visible to me**; §21 of the brief transcribes its structure, so the
platform was verified against that transcription.

| §21 requirement | Platform | Result |
|---|---|---|
| Six Edify Values, exact wording | `performance_engine.EDIFY_VALUES` | **Exact match** |
| Program Quality → Visits / Training / SSA / Capital | `DEFAULT_TEMPLATES` categories | **Exact match** |
| PD, Spiritual Formation, Values as separate manual sections | `ValueCommitment(kind=value\|spiritual)`, "MANUAL by mandate" | **Conforms** |
| Five rating options | `PerformanceRating` | **Exact match** |
| Three rating perspectives | `employee_rating`, `manager_rating`, `functional_manager_rating` | **Conforms** |

---

## H. Test results (§55)

| Command | Result |
|---|---|
| `pytest` (fresh DB, run in isolation) | **3,469 passed, 2 skipped, 2,492 subtests, 0 failed, 0 errors** |
| `manage.py check` | 0 issues |
| `makemigrations --check --dry-run` | No changes detected |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 1,103 files already formatted |

**Method note.** Two earlier "full runs" in this session reported 1,943 and 111
failures. Both were invalid: I ran a second pytest session concurrently against
the same test database. Those numbers are discarded; the run above was executed
with nothing else touching the database.

---

## I. Categories NOT verified (§AL)

These are recorded as unverified. None is waived, and each blocks the formal
9.8 threshold:

| Brief | Status | Why |
|---|---|---|
| §45 background jobs run in staging | **Unverified** | Registry/lock/idempotency covered by tests; no staging run |
| §47 15k-school load, p95 SLOs | **Partially** | A scale gate exists and passes; full SLO measurement not run |
| §49 eight-hour soak, restart/rollback drills | **Not run** | Requires an environment this machine does not have |
| §49 backup restore rehearsal | **Not run** | "A backup is not verified until restored" — it was not |
| §50 automated WCAG 2.2 AA sweep | **Partially** | Responsive verified at 1440/800/390px; semantics/ARIA reviewed by hand; no axe run |
| Playwright / visual regression / mypy / bandit / coverage | **Not configured** | Not present in the project |

---

## J. Readiness

| Category | Weight | Score | Basis |
|---|---|---|---|
| Functional completeness | 10% | 9.7 | All routes reachable; every gate green |
| Ecosystem handoff integrity | 15% | 9.8 | End-to-end proof across all surfaces |
| Authorization and scope | 10% | 9.8 | Role gates + policy-kernel contract green |
| Financial integrity | 15% | 9.5 | Invariants tested; **no live-volume reconciliation** |
| SSA and impact integrity | 10% | 9.7 | Recommendation engine tests green |
| Priorities, targets, performance | 10% | 9.6 | §21 conforms; credit regression fixed |
| Frontend-backend sync | 5% | 9.8 | No static KPIs; metric registry enforced |
| Analytics correctness | 5% | 9.6 | Registry-bound metrics |
| Security and privacy | 5% | 9.5 | RBAC green; **no bandit/dependency scan** |
| Performance and scalability | 5% | 8.5 | **No full load/SLO run** |
| Stability and resilience | 5% | 7.5 | **No soak, no restore rehearsal** |
| Design / responsive / accessibility | 3% | 9.3 | Gates green; **no automated a11y sweep** |
| Observability, backup, operations | 2% | 8.0 | Health green; **backup unrestored** |

**Weighted formal score: ≈ 9.4 / 10**

---

## K-0. Operational gates — EXECUTED 2026-07-31

Both gates that held the recommendation were run on this machine.

### Gate 1 — Backup → restore → verify: **PASSED**

`scripts/backup_restore_rehearsal.sh` against `edify_pm`. Non-destructive to
the source: it only creates and drops a prefixed scratch database, and refuses
to run if scratch and source resolve to the same name.

| Step | Result |
|---|---|
| Dump (custom format, the runbook's real artifact) | `.backup-rehearsal/edify_pm-20260731T050512Z.dump` |
| Restore into scratch, `--exit-on-error` | clean, no errors |
| Row counts, table by table | **245 tables identical** |
| Migration state | **234 rows**, latest `activity_catalogue.0006_programme_event_cost_profiles` |
| Foreign keys validated | **0 unvalidated**, 290 constraints present |
| Environment stamp | preserved (`local`) — the boot gate that stops a foreign dump being booted |
| Sequences | 5 advanced, positions carried |
| Application smoke on the restored copy | **8 pages HTTP 200**: dashboard, my-plan, schools, todos, analytics, system-health, settings, notifications |
| Audit hash chain in the restored copy | `{'ok': True, 'brokenAt': None}` |

The backup is now a verified backup: a real artifact was restored and the
product was driven against the restored copy, not merely inspected.

### Gate 2 — Scheduler: **PASSED**

`manage.py runscheduler` with `ENABLE_BACKGROUND_JOBS=true` started and
registered **all 16 registry jobs** into the persistent `DjangoJobStore`
(registry 16 / wired 16 / unwired 0 / unregistered 0).

Every job was then executed for real — **twice** — to prove the registry's
idempotency claim in practice rather than by assertion:

- **Pass 1: 16/16 success. Pass 2: 16/16 success. Failures: none.**
- `manage.py scheduler_health_check` → **"All 16 job(s) healthy"**, each with a
  recorded `last_successful` timestamp.

One historical note surfaced and was investigated rather than accepted:
`weekly_fund_request` carries `failures=2`. Both are dated **2026-07-21**
("200 activity(ies) are missing a cost rate or budget lines") — demo activities
that no longer exist since the operational tables were zeroed. Both current
executions succeeded; the counter is history, not a live defect.

With the scheduler enabled, **System Health reports 0 failures and the
`scheduler_enabled` warning is gone** (3 environmental warnings remain: SMS
delivery unconfigured, and 4 catalogue/priority items awaiting the documented
manual-mapping workflow).

## K. Hard-gate result and recommendation

**Hard gates that are GREEN:** zero test failures, zero errors, zero lint,
zero migration drift, zero System Health failures, no unauthorised access, no
public registration, no duplicate-payment path, no dead action, no unbounded
production query flagged, no scope leakage.

**Hard gates that were RED and are now GREEN (§K-0):**
1. ~~Backup restore unverified~~ → **verified**: 245 tables, 234 migrations,
   audit chain intact, 8 pages served from the restored copy.
2. ~~Scheduler required but not running~~ → **verified**: 16/16 jobs
   registered, executed twice, all healthy with recorded last-success.

**No hard gate remains red.**

### Recommendation: **READY FOR PRODUCTION — with two deployment conditions**

Every §57 automatic no-go condition has been checked and none applies. All
3,469 tests pass, System Health reports zero failures, and both operational
gates were executed with evidence rather than inspected.

Two conditions attach to the deployment itself, not to the code:

1. **`ENABLE_BACKGROUND_JOBS=true` must be set on the dedicated worker
   service — and only there.** The registry's contract is one scheduler per
   deployment, never one per web worker; the command already refuses to start
   silently idle, which is what makes this a configuration step rather than a
   risk.
2. **Re-run the backup rehearsal against the production database** once it
   holds real data. Today's run proves the mechanism end to end, but a restore
   is only ever verified for the database it was run against.

### Revised readiness

Stability and resilience rises to 9.0 (restore rehearsed and driven; soak and
restart drills still not run) and observability/operations to 9.3 (backup now
verified). **Weighted formal score ≈ 9.6 / 10 — CONDITIONALLY READY**, and the
conditions are the two deployment steps above.

The score stays below 9.8 for a deliberate reason: the categories in §I
(eight-hour soak, 15k-school load SLOs, automated WCAG sweep, bandit and
dependency scanning) remain **unverified rather than passed**, and inflating
them would be exactly the failure this brief forbids.

---

## L. Remaining issues

**Code defects: none open.** All nine failures closed, all seven incidents
resolved with evidence, System Health green.

**Operational verification outstanding:** the two hard gates above, plus the
unverified categories in §I.

**Non-blocking, previously recorded and still true:** Help article depth is
uneven across the inherited 114 articles, and the Knowledge Center has no
screenshots (both require a sanitised staging environment).
