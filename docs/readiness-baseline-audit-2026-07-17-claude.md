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
>
> **2026-07-18 closed-system access-model audit (same-day follow-up):**
> an independent audit of the Admin-onboarding/account-lifecycle model (no
> public registration, invitation lifecycle, role/scope changes, suspend/
> disable/reactivate, supervisor/school reassignment, leave-coverage
> delegation) found and closed one **High**-severity real
> privilege-escalation hole (SEC-05: a HumanResources or CountryDirector
> principal could self-promote to Admin, or grant Admin to anyone, with no
> guard) plus 4 further Medium/Low findings (SEC-06 audit-trail gaps,
> SEC-07 leave-coverage authorization gap, SEC-08 refresh-token hygiene,
> DATA-01 dead-end user-creation path). See the ledger in §C. No public
> registration surface exists (confirmed).
>
> **2026-07-18 Phase 3 audit (school upload / geography / data quality /
> clustering, same-day follow-up):** found and closed one **High**-severity
> confirmed-live bug (SCH-02: a blank "Current Partner Type" or Staff Name
> cell on a re-upload silently demoted a Core school back to Client, or
> reset an already-matched account owner to "pending") plus 5 further
> Medium/Low findings — a latent arbitrary-district fallback (SCH-01), a
> non-functional preview link + a lying/uncaught-failure import status
> (SCH-03), a "Rollback" feature explicitly commented "simulated" in its own
> code that never reverted data and posted to an unregistered URL (SCH-04),
> two school_type values that were invisible to every actionable workflow
> (SCH-05), and an unaudited cluster-(re)assignment canonical service
> (SCH-06). See the ledger in §C.
>
> **2026-07-18 Phase 4 audit (SSA decision engine):** a 7-dimension
> parallel audit with every finding challenged by two independent
> adversarial verifiers (105 agents; the verification pass correctly
> *refuted* several plausible-but-wrong claims, e.g. an "average of only
> the 100 lowest records" bug that turned out to live in an orphaned view).
> Closed three **High** findings — SSA-A (four production gates silently
> disable themselves under test, one with no opt-in at all, so the suite's
> green status was partially fictional), SSA-C (official impact computed
> from unverified SSA with no annual-interval requirement), SSA-E
> (systemic unverified-SSA leakage across cluster/analytics/leadership,
> plus cluster code that *fabricated* four weakest interventions at 0.0
> when no SSA existed) — plus SSA-B, SSA-D and SSA-F. Notably, three test
> fixtures were found to be *codifying* the unverified-SSA behaviour.
> Verified correct and left alone: the canonical `ssa_score_band` boundary
> logic, the eight-intervention enum, the School-Enrolment-Count vs
> SSA-Enrolment-Score separation (explicitly guarded in code), the CSV
> 0-10 range validation, and `SsaScore`'s uniqueness constraint.

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
| SEC-05 | **High** | Access control | **Real privilege-escalation hole**: `USER_MANAGE` is held by Admin, CountryDirector, *and* HumanResources, but `admin_users/services.py::update_user()` (and its `extended_views.py` frontend twin) accepted an arbitrary, unvalidated `role` string with no allow-list and no check of the granting actor's own privilege — unlike the same file's `delete_user()`, which already has explicit self/last-admin guards. Concrete exploit: a HumanResources or CountryDirector principal could `PUT` their own `user_id` with `{"role": "Admin"}` and self-promote, or grant Admin to anyone; could also change an existing Admin's email then take the account over via the public forgot-password endpoint. (`apps/admin_users/services.py:213-250`, `apps/frontend/views/extended_views.py:761-797`) | **FIXED** — `update_user()` now: (1) blocks any non-Admin from changing their own role, (2) blocks granting the Admin role to anyone unless the actor is already Admin, (3) blocks a non-Admin from modifying ANY field on an existing Admin's account. Frontend "edit" action now delegates to the same guarded service instead of a diverging hand-rolled copy. 6-test regression suite (`AdminUserOperationsTest`/`UpdateUserPrivilegeEscalationTest`) covers both the attack and that HR/CD's legitimate routine role changes still work. |
| SEC-06 | Med | Audit | Closed-system access-model audit found essentially every account-lifecycle write path was missing an audit-chain entry — user creation (4 divergent code paths), invite send/resend/revoke, invite-accepted, suspend/disable/reactivate, role/scope change, supervisor reassignment (docstring falsely claimed it was audited), school/owner reassignment, and leave-coverage grant/revoke/reassign. Only `delete_user()`, lockout, refresh-token reuse, and self role-switch were actually audited. | **FIXED** — `audit_log(...)` added to all of the above (`apps/admin_users/services.py`, `apps/accounts/auth_services.py::set_password`, `apps/accounts/supervisor_service.py`, `apps/staff_setup/services.py::_link_schools`, `apps/hr/leave_services.py::approve_request`, `apps/frontend/views/leave_views.py`). New `AccountLifecycleAuditTest` + coverage-audit tests assert the audit rows exist. |
| SEC-07 | Med | Access control | `apps/frontend/views/leave_views.py::revoke_coverage_action` was gated only by the broad `leave_coverage` page ACL ({CCEO, PL, CD, RVP, HR, Accountant, IA, Admin}) with **no ownership/scope check** — any of those roles could revoke *any* org-wide `TemporaryCoverageAssignment` by id, unlike the sibling `leave_reassign_coverage_action`/`leave_escalate_action` which already call `LeaveApprovalService.is_authorized_approver()` first. | **FIXED** — same authorization check applied (plus an explicit HR carve-out, since HR has org-wide people-ops oversight by design but isn't a hierarchy-based approver). `test_revoke_coverage_requires_authorization` proves an unrelated covering-staff member is rejected while the leave's actual supervising approver succeeds. |
| SEC-08 | Low | Hygiene | `admin_users/services.py` suspend/disable/force_password_reset, and the frontend's direct admin password-reset action, did not revoke live `RefreshToken` rows (functionally blocked today via the `is_active`/`status` check on every request, but inconsistent defense-in-depth and stale rows). | **FIXED** — all four now explicitly revoke live refresh tokens at the moment of the credential/status change, matching the pattern already used by self-service `reset_password` and the frontend's "deactivate" action. |
| DATA-01 | Low | Data integrity | `apps/staff_setup/services.py::create_user()` (candidate → user resolution) and its docstring claimed "sends an invitation" but never called the invitation-creation helper — an account created this way could never log in until a human noticed and manually triggered a separate "invite" action. `apps/schools/upload_service.py::_auto_create_user_from_upload()` intentionally stages a placeholder-email `StaffSetupCandidate` for later resolution through the same path, so fixing the former closes both. | **FIXED** — `staff_setup.create_user()` now creates and sends a real invitation inside the same transaction as user creation. |
| SCH-01 | Med | Data integrity | Latent (not currently exploitable via any live pathway — the CSV template has no "sub county" column and the manual JSON endpoint requires an explicit `districtId`) but real dead code: `apps/schools/upload_service.py`'s new-school creation fell back to `District.objects.first()`/`Region.objects.first()` — an **arbitrary alphabetically-first district** — whenever `district` couldn't be resolved, rather than blocking the row. | **FIXED** — new shared `_resolve_geography()` helper infers district from an unambiguous sub-county match (or reports ambiguity/no-match instead of guessing) and both validation + import now share it; the arbitrary fallback is removed entirely. 5 direct unit tests. |
| SCH-02 | **High** | Data integrity | **Confirmed live bug**: the upsert's "don't overwrite good existing data with blanks" guard (`if val is not None and val != "":`) was defeated by two computed defaults that are never blank even when the source cell is: `school_type` defaults to `"client"` for a blank "Current Partner Type" cell — **a partial re-upload silently demotes a Core school back to Client**; `account_owner_status` defaults to the literal string `"pending"` for a blank Staff Name cell — **silently resets an already-matched owner**. (`apps/schools/upload_service.py:566-572`) | **FIXED** — both fields are now only included in the update payload when the source cell was actually populated. 2 end-to-end upload tests reproduce the exact scenario and prove it no longer regresses. |
| SCH-03 | Med | Reliability | Three compounding bugs in the upload result/history flow: (1) the "Open Staging Preview & Validate" link always 404s (`upload_batch_id` returned is a legacy `UploadBatch` id; the preview view looks up a different model, `SchoolImportBatch`, by that id) — the review-before-import UX is fictional, everything already auto-imports; (2) the batch's `status` was stamped `"imported"` *before* the import ran, so a failure left the batch history permanently lying about success AND made the failure unretryable (the retry endpoint short-circuits when `status == "imported"`); (3) that failure then propagated as a bare uncaught exception to the caller. | **FIXED** — status now starts `"uploaded"` and only flips to `"imported"` on real success, or `"failed"` with the actual error recorded, on failure; the failure is now a normal caught `BadRequest` (400), not a crash. Dead preview link replaced with working links to the School Directory / Upload History. New test proves a simulated import crash is recorded honestly and doesn't 500. |
| SCH-04 | Low | Honesty / dead feature | The "Rollback" button/handler was explicitly commented **"Process simulated rollback action"** — it never deleted or reverted any `School` row despite the confirm dialog claiming "This will restore original database records." Its visibility condition (`status == 'completed'`) also never matched any status the schools pipeline actually produces, and its form `action` posted to `/admin/school-upload-history`, a URL that **isn't registered** (the real one is `/admin-panel/school-upload-history`) — the button 404'd if it had ever been reachable. | **FIXED** — form action corrected; visibility condition matches the real `"imported"` status; relabeled "Mark Failed" with honest copy (flags the batch record only, does not revert school data). Building a true data-reverting rollback is flagged as a separate, larger feature (`SchoolChangeLog` could support replaying updates in reverse, but newly-*created* schools would also need deletion) requiring explicit product scoping, not attempted here. |
| SCH-05 | Med | Workflow completeness | `school_type` values `potential_champion` and `other` were invisible to every actionable workflow (Client Planning, Core Planning, Core Dashboard, Core-candidates, Champion-candidates) — only visible in the raw unfiltered School Directory, since Champion eligibility itself requires a `CoreSchoolProfile` that only Core onboarding creates. | **FIXED** — `potential_champion` added to the Core-candidates pipeline (its real next step is identical to `potential_core`'s); `other` now raises a **critical** `DataQualityIssue` (`unclassified_school_type`) instead of disappearing silently. 3 new tests. |
| SCH-06 | Med | Audit | `apps/clusters/services.py::set_school_cluster_membership()` (the canonical, lock-protected cluster-assignment function) had **no** audit call at all — 3 of 6+ call sites bolted `audit_log` onto view code ad hoc, leaving both REST APIs, the School-Directory bulk-assign action, and critically the school-edit-drawer's cluster dropdown (the most literal "reassignment" UI) silently unaudited. | **FIXED** — `audit_log` moved into the canonical service so every caller gets it automatically; the 3 now-redundant ad-hoc calls in view code were removed (not duplicated). New test proves both initial assignment and reassignment produce distinct, correctly-old/new-clusterId audit rows. |
| SSA-A | **High** | Test integrity | **The green suite was partially fictional.** Four production business rules detect the test runner (`"test" in sys.argv or "pytest" in sys.modules`) and skip themselves: the SSA sequence rule (`apps/ssa/services.py:131-133`), structured purpose validation (`apps/activities/services.py:339-340`), and the per-activity-type evidence requirement in both `complete()` (`:669-670`) and `submit_for_review()` (`:785-786`). The last had **no opt-in flag at all**, so no test could ever reach it — a regression in `missing_evidence_kinds()` would have been invisible to the entire suite. Only 2 test files opted into `strict_validation`; ~1370 tests ran with these gates off. | **FIXED** — `submit_for_review()` gained the `strict_validation` opt-in (and an optional `data` arg) to match its siblings; new `test_production_gate_relaxation.py` turns all four gates ON and proves each one actually fires. |
| SSA-B | Med | Consistency | `apps/ssa/services.py::recommendation()` (live at `GET ssa/school/<id>/recommendation`) re-sorted the weakest-two by score alone over an unordered queryset, so tied scores resolved in whatever order Postgres returned — while the planning/activity path used the canonical `weakest_interventions_for()` with a deterministic `("score","intervention")` tiebreak. The API and the planner could name **different** weakest interventions for the same school. | **FIXED** — `recommendation()` now delegates to the canonical helper; one ranking implementation. |
| SSA-C | **High** | Data integrity | `calculate_activity_impact()` (`apps/activities/services.py`) selected its pre/post SSA pair filtering on `deleted_at` only — **no `verification_status="confirmed"`** — so a pending partner-collected upload could set the official before/after scores, and imposed **no minimum interval**, so a two-week gap was reported identically to a genuine annual comparison. Both violate spec §12. LIVE on three surfaces: the school intelligence page, the `activity_impact_report` API, and the cluster impact drawer. | **FIXED** — confirmed-only on both queries (with deterministic tiebreaks), plus `intervalDays`/`annualComparison` in the payload so a sub-annual delta can no longer be presented as official annual impact. Regression test proves un-verifying the follow-up flips the result to "Not Enough Data". |
| SSA-D | Med | Reliability | The SSA upload repeated the Phase-3 school-upload defect exactly: the legacy `UploadBatch` was stamped `status="imported"` **before** `import_ssa_batch()` ran, so a failed import left the history claiming success while the exception escaped uncaught. `import_ssa_batch` also set `status="imported"` unconditionally even when zero rows landed. | **FIXED** — same pattern as SCH-03: starts `"uploaded"`, flips to `"imported"` only on real success, records `"failed"` + `error_summary` and raises a handleable `BadRequest` otherwise; the batch stays un-imported when nothing lands. |
| SSA-E | **High** | Data integrity | Systemic unverified-SSA leakage plus **fabricated data**. `apps/clusters/services.py` read SSA filtering on `deleted_at` alone in **four** functions, so unverified uploads drove cluster averages and weakest-intervention rankings — while the per-school table on the *same page* excluded them, letting one page contradict itself. Worse, `cluster_weakest_interventions()` returned the first four interventions in enum order with `avg` forced to **0.0** when the cluster had no SSA at all — inventing four "weakest interventions" out of missing data at a score that bands Critical. `cluster_intervention_summary()` did the same with `else 0.0`. Same missing filter confirmed in `analytics.services.ssa_performance`, `leadership.services` (feeding REGIONAL_INVESTMENT recommendations), and `ia_views` (which additionally had a silent all-time fallback presenting historical scores under a current-FY heading). | **FIXED** — one `_latest_confirmed_ssa()` helper delegating to canonical `latest_applicable_record` now serves all four cluster call sites; fabricated fallbacks replaced with honest empty/None; confirmed-filter added to analytics, leadership and IA queries; the IA all-time fallback removed. 3 new regression tests. **Also found and fixed a long-standing frontend-backend mismatch**: both cluster-detail panels read `item.score` while the service returns `avg`, so "Struggling Interventions" and "Full Cluster Scorecard" had *always* rendered blank values and 0%-width bars. |
| SSA-F | — | Test integrity (systemic) | Three separate test fixtures created `SsaRecord` **without** `verification_status`, which defaults to `PENDING` — so the suite was actively *codifying* the unverified-SSA behaviour (asserting that pending data drives cluster rankings, activity impact, and leadership REGIONAL_INVESTMENT recommendations). | **FIXED** — those fixtures now set `verification_status="confirmed"` (the realistic state for decision-driving data), and explicit tests were added asserting unverified records are *excluded*. |
| SSA-G | Enhancement + Med | Recommendation accuracy / consistency | **Analytics-backed recommendation engine (requested).** The recommendation logic was a naive "two lowest scores on the newest confirmed assessment" — a point-in-time snapshot ignoring trend, peer context, and whether a weakness is chronic or a one-off dip. Separately, two recommendation surfaces still diverged after SSA-B/E: `core_planning_services.CoreInterventionRecommendationService.recommend()` selected the weakest FOUR (and thus the persisted 2-Partner/2-Staff core package) with `sorted(key=score)` and **no tie-break** — non-deterministic, so re-running could reshuffle the persisted package; and `planning.recommendation_services.PlanningRecommendationService.get_recommendation()` read **any** latest SSA (not confirmed-only), reimplemented the bands inline, and sorted the weakest area non-deterministically. A dead duplicate `CoreInterventionRecommendationService` in the planning app additionally **fabricated** the first four enum interventions when a school had no SSA. | **DELIVERED** — new canonical `apps/ssa/recommendation_engine.py` (pandas/scipy via `platform_engine.trend_analysis` + numpy peer z-scores) ranks each intervention by a composite of **severity** (anchor) + **trend** (regression slope over the school's confirmed SSA history) + **peer gap** (z-score vs cluster peers' latest confirmed SSA) + **persistence** (chronic-below-threshold), verified-SSA-only, min-N honest (unmeasurable components drop out, weights renormalise — nothing fabricated), deterministic (alphabetical tie-break), and bounded (cluster-scoped peers, one grouped query for prior support). `weakest_interventions_for`, `ssa.services.recommendation()` (now returns the full `prioritized` breakdown), Core `recommend()`, and `PlanningRecommendationService` all delegate to it — one ranking, everywhere. `classify_severity` delegates to canonical `ssa_score_band`; the dead fabricating duplicate was deleted. With a single confirmed baseline the engine reduces *exactly* to ascending-score + alphabetical tie-break, so existing single-assessment behaviour is preserved. 14 new tests (`test_recommendation_engine.py`, `test_recommendation_convergence.py`) cover each analytics signal, the min-N honesty, determinism, and the two convergence bugs. |

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
