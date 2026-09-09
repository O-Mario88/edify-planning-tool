# Performance and reliability audit — 9 September 2026

## Changes

- Country Director map requests no longer compute hidden operational tables. Both views retain the same KPI data; direct service callers retain the complete default response.
- Dashboard requests no longer compute alerts and daily command-center data that no current dashboard renders.
- Analytics workspace and tabs share the existing hashed, user/role/portfolio/filter-isolated cache-key implementation. This also removes whitespace-invalid cache keys for roles such as Program Lead.
- Nested DOM insertions receive one enhancement pass per connected subtree. KPI scrolling updates text, accessibility attributes and navigation markup only when their values change, with geometry reads preceding writes.
- Shared CSS is minified and broad class-substring selectors are compiled into indexed class selectors. Specificity is preserved using `:is()`. Relative asset URLs are rebased for the generated location.
- Returned-evidence bookmarks now redirect to the scoped, paginated evidence workspace. The retired view queried records globally and rendered model records through an incompatible presentation.
- IA comparison defaults and its picker now use the same authorized queue. An out-of-scope first record no longer makes a valid reviewer page return 404; explicit unauthorized record requests still return 404.
- Removed 27 confirmed unreferenced templates, including the retired returned-evidence view, old school card, country-budget wrapper, PL team-performance presentation, and unused finance/project/help/planning fragments, old analytics/targets/reimbursement wrappers and unused mobile prototypes. Active compatibility routes and database migrations remain because existing integrations and stored data still depend on them.
- KPI trend values now use the existing compact helper row, retain the helper in the tooltip, and safely handle missing trend tones. No extra row or height is introduced.
- Forced-color boundaries override all three themes, and project metadata uses theme-aware surfaces.
- The retained country-budget action fragment has a stable swap root and uses outer replacement, avoiding missing targets and duplicate nested IDs.
- Reconciled stale design-contract expectations with the approved blue theme and fixed repository lint/format drift.

## CSS maintenance

Edit source styles in `assets/css/` or `static/css/`, then run `npm run build:css`. Do not edit `static/css/main.css`, `static/css/tokens.css`, or `static/build/css/` by hand. Commit generated output with source changes. `npm run watch:css` watches templates, Python, JavaScript and style sources and rebuilds both stages.

The compiler scans application class candidates and CSS declarations. Runtime class names assembled from fragments must be represented by a complete candidate in source or CSS, as with Tailwind. `static/build/css/selectors.json` records the mapping; the authenticated route audit detects rendered class patterns absent from it. The theme-equivalence browser test compares generated and original computed styles on five live workspaces in all three themes. CI checks generated-asset drift.

## Measurements and verification

Browser style-update benchmark (median of seven samples, same local browser,
without the functional test workers competing for CPU):

| Workspace | Before | After |
| --- | ---: | ---: |
| Analytics | 81.69 ms | 10.23 ms |
| Schools | 3.40 ms | 0.82 ms |
| System health | 10.31 ms | 0.09 ms |

These timings measure style recalculation following a workspace-root class change, not
end-to-end navigation or click latency. The analytics result now meets the
existing one-frame regression budget.

The ten shared stylesheets total 243,459 bytes with gzip at the baseline and
186,448 bytes after compilation (23% less compressed payload).
The uncompressed compiled files are larger because they enumerate class names;
production uses WhiteNoise's compressed manifest storage. The original source
files remain build inputs.

Controlled backend measurements used the same local dataset (703 schools,
277 activities, 42 users), two warm-up requests and five measured requests per
combination, with no browser audit or functional workers running concurrently.
The baseline was commit `c6685353` in a detached worktree.

| Dashboard role | Median before → after | p95 before → after | Queries before → after |
| --- | ---: | ---: | ---: |
| CCEO | 28 → 28 ms | 35 → 30 ms | 12 → 12 |
| Program Lead | 492 → 497 ms | 544 → 563 ms | 137 → 132 |
| Country Director | 512 → 346 ms | 540 → 403 ms | 135 → 83 |

The Country Director median improved by 32%. Program Lead query work decreased,
but this small sample did not show a latency improvement. All 27 measured
page/role combinations met their configured p95 budgets before and after. With
five samples, p95 is effectively the slowest sample; this is a regression check,
not a population tail-latency estimate. Reproduce with
`ITERATIONS=5 .venv/bin/python scripts/latency_budget.py`.

The final Chromium authenticated audit passed all 14 roles in one clean run
(9.4 minutes), covering 1,051 permitted argument-free role/page combinations
(overlapping routes across roles, not 1,051 unique pages). It checks HTTP/browser
errors, document overflow, visible control names, DOM size and generated-selector
coverage. The earlier sweep identified missing generated calendar and chart-legend
classes, which were added before the final audit.

Production static collection passed using the same compressed manifest backend
as deployment, with an isolated temporary output directory. Ruff lint and
format checks passed, Django configuration checks passed, and no missing
database migrations were detected.

The 22 isolated scale checks passed at 15,000 schools. Measured p95 values
included dashboard 62 ms, schools 187 ms, analytics 515 ms and My Plan 109 ms
for the scale harness's configured role and fixtures; these are not the same
role/data distribution as the controlled dashboard comparison above.

The requirements traceability rebuild completed: 20 of 22 requirements traced,
with the same two untraced requirements as the baseline: Offline field activity
and Integration outage. The offline fallback browser check is separate from
end-to-end offline activity synchronization. The focused correction
suite passed 166 tests, including trend rendering, scoped IA defaults and the
retained evidence redirects. The first full run surfaced stale design assertions
and generated inventories as well as the trend/forced-color regressions; these
were corrected before the clean full-suite rerun.

The clean full functional suite passed all **6,769 tests** in 1,308.888 seconds
with four workers (`--exclude-tag=scale --keepdb --noinput`). The 22 scale tests
above ran separately without competing workers. The final source checks also
passed: Ruff lint, formatting for 1,688 files, Django checks and `git diff --check`.

The desktop browser matrix passed **109 checks** across Chromium, Firefox and
WebKit, with two intentional skips for a field workflow exercised in Chromium.
It covers login and password controls, blue-brand consistency, KPI resizing and
HTMX replacement, contrast checks, filters, drawer containment, landscape maps,
map loading, time-sensitive greetings, populated workspaces and offline fallback.

The final populated landscape audit passed all **14 roles**, covering
276 role/page/theme/viewport layouts at 390, 768, 1280 and 1920 px
(the smaller widths target key dense workspaces).

The clean phone/tablet rerun passed all **75 checks** across Android, iPhone
and tablet profiles, including responsive drawers, KPI layouts/navigation,
HTMX replacement, contrast, password visibility and successful sign-in. The
initial run exposed a missing viewport meta tag in the standalone KPI fixture;
the live app already had the correct tag. The fixture was corrected to match
the app before rerunning the entire matrix.

Visual review covered laptop and phone login, Firefox tablet login, phone/tablet
KPI strips, scheduling and cluster drawers, blue project planning, the Accountant
workspace and a complete landscape map. The separate rendering regressions
passed for bounded page initialization, stable DOM/listener counts after tab
churn, subtree batching, calendar classes, forced colors and generated/source
style equivalence.

These are local seeded-database and browser regression checks, not a production concurrency benchmark. Route coverage checks permitted pages and visible controls; workflow tests exercise state transitions separately. Neither establishes that every possible combination of production data, permissions and external integrations has been exercised.

## Retired template inventory

- `templates/components/mobile_record_card.html`
- `templates/components/mobile_section_picker.html`
- `templates/components/mobile_sticky_action_bar.html`
- `templates/components/school_list_card.html`
- `templates/pages/accounts/reimbursements.html`
- `templates/pages/analytics/cd_analytics.html`
- `templates/pages/analytics/pl_analytics.html`
- `templates/pages/closure/completed_activities.html`
- `templates/pages/core_schools/leadership.html`
- `templates/pages/evidence/returned.html`
- `templates/pages/finance/country_budget.html`
- `templates/pages/targets/team.html`
- `templates/partials/dashboards/pl/team_performance.html`
- `templates/partials/finance/_chip_icon.html`
- `templates/partials/finance/country_budget/_kpi_icon.html`
- `templates/partials/finance/fund_allocation_filters.html`
- `templates/partials/finance/fund_allocation_table.html`
- `templates/partials/fund_requests/monthly_preview.html`
- `templates/partials/help/contextual_dialog.html`
- `templates/partials/help/topic_icon.html`
- `templates/partials/planning/reason_required_notice.html`
- `templates/partials/projects/attention_row.html`
- `templates/partials/projects/project_minilist.html`
- `templates/partials/projects/workflow_step.html`
- `templates/partials/targets/team/_area_icon.html`
- `templates/partials/todos/command_center.html`
- `templates/partials/work_plan/monthly_plan.html`
