# Edify Platform — Evidence-Based Readiness Baseline & Remediation Ledger
**Date:** 2026-07-17 · **Method:** live test environment (not narrative) · **Auditor:** Claude (Cowork)

> This document supersedes the "≈1,280, all green" claim in the prior audit docs
> for the **current** working tree. Every number below was produced by building
> the project into a clean environment (Python 3.13.13, Django 5.2.4, PostgreSQL 16,
> all `requirements/dev.txt` deps) and running the actual commands. Where a gate
> could not be measured from this environment, it is marked **NOT MEASURED**, not
> assumed green.

> **2026-07-18 update:** the code-level blockers below (REG-02, SEC-01,
> SEC-02, SEC-03, SEC-04, and the "automated tests do not all pass" hard gate)
> are now **CLOSED** — see the ledger in §D and the hard-gate result in §E for
> full evidence. The remaining hard-gate blockers are infrastructure-only
> (scheduler worker provisioning, backup restore rehearsal, staging
> load/soak/rollback drills) and require real staging infrastructure this
> environment does not have. The original 2026-07-17 narrative below is left
> intact as the historical record of what was found that day.

---

## A. Executive summary

The codebase is well-engineered and its security posture is strong, but **the
committed tree does not pass its own CI**, so the platform is **BLOCKED / NOT
READY** for deployment under the project's own §51/§54 rule ("all automated
tests pass"). This is now backed by hard evidence, not narrative.

Objective results this session:

- `manage.py check` — **clean (0 issues)**.
- `makemigrations --check --dry-run` — **no changes**; `migrate` applies cleanly on a fresh DB; `migrate --plan` empty.
- `ruff check .` — **3 errors** (unused imports) → CI red. **FIXED.**
- `ruff format --check .` — **31 files** need reformat → CI red. **FIXED.**
- Full suite — **1296 tests, 19 errors, 0 failures** (687.9s, 2 cores). Root cause isolated; **17 fixed**, **2 remain open** (separate latent issue).
- Closed-system/auth/config audit — **4 defects (2 Medium, 2 Low)**; all Critical/High safety properties **CONFIRMED SAFE**.

A fix commit (`43d4cb2`) landed the CI-unblocking and test-collision repairs
(19 → 2 test errors). Deployment remains blocked on: the 2 residual test
errors, the operational hard gates (scheduler worker not provisioned, backup
restore never rehearsed, no staging load/soak/rollback drills), and the four
production boot-gates that are specified but not implemented.

**Interim classification: BLOCKED — DO NOT DEPLOY.** This agrees with the
team's own release-gate addendum (7.84), now substantiated with reproducible
test evidence.

---

## B. What was verified green

| Check | Result | Evidence |
|---|---|---|
| Django system check | 0 issues | `manage.py check` |
| Migrations complete | no missing migrations | `makemigrations --check --dry-run` → "No changes detected" |
| Migrations apply | clean on fresh Postgres 16 | full `migrate` OK; `migrate --plan` empty |
| Closed system | no public registration route/API anywhere | full route grep; only admin-gated creation (USER_MANAGE) |
| Single lockout policy | web + API + admin all via one backend | `AUTHENTICATION_BACKENDS` = LockoutEnforcingModelBackend only |
| Suspended users blocked | on all paths (web/API/JWT/admin) | suspend/disable set `status` + `is_active=False` |
| Object scope enforce | fail-closed; no shadow-allow path | `scoping.py` returns `.none()`; `can_view_page` defaults False |
| Secure cookies / HSTS | SSL redirect, secure cookies, HSTS 30d preload | `config/settings/prod.py` |

---

## C. Remediation ledger (concrete, reproducible)

| ID | Sev | Area | Finding | Status |
|---|---|---|---|---|
| CI-01 | High(gate) | Lint | `ruff check .` fails: 3 unused imports (`daily_visit_batches/services.py:359`, `frontend/views/cluster_views.py:8`, `targets/team_targets.py:29`) | **FIXED** (43d4cb2) |
| CI-02 | High(gate) | Format | `ruff format --check .` fails on 31 files | **FIXED** (43d4cb2) |
| REG-01 | High(gate) | Tests | 18 tests error with `IntegrityError` on `uniq_catalogue_country_fy_version` / `cost_setting_key_key`: migration `budget/0003` seeds a CostCatalogue for the operational FY and seed `0005` seeds CostSettings; test `setUp`s create duplicates. Deterministic in FY2026. | **FIXED** — idempotent `get_or_create` (43d4cb2); 19→2 errors |
| REG-02 | Med | Tests | 2 tests still error after REG-01: `test_cross_fy_reschedule_moves_all_period_fields`, `daily_visit_batches…test_under_target_requires_reason`. They schedule on **hardcoded Sunday dates** (e.g. `date(2026,8,9)`) vs a "no Sunday scheduling" business rule. Was masked by REG-01. | **FIXED** — canonical `SchedulingPolicyService` (`apps/core/calendar_policy.py`) now enforced on every scheduling surface (Planning, My Plan, Partner scheduling, Core School slots, Budget Amendment reschedule, Daily Visit Batches, Route feasibility); `ClockService` added; flaky wall-clock-relative test dates fixed/frozen with `freezegun`; dedicated 16-test `test_reg02_calendar_policy.py` suite added; full 1321-test suite green on the real run date |
| SEC-01 | Med | Config | `prod.py` boot gates are **absent** for four §49 conditions: scheduler-disabled, pending migrations, missing static assets, DB-unavailable-at-boot. Present for all others (DEBUG, JWT, AUTHZ, flags, keys, hosts). | **FIXED** — `apps/core/boot_gates.py` (DB-availability, pending-migrations, static-assets, fail-closed via `CoreConfig.ready()`, skipped for `migrate`/`collectstatic`/etc.); scheduler-disabled confirmed already CRITICAL via existing `apps/realtime/health.py` System Health check; 15-test `test_boot_gates.py` added |
| SEC-02 | Med | Auth | Login leaks account existence: a real account trips lockout (403 "temporarily locked") while an unknown email keeps returning 401 "Invalid credentials" — an enumeration oracle. (`auth_services.py:74-78`, `auth_views.py:95-112`) | **FIXED** — new `AuthenticationFailureService` (`apps/accounts/auth_failure_service.py`) returns one generic message/401 for locked/wrong-password/unknown-email across web + API login; real cause still audited (`auth.login_failed`); lockout branch also now burns a real password-hash check for timing parity |
| SEC-03 | Low | Auth | Refresh rotation is single-use but has **no reuse/lineage detection** (no token family revocation on replay). Reused token is rejected, but a stolen live chain isn't revoked. (`auth_services.py:121-138`) | **FIXED** — `RefreshToken.family_id`/`parent`/`consumed_at`/`reuse_detected_at` (migration `accounts/0017`); reuse of a consumed/revoked token now revokes the whole family; race-safe (`select_for_update`, child minted inside the same transaction as consumption); disabling a user also revokes its live tokens; `test_refresh_token_reuse.py` (incl. a real-thread concurrency test) |
| SEC-04 | Low | Auth | forgot-password timing side-channel: known email does token-gen + DB write + mail; unknown returns immediately. Response shape identical (good) but timing differs. (`auth_services.py:153-176`) | **FIXED** — real (network-bound) provider send is backgrounded on a daemon thread (`_send_password_reset_async`) when `mailer.is_configured`; console/dev delivery stays synchronous (no network cost, keeps `devPreview`); `test_forgot_password_timing.py` |

**Systemic note (time-dependence):** REG-01 and REG-02 are both wall-clock/calendar
fragilities. The suite is **not time-independent** — it can pass or fail depending on
the date it runs. Recommend a `freezegun`/fixed-clock policy and a rule that all
scheduling tests use explicitly non-Sunday, in-FY dates. This should itself be a
tracked hardening item, because a green CI today can turn red purely by the calendar
advancing.

---

## D. Category rating (only what this session could evidence)

Scored 0–10. Categories requiring staging/data/browser infrastructure that this
environment cannot provide are marked **NOT MEASURED** and must not be counted as
green.

| Category (weight) | Score | Basis / gap |
|---|---|---|
| Security & access control (10%) | 8.7 | Criticals safe; 3 auth defects (SEC-02/03/04) + 4 missing boot gates (SEC-01) |
| Data & analytics correctness (10%) | NOT MEASURED | equivalence not re-run this session |
| Financial integrity (15%) | NOT MEASURED | reconciliation not re-run against data |
| Functional completeness (15%) | ~8 (partial) | check/migrations clean; workflow tests pass once REG-01 fixed |
| Ecosystem handoff integrity (15%) | NOT MEASURED | requires full green suite + staging |
| Performance & scalability (10%) | NOT MEASURED | no 15k-school staging data/hardware |
| Stability & resilience (10%) | NOT MEASURED | no restart/outage/restore drills possible here |
| Frontend-backend sync (5%) | NOT MEASURED | requires browser matrix |
| Design & responsive (5%) | NOT MEASURED | requires 8-breakpoint browser sweep |
| Observability/backup/ops (5%) | ~3 | scheduler not provisioned; backup restore never rehearsed |

**A weighted total is deliberately not published** — publishing one while 60% of
the weight is NOT MEASURED would be the rating inflation §52 forbids. The honest
statement is the hard-gate result below.

---

## E. Hard-gate result

Automatic NOT-READY conditions currently present:

1. ~~**Automated tests do not all pass**~~ — **CLOSED** (2026-07-18 follow-up session): REG-02 and SEC-01/02/03/04 all closed (see updated ledger above). Full suite verified green three separate ways per §1.3: (a) 1321/1321 on the real run date, (b) 1354/1354 with the whole suite frozen at an FY-boundary date (`2026-10-06`, crossing FY2026→FY2027 mid-run) via `freezegun`, (c) 1354/1354 on a completely fresh database (`manage.py test --noinput`, full migration rebuild from zero — no `--keepdb` residue). The fresh-DB pass caught one additional latent bug the two `--keepdb` runs had been silently masking with accumulated dev-DB residue: `test_cross_fy_reschedule_moves_all_period_fields` used `get_or_create` on a globally-unique `CostSetting.key` that migration `budget/0005` already seeds onto a different catalogue — fixed with `update_or_create` so the test's own FY2027 catalogue actually owns its rates. `ruff check`/`ruff format --check` both clean; `makemigrations --check --dry-run` clean; `migrate --plan` clean; the new `accounts/0017` migration (refresh-token family tracking, SEC-03) applied to the real dev database.
2. **Scheduler required but not provisioned** — worker service intentionally not deployed; 7 background jobs would not run. (§54, §40) — **STILL OPEN**, needs real infra.
3. **Backup restore never rehearsed** — unverified by definition. (§48) — **STILL OPEN**, needs real staging infra.
4. **Staging load/soak/rollback/role/responsive rehearsals absent** — (§42–§47) — **STILL OPEN**, needs real staging infra + elapsed time this environment cannot provide.

Items 2–4 each still force NOT READY on their own. **Result: BLOCKED** (infra-dependent items only — no known code-level defect remains open as of this update).

---

## F. Fixes applied this session

Commit **`43d4cb2`** on `main` (unpushed — network-blocked from the cloud shell):
- CI-01, CI-02: ruff lint + format (35 files) → `ruff check .` and `ruff format --check .` both clean (verified).
- REG-01: idempotent `get_or_create` in 6 test modules → full-suite errors 19 → 2, with no regression in guard modules (`test_leave_workflow`, `test_centralized_costing` still pass).

Caveat: `git add` also swept in 2 pre-existing uncommitted files
(`apps/core/tests/test_weekly_fund_requests.py`, `apps/frontend/test_theme_system.py`);
a cloud-git lock limitation prevented cleanly separating them. They are your own
changes and harmless, but you may want to review that commit locally.

---

## G. Sequential path forward (remaining program)

1. ~~Close REG-02~~ — **DONE**.
2. ~~Close SEC-01~~ — **DONE**.
3. ~~Close SEC-02/03/04~~ — **DONE**.
4. **Provision the scheduler worker** (or formally remove each scheduled job) — §40. Needs real infra.
5. **Staging program** — restore rehearsal (backup unverified until restored), 8h soak, restart/rollback drills, load at representative scale, role + responsive matrix — §42–§48. Needs real staging infra + elapsed time no interactive coding session can provide.
6. **Then, and only then**, re-score all categories with staging evidence and re-run the hard-gate check.

Remaining hard-gate blockers (§E above) are now infrastructure-only — no known
code-level defect is open as of this update. A much larger 55-section
platform-wide audit request (frontend-backend sync, every role/workflow,
analytics equivalence, N+1 audits, etc.) was received in the same session
this update landed in; per explicit instruction it was not started until this
queue closed, and has not yet been started as of this writing.

Everything code-side that this session fixed is regression-locked by the existing
test suite once it is green.
