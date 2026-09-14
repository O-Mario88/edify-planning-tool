# Platform controls audit — 14 September 2026

**Status: fixes implemented and verified by automated tests. This report is still not a platform-wide pass, release approval or independent acceptance: human role acceptance and production performance measurement remain outstanding.**

Findings F-01 to F-08 and verification gaps G-01 and G-02 were fixed on 14 September 2026. Each keeps its original text below as the record of what was found, with a resolution added under its heading. Results after the fixes, including two full-suite failures still under investigation at the time of writing, are in [Verification after fixes](#verification-after-fixes).

The audit covers the entire repository and role model. It combines a complete template-control inventory, the application test suite, a focused workflow suite, JavaScript interaction tests, source tracing and live browser checks. Inventory coverage and executed interaction coverage are different: a declaration with an event handler is not evidence that its workflow succeeds.

## Scope and evidence

Recorded environment: Python 3.13.15, Django 5.2.17, pytest 9.1.1, Node 24.20.0. Git HEAD `f80a90569a368f9f8087f43d62ccf59bf025be8a` with additional uncommitted working-tree changes.

- 684 templates scanned; 3,125 control declarations: 1,020 buttons, 887 links, 1,097 input/select/textarea fields, 67 disclosures and 54 explicit tabs. Shared components and template branches mean these are not counts of unique rendered controls. Clickable nonsemantic elements and JavaScript-generated controls require additional review.
- The existing route inventory contains 803 surfaces: 255 pages, 163 drawers, 96 partials, 261 actions and 28 exports. It represents 15 roles. Parameterized routes require fixture records and are not automatically exercised by an argument-free route crawl.
- `control-inventory.csv` is the declaration checklist. `candidate-triage.csv` records review of 41 static candidates. `route-coverage-register.csv` lists all 803 surfaces without upgrading previous source-contract labels to live passes.
- `workflow-tests.xml` and `.log`: 370 tests passed, plus 354 subtests, with ordinary application password hashers. Initial database migration is included in the 801-second duration.
- Four isolated expected-behavior probes reproduce F-01/F-02/F-03/F-06. `defect-reproductions-assertions.log` contains the actual failed assertions. They are marked strict expected failures in [tests/audits/test_controls_reproductions.py](/Users/edwinomario/Developer/edify-planning-tool/tests/audits/test_controls_reproductions.py); expected failure is evidence of an unresolved bug, not a pass. After the fixes the expected-failure markers were removed: the F-02, F-03 and F-06 probes pass as plain tests, and the F-01 probe was replaced by the database-backed `BatchPaymentsSelectionTest`, because a mocked queryset cannot exercise the server-side re-check of selected IDs.
- `javascript-tests.log`: 9 passed. Covers concurrent requests, cancellation cleanup, actual submitters, duplicate-submit protection, restoring original button content, error announcements, session/capacity errors, table/card preference retention and generated-control cleanup.
- Full application suite: 7,713 tests collected. Final results are recorded separately below when execution finishes. The final run uses four pytest-xdist workers with separate disposable databases, process-local caches, disabled external realtime transport and a fast password hasher only inside those test processes; configured production-format hashers remain available for verification. It does not measure production password strength or authentication latency. A preliminary standard-hasher run was deliberately interrupted after 129 passes and 3 subtests to reduce fixture setup time; it is not counted as a completed full run. A serial fast-hasher run was also deliberately stopped after 1,177 passes and 239 subtests to move to isolated parallel workers; these overlapping partial results are not added to final totals.
- An earlier parallel run was stopped after discovering inherited Redis cache configuration without a test namespace. Its 5,130 passes, 10 failed cases and 8,525 passing subtests are provisional and excluded from the final clean-run totals. Earlier serial runs also inherited the application cache configuration. See G-02.
- The final isolated run did not finish. Its log, `full-suite.log`, stops at 69% after 5,429 passes and 5 failures, with no summary, and no `full-suite.xml` was written. None of its results are counted. The full suite was run again after the fixes; see [Verification after fixes](#verification-after-fixes).
- Test databases: `edify_controls_audit_test` and its four `_gw0`–`_gw3` worker copies. No real payments, approvals, messages, school assignments or HR decisions were submitted during this audit. Production application code was not changed for the findings below. The fixes recorded under each finding were made afterwards and do change application code, templates and settings.
- The workspace includes uncommitted changes from earlier work and concurrent edits. Results describe this working tree, not an immutable release commit. Repeat release verification against a frozen commit.

The role set is CCEO, Programme Lead, Country Director, Regional Vice President, Regional Programme Lead, Impact Assessment, Accountant, Human Resources, Project Coordinator, Partner Admin, Partner Field Officer, Business Transformation Officer, MFI Partner Admin, MFI Loan Officer and Admin. A role being included in the suite does not mean every control was clicked under that role.

## Confirmed findings and proposed fixes

Line references in the findings point at the source as audited, before the fixes; they no longer match the edited files.

### F-01 — High: batch payment selection is ignored by export

**Resolution (14 September 2026):** Fixed. Each tab of [templates/pages/accounts/batch_payments.html](/Users/edwinomario/Developer/edify-planning-tool/templates/pages/accounts/batch_payments.html) is now a GET form with checkboxes named `activity_ids`, a live selected count and UGX total, an “Export selected” button that stays disabled until something is ticked, and a separate “Export all eligible (N)” action. `batch_payments_view` in [apps/frontend/views/finance_operating_views.py](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/views/finance_operating_views.py) re-checks the selected IDs against the same eligibility and the user's country scope (`activity_country_q`), and refuses the export (HTTP 400) for an empty selection or any stale, paid, foreign or unknown ID. The silent 5,000-row cap is removed, and the file name says whether it holds the selected or all eligible payments (`batch_<tab>_selected.csv` or `batch_<tab>_all.csv`). Tests: `BatchPaymentsSelectionTest` in [apps/fund_requests/test_money_unit_regression.py](/Users/edwinomario/Developer/edify-planning-tool/apps/fund_requests/test_money_unit_regression.py) (4 tests).

**Affected roles:** Accountant and Admin where permitted. **Evidence:** source-confirmed; live finance UI confirmed checked controls leave the export destination unchanged.

[templates/pages/accounts/batch_payments.html:56](/Users/edwinomario/Developer/edify-planning-tool/templates/pages/accounts/batch_payments.html:56) and `:80` render checkboxes without names, record values or a selection model. The export links contain only `?export=advances` / `?export=partners`. [apps/frontend/views/finance_operating_views.py:853](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/views/finance_operating_views.py:853) builds all eligible activities; lines 898 and 912 iterate the full eligible querysets, capped at 5,000, without consuming selected IDs.

**Reproduction:** Open Batch Payments with at least two eligible payments, open Partner Payments, select one row and inspect the export request. It has no selected IDs. The backend therefore exports all eligible rows regardless of selection. No actual payout was executed.

**Impact:** The UI suggests selection controls an operational payment file when it does not. This can produce a broader file than the accountant intended.

**Proposal:** Implement an explicit `Export selected (N)` form with named activity IDs and a separate `Export all eligible` action if needed. Re-query and validate eligibility and role scope on the server at export time. Show count and total before export; reject an empty or stale selection. Exports should not mark anything paid. Replace silent 5,000-row truncation with a visible limit or a complete streamed export.

**Acceptance tests:** With three eligible records, select two and assert the CSV contains exactly those two and the matching total; reject inaccessible, paid or stale IDs; exercise both tabs, empty selection, select-all scope and a dataset over the export limit.

### F-02 — Medium: pagination ellipsis acts as a page and resets the directory

**Resolution (14 September 2026):** Fixed. `elided_page_numbers()` in [apps/core/pagination.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/pagination.py) normalizes Django's Unicode ellipsis to a single `PAGE_GAP` token, and the school, staff, cluster and core-school views use it. The five legacy templates named in this finding accept either token and render a gap as `aria-hidden` decoration, never as a page button. Tests: `PaginationGapTest` in [apps/frontend/test_directory_controls_audit.py](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/test_directory_controls_audit.py); the F-02 probe in [tests/audits/test_controls_reproductions.py](/Users/edwinomario/Developer/edify-planning-tool/tests/audits/test_controls_reproductions.py) now passes as a plain test.

**Affected:** School Directory, with the same source mismatch in staff, cluster and core-school pagination. **Evidence:** browser-confirmed in School Directory; source-confirmed in the other named templates.

[templates/partials/schools/table.html:105](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/schools/table.html:105) compares a page item with three ASCII dots (`...`). [apps/frontend/views/school_views.py:630](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/views/school_views.py:630) returns Django's Unicode ellipsis (`…`) from `get_elided_page_range`. The template renders it as a button and submits `page=…`.

**Reproduction:** In a sufficiently large directory, click Next to reach page 2, then click the `…` button. The live URL became `page=%E2%80%A6` and the list returned to rows 1–15. Next itself correctly reached rows 16–30.

**Other source locations:** [templates/pages/staff/index.html:137](/Users/edwinomario/Developer/edify-planning-tool/templates/pages/staff/index.html:137), [templates/partials/clusters/cluster_list.html:49](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/clusters/cluster_list.html:49), [templates/partials/core_schools/matrix_table.html:117](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/core_schools/matrix_table.html:117), [templates/partials/core_schools/team_oversight.html:140](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/core_schools/team_oversight.html:140). Staff, cluster and core-school views also use Django's elided page range. The shared `components/table_pager.html` uses a different normalized pagination helper; it must not be changed blindly merely because it compares `...`.

**Proposal:** Normalize page tokens in one pagination adapter, or compare with the paginator's ellipsis constant. Render gaps as noninteractive, hidden-from-accessibility decoration. Reuse the common pager and preserve every active filter and other independent table-page parameter.

**Acceptance tests:** First/middle/last pages with enough records to produce gaps; no gap button or link; Next/Previous and numbered pages preserve filters; changing filters resets the relevant page only; multi-table pagination remains independent.

### F-03 — Medium: filtered empty results incorrectly claim the registry is empty

**Resolution (14 September 2026):** Fixed. The School Directory view ([apps/frontend/views/school_views.py](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/views/school_views.py)) computes `directory_empty_state` (`registry_empty`, `scope_empty` or `no_matches`) only when the page is empty. [templates/partials/schools/table.html](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/schools/table.html) then shows “No schools match these filters.” with a Clear filters link, or “No schools are assigned to you yet.”, and shows the upload message only when the registry itself is empty. Tests: `DirectoryEmptyStateTest` in [apps/frontend/test_directory_controls_audit.py](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/test_directory_controls_audit.py) (2 tests); the F-03 probe in `tests/audits/test_controls_reproductions.py` also passes.

**Affected:** School Directory across roles. **Evidence:** browser- and source-confirmed.

[templates/partials/schools/table.html:63–64](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/schools/table.html:63) uses the same empty state for every empty result: “No schools uploaded yet” and “Upload schools to build the directory registry.”

**Reproduction:** Regional Programme Lead, School Directory: district Abim has 3 schools, all clustered. Selecting Unclustered shows 0 records but says no schools have been uploaded. The role is read-only; clearing filters restores 703 schools.

**Impact:** Users may think data is missing or that an upload is required, when only the current filter combination is empty.

**Proposal:** Distinguish empty registry, no records in the user's permitted scope and no matches for active filters/tab. For no matches, show “No schools match these filters” with a Clear filters action. Offer upload only to authorized users when the underlying registry is empty.

**Acceptance tests:** Nonempty registry + zero-result query/tab, empty registry, restricted role with no scoped schools, active district/sub-county, and filter reset. Assert wording and permitted recovery action, not just HTTP 200.

### F-04 — Medium: planning cluster expansion lacks a usable accessible control

**Resolution (14 September 2026):** Fixed. In [templates/partials/planning/school_table.html](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/planning/school_table.html) the cluster name is now one semantic button with `aria-expanded`, `aria-controls` pointing at an `id` on its panel, and the shared visible focus style. The icon is decorative, and the chevron is a pointer-only shortcut (`tabindex="-1"`, `aria-hidden`). The Batch Payments tab panels now have `aria-labelledby`. Test: `PlanningClusterDisclosureTest` in [apps/frontend/test_directory_controls_audit.py](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/test_directory_controls_audit.py).

**Affected:** Planning's cluster cards for roles allowed to use that view. **Evidence:** source-confirmed; this specific card was not browser-tested in this audit.

[templates/partials/planning/school_table.html:56](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/planning/school_table.html:56) renders an icon-only button without an accessible name, `aria-expanded` or `aria-controls`. The icon container at line 17 and heading at line 28 also toggle expansion through click-only handlers. The button removes the focus outline without an explicit local replacement. The shared naming enhancer can copy a title but this control has none. Batch Payment tab panels also lack `aria-labelledby` linking them to their tabs, and appeared unnamed in the browser accessibility tree; include those panels in the same semantics cleanup.

**Proposal:** Make the cluster heading a single semantic button, give it a label including the cluster name, expose expanded state and its panel relationship, and provide the shared visible focus treatment. Remove redundant nonsemantic click targets. Native `details/summary` is an alternative if it meets the card layout requirements.

**Acceptance tests:** Tab reaches the control; Enter and Space each toggle once; expanded/collapsed state is announced; focus remains visible in light, blue and dark themes; Escape behavior follows the platform accordion convention.

### F-05 — Medium: metric explanations expose implementation details

**Resolution (14 September 2026):** Fixed. `user_explanation(spec)` in [apps/core/metrics/spec.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/metrics/spec.py) removes module paths, display expressions and query provenance from a definition, falling back to the metric's question when nothing readable remains, and the metric payload (`apps/core/metrics/payload.py`) renders that text. The internal definition stays in the registry for maintainers. 306 of the 535 registered definitions contained provenance; none of it reaches a tooltip now. Tests: [apps/core/tests/test_metric_user_explanations.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/tests/test_metric_user_explanations.py) (3 tests).

**Affected:** Shared KPI/context metrics consuming generated registry definitions. **Evidence:** browser-confirmed in School Directory; shared source path confirms wider exposure.

[templates/components/context_metrics.html:25](/Users/edwinomario/Developer/edify-planning-tool/templates/components/context_metrics.html:25) uses a metric's definition as a title when no tooltip is supplied. Definitions in [apps/core/metrics/reconciled_registry.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/metrics/reconciled_registry.py) contain module paths, Python expressions and query provenance. The live accessibility tree included these strings as school KPI explanations.

**Impact:** Staff encounter technical descriptions instead of explanations of what a number means. This is a usability and accessibility-content defect; no secret disclosure was established.

**Proposal:** Separate `user_explanation` from internal provenance in the registry. Render a concise business definition, reporting period and relevant denominator. Keep diagnostic provenance in developer documentation or an authorized diagnostic view. Example: “Schools matching your current district and partner-type filters; closed schools are excluded.” Validate the actual calculation before approving each explanation.

**Acceptance tests:** All rendered KPI tooltips and accessible descriptions use reviewed user copy; reject code-like provenance in the shared component's user-facing output; check compact and exact values still agree.

### F-06 — Medium: Send to Inbox discards the current analytics filters

**Resolution (14 September 2026):** Fixed. The Send to Inbox buttons on the Analytics index and workspace pages now carry the page's query string. The drawer shows a “Report scope” summary and posts the filters back as hidden fields. The view passes only recognized filters (`ANALYTICS_FILTER_KEYS`) to `send_analytics_snapshot` ([apps/analytics/report_delivery.py](/Users/edwinomario/Developer/edify-planning-tool/apps/analytics/report_delivery.py)), which reads the filtered dataset inside the user's permission scope and writes the filters and a filtered `/analytics` link into the message. Test: `test_the_snapshot_carries_the_filters_on_screen` in [apps/core/tests/test_analytics_dashboard.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/tests/test_analytics_dashboard.py); the F-06 probe in `tests/audits/test_controls_reproductions.py` also passes.

**Affected:** Analytics users with permission to send a private snapshot. **Evidence:** source-confirmed; no real message sent.

[templates/pages/analytics/index.html:23](/Users/edwinomario/Developer/edify-planning-tool/templates/pages/analytics/index.html:23) opens the snapshot drawer without the current query parameters, unlike Download CSV immediately above it. The same pattern occurs in [templates/pages/analytics/workspace.html](/Users/edwinomario/Developer/edify-planning-tool/templates/pages/analytics/workspace.html). The drawer posts only categories. [apps/frontend/views/analytics_views.py:708](/Users/edwinomario/Developer/edify-planning-tool/apps/frontend/views/analytics_views.py:708) passes user and categories to `send_analytics_snapshot`; [apps/analytics/report_delivery.py:33](/Users/edwinomario/Developer/edify-planning-tool/apps/analytics/report_delivery.py:33) calls `get_analytics_data(user, {})` with an empty filter dictionary.

**Reproduction:** Choose a nondefault fiscal year/district/status combination on Analytics and invoke Send to Inbox. The delivery path reconstructs the default analytics scope, so it does not preserve the visible report. User permission scope is still applied; this finding is about filter consistency, not proven unauthorized disclosure.

**Proposal:** Carry a validated, canonical filter set through drawer GET and POST into the snapshot service. Include the selected period and geography in the message and its return link. If a default-scope digest is intentional, name the action explicitly and show the scope before sending.

**Acceptance tests:** Use fixtures with different default and filtered totals, generate a snapshot through the isolated test client, and assert its metrics and link match the selected filters. Verify invalid filters cannot broaden permission scope. Test CSV and inbox output against the same canonical filtered dataset.

### F-07 — Medium: saved dates can open the wrong calendar month in western time zones

**Resolution (14 September 2026):** Fixed. All six calendar drawers (planning school and cluster scheduling, the clusters planned-date field, core-school visit and training, and assign-to-project) now parse a saved date as calendar parts instead of a UTC instant. Test: [tests/js/calendar-dates.test.cjs](/Users/edwinomario/Developer/edify-planning-tool/tests/js/calendar-dates.test.cjs) runs each drawer's real snippet under America/Guatemala, UTC, Africa/Kampala and Pacific/Kiritimati for 1 September, 29 February and 1 January. [tests/audits/calendar-timezone-reproduction.cjs](/Users/edwinomario/Developer/edify-planning-tool/tests/audits/calendar-timezone-reproduction.cjs) now passes.

**Affected:** Shared/duplicated planning calendars, particularly rescheduling an existing activity dated on the first day of a month. **Evidence:** executable JavaScript reproduction against the actual initialization snippets; not a live browser timezone test.

[templates/partials/planning/schedule_drawer.html:385](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/planning/schedule_drawer.html:385), [templates/partials/planning/schedule_cluster_drawer.html:81](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/planning/schedule_cluster_drawer.html:81) and [templates/partials/clusters/planned_date_field.html:12](/Users/edwinomario/Developer/edify-planning-tool/templates/partials/clusters/planned_date_field.html:12) initialize the calendar using `new Date(this.selectedDate)` and then local `getMonth()`. A date-only ISO string is parsed at UTC midnight. In a timezone west of UTC, `2026-09-01` becomes August 31 locally, so the month grid opens in August while the field represents September 1. Similar duplicated initialization exists in core-school visit/training and project-assignment drawers; an empty initial date does not trigger the defect.

**Reproduction:** `TZ=America/Guatemala node tests/audits/calendar-timezone-reproduction.cjs` runs the actual snippets with a saved `2026-09-01`; all three open `2026-08`. The same probe under `TZ=Africa/Kampala` opens `2026-09`. These tests do not change the computer's timezone.

**Proposal:** Parse date-only values as calendar components (`year`, `month`, `day`) and construct a local calendar date, or keep integer calendar components without a timestamp. Consolidate the duplicated date pickers into one component so initialization, display, selection and validation use the same semantics.

**Acceptance tests:** Saved dates on January 1, September 1, leap day and DST boundaries in east/west/UTC zones; displayed value, open month, highlighted day and posted date must agree. This finding concerns the open calendar month; an incorrect saved database date was not established.

### F-08 — High: failed dashboard tab requests remove the last valid panel

**Resolution (14 September 2026):** Fixed. [static/js/view-panels.js](/Users/edwinomario/Developer/edify-planning-tool/static/js/view-panels.js) parks a panel only for a swap that will happen (`shouldSwap` not false and not `isError`), and if a swap is cancelled after parking it restores the last good panel and its tab on `htmx:afterRequest`. The script's cache key in `templates/base.html` was bumped. Test: [tests/js/view-panels.test.cjs](/Users/edwinomario/Developer/edify-planning-tool/tests/js/view-panels.test.cjs) (2 tests); [tests/audits/dashboard-error-reproduction.cjs](/Users/edwinomario/Developer/edify-planning-tool/tests/audits/dashboard-error-reproduction.cjs) now passes.

**Affected:** Dashboard views using `static/js/view-panels.js` caching. HR and Regional Programme Lead mark their dashboards `data-dashboard-live` and bypass this cache, so this specific removal path does not apply to those dashboards. **Evidence:** isolated execution of the actual JavaScript script and verification of bundled HTMX's event contract; no live server failure was induced.

`static/js/view-panels.js:167` handles `htmx:beforeSwap` by immediately parking/removing the current panel. It does not check `event.detail.shouldSwap`, `isError` or cancellation. The bundled HTMX emits that event for a 500 response with `shouldSwap=false`, then skips the replacement. The old panel has already been detached, leaving the workspace empty.

**Reproduction:** `node tests/audits/dashboard-error-reproduction.cjs` loads the real cache script with a minimal event/DOM harness and emits the non-swapping 500 event. It reports `actualPanelAttached:false` when the expected value is true. The bundled HTMX source confirms `beforeSwap` occurs before its `if (o.shouldSwap)` guard.

**Proposal:** Move panel detachment to a point where a replacement is committed, or gate it on a confirmed successful swap and restore it if a later listener cancels. Preserve the old panel, selected tab, URL and focus on failure; show an actionable error notice. Extend the existing request-error tests to exercise the dashboard cache together with the tab rail.

**Acceptance tests:** 500, session-expiry, busy/retry and cancelled swaps retain the last good content; a successful switch still caches/reuses panels; rapid replacement does not show a panel under the wrong tab; failures never leave a blank shell.

### G-01 — High verification gap: the visual audit cannot fail on the measurements it collects

**Resolution (14 September 2026):** Fixed. [e2e/ui-design-audit.spec.js](/Users/edwinomario/Developer/edify-planning-tool/e2e/ui-design-audit.spec.js) now asserts on what it measures: no page-wide sideways scroll, an accessible name on every button, link, tab and field, and a page heading. A self-test feeds the checks the measurements of an overflowing page, an unnamed control and a missing heading, and requires each to be reported. All 26 sampled crawl pages passed in all 9 viewport/theme combinations (27 tests including the self-test).

[e2e/ui-design-audit.spec.js](/Users/edwinomario/Developer/edify-planning-tool/e2e/ui-design-audit.spec.js) collects nine viewport/theme combinations, but its final assertion only checks `expect(results).toHaveLength(9)`. It does not assert against the collected overflow, typography or control measurements. It uses rendered HTML fixtures and does not execute the real workflow endpoints.

**Proposal:** Keep that script as a measurement collector, clearly named as such, and add explicit assertions for overflow, accessible names, focus visibility and selected visual baselines. Add real interaction tests with deterministic fixtures. The existing inventory's automated scores and passing source contracts must not be presented as independent design approval.

**Acceptance tests:** Deliberately introduce an overflowing element or a missing accessible control name in a test fixture; the audit must fail for the correct reason. Removing a tab's action must fail a functional test even though the tab still renders.

### G-02 — High verification gap: local tests inherit the application Redis cache

**Resolution (14 September 2026):** Fixed. [config/settings/base.py](/Users/edwinomario/Developer/edify-planning-tool/config/settings/base.py) now keeps every test run off the application cache: each test process gets a private `LocMemCache` (and the database session engine) unless `EDIFY_TEST_REDIS_URL` names a Redis kept for tests, and that URL is refused if it equals `REDIS_URL`. Tests: [apps/core/tests/test_test_cache_isolation.py](/Users/edwinomario/Developer/edify-planning-tool/apps/core/tests/test_test_cache_isolation.py) (3 tests). The audit's own repeated run under isolation did not finish (see Scope and evidence); the full suite after the fixes ran with these private caches.

The audit verified that the development test settings selected `django.core.cache.backends.redis.RedisCache` with no key prefix. Django isolates test databases, but not that cache. Concurrent workers can change shared revision keys or clear one another's cached state; the configuration can also overlap the cache used by a development application. This makes the parallel results unreliable as a clean release gate.

**Action taken for this audit:** stopped the affected run, reset the four disposable worker databases, and changed the audit-only settings to a separate process-local cache per worker with external realtime transport disabled. The final run is being repeated under that isolation. No live database records were used by the test suite. Cache interference in the earlier run remains a limitation; no claim is made that the application cache was unaffected.

**Proposal:** make dedicated test settings the standard entry point. Tests requiring real Redis should use a disposable Redis instance/database exclusively assigned to the run; avoid using `cache.clear()` against a shared application cache. Add a startup guard that rejects application cache/storage/transport endpoints for destructive test operations. Test cache-backed production behavior separately against the isolated real service.

**Acceptance tests:** independent workers cannot see or invalidate one another's sentinel keys, test cleanup cannot remove an application sentinel, and revision invalidation tests behave consistently in serial and parallel execution.

## Live interaction evidence

| Area | Executed action | Observed result |
|---|---|---|
| Regional Programme Lead dashboard | Overview, Coaching, Programmes, Reporting | Correct selected tab and panel eventually rendered. Rapid requests were aborted by request replacement; no persistent tab failure established. |
| Regional dashboard filters | Change FY 2026 to FY 2025 and apply on Programmes | FY and relevant links/data changed; Programmes stayed selected. Explicitly labelled “latest regional cycle” content retained its own FY. |
| Shared shell | Messages, Escape dismissal, Notifications, close button | Drawers rendered appropriate empty states; navigation became usable after dismissal. No messages sent. |
| School Directory | Select district Abim | Count changed from 703 to 3; sub-county enabled with Abim options. |
| School Directory | Select Unclustered under Abim | 0 records, tab preserved; wrong empty-state copy, F-03. |
| School Directory | Clear Filters | Full 703-school scope restored. |
| School Directory | Next | Rows 16–30 displayed. |
| School Directory | Ellipsis on page 2 | Submitted nonnumeric page; rows 1–15 returned, F-02. |
| Finance | Sign in and open Batch Payments | Permitted finance workspace and both tabs rendered. |
| Batch Payments | Partner Payments tab; check a payment | Partner panel rendered; export destination remained unfiltered, F-01. Backend source confirms all eligible records are exported. |

Local requests sometimes took long enough to exceed the browser command deadline, then completed successfully. That is an observed responsiveness concern, not a reliable performance benchmark: database migration, tests and other local activity were concurrent. Re-measure isolated server response times and browser interaction latency before assigning a performance severity. The browser later navigated between test steps outside the audit sequence; further session manipulation was stopped to avoid interfering with the active user session.

## Verification after fixes

Run on 14 September 2026 against the working tree with the fixes applied. The fixes were uncommitted at the time of writing, so release verification must still be repeated against a frozen commit. All results here are automated; the browser checks under Live interaction evidence were made before the fixes.

| Check | Result |
|---|---|
| `npm run test:ui-state` (all `tests/js/*.test.cjs`, including the new calendar and dashboard-panel tests) | 17 passed |
| Audit reproduction probes in `tests/audits/test_controls_reproductions.py`, under pytest | 3 passed (F-02, F-03, F-06; the F-01 probe was replaced by `BatchPaymentsSelectionTest`) |
| `tests/audits/calendar-timezone-reproduction.cjs` and `tests/audits/dashboard-error-reproduction.cjs` | Both pass |
| Visual audit, `e2e/ui-design-audit.spec.js` | 27 passed (26 sampled crawl pages × 9 viewport/theme combinations, plus the self-test) |
| Full Django suite (`config.settings.dev`, `--parallel 4`, private per-process caches) | 7,728 tests; 2 failures, both resolved below (one fixed, one environmental and passing on rerun) |

The two full-suite failures were then investigated and rerun:

- `apps.frontend.test_ia_performance` `IAVerificationQueueN1FixTest` (26 queries against a ceiling of 25): **fixed.** The 26th query was the school-identity middleware's batched lookup, added to the IA queue by commit aa56d165. On this page it only mapped each School ID to itself, because the row already carries the display code. `templates/pages/ia/partials/queue_table.html` now passes `code=act.schoolId`, which renders the same markup without registering a lookup. The page is back to 25 queries for both 5 and 55 queued activities, and the test's ceilings are unchanged. Rerun: `apps.frontend.test_ia_performance` 18 tests OK; the IA dashboard, mobile, search, reach and school-identity suites 81 tests OK.
- The scale gate (`apps.system_health.test_load_scale` `ScaleGateTest`, `/analytics` p95 1,799 ms against 1,500 ms): **no regression; passed on rerun.** Profiling on the dev data and on the gate's own 15,000-school fixture found the new `user_explanation` costs under 1 ms per request (0.13–0.16 ms on `/analytics`), and median times with and without it were equal within noise. The failing run was slowed about fourfold across pages untouched by the fixes (load average 6–11, swap 7.3 of 8 GB). Rerun: 19 tests OK, with `/analytics` p95 567 ms. This remains a local test timing, not a production measurement. An optional query simplification in `apps/analytics/subcounty_insight.py` (dropping DISTINCT on counts whose joins are many-to-one, 116 ms to 46 ms on the fixture) was identified and not applied, because it is not a regression fix.

**Not covered by the new tests.** The new tests verify the fixes against the defects as found; they do not carry out every acceptance test proposed under the findings. These remain for role acceptance or further automation:

- F-01: the tests export the Partner Payments tab and compare IDs. The Advances tab, the file total, the on-page count and UGX total, and a large export are not exercised.
- F-02: the tests render only the School Directory template. The staff, cluster and core-school templates, filter preservation across pages and independent pagers are not exercised.
- F-03: the view's `scope_empty` decision is not tested with a restricted role; only the template's rendering of that state is.
- F-04: the test checks the cluster card's rendered markup. Keyboard operation, focus visibility in each theme and the Batch Payments panel labels are not tested.
- F-05: every explanation is derived automatically by removing provenance (no metric sets its own `user_explanation` yet). Checking each explanation against its calculation, as the proposal asked, remains.
- F-06: the test checks the filters used and the message text. It does not compare metric values with a differently filtered total, try filter values outside the user's scope, or compare CSV and inbox output.
- F-07: only the month the calendar opens is checked, not the displayed value, highlighted day, posted date or DST boundaries. The six copies were corrected in place, not consolidated into one component.
- F-08: the test uses a minimal DOM, not a browser. Session expiry, busy/retry, panel reuse after a successful switch and rapid replacement are not exercised.
- G-01: the audit still measures saved crawl HTML with network requests stubbed, not live workflows. Focus visibility, visual baselines and functional tab tests were not added.

## Platform-wide fix and verification proposal

The fixes named in items 1–3 are in place; see the resolution under each finding. The wider work those items also call for (finance operations acceptance, every legacy pager and date picker, empty/loading/denied/stale/error states, keyboard checks) and items 4 and 5 were not part of the fixes.

1. **High-priority correctness and recovery:** implement selected-payment exports (F-01) and retain the last valid dashboard panel on failed requests (F-08). Validate exported IDs, amounts, permission scope, stale records and failed-tab recovery using disposable fixtures. Proposed owners: finance workflow and frontend engineers, with finance operations acceptance.
2. **Shared interaction consistency:** resolve F-02/F-04 using the shared pager and disclosure patterns. Audit every legacy pager and calendar/date picker; verify keyboard navigation, accessible labels and selected states. Proposed owner: frontend engineer.
3. **Recovery and explanations:** resolve F-03/F-05 in shared rendering/data contracts. Review empty, loading, denied, stale-data and error states with role-appropriate recovery actions. Proposed owners: frontend engineer and product/content reviewer.
4. **Behavioral coverage:** associate each control family with an executable assertion. A successful GET, template string or event-handler presence alone is insufficient. Test tabs against the panel and URL, filters against actual result IDs and totals, and buttons against the intended state change or opened destination.
5. **Independent acceptance:** a QA reviewer and representatives for IA, Regional Programme Lead, HR, finance and field/partner operations should execute the role matrix on a frozen staging build. Accessibility review and user acceptance are not replaced by this automated audit.

### Required matrix for final sign-off

This matrix is for human acceptance: the reviewers named in item 5 execute it, role by role, on a frozen staging build. The fixes for F-01 to F-08, G-01 and G-02, and the automated tests that verify them, do not replace it. The Tabs, Filters/search, Tables/disclosures, Planning/scheduling and Finance rows cover the areas those findings touched and must still be executed for every listed role, including the acceptance items the new tests do not cover (see [Verification after fixes](#verification-after-fixes)).

| Family | Required assertions | Data/role cases |
|---|---|---|
| Tabs | Correct panel and URL; refresh/back/forward; keyboard arrows/Home/End; no stale panel after rapid changes | Every tab family, permitted and forbidden roles |
| Filters/search | Single/combined filters match records and totals; dependent options reset; empty results recover; export matches scope | FY, period, region, district, sub-county, owner, status, school ID, special characters |
| Tables/disclosures | Numbered paging, no clickable gaps, independent pagers, sort, row/card view, expansion, school identity | Empty, one row, multiple pages, large districts, mobile |
| Planning/scheduling | Correct school/cluster/non-school fields, SSA linkage, delivery mode, responsible person, cost, period, status, owner/supervisor actions | IA, PL, CCEO, HR, Regional Lead, partner; valid/invalid/stale/unauthorized inputs |
| Finance | Exact selected export, approvals/refusals, duplicate-submit protection, verified totals, permission isolation | Accountant, CD, RVP, PL, Admin, unauthorized staff |
| HR | Tabs/filters, validation, draft/cancel, role restrictions, leave/coverage transitions, confidentiality | HR director, supervisor, employee, unrelated employee |
| IA/SSA | School scope, assessment filtering, verification/refusal, plan support, district aggregation | Assigned/unassigned schools; draft/submitted/verified records |
| Partner/lending | Invitations/handoffs, acceptance, scheduling, completion/evidence, loan filters/actions | Partner admin/staff, MFI admin/officer, business transformation |
| Shared shell | Search, navigation history, account/settings, modal focus/close, alerts, offline/session expiry | Every role; keyboard; small screen; blue/dark/light |
| Forms/actions | Validation keeps input, errors announced, success reflects persisted change, cancel does not mutate, retries safe | Valid/invalid input, server failure, stale permission, duplicate clicks |

Final sign-off requires no unresolved high-severity workflow defects, all discovered medium defects fixed or explicitly accepted with a reason, and an evidence-backed coverage register. The fixes for this audit's findings and their automated tests are an input to that decision, not a substitute for it. Still outstanding: execution of this matrix by people in each role; the two full-suite failures under Verification after fixes; execution evidence for the coverage register, where the control inventory still marks 3,109 of its 3,125 declarations “Not individually executed”; and production performance measurement. No independent expert certification is claimed.

## Reproduction commands

```sh
python3 scripts/audit_ui_controls.py
npm run test:ui-state
TEST_DATABASE_NAME=edify_controls_audit_test DATABASE_URL=postgresql://edwinomario@127.0.0.1:5432/postgres PYTHONUNBUFFERED=1 .venv/bin/python scripts/run_controls_audit_tests.py apps -n 4 --dist loadfile -q --reuse-db --tb=short --junitxml=docs/audits/controls-2026-09-14/full-suite.xml
```

The parallel run requires `pytest-xdist` (3.8.0 was installed in the local virtual environment for this audit). No production requirements or application settings were changed. The G-02 resolution later changed application settings (`config/settings/base.py`) so that test runs use private caches.

The CSV register intentionally retains “not individually executed” for controls without specific execution evidence. This audit does not claim that all 3,125 declarations, every role/data combination, external integrations, real email delivery, or every production browser/device combination passed.
