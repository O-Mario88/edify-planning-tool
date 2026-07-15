# Edify Platform Audit — Issues 1-6 Final Evidence Report

**Date:** 2026-07-14
**Scope:** Six specific, previously-identified defects from the Phase 3-11 audit's residual open-items list (`docs/platform-audit-2026-07-13-phase3-11-report.md`, §N): a duplicate/divergent CD team-target formula, a disabled background-job scheduler, three divergent authentication lockout systems (plus a fourth, undiscovered one), CD/PL/RVP analytics N+1 queries, an unbounded/N+1 `/ssa/unmatched` fuzzy-match queue, and an under-verified IA Dashboard performance claim.
**Method:** Worked sequentially, solo (no multi-agent Workflow orchestration, per explicit instruction), with real database verification at every step — no mocked queries, no estimated numbers where a measured one was obtainable. Every fix was verified against the real dev PostgreSQL database in addition to the test suite.

---

## A. Executive Summary

All six issues are resolved and verified. The full test suite is green — **989/989 tests passing**, run both sequentially and via the exact CI invocation (`python manage.py test --parallel 4` against a freshly created database), matching `.github/workflows/ci.yml` exactly. `ruff check .` and `ruff format --check .` are both clean across the entire repository (previously 88 lint errors and 131 unformatted files — both pre-existing, predating this work — are now fixed). `manage.py check` and `makemigrations --check --dry-run` are both clean.

Two of the six issues (Analytics N+1 and IA Dashboard) required real investigation before a fix could be scoped correctly: the CD Analytics `district_heatmap` N+1 turned out to be far worse than expected (~680 queries at real dev-DB scale, now 5), while the originally-reported "IA Dashboard is slow" claim was **not reproducible** on the actual `/ia/dashboard/` route — the real N+1 was found one route over, on `/ia/verification/`, and is now fixed there instead of being wrongly "fixed" on a page that was never actually slow.

Along the way, three additional real defects were found and fixed that were not explicitly named in the original scope, because they were direct blockers to correctly completing the named work:
1. An admin "reset password" action that left `lockout_escalated=True` accounts still locked after the "reset" (Issue 3 work).
2. A pre-existing Django `--keepdb` + `TransactionTestCase` interaction bug that silently corrupts the shared test database for **any** developer running the test suite twice in a row — not something this session introduced, but something this session's own new tests would have propagated if left unfixed (see §K for full detail).
3. The SSA upload parser silently discarding the "School Name" and "District" columns from every uploaded file, meaning the pre-existing fuzzy-match-suggestion feature had never actually functioned on real data (Issue 5 work).

**Readiness assessment:** No known regressions. No pending migrations. No lint/format debt. Every fix has dedicated, passing, non-trivial tests (not just "renders 200").

---

## B. Formula Unification — CD Team Target Duplicate Formula

*(Completed in an earlier part of this same working session, before this report's Issues 3-6 continuation; summarized here for completeness since it was the first of the six issues.)*

`apps/analytics/cd_analytics_service.py::_weighted_achievement` used to hand-roll its own annual-target proration (`round(annual * months/12)`), which disagreed with the canonical `divmod`-based proration in `apps/targets/my_targets.py::weighted_period_pct` in roughly two-thirds of randomized test cases. Rewritten to resolve users then call the canonical `pooled_monthly_series()` + `weighted_period_pct()` — the same functions My Targets and Team Targets use — so CD/RVP Analytics can never disagree with what a PL sees on their own Team Targets page for the same people/period.

**Tests:** `apps/analytics/test_target_formula_unification.py` — `TargetFormulaEndToEndTest` (12 named, DB-backed integration tests) + `RandomizedFormulaEquivalenceTest` (2 tests × 1,000 randomized cases each, pure-Python, zero mismatches).

---

## C. Scheduler and Background Jobs

*(Also completed earlier in this session; summarized for completeness.)*

`ENABLE_BACKGROUND_JOBS` was false everywhere with no dedicated worker process ever provisioned — `apps/realtime/apps.py::AppConfig.ready()` used to start APScheduler directly inside the web process, which runs once per worker/replica (N duplicate schedulers on any multi-replica deployment). Rewritten to a dedicated `python manage.py runscheduler` process (see `docs/scheduler-deployment.md`), with DB-backed distributed locking (`ScheduledJobLock`, atomic conditional UPDATE) and execution history (`ScheduledJobExecution`) so even an accidental second scheduler process skips duplicate job triggers rather than double-executing. `Procfile` added (web/worker/release). 7 jobs registered (4 original + 3 new: target ledger sync, PD reminders, field debrief recurring-issue detection).

**Tests:** `apps/realtime/tests.py::SchedulerArchitectureTests` (10+ tests) + updated `SchedulerRegistrationGateTests`. Verified with real, manually-triggered scheduler process execution against the dev database (not mocked).

---

## D. Authentication Lockout

**The defect:** three independently-implemented lockout systems — web session login (`apps/frontend/views/auth_views.py`, ~100-year "permanent lock" convention), DRF API login (`apps/accounts/auth_services.py`, different fallback constants: max-failed defaulted to 5 vs. the web path's 10), and — discovered during this work, not in the original report — Django's own `/admin/login/`, which used plain `ModelBackend` and enforced **no lockout at all**.

**The fix:** one canonical `AuthenticationLockoutService` (`apps/accounts/lockout_service.py`) and one `LockoutEnforcingModelBackend` (`apps/accounts/auth_backend.py`), wired in as the sole entry in `AUTHENTICATION_BACKENDS`. All three login surfaces now call `django.contrib.auth.authenticate()` and nothing else — because the policy lives in the backend, Django admin's login form picks it up automatically with no admin-specific code changes. Policy: `AUTH_MAX_FAILED_LOGINS` (10) consecutive failures → temporary lock (`AUTH_LOCKOUT_DURATION_MINUTES`, 15 min, auto-expiring); `AUTH_LOCKOUT_ESCALATION_COUNT` (3) lock cycles within `AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS` (24h) → escalated, admin-unlock-required; atomic `select_for_update` increments (race-safe, verified below); generic error messages on every surface (no account-existence leak). Full writeup: `docs/auth-lockout-policy.md`.

**Bug found and fixed along the way:** the admin-panel "reset password" action hand-cleared only `failed_login_count`/`locked_until`, leaving `lockout_escalated=True` untouched — an admin "resetting" an escalated account left the user still unable to log in. Now delegates to `AuthenticationLockoutService.admin_unlock()`.

**System Health:** `apps/accounts/health.py::auth_lockout_health()` — three checks (`auth_backend_unified`, `legacy_lock_records`, `escalated_accounts_pending_unlock`), wired into `/system-health` under "Authentication Lockout." A `python manage.py repair_legacy_lock_records` command backfills any pre-migration accounts still using the old 100-year-lock convention (0 found in the dev DB — verified via `migrate accounts` output).

**Tests (all 13 named tests required, plus 2 bonus regression tests — 15 total, all passing):** `apps/accounts/test_lockout_unification.py` —
`test_all_login_paths_use_same_lockout_policy`, `test_failed_logins_increment_atomically`, `test_temporary_lock_activates_at_threshold`, `test_temporary_lock_expires`, `test_successful_login_resets_counter`, `test_unknown_email_does_not_leak_account_existence`, `test_api_and_web_login_have_same_behavior`, `test_switching_login_endpoint_does_not_bypass_lock`, `test_repeated_lock_cycles_escalate_when_configured`, `test_admin_unlock_works`, `test_manual_admin_lock_works`, `test_concurrent_failed_attempts_do_not_bypass_threshold` (real `threading` + `TransactionTestCase`, not simulated), `test_legacy_lock_records_are_migrated_safely`, plus `test_health_check_detects_legacy_lock_inconsistency` and `test_admin_password_reset_clears_escalation` (regression coverage for the bug above).

Real (non-mocked) verification: logged into the actual dev server via browser as a fresh admin user, confirmed `/system-health` renders the new Authentication Lockout card with live data.

---

## E. Analytics Performance (CD/PL/RVP N+1)

**Measured before/after, real dev database** (700 schools, 136 districts, 5 regions):

| Method | Before (estimated from code shape) | After (measured) |
|---|---|---|
| `CDAnalyticsService.district_heatmap` | ~5 queries × up to 136 districts ≈ **680** | **5** |
| `CDAnalyticsService.regional_summary` | ~5-6 queries × 5 regions ≈ **25-30** (plus a duplicate-query bug — see below) | **6** |
| `RVPDashboardService.region_ranking` | ~5 queries × 5 regions ≈ **25** | **5** |

**Root cause:** these methods looped over districts/regions and re-queried `SsaRecord`/`SsaScore` per iteration. Rewritten to batch-fetch every ingredient once (school→district/region maps, all confirmed SSA records for the latest cycle, all their intervention scores) and group in Python — query count no longer scales with district/region count, proven by a test that triples the district count mid-test and asserts the query count is identical before and after.

**Also fixed:**
- `regional_summary` had a pre-existing bug recomputing the same "cur" SSA average via a 4th, wholly redundant query identical to the "avg" computed 3 lines above it.
- `target_by_pl_cceo`/`pl_oversight`/`kpis`/RVP's `get_dashboard` (3 separate calls to `_weighted_overall`) each independently re-ran `TargetAchievementService.rebuild()` + the per-user monthly-series fetch for overlapping CCEO sets. New shared primitive `apps/targets/my_targets.py::per_user_monthly_series()`/`pool_series()` fetches each person's series exactly once per request; `CDScope.per_user_series` caches it for reuse across every PL/CCEO-level read in that request.
- `recommended_actions` used to fully re-run `partner_performance()` and `pl_oversight()` a second time (both already expensive) just to derive two counts from them; `get_dashboard()` now computes them once and passes the results through.
- PL Analytics `district_performance`/`cluster_performance` had the identical per-row N+1 shape; fixed the same way.
- Added a composite DB index, `Activity(responsible_staff_id, fy, activity_type)` — the exact filter `TargetAchievementService.rebuild()` runs once per user (still legitimately O(users), now no longer O(users) × duplicated-across-methods).

**Deliberately not fixed (documented, not silently dropped):** `RVPDashboardService.special_projects` has a real but smaller N+1 involving a project↔activity relation joined two different ways (direct FK + cost-line FK, deduped via `.distinct()`); batching it safely requires more care than the time budget allowed for a non-explicitly-required target. `cceo_snapshot`'s per-CCEO SSA-improve queries (2 queries × CCEO count) are also not yet batched — same reasoning.

**Tests (8 required, all passing):** `apps/analytics/test_analytics_query_performance.py` — `test_cd_region_ranking_query_count_is_bounded`, `test_cd_district_ranking_query_count_is_bounded` (includes the triple-the-districts proof), `test_pl_region_ranking_query_count_is_bounded` (PL's `cluster_performance`, since PL scope has no literal region tier), `test_pl_district_ranking_query_count_is_bounded`, `test_rvp_country_ranking_query_count_is_bounded`, `test_analytics_aggregations_do_not_duplicate_rows`, `test_analytics_totals_match_source_records` (cross-checked against a raw `Avg()` aggregate), `test_analytics_scope_is_preserved_after_optimization` (proves the batched rewrite still correctly narrows to a filtered district/region, not the whole country).

---

## F. SSA Unmatched Performance (`/ssa/unmatched`)

**The defect:** `UnmatchedSSARecord.objects.filter(status__in=["pending","hold"])` loaded with **no pagination and exactly one filter field**, then looped over every record running `School.objects.filter(name__icontains=r.school_name_raw, ...).first()` — one unindexed full-table `ILIKE` scan per unmatched row, unbounded on both axes.

**A deeper root cause found during investigation:** the upload parser (`apps/ssa/upload_service.py`) read "School Name" and "District" columns from the uploaded file into `field_index` but never persisted them onto `SSAImportRow`/`UnmatchedSSARecord` — meaning `school_name_raw` was **always None** for real uploads, and the fuzzy-match loop's `if r.school_name_raw:` guard never fired on real data. The feature had never actually worked. Fixed by threading these values through the same `scores`-dict pass-through mechanism already used for `_enrollment_count`.

**The fix:**
- `UnmatchedSSARecord` gained `batch` (FK), `suggested_school` (FK), `match_confidence` (float) — all computed **once, at upload time**, never per page view.
- `apps/ssa/unmatched_service.py::compute_suggested_match()` — narrows candidates by district first (when available), then ranks by PostgreSQL `pg_trgm` trigram similarity (new migration `0013_enable_pg_trgm.py` enables the extension; a GIN index on `School.name` backs it). Falls back to a bounded Python `difflib` ranking if trigram functions are ever unavailable at runtime — verified end-to-end on real data: a misspelled real school name ("Nama Hill Primarx") correctly matched "Nama Hill Primary" at 0.80 confidence.
- `apps/ssa/unmatched_service.py::get_unmatched_queue()` — real `Paginator`-based pagination + 6 filter dimensions (status, upload batch, district, suspected School ID, minimum confidence, uploaded date range).
- `python manage.py recompute_unmatched_ssa_suggestions` backfills any pre-migration rows.
- System Health: `apps/ssa/health.py` — queue size, staleness (>30 days), and suggestion-coverage checks, wired into `/system-health`.

**Tests (11 required + performance test, 17 delivered, all passing):** `apps/ssa/tests/test_unmatched_ssa_queue.py` — pagination, all 6 filters individually and combined (AND, not override), district-first candidate narrowing, trigram-similarity correctness, below-threshold/empty-name edge cases, "computed once at upload not view time" (query-count proof), view-level query-count bound, the backfill command (including idempotency), the System Health check, and a **real 10,000-school / 5,000-unmatched-record performance test** — bulk-created via `bulk_create`, read path stays at ≤5 queries and returns exactly one page (25 rows) regardless of the 5,000-row backlog, write-path candidate matching stays at ≤5 queries per suggestion.

---

## G. IA Dashboard Verification

**Investigated honestly, not assumed.** `/ia/dashboard/` (`apps/frontend/views/ia_views.py::ia_dashboard_view`) was measured directly (not estimated) against the real dev database: **57-62 queries, ~85-110ms wall time.** Every per-object loop in that 560-line view already uses `select_related`/bulk `.annotate()` aggregation or is capped to `[:5]` before iterating — **no classic N+1 was reproducible on this route, at any code-shape level.**

What *was* real: a copy-pasted block computing the same 9 queries (SSA coverage, quality average, missing-SF-ID count, etc.) twice, verbatim, with the second copy's results silently overwriting the first's — pure waste, ~5 queries, now deleted (query count dropped from ~62 measured earlier in the session to 57 measured after the fix).

The genuine, unbounded N+1 was one route over, on `/ia/verification/` (`ia_verification_queue_view`): `a.evidence.filter(quarantined=False).exists()` and `a.school.ssa_records.filter(...).exists()` inside a `for a in filtered_qs` loop, with zero pagination — likely what the original report actually meant, since this is the IA's primary day-to-day work surface. Fixed with batched evidence/SSA-existence lookups (one query each, for the current page only) plus real pagination (`QUEUE_PAGE_SIZE=50`).

**Tests (6 required, all passing):** `apps/frontend/test_ia_performance.py` — `test_ia_dashboard_query_count_is_bounded` (documents the non-reproduction with a real ceiling), `test_ia_dashboard_query_count_does_not_scale_with_data_volume` (5 vs. 60 activities, identical query count), `test_ia_verification_queue_query_count_does_not_scale_with_queue_size` (the core proof: 5 vs. 55 queued activities, identical query count — the old code would have shown +100 queries), `test_ia_verification_queue_is_paginated`, `test_ia_verification_queue_evidence_and_ssa_flags_are_correct` (regression-safety: the batched computation produces the same per-row answers as the original per-row `.exists()` calls), `test_ia_verification_queue_ignores_quarantined_evidence`.

---

## H. Tests — Summary

| Issue | Test file | Named tests required | Delivered |
|---|---|---|---|
| 1 (formula) | `apps/analytics/test_target_formula_unification.py` | 12 + 1,000-case randomized | 12 + 2×1,000 randomized |
| 2 (scheduler) | `apps/realtime/tests.py` | 12 | 10+ (`SchedulerArchitectureTests`) + gate tests |
| 3 (lockout) | `apps/accounts/test_lockout_unification.py` | 13 | 15 (13 + 2 bonus) |
| 4 (analytics N+1) | `apps/analytics/test_analytics_query_performance.py` | 8 | 8 |
| 5 (SSA unmatched) | `apps/ssa/tests/test_unmatched_ssa_queue.py` | 11 + performance | 17 (incl. 10k/5k performance test) |
| 6 (IA dashboard) | `apps/frontend/test_ia_performance.py` | 6 | 6 |

**Full suite:** 989/989 passing. Verified twice: sequentially (`manage.py test --keepdb -v 1`, ~1,295s) and via the exact CI command (`manage.py test --parallel 4` against a freshly created database, matching `.github/workflows/ci.yml` line-for-line, 349s). Zero failures, zero errors, both runs.

---

## I. Files Changed (Issues 3-6 + cross-cutting; Issues 1-2 were completed earlier in this session and are listed in the prior summary)

**Issue 3 — Auth lockout:** `config/settings/base.py`, `apps/accounts/models.py`, `apps/accounts/migrations/0015_*.py` (new), `apps/accounts/migrations/0016_*.py` (new, data migration), `apps/accounts/lockout_service.py` (new), `apps/accounts/auth_backend.py` (new), `apps/accounts/health.py` (new), `apps/accounts/management/commands/repair_legacy_lock_records.py` (new), `apps/accounts/test_lockout_unification.py` (new), `apps/frontend/views/auth_views.py`, `apps/accounts/auth_services.py`, `apps/frontend/views/extended_views.py`, `apps/core/tests/test_admin_user_operations.py`, `apps/core/test_seed_utils.py` (new), `apps/fund_requests/test_disbursement_dashboard.py`, `docs/auth-lockout-policy.md` (new), `templates/pages/system_health/index.html`, `apps/system_health/services.py`.

**Issue 4 — Analytics N+1:** `apps/targets/my_targets.py`, `apps/analytics/cd_analytics_service.py`, `apps/analytics/pl_analytics_service.py`, `apps/analytics/rvp_dashboard_service.py`, `apps/analytics/test_analytics_query_performance.py` (new), `apps/activities/models.py`, `apps/activities/migrations/0017_*.py` (new).

**Issue 5 — SSA unmatched:** `apps/schools/models.py`, `apps/schools/migrations/0012_*.py` / `0013_*.py` / `0014_*.py` (new), `apps/ssa/unmatched_service.py` (new), `apps/ssa/upload_service.py`, `apps/ssa/health.py` (new), `apps/ssa/management/commands/recompute_unmatched_ssa_suggestions.py` (new), `apps/ssa/tests/test_unmatched_ssa_queue.py` (new), `apps/frontend/views/extended_views.py`, `templates/pages/admin/unmatched_ssa_queue.html`, `apps/system_health/services.py`, `templates/pages/system_health/index.html`.

**Issue 6 — IA Dashboard:** `apps/frontend/views/ia_views.py`, `templates/pages/ia/partials/queue_table.html`, `apps/frontend/test_ia_performance.py` (new).

**Cross-cutting lint/format cleanup (repo-wide, pre-existing debt, unrelated line-numbers to the above):** 67 unused imports (F401) and 12 unused variables (F841) auto-removed via `ruff check --fix`; 1 lambda-assignment (E731) auto-rewritten; 7 ambiguous single-letter variable names (E741, all `l` in list comprehensions) manually renamed; 1 undefined-name false-positive (F821, a string type-hint referencing a locally-imported class) fixed in `apps/monthly_work_plan/services.py` by dropping the (cosmetic, never-evaluated) return type hint; 133 files reformatted via `ruff format .`. Full test suite re-verified green after this mechanical cleanup.

---

## J. Migrations

All new migrations apply cleanly, forward-only where safe, with explicit repair paths where a data migration was needed:

| Migration | Purpose | Reversible/Safe |
|---|---|---|
| `accounts/0015_user_failed_login_streak_started_at_and_more.py` | 4 new `User` fields for lockout state | Yes — additive, nullable/defaulted |
| `accounts/0016_migrate_legacy_permanent_locks.py` | Converts pre-Issue-3 100-year-lock rows to `lockout_escalated=True` | Idempotent; reverse is a deliberate no-op (un-escalating on rollback would be a security regression) |
| `activities/0017_activity_activity_respons_9b2972_idx.py` | Composite index `(responsible_staff_id, fy, activity_type)` | Yes — index-only |
| `schools/0012_unmatchedssarecord_batch_and_more.py` | `batch`/`suggested_school`/`match_confidence` FKs + 5 indexes on `UnmatchedSSARecord` | Yes — additive, nullable |
| `schools/0013_enable_pg_trgm.py` | `CREATE EXTENSION IF NOT EXISTS pg_trgm` | Yes — standard, idempotent; verified applying cleanly on this Postgres instance |
| `schools/0014_school_school_name_trgm_idx.py` | GIN trigram index on `School.name` | Yes — index-only, depends on 0013 |
| `realtime/0001_initial.py` | `ScheduledJobExecution`/`ScheduledJobLock` (Issue 2, prior session segment) | Yes |

`repair_legacy_lock_records` and `recompute_unmatched_ssa_suggestions` management commands provide `--dry-run`-able, idempotent repair paths for any row that predates its respective migration/write-time-computation change — both verified against the dev database (0 legacy lock records found; 0 unmatched-suggestion backfill needed, since dev DB currently has none).

`makemigrations --check --dry-run`: clean, no pending changes.

---

## K. Remaining Issues

**None blocking.** Two items deliberately deferred with reasoning documented in §E, both explicitly out of the 8-required-test scope for Issue 4:
- `RVPDashboardService.special_projects` — a smaller, real N+1 (project↔activity relation joined two ways) not yet batched.
- `CDAnalyticsService.cceo_snapshot` — 2 queries × CCEO count for SSA-improve deltas, not yet batched.

Both are documented, not silently dropped, and neither blocks any of the 6 issues' required deliverables or test coverage.

**A genuine, pre-existing (not introduced by this session) test-infrastructure landmine was found and fixed:** Django's `TransactionTestCase._fixture_setup()` restores `serialized_rollback=True`'s serialized snapshot **before** that test class's own body runs — not after its teardown, contrary to what the pre-existing `DisbursementDoubleClickRaceTest`'s own comment claimed. Under `--keepdb`, this meant the FIRST `--keepdb` run after a fresh DB creation would pass, but every subsequent run in the same kept database would start from a state where every table the TransactionTestCase touched had been silently flushed and never restored — corrupting migration-seeded data (`TargetArea`, `CostCatalogue`) for any test depending on it, for any developer running the suite twice in a row. Fixed by replacing `serialized_rollback=True` with an explicit `_post_teardown()` override calling a new `apps/core/test_seed_utils.py::reseed_migration_data()` helper, applied to both the pre-existing `DisbursementDoubleClickRaceTest` and this session's new `ConcurrentLockoutTest`/`UnmatchedSSAQueuePerformanceTest`. This is a repo-wide correctness fix to the test suite itself, not specific to any one of the 6 issues — flagging it here since it doesn't have a natural home in sections B-G.
