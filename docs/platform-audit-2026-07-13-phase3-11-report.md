# Edify Platform Audit — Phase 3-11 Final Report

**Date:** 2026-07-13
**Scope:** Resumes the 13-phase platform audit begun earlier in July 2026. Phase 1 (14-agent read-only inventory) and Phase 2 (fix all CRITICAL/HIGH defects) are covered by prior reports/memory (`edify-platform-audit-2026-07.md`). This report covers Phases 3-11: re-verification of Phase 2's claimed fixes, resolution of the remaining MEDIUM/LOW punch-list, an HTMX/frontend-state sweep, a performance/N+1 sweep, adversarial spot-verification, and four user-directed fixes discovered during the session.
**Method:** A 15-agent workflow (13 domain reverify-and-fix agents + 2 discovery agents) followed by 17 independent adversarial spot-verify agents, plus 4 fixes I made directly in response to specific bug reports during the session. Total: 32 workflow agents, ~3.9M tokens, ~108 minutes, 0 agent errors.

---

## A. Executive Summary

**Overall platform health:** Substantially improved. Phase 2 already closed all CRITICAL/HIGH defects from the Phase 1 inventory. This pass re-verified every one of those claims against current code (not just trusted the record) and found **all of them still correctly in place** — no regressions from Phase 2 to now. It then closed nearly the entire remaining MEDIUM/LOW backlog (32 of ~40 tracked items), ran two fresh discovery sweeps that found and fixed **2 additional CRITICAL-severity bugs** the original Phase 1 inventory missed entirely (a double-click duplicate-activity bug and a severe N+1/unbounded-query pattern hitting 4 high-traffic pages), and closed 4 more defects the user found and reported directly mid-session.

**Critical risks found this phase:** 2 (both CRITICAL, both fixed — see §E).
**Critical risks fixed:** 2/2, plus all of Phase 1's original 2 CRITICAL + 23 HIGH items reconfirmed intact.
**Remaining risks:** 1 confirmed-partial fix (a 4th divergent "team target %" implementation in `cd_analytics_service.py`, found by adversarial verification, not yet fixed — see §N), 2 deliberately-deferred policy questions (login lockout behavior, background-job scheduling), a handful of lower-priority items explicitly marked `skipped_out_of_scope` by domain agents (see §N).
**Readiness assessment:** Full test suite green (915/915, 0 failures) against a freshly created database. No migrations pending. No conflict markers or corrupted state remain in the working tree (see §M for a process-integrity incident that occurred mid-session, fully recovered).

---

## B. Architecture and Workflow Map

13 domains covered, matching the Phase 1 feature-to-code map: Schools/Clusters/Geography, Planning/My Plan, Core Schools/Special Projects, Activities/Evidence/IA/Route Intelligence, Cost Catalogue/Fund Requests/Budget, Targets/Analytics, Field Debrief/Messaging/Notifications/To-Do, HR/Professional Development, Leave/Temporary Coverage, Partners/RVP, Core Permissions/Security/Admin, Accounts/Auth/Shell, Background Jobs/Scheduling — plus 2 cross-cutting discovery passes (HTMX/frontend state, performance/N+1).

**Feature handoffs touched this phase:** School Directory → Data Quality Center (now has real resolve/assign actions), Planning → Partner Assignment (row-level scoping fixed), Core School onboarding → SSA gate (self-heal path hardened), Activity scheduling → duplicate-submission guard (new), Field Debrief → Notifications/To-Do (deep-links and coverage fixed), Leave request → balance/attachment validation (delegated to canonical service, closing a parallel-endpoint bypass).

---

## C-D. Data-Fetching and Database-Persistence Audit

**Pages/services audited:** all 13 domains' primary views + 2 dedicated sweeps.

**Incorrect querysets / scope leaks found and fixed:**
- `/partners` and `/partners/<id>` had no row-level scoping (`ALL_ROLES`) — a partner-org login could browse any other partner's detail page through the browser route the REST API already refused. **Fixed.**
- `Partner.update()` had no ownership/scope check. **Fixed.**
- `TemporaryCoverageAssignment` display surfaces (3 of them) filtered only on `status="active"` with no datetime-window check, showing expired coverage as active indefinitely. **Fixed.**

**N+1 queries and unbounded querysets found and fixed (performance discovery sweep):**
| Page | Issue | Severity | Status |
|---|---|---|---|
| `/staff` (staff_directory_view) | Unbounded queryset + N+1 | CRITICAL | Fixed |
| `TeamAvailabilityService.get_4week_heatmap()` (feeds leave tracker, PTO page, leave approvals) | Nested N+1 | CRITICAL | Fixed |
| `/leave/tracker` (HR/PL/CD/RVP/Admin) | Unbounded queryset + severe N+1 | CRITICAL | Fixed |
| `/schools` (`SchoolDirectoryViewModel.from_school`) | N+1 per row | HIGH | Fixed |
| `/core-schools/champions` | N+1 + missing `select_related` | MEDIUM | Fixed |
| IA analytics dashboard (774-line view) | — | LOW | Could not reproduce as described |
| CD/PL/RVP analytics dashboard services | Per-entity loops | MEDIUM | Flagged, not fixed (out of scope for this pass — logged, not silently dropped) |
| `/ssa/unmatched` fuzzy-match loop | Unbounded + N+1 | MEDIUM | Flagged, not fixed |

**Buttons/forms/persistence audited:** Data Quality Center resolve/assign actions (new, previously entirely read-only), scheduling-form param mismatches (trainings/visits pages linked with the wrong GET param names — fixed), salesforce_id_action (was skipping format validation + IA-confirmation lock — fixed).

**Duplicate-write risks found and fixed:**
- **CRITICAL — double-click on "Schedule Activity" created two identical, fully-costed Activity rows.** `apps.daily_visit_batches.services.schedule_visits()` already had a guard; three other direct callers of `apps.activities.services.create()` (cluster training/meeting scheduling, partner/project-scoped scheduling) did not. Fixed with a duplicate-submission guard in `create()` itself (see below) plus a separate HTMX-layer fix for the same symptom on the Schedule Activity drawer.
- **HIGH — Disburse Funds double-click race could write duplicate `Disbursement` audit rows.** Fixed.
- **HIGH — `apps.hr.services.request_leave` bypassed the canonical `LeaveRequestService`,** writing an unvalidated `Leave` row directly — skipping balance-sufficiency checks and the `requires_attachment` server-side check entirely. Fixed by delegating to the canonical service (user-reported, fixed directly).

---

## E. Workflow Handoff Audit (selected — full detail in workflow journal)

| Source → Destination | Defect | Fix | Verification |
|---|---|---|---|
| School Directory → Data Quality Center | Six issue-type querysets computed but never rendered; no resolve/assign action existed at all | New issue-row partials + `data_quality_issue_action_view`, atomic write + audit log + HTMX row-swap | `DataQualityCenterActionTests` (3 tests) |
| Planning → Schedule Activity (any create() caller) | Double-click created duplicate fully-costed Activities | Duplicate-submission guard in `activities.services.create()`, matched on type+school/cluster+date+staff/partner+planned week/month | `test_double_submit_identical_activity_is_rejected` + 2 more, plus full-suite regression run |
| Core School promotion → Self-heal onboarding | Auto-onboard created CorePlan+slots with no SSA gate and no audit trail | SSA-record gate added (mirrors the official `onboard()` path) | Domain fix + spot-verify CONFIRMED_FIXED |
| Field Debrief action → Notification | 6 event types deep-linked to generic `/dashboard`, not the debrief | `NotificationLinkResolver` branches added | Spot-verify CONFIRMED_FIXED |
| Leave request (DRF endpoint) → Balance/Attachment validation | Parallel endpoint bypassed `LeaveRequestService` entirely | Delegated to canonical service; attachment threaded through | 3 new tests, 18/18 `apps.hr` passing |
| Evidence upload (attendance/SSA forms) → `EvidenceKind` | `kind="attendance_sheet"`/`"ssa_form"` — not real enum members, upload always failed | Corrected to real enum values (`attendance_form`/`assessment_form`) | 2 new tests, 17/17 passing |
| Command Center dashboard → KPI strip | 5 separate hardcoded/fabricated values (`target_achievement` fallback, `operational_health`, 3 fabricated trend badges, hardcoded "8/10" and "78%") | All replaced with real queries or honest zero/empty states; PL card now delegates to the canonical `PLAnalyticsService._team_target()` | 6 new tests |

---

## F. Calculation Audit

**Confirmed fixed this phase:**
- `core_2nd_visit_pending`/`core_2nd_training_pending`: was `max(0, first_round_pending - 15/20)` — a fabricated offset. Now a real `CoreActivitySlot` query.
- PL "Team Target Achievement %" label collision: three textually-identical hand-rolled weighted-% implementations (`my_targets.py`, `team_targets.py` ×2) consolidated into one `weighted_period_pct()` helper; PL Analytics/Command Center relabeled to "Team Execution Progress %" (a deliberately different, non-IA-verified execution metric) so the same label never means two different numbers in one session.
- `analytics_dashboard_service.py`'s fabricated target denominator (achieved-count-as-target, reading as near-100% by construction) — confirmed already fixed in Phase 2.
- Command Center `operational_health` (hardcoded 93) → real composite of school-readiness and this-month completion rate.
- Command Center `target_achievement` fallback (hardcoded 72) → honest 0.

**Confirmed NOT fully fixed (see §N):** a 4th independent "team target %" reimplementation in `apps/analytics/cd_analytics_service.py` (`_weighted_achievement`/`target_by_pl_cceo`) uses a different annual-target proration algorithm than the canonical `weighted_period_pct()` — verified to disagree in 66/100 tested (annual_target, quarter) combinations. This feeds the CD's "Target Achievement by PL & CCEO" table and can show a PL a different number than their own Team Targets page for the same quarter — the exact defect this item's title named, not fully closed.

---

## G. Role and Security Audit

- Fixed: `get_scoped_object_or_404`'s `PermissionDenied` was rendered as raw JSON by the global exception middleware on plain server-rendered pages — now matches `require_page_permission`'s established denial contract.
- Fixed: `PAGE_PERMISSIONS` self-contradictions (`users` excluded HR despite HR holding `USER_MANAGE`; `upload_history` excluded the role that generates it; `quality_checks` was unreachable by the roles who need it).
- Fixed: audit log's `verify_chain()` (hash-chain tamper detection) was never called anywhere — wired into a real call site.
- Fixed: `leave_coverage` page permission excluded ImpactAssessment despite the eligibility engine explicitly supporting IA-to-IA coverage.
- Confirmed already fixed (Phase 2, reverified): the HR self-approval security hole in `apps/hr/services.py::review_leave`, holiday-exclusion consistency, 4 broken Partner Portal pages, the partner-identity resolution bug in field debrief linking.

---

## H. Finance Audit

- Fixed: dead `/accounts/reimbursements/` queue (zero callers ever created a `ReimbursementClaim`) — permanently-empty sidebar link removed/wired.
- Fixed: Advances tab of batch-payments filtered on an invalid `PaymentStatus` value.
- Fixed: three independent "current budget status" KPI computations (disbursement dashboard, accountant dashboard, budget rollup trio) consolidated to share one helper.
- Confirmed already fixed (Phase 2, reverified in full): `AdvanceDisbursementService.disburse_advance()` confirmation gate, CD→RVP country-scope guard, and `transaction.atomic()` coverage on all 5 previously-flagged multi-write financial sequences (`apply_to_activity`, `create()`, `reschedule()`, `_ensure_fund_request()`, `disbursement_dashboard_service.disburse()`).

---

## I. Target and Analytics Audit

Covered above in §F/§N. Core Schools completion tracking (the Phase 2 CRITICAL headline fix) was re-verified end-to-end this phase and confirmed still fully intact.

---

## J. Performance Audit

No systematic before/after query-count instrumentation was run platform-wide (out of scope for this pass's time budget), but every fix in the performance sweep (§C-D table above) was verified by the fixing agent with `assertNumQueries`/`CaptureQueriesContext`-based regression tests proving the query count is now bounded and independent of row count — these tests are part of the 915-test suite.

---

## K. Test Results

- **Domain/discovery fix agents:** each added or updated tests as part of its own fix (see workflow journal for the full per-item test names — dozens of new/updated test methods across `apps/frontend/tests.py`, `apps/core/tests/*`, `apps/hr/tests.py`, `apps/analytics/test_pl_analytics.py`, `apps/targets/test_weighted_period_pct.py` (new file), `apps/partners/tests.py` (new file), `apps/realtime/tests.py` (new file), and more).
- **My own direct fixes:** 6 new test methods across `apps/command_center/tests.py` (new file), `apps/frontend/test_evidence_upload_kind_fix.py` (new file), `apps/hr/tests.py`, `apps/activities/test_atomic_writes.py`.
- **Adversarial spot-verification:** 17 independent agents, each re-reading actual current code (not summaries) and re-running the claimed tests. **16/17 CONFIRMED_FIXED cleanly; 1/17 CONFIRMED_FIXED for its claimed scope but flagged a real, unaddressed 4th sub-case** (see §N).
- **Full suite, final run, fresh database:** **915/915 tests passing, 0 failures.** Confirmed on a second independent fresh-database run for good measure. (`python manage.py check` and `makemigrations --check --dry-run` both clean.)

Three issues surfaced and were fixed during this final verification pass:
1. My duplicate-submission guard's match window was initially too broad (missing `planned_week`/`planned_month`), which broke a legitimate existing test that intentionally books two different-period visits on the same calendar date. Fixed by adding those two fields to the match — safe because the real scheduling UI derives `plannedWeek` deterministically from the date, so a genuine double-click still matches exactly.
2. My SSA-gate test fixture (added to make an existing Core School test compatible with a newly-added self-heal SSA gate) initially made a *different* assertion in the same test — "IA verification fails without an SSA baseline" — impossible to reach, since it reused the same permanent record. Fixed by scoping the fixture SSA record locally and soft-deleting it immediately after the onboarding step it was needed for.
3. **Pre-existing, unrelated to this session's work:** `apps/my_plan/tests.py::MyPlanOwnerNameDisplayTest` used `timezone.now().date()` (UTC) to build its "today" fixture, while the production code it's testing (`get_frontend_context`) correctly uses `date.today()` (server-local, `Africa/Kampala`/EAT). These only disagree on the calendar date during the 21:00–24:00 UTC / 00:00–03:00 EAT window — which this verification pass happened to run through — silently failing the suite for 3 hours every night regardless of any code change. Fixed by switching the test to `timezone.localdate()`.

---

## L. Files Changed

69 files touched this phase (62 modified, 7 new). Full list via `git status --short`; grouped by area:

- **Schools/Data Quality:** `apps/frontend/views/extended_views.py`, `apps/frontend/urls.py`, `templates/pages/admin/data_quality_center.html`, `templates/partials/data_quality/` (new)
- **Activities/Evidence/IA:** `apps/activities/services.py`, `apps/activities/test_atomic_writes.py`, `apps/evidence/services.py`, `apps/frontend/views/{closure_views,my_plan_views,staff_views}.py`, `apps/frontend/test_activities_evidence_ia_routes_fixes.py` (new), `apps/frontend/test_evidence_upload_kind_fix.py` (new)
- **My Plan (test-only, pre-existing date-boundary flake, unrelated to any fix above):** `apps/my_plan/tests.py`
- **Core Schools:** `apps/core_schools/{champion_services,core_planning_services}.py`, `apps/core_schools/test_core_planning.py`, `apps/core/tests/{test_champion_proposal_engine,test_core_school_workflow}.py`, `apps/frontend/views/core_schools_views.py`
- **Planning/My Plan:** `apps/planning/{planning_service,tests}.py`, `templates/pages/{trainings,visits}/index.html`, `templates/partials/clusters/cluster_schools_table.html`
- **Cost/Fund/Budget:** `apps/fund_requests/disbursement_dashboard_service.py`, `apps/fund_requests/test_{disbursement_dashboard,finance_operating}.py`, `apps/frontend/views/finance_operating_views.py`
- **Targets/Analytics:** `apps/analytics/{pl_analytics_service,pl_dashboard_service,test_pl_analytics}.py`, `apps/targets/{my_targets,team_targets}.py`, `apps/targets/test_weighted_period_pct.py` (new)
- **Field Debrief/Notifications/Command Center:** `apps/debriefs/{dashboard_service,tests}.py`, `apps/frontend/views/debrief_views.py`, `apps/command_center/{dashboard_service,todo_service,tests}.py` (tests.py new), `templates/pages/debriefs/detail.html`, `templates/partials/debriefs/dashboard_body.html`
- **HR/PD/Staff:** `apps/accounts/hr_dashboard_service.py`, `apps/hr/{leave_services,services,tests,views}.py`, `apps/frontend/views/staff_views.py`, `templates/pages/staff/index.html`
- **Partners:** `apps/partners/services.py`, `apps/partners/tests.py` (new), `apps/frontend/views/partner_views.py`
- **Permissions/Security/Admin:** `apps/core/{middleware,navigation,permissions}.py`, `apps/core/tests/test_role_gating.py`, `apps/system_health/services.py`, `templates/pages/{quality_checks/index,system_health/index}.html`
- **Accounts/Shell:** `apps/frontend/views/{dashboard_views,school_views}.py`, `templates/pages/dashboards/main.html`
- **Background Jobs:** `apps/realtime/tests.py` (new — documents the systemic finding, no production code change per the deliberate scope decision)
- **Analytics dashboard:** `templates/pages/ia/analytics_dashboard.html`
- **Docs:** `docs/railway-deployment.md`

---

## M. Migrations and Data Repairs

**No new migrations this phase.** All fixes were code/template-level; `makemigrations --check --dry-run` confirmed clean throughout.

**Process-integrity incident (not a data repair, but must be disclosed):** mid-session, while this workflow's agents were actively running with shared (non-isolated) filesystem and git access on the same working tree I was using, two unplanned git operations occurred that I did not initiate:
1. A `git commit` I made for the Phase 2 checkpoint inadvertently became a merge commit incorporating an already-GitHub-merged prior PR (`#5`, "ui-design-audit") that the local clone was 4 days out of sync with. No conflicts, content tested clean before commit.
2. A `git stash` (almost certainly run by one of the workflow's subagents) dangled several of my in-progress fixes without popping them back. **Recovered in full** via the dangling stash commit (confirmed via `git fsck`); all recovered code was reverified by test run before continuing. No data was permanently lost, but this is a real risk of running multi-agent workflows with unrestricted git access on a shared, non-isolated working tree — worth using `isolation: 'worktree'` for future runs of this kind, or explicitly instructing agents never to run `git stash`/`git pull`/`git merge`.

---

## N. Remaining Issues

Nothing below is hidden or silently dropped — each was explicitly flagged by the agent that found it.

| Issue | Impact | Reason not completed | Recommended next step | Priority |
|---|---|---|---|---|
| `cd_analytics_service.py`'s `_weighted_achievement`/`target_by_pl_cceo` is a 4th independent "team target %" formula, verified to disagree with the canonical one in 66/100 tested cases | A CD can see a different "team %" for a PL than that PL sees on their own Team Targets page, for the same quarter | Out of the fix's original investigation scope; found only by adversarial spot-verification, not yet fixed | Point `target_by_pl_cceo`'s per-PL proration at the same `weighted_period_pct()` helper the other 3 call sites now share | HIGH |
| `ENABLE_BACKGROUND_JOBS=False` everywhere — 4 apscheduler jobs + 2 cron-only management commands never run automatically in this deployment | Targets ledger staleness, PD reminders, Field Debrief recurring-issue detection all silent unless someone runs a command by hand | Requires an infrastructure/ops decision (does a worker process exist in this deployment?), not a code fix — deliberately not decided unilaterally | Human/ops decision: provision a scheduler-capable process, or accept manual-trigger as the operating model and document it | HIGH (systemic) |
| `AUTH_MAX_FAILED_LOGINS` / login lockout: two auth systems with different lockout behavior (permanent-admin-gated vs. 15-min self-expiring) | Latent inconsistency, invisible until the underlying setting changes | Deliberately left open for the human product owner since Phase 2 — a prior agent attempt to unify it was blocked | Product owner decides the intended policy, then implement | Open policy question, not a defect |
| CD/PL/RVP analytics dashboard services (`apps/analytics/*.py`) — per-entity-loop N+1 patterns in region/district ranking | Slower page loads at scale, not a correctness bug | Flagged by the performance sweep but not fixed — broader scope than the pass's time budget | Apply the same `select_related`/`annotate` treatment used elsewhere this phase | MEDIUM |
| `/ssa/unmatched` unbounded queryset + N+1 fuzzy-match loop | Slower page loads at scale | Same as above | Add pagination + query consolidation | MEDIUM |
| `ia_dashboard_view` performance | Could not reproduce the described N+1 as stated | — | Re-scope and re-investigate if a specific slow-page report comes in | LOW |

---

## Appendix: Session-reported bugs fixed directly (outside the workflow)

Four defects were reported by the user mid-session and fixed directly, each cross-checked against the concurrently-running workflow to avoid collisions:

1. **Evidence upload kind mismatch** — `kind="attendance_sheet"`/`"ssa_form"` were not real `EvidenceKind` enum members; both upload flows always failed. Fixed + 2 tests.
2. **Command Center dashboard fabricated values** — 5 separate hardcoded/fabricated numbers (target_achievement fallback, operational_health, 3 fake trend badges, hardcoded "8/10" and "78%"). Fixed + 6 tests.
3. **HR leave-request endpoint bypass** — `apps/hr/services.py::request_leave` wrote directly to the `Leave` model, skipping balance and attachment validation the canonical service enforces. Fixed + 3 tests.
4. **`create()` duplicate-submission guard** — added, then corrected once real-world testing surfaced a too-broad match window; final version verified via the full 915-test suite.

All four were independently discovered again by the concurrent workflow's own agents and correctly marked `already_fixed_confirmed` where relevant, confirming no conflict or duplicate work.
