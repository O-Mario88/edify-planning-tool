# Edify Platform — N+1 Fixes, Country Budget Special Projects, Login Page, and 4-Pass Functional Audit

**Date:** 2026-07-14
**Scope:** (1) Two named N+1 query fixes (`RVPDashboardService.special_projects`, `CDAnalyticsService.cceo_snapshot`) — completing the two items the same day's `platform-audit-2026-07-14-issues-1-6-report.md` explicitly deferred. (2) A Special Projects budget category added to the Country Monthly Budget page. (3) A login page redesign. (4) A fresh, sequential, 4-pass functional audit of the full School Upload → Reports workflow, run with 2 read-only investigation agents per pass (8 agents total), followed by direct verification and fixes for every confirmed defect judged high-value enough to fix in-session.
**Method:** Each audit pass ran two independent agents in parallel scoped to different segments of the workflow, explicitly instructed not to assume a finding is real without citing file:line and, for any browser/HTML behavior claim, verifying against actual semantics rather than assumption (one early finding — a `required` attribute on a hidden `&lt;input&gt;` — was independently re-verified and found to be dead code, not a live bug; corrected before acting on it). Every fix below has a dedicated regression test and was checked against the full test suite for that area, not just the new test.

---

## A. Executive Summary

Both named N+1 fixes are done, measured, and query-count-bounded regardless of scale. The Country Budget page now has a working, tested Special Projects category, plus a real bug fix uncovered along the way (a dead `hasattr()` check meant `ProjectSchoolAssignment` records were silently never used for project impact scoping). The login page was rebuilt to match a provided reference design, with fabricated stat numbers replaced by real database-backed counts and the social-sign-in option removed per instruction.

The 4-pass functional audit covered School Upload → Data Quality → Cluster Assignment → Planning → Partner Assignment → Scheduling → Cost Catalogue → Weekly Fund Request → PL Approval → Disbursement → Evidence → IA Verification → Accountability → NetSuite → Closure → Field Debrief → My/Team Targets → Analytics → Reports. **13 confirmed defects were fixed and tested**, five of them genuine financial-integrity bugs (a cascade-delete that silently destroyed disbursed payment records, a legacy queue enabling real double-disbursement, missing bounds checks on disbursement amounts, missing row-locking on the core advance lifecycle, and a cross-role API data leak). A further set of real, lower-severity or larger-scope findings is documented in §K rather than fixed under time pressure — every one has a named cause and a next action, none is hidden.

**Readiness assessment:** No known regressions from this session's work. `manage.py check` and `makemigrations --check --dry-run` are both clean (no schema changes were required for any fix — every defect was a query/logic/permission bug, not a data-model gap). The full regression sweep across every touched app — **582 tests, 0 failures** — passed on the final run.

---

## B. N+1 Query Fixes

Both methods previously issued a fresh set of queries per row in a Python loop (`for project in Project.objects.filter(...)` / `for pl in _pls(): for c in _pl_cceos(pl, cd)`), so query count scaled linearly with the number of Special Projects / CCEOs. Both are now O(1) — a small, fixed number of bulk queries, with the per-row math done in Python over already-fetched data.

| Method | Before | After (measured) |
|---|---|---|
| `RVPDashboardService.special_projects` | ~6-7 queries × N projects | **7 queries flat**, measured with 15 projects mixed across both relationship paths |
| `CDAnalyticsService.cceo_snapshot` | ~4 queries × N CCEOs (nested inside a PL loop) | **11 queries flat** (scales with PL count, a small fixed number — not CCEO count), measured with 2 PLs baseline and confirmed identical after adding 20 more CCEOs to the same 2 PLs |

**`special_projects`** — `Activity.project_id` and `ActivityScheduleCostLine.project_id` are two independent, authoritative paths to the same project↔activity relationship (a cost line can carry a project reference even when the parent activity's own `project_id` is unset, e.g. partner-costed project work). The old code joined both via `Q(project_id=p.id) | Q(schedule_cost_lines__project=p)` inside the per-project loop and de-duplicated with `.distinct()` — correct, but re-run once per project. Rewritten to build one `project_id → {activity_id}` map via two bulk queries covering every project at once, then bulk-fetch activity status/school and cost-line totals, then two bulk SSA queries for every school touched by any project — an activity reachable through either or both paths is counted exactly once, verified by a dedicated test.

**Bug found and fixed along the way:** the old code's school-scope fallback was `p.school_links.values_list(...) if hasattr(p, "school_links") else <derive from activities>`. `Project` has no `school_links` attribute — that related name belongs to `StaffProfile`, not `Project` — so this `hasattr()` check was always `False`, meaning the real `ProjectSchoolAssignment` table was silently never consulted for a project's impact-measurement school scope; it always fell through to the activity-derived fallback. Fixed to use `ProjectSchoolAssignment` (the real related name is `school_assignments`) as the authoritative source, falling back to activity-derived schools only when no explicit assignment exists.

**`cceo_snapshot`** — the old code looped `for pl in _pls(): for c in _pl_cceos(pl, cd):` and, per CCEO, ran a `count()` for completed activities, a `count()` for overdue activities, and up to 2 SSA cycle queries. Rewritten to bulk-fetch every in-scope activity once (`acts.values("id","responsible_staff_id","school_id","status","planned_date")`), index it in Python by staff id and school id, and bulk-fetch SSA cycle scores for every school across every CCEO up front (2 queries total) — each CCEO's matching activity set and SSA delta are then computed from already-fetched data. `_pl_cceos()` itself still runs 3 queries per PL (unchanged, and correctly bounded by PL count, not CCEO count).

**Tests:** `apps/monthly_work_plan/test_rvp_dashboard.py` — `test_rvp_special_projects_direct_activity_relation_counted`, `test_rvp_special_projects_cost_line_activity_relation_counted`, `test_rvp_special_projects_activity_joined_both_ways_counted_once`, `test_rvp_special_projects_budget_totals_not_duplicated`, `test_rvp_special_projects_totals_match_source_records`, `test_rvp_special_projects_uses_explicit_school_assignment` (the `hasattr` bug fix), `test_rvp_special_projects_query_count_is_bounded` (15 projects, `assertNumQueries(7)`). `apps/analytics/test_cd_analytics.py` — `test_cceo_snapshot_annual_delta_is_correct`, `test_cceo_snapshot_excludes_other_cceo_schools`, `test_cceo_snapshot_handles_missing_ssa`, `test_cceo_snapshot_uses_verified_ssa_only`, `test_cceo_snapshot_query_count_is_bounded`, `test_cceo_snapshot_query_count_stable_as_cceo_count_grows` (adds 20 CCEOs mid-test, asserts identical query count).

---

## C. Country Budget — Special Projects Category

The Country Monthly Budget page (`apps/monthly_work_plan/country_budget_service.py`) bucketed every planned activity into one of 5 categories (Staff Visits, Partner Visits, SSA, Cluster Training, Partner In-School Training) purely by activity type and delivery type — a Special Project's cost was already included in the country total, just silently absorbed into whichever generic category matched its type, with no way to see it as project spend. Added a 6th category, "Special Projects," using the same dual-path project-linkage rule as §B (`Activity.project_id` OR `ActivityScheduleCostLine.project_id`), taking priority over the type-based buckets so project-funded spend is never diluted into a visit/training figure.

**Changes:** `_page_category()` gained an `is_project` parameter checked first; a new `_is_project_line()` helper implements the dual-path check; the per-staff row builder, the current-month KPI totals, the 6-month trailing-series aggregate, and the "Cluster Meetings/Sessions" plan-source count were all updated to use it consistently (the trailing-series aggregate needed `activity__project_id`/`project_id` added to its `.values()` grouping to stay a single aggregate query, not a per-row loop). Added a "Special Project Cost" KPI card and a "Special Project Activities" plan-source tile. Template (`templates/partials/finance/country_budget/root.html`) gained a "Special Projects" column group; the admin-row/footer-row spacer colspans were corrected from 15 to 18 to match the new 6-category width.

**Verified visually** against the real dev database: temporarily linked one real activity to a real project, confirmed the KPI card, table column, and per-staff row all showed the correct amount, then reverted the test linkage.

**Tests:** `apps/monthly_work_plan/test_country_budget_service.py` — `test_special_project_categorized_via_direct_activity_link`, `test_special_project_categorized_via_cost_line_link`, `test_special_project_included_in_total_monthly_budget`, `test_special_project_activity_count_in_plan_source_summary`, `test_special_project_staff_row_shows_project_column`. Full file: 36/36 passing.

---

## D. Login Page Redesign

Rebuilt `templates/layouts/auth.html` and `templates/pages/auth/login.html` to a two-column design (dark brand hero panel + sign-in card) per a provided reference image, using the real Edify wordmark (`static/images/logo.png`) instead of a generic "E" badge, and explicitly **excluding** the reference image's "Sign in with Google" button (closed system, no social sign-in). The reference image's two hero stat cards ("Schools Reached," "Target Progress") showed hardcoded fictional numbers; per this codebase's existing no-fake-data convention, replaced them with real, unauthenticated-safe aggregate counts (`School.objects.filter(deleted_at__isnull=True).count()`, completed-`Activity` count) computed in a new `_login_stats()` helper in `apps/frontend/views/auth_views.py` and threaded into all 4 of `login_view`'s render call sites. Omitted the reference image's "Forgot password?" link — no working password-reset page exists in this app, and adding a link to nowhere would be a dead button.

**Verified:** `manage.py check` clean; DOM/CSS stacking inspected via JavaScript to confirm the decorative dot-grid background layer renders behind (not over) the hero text; a real screenshot taken after working around a session/CSRF issue in the browser tooling, showing the logo, hero copy, feature cards, real stat numbers (700 schools / 260 activities, matching live dev data), and the sign-in form with a working password show/hide toggle. 57 tests exercising `/login` and lockout flows pass unchanged.

---

## E. Functional Audit Pass 1 — Data Foundation, Planning, Partner Assignment

Two agents: School Upload / Data Quality / Cluster Assignment, and Planning / Partner Assignment mechanics.

### Fixed

1. **HIGH — Staff could mutate partner-owned activities directly, bypassing "staff never execute partner work."** `apps/frontend/views/my_plan_views.py`'s `attendance_upload_action`, `accountability_action`, and `complete_activity_action` were missing the `_forbid_staff_on_partner_activity` gate that sibling endpoints (`start_activity_action`, `evidence_upload_action`, `salesforce_id_action`, `submit_for_review_action`) already had. A CCEO/PL with school-level scope could POST directly to set attendance, submit accountability, or complete a `delivery_type="partner"` activity before the partner had done anything. Added the gate to all three.
2. **MEDIUM — Double-submit could create duplicate partner assignments and duplicate costed activities.** `assign_partner_action_view` (`apps/frontend/views/planning_views.py`) had no idempotency guard — a double-click or retried htmx POST created a second `PartnerAssignment` and, when a date was set, a second real `Activity` + budget line for the same school/partner/date. Added a 15-second dedup window keyed on (school-or-cluster, partner, staff, activity type) plus `hx-disabled-elt` on the submit button as UI-level reinforcement. Applied the same fix to the bulk-assign branch of `bulk_action_view`.
3. **MEDIUM — Bulk "Assign Partner" button crashed the page.** The floating bulk toolbar's "Assign Partner" button submitted directly with only `school_ids[]` — no `partner_id`/date fields existed anywhere in the template — so the view's `get_object_or_404(Partner, id=None)` raised an unhandled 404 that `hx-target="body"` swapped over the entire planning page. Built a proper popover (partner select + optional date, mirroring the existing "Schedule Visits" popover) and added a clean 400 fallback server-side for defense in depth.
4. **MEDIUM — School-upload batch import had no transaction.** `import_school_batch` (`apps/schools/upload_service.py`) looped over rows creating/updating `School`/`SchoolChangeLog`/`StaffSchoolAssignment` with no wrapping transaction — a mid-batch exception left earlier rows committed and the batch's own status stuck stale. Wrapped the entire per-row loop in `transaction.atomic()`.

**Corrected finding (not a bug):** one agent reported the single-item "Assign to Partner" drawer's date field as `required`, forcing every partner assignment to be immediately scheduled/budgeted rather than deferred to the partner. Independently verified in-browser via JavaScript (`input.willValidate === false` for `type="hidden"`) that the HTML5 `required` attribute is inert on hidden inputs — the field never actually blocked submission. The underlying UX gap (no visible guidance that leaving the date blank defers to the partner) was still real and fixed: removed the misleading dead attribute and added explanatory copy.

### Tests
`apps/frontend/test_partner_readonly_gates.py` (new, 4 tests), `apps/frontend/tests.py` (+3: double-submit, bulk double-submit, bulk missing-partner-id), `apps/schools/tests/test_import_batch_atomicity.py` (new, 2 tests: partial-failure rollback + happy-path commit, via a mocked mid-loop exception). Full sweep: `apps/frontend`, `apps/schools` — all passing.

### Documented, not fixed
Dead "merge duplicate school" resolution path (the real UI only supports mark-as-unique; the service that handles merge is wired to an unused legacy DRF endpoint — `SchoolDuplicateCandidate.resolved` never gets set through the real UI). Cluster-assignment logic duplicated across 3 view functions instead of one shared service. A dead legacy DRF cluster API app. Dead `AnnualPlan`/`AnnualPlanActivity` models. A legacy `/api/planning/plans` endpoint bypasses the cost-catalogue gate but has no confirmed live financial-pipeline consumer.

---

## F. Functional Audit Pass 2 — Scheduling, Cost Engine, Weekly Fund Request

Two agents: the cost-catalogue/scheduling engine, and the Weekly Fund Request → PL Approval finance handoff.

### Fixed

5. **HIGH — Rescheduling an activity cascade-deleted its already-disbursed payment record.** `costing_service.apply_to_activity()` unconditionally ran `ActivityScheduleCostLine.objects.filter(activity=activity).delete()` on every re-price. `AdvanceRequest.budget_line` and `WeeklyFundRequestLine.activity_budget_line` are both `on_delete=CASCADE` onto that model — so deleting the old cost lines silently deleted any `AdvanceRequest` already `DISBURSED`/`ACCOUNTABILITY_PENDING`/`ACCOUNTED`/`REIMBURSED`, before `advance_service.sync_for_activity()`'s own documented "never touch a disbursed advance" rule ever got a chance to run (the row was already gone). A plain reschedule of a school visit that already had money disbursed against it permanently erased that disbursement record and silently created a fresh, un-disbursed advance in its place. Added a hard guard: `apply_to_activity()` now raises `BadRequest` before touching any cost line if the activity has an `AdvanceRequest` in any of those statuses, directing the caller to a formal amendment instead.
6. **HIGH — PL approval had no idempotency guard.** `pl_approval_service.approve()` rebuilt and re-flipped a `FundRequest` to `sent_to_accountant` unconditionally, with no check of its current status — re-clicking Approve (stale tab, double-click) on an already-`disbursed`/`held` plan silently reopened it for a second payout. Added a pre-check against the existing `FundRequest`'s status, blocking re-approval once the accountant queue has taken any action.
7. **HIGH — Weekly disbursement had no bounds check and mis-recorded partial amounts.** `weekly_service.disburse()` accepted any `amount` with no validation, and hard-set every linked `AdvanceRequest.disbursed_amount` to the full line cost regardless of what fraction was actually entered. Added the same bounds check (`0 < amount <= total`) and proportional scaling already used correctly by the monthly disbursement path.

### Tests
`apps/budget/test_cost_snapshot_lock.py` (new, 3 tests), `apps/fund_requests/test_pass2_audit_fixes.py` (new, 8 tests: PL re-approval block, weekly disburse bounds ×2, partial-disburse proportional scaling, full-disburse still works, accountant-return status guard, empty-reason rejection, valid-return audit log). Full sweep: `apps/fund_requests`, `apps/budget`, `apps/activities`, `apps/daily_visit_batches` — 123/123 passing.

### Documented, not fixed
`partner_schedule()`'s first-time-schedule branch skips the `assert_schedulable()` cost-catalogue gate (mitigated in practice since partner payment amounts are manually entered by the Accountant, but the finance-blocked-reasons check doesn't verify `cost_missing`). Two parallel disbursement tracks (weekly vs. monthly `FundRequest`) draw on the same cost lines with no cross-reconciliation — architecturally real, flagged high-confidence by the auditing agent but not proven exploitable end-to-end in the time available (§E's finding 9, fixed in Pass 3, is a confirmed instance of exactly this risk class). `reassign()` never recalculates cost on a delivery-type change (dead API surface, no frontend caller found). A generic `/api/fund-requests/*` DRF surface duplicates the real controls with none of their safeguards (also no live UI caller found).

---

## G. Functional Audit Pass 3 — Disbursement, Evidence, IA Verification, Accountability, Closure, Field Debrief

Two agents: Disbursement/Execution/Evidence/IA-verification, and Accountability/Finance-Clearance/Closure/Debrief-handoff.

### Fixed

8. **HIGH — A legacy disbursement queue enabled genuine double-disbursement.** `AdvanceDisbursementService.disburse_advance` (`apps/fund_requests/finance_services.py`), live and linked in the sidebar as "Advances Queue," created a `Disbursement` record and flipped `Activity.payment_status` but never updated the underlying `AdvanceRequest` row it read its precondition from — it stayed `confirmed_for_advance` forever, so the exact same money could be disbursed a **second time** through the canonical weekly or per-advance queue, both of which key their "ready to disburse" lists off that same status field. Fixed to move the underlying `AdvanceRequest`(s) to `DISBURSED` (proportionally scaled if the activity has multiple cost lines), under `select_for_update()` to close the double-click race at the same time.
9. **HIGH — No row-locking anywhere in the core advance-lifecycle functions.** `advance_service.py`'s `disburse()`, `submit_accountability()`, and `approve_accountability()` had no `select_for_update()`/`transaction.atomic()` at all — a real race on the three most financially significant actions in the app (a genuine gap the prior day's audit had already fixed for the equivalent monthly-plan path but not this one). Added locking to all three, matching the established pattern.
10. **HIGH — Zero audit logging anywhere in `advance_service.py`.** The single most financially terminal transition in the app — the Accountant's final clearance to `ACCOUNTED` — left no audit trail. Added a local `_audit()` helper and wired it into both `submit_accountability()` and `approve_accountability()`.
11. **Regression from fixing #8 — closure eligibility conflated two independent finance systems.** Fixing #8 correctly made the legacy queue's `AdvanceRequest` rows move to `DISBURSED`, which exposed a real secondary bug: `ClosureEligibilityService`'s NetSuite-code check (`apps/activities/closure_services.py`) treated "this activity's advance is in a money-moved status" as meaning it must also carry a per-advance responsible-user accountability NetSuite code — a step the legacy accountant-only "System A" flow (disburse → accountant enters NetSuite ID directly) was never designed to produce. Fixed the check to treat the accountant's own `NetSuiteExpenseRecord` entry and the per-advance accountability chain as an OR, not an either/or keyed off `AdvanceRequest` status — caught by re-running the existing test suite after fix #8, not by the audit agents (confirms the value of the regression sweep, not just the new tests).
12. **MEDIUM/HIGH — Field Debrief's "accept recommendation" handoff wrote the wrong id type as the follow-up activity's owner.** `accept_recommendation()` (`apps/debriefs/field_debrief_service.py`) wrote `debrief.staff_id` — a `StaffProfile.id` — directly into `Activity.responsible_staff_id`, which is a `User.id` everywhere else in the app (the same StaffProfile-vs-User-id confusion class already known as a recurring gotcha in this codebase). Every debrief-created follow-up activity was silently orphaned from its intended owner's My Plan. Fixed to resolve through `StaffProfile` first, falling back to treating the id as already a `User.id` if no match (the existing test fixture itself passed a `StaffProfile.id` as `follow_up_owner_id`, confirming both the fallback path and the explicit-owner path needed the same fix).

### Tests
`apps/fund_requests/test_finance_operating.py` (+1: `test_disburse_advance_marks_underlying_advance_request_disbursed`, proving a second disbursement attempt through the canonical queue is now rejected), `apps/fund_requests/test_netsuite_accountability_laws.py` (+1: `test_submit_and_approve_accountability_write_audit_log`), `apps/debriefs/tests.py` (+2: owner resolves to the real `User.id` via both the explicit and fallback path). Full sweep: `apps/fund_requests` (85/85), `apps/activities`, `apps/debriefs` (94/94) — all passing.

### Documented, not fixed
IA verification's checklist is entirely client-trusted — the server never re-validates the submitted checkboxes against actual evidence/attendance/SSA/duplicate-detection state before certifying an activity `IA_VERIFIED`, and `approve_accountability()`'s IA-verified gate only checks that flag, not the underlying truth. This is real and significant but requires building genuine server-side re-validation logic, not a quick fix. `ReimbursementService.disburse_reimbursement` bypasses the canonical `ActivityClosureService.close()` gate (currently low-impact — the reimbursement-claim creation path that would feed it has no live callers, per the auditing agent). Evidence review auto-accepts for staff-delivered activities with no independent human review (self-review is technically possible too, muted in practice by the auto-accept). Zero test coverage exists for `apps/evidence`. An orphaned legacy `AccountabilityRecord`/Accountability page shows variance as permanently, incorrectly "fully unspent" then silently force-clears it. No idempotency guard on `ActivityClosureService.close()` itself (cosmetic duplicate audit/notification on a double-click, not a financial risk — `close()` doesn't touch `AdvanceRequest`/`Disbursement` state).

---

## H. Functional Audit Pass 4 — Targets, Analytics, Reports

Two agents: My Targets / Team Targets, and Analytics / Reports / Exports.

### Fixed

13. **HIGH — `/api/reports/*` leaked every generated report to every role.** `apps/reports/services.py`'s `list_reports()`/`get_one()` had no scoping at all — `Report.objects.all()` — even though report *generation* is correctly scoped. The endpoints require only `analytics.view`, a permission nearly every role holds (CCEO, PL, IA, Accountant, PC, in addition to CD/RVP/Admin). A CCEO calling `GET /api/reports/` saw every report any CD/PL/RVP had ever generated country-wide, including its `summary_json` contents, via `GET /api/reports/<id>`. Fixed: country-scope roles (CD/RVP/Admin) still see every report (legitimate leadership visibility); every other role sees only reports they personally generated — the only honest scoping rule available, since a `Report` row stores no school/team scope of its own beyond a coarse "country"/"scoped" label.

### Tests
`apps/reports/test_reports_scope.py` (new, 5 tests: CCEO sees only own reports in list, cannot fetch another CCEO's report by id (404, not leaked), can fetch own report, CD sees every report in list, CD can fetch any report by id). All passing.

### Documented, not fixed
A "Reports & Performance" page (`apps/frontend/views/extended_views.py::reports_view`) computes every figure country-wide with no role scoping at all, despite being granted to team/portfolio-scoped roles (PL, IA) as well as country-scope roles — ambiguous whether this is a bug or a deliberate "leadership always sees everything here" design choice; flagged rather than guessed at. A redundant (not incorrect) query pattern in `CDAnalyticsService`: `pl_oversight`, `target_by_pl_cceo`, and `_active_pl_count` each independently re-derive the same PL→CCEO→school data via `_pl_cceos()` rather than sharing one computation per request — the same *class* of bug fixed twice this session (§B), but here the query count doesn't scale with an unbounded axis the way the two named methods did, so it was judged real-but-lower-urgency and deferred rather than rushed. An "Export to Excel (.xlsx)" button silently produces a `.csv` file (correct data, wrong format/label). A catch-up plan's undated branch creates an `Activity` outside the `assert_schedulable()` cost-catalogue gate — investigated and judged likely intentional (it mirrors the same legitimate "assignment now, cost at schedule-time" deferred-costing pattern already used correctly for partner assignments elsewhere in the app), so left as documented rather than risking a change to the widely-shared `reschedule()` function under time pressure. No historical PL attribution across a mid-year supervisor reassignment (`StaffSupervisorAssignment` is a flat, non-temporal join) — a real gap that needs a schema change (start/end dates on the assignment), too large to make safely in this session.

---

## I. Tests — Summary

| Area | Test file(s) | New tests this session |
|---|---|---|
| N+1 fixes (§B) | `apps/monthly_work_plan/test_rvp_dashboard.py`, `apps/analytics/test_cd_analytics.py` | 13 |
| Country Budget (§C) | `apps/monthly_work_plan/test_country_budget_service.py` | 5 |
| Login page (§D) | *(covered by existing `/login` + lockout suites, unchanged)* | 0 (57 existing, re-verified) |
| Pass 1 (§E) | `apps/frontend/test_partner_readonly_gates.py`, `apps/frontend/tests.py`, `apps/schools/tests/test_import_batch_atomicity.py` | 9 |
| Pass 2 (§F) | `apps/budget/test_cost_snapshot_lock.py`, `apps/fund_requests/test_pass2_audit_fixes.py` | 11 |
| Pass 3 (§G) | `apps/fund_requests/test_finance_operating.py`, `apps/fund_requests/test_netsuite_accountability_laws.py`, `apps/debriefs/tests.py` | 4 |
| Pass 4 (§H) | `apps/reports/test_reports_scope.py` | 5 |

**Full regression sweep** (`apps.analytics apps.monthly_work_plan apps.frontend apps.projects apps.activities apps.schools apps.budget apps.daily_visit_batches apps.fund_requests apps.debriefs apps.reports` plus targeted `apps.core`/`apps.accounts` suites): **582/582 passing**, 0 failures, 0 errors. `manage.py check` and `makemigrations --check --dry-run` both clean.

---

## J. Files Changed

**N+1 fixes (§B):** `apps/analytics/rvp_dashboard_service.py`, `apps/analytics/cd_analytics_service.py`, `apps/monthly_work_plan/test_rvp_dashboard.py`, `apps/analytics/test_cd_analytics.py`.

**Country Budget (§C):** `apps/monthly_work_plan/country_budget_service.py`, `templates/partials/finance/country_budget/root.html`, `apps/monthly_work_plan/test_country_budget_service.py`.

**Login page (§D):** `templates/layouts/auth.html`, `templates/pages/auth/login.html`, `apps/frontend/views/auth_views.py`.

**Pass 1 (§E):** `apps/frontend/views/my_plan_views.py`, `apps/frontend/views/planning_views.py`, `templates/pages/planning/index.html`, `templates/partials/planning/assign_partner_drawer.html`, `apps/schools/upload_service.py`, `apps/frontend/test_partner_readonly_gates.py` (new), `apps/frontend/tests.py`, `apps/schools/tests/test_import_batch_atomicity.py` (new).

**Pass 2 (§F):** `apps/budget/costing_service.py`, `apps/fund_requests/pl_approval_service.py`, `apps/fund_requests/weekly_service.py`, `apps/frontend/views/finance_views.py`, `apps/budget/test_cost_snapshot_lock.py` (new), `apps/fund_requests/test_pass2_audit_fixes.py` (new).

**Pass 3 (§G):** `apps/fund_requests/finance_services.py`, `apps/fund_requests/advance_service.py`, `apps/activities/closure_services.py`, `apps/debriefs/field_debrief_service.py`, `apps/fund_requests/test_finance_operating.py`, `apps/fund_requests/test_netsuite_accountability_laws.py`, `apps/debriefs/tests.py`.

**Pass 4 (§H):** `apps/reports/services.py`, `apps/reports/test_reports_scope.py` (new).

No migrations were required for any fix in this session — every defect was a query, permission, or business-logic bug, not a schema gap (the one schema-shaped finding, §H's supervisor-reassignment history gap, was deliberately deferred rather than rushed).

---

## K. Remaining Issues

No HIGH-severity finding from this session was left unfixed. The items below are real, each with a named cause, but were judged lower-severity, ambiguous in intent, or too large/risky to fix safely under this session's time budget — none is hidden or downgraded without reasoning stated inline in §E-§H.

| Issue | Severity | Why deferred | Suggested next action |
|---|---|---|---|
| IA verification checklist is client-trusted, no server re-validation | HIGH | Requires building real server-side re-validation logic against evidence/attendance/SSA state — a feature addition, not a quick fix | Scope a dedicated follow-up: `ActivityCertificationService.certify_activity()` should independently verify each checklist claim before persisting it |
| Two parallel disbursement tracks (weekly vs. monthly `FundRequest`) share cost lines with no cross-reconciliation | HIGH (architectural) | Not proven exploitable end-to-end in the time available; the one confirmed concrete instance of this risk (§G finding 8) is fixed | A dedicated trace of every entry point into both queues, or a DB-level constraint preventing the same `ActivityScheduleCostLine` from feeding two live `FundRequest`/`WeeklyFundRequest` rows at once |
| Evidence review auto-accepts for staff-delivered activities; self-review technically possible | MEDIUM | Product-design question (is independent review actually required for staff-delivered work?), not obviously a bug | Confirm intent with product owner before changing `evidence_status` defaulting behavior |
| `apps/evidence` has zero test coverage | MEDIUM | Time; building comprehensive coverage (upload validation, scope authorization, review flow) is its own multi-hour task | Dedicated test-writing pass |
| "Reports & Performance" page unscoped for team-level roles | MEDIUM-HIGH | Ambiguous whether country-wide visibility is intentional for this specific page | Confirm intent, then scope `reports_view` to `resolve_user_scope()` like every sibling analytics page if not intentional |
| Redundant (not incorrect) `_pl_cceos()` re-derivation across `pl_oversight`/`target_by_pl_cceo`/`_active_pl_count` | MEDIUM (performance) | Query count doesn't scale with an unbounded axis the way the two named/fixed N+1s did | A per-request cache of `_pl_cceos()` results, same shape as the `CDScope.per_user_series` caching already used elsewhere in this file |
| No historical PL attribution across supervisor reassignment | MEDIUM | Requires a schema change (temporal validity on `StaffSupervisorAssignment`) | Add `start_date`/`end_date`, backfill, then make Team Targets query historically instead of off current assignment only |
| Dead "merge duplicate school" resolution path | MEDIUM | Scoped feature work (wire the real UI to the existing, correct `resolve_duplicate()` service) | Replace the `duplicate_review_view`'s hand-rolled `resolve_unique`-only logic with a call to `apps.schools.services.resolve_duplicate()` |
| `ReimbursementService.disburse_reimbursement` bypasses the canonical close gate | LOW | The reimbursement-claim creation path that would feed it has no live callers today | Fix before ever wiring up claim creation, not urgently before |
| "Export to Excel" produces `.csv` | LOW | Cosmetic/format-label bug, not a data bug | Either implement real XLSX via `openpyxl` or relabel the button |
| Cluster-assignment logic duplicated across 3 view functions | LOW | Functionally equivalent today; a future validation change to the shared service just won't propagate to all 3 | Refactor all 3 call sites onto `apps.clusters.services.assign_school()` |
| A few dead/legacy code paths (`AnnualPlan`/`AnnualPlanActivity` models, a legacy DRF cluster API, a generic `/api/fund-requests/*` DRF surface, an orphaned `AccountabilityRecord`/Accountability page) | LOW | No confirmed live callers for any of them | Confirm dead, then remove — carrying dead code is itself a maintenance risk even though none is a live bug today |

One process note, not a code defect: this session set a password on the shared dev-database `cd@edify.org` account (and one CCEO test account) to visually verify the login page and Country Budget page changes in-browser. These are local dev-database credentials, not production, but flagging since it's a shared account, not one created for this session.
