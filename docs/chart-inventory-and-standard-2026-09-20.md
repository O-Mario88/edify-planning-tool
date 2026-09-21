# Platform chart inventory and proposed standard

Source audit: 20 September 2026. This document records the chart implementations found in templates and JavaScript, including compact CSS/SVG visualizations. The inventory records the original formats; implementation status is recorded below. Role permissions and available data determine which charts appear. Repeated instances of the same component are grouped below.

## Required visual standard

Use the three supplied screenshots as the reference for horizontal bars, vertical columns, and grouped comparisons.

- Single measure: system blue, `--edify-series-1` (`#0e5da3`).
- Comparison series, in order: blue `#0e5da3`, orange `#ea580c`, green `#10b981`, purple `#8b5cf6`. These already exist as the first four series tokens.
- Rectangular bars, consistent spacing, readable category labels, restrained axes/grid, explicit units, and values above columns or beside horizontal bars. Comparison legends sit above the plot.
- Light mode charts sit on white cards against the requested `#80aad3` page background. Other themes retain readable surfaces with the same chart geometry.
- Updated reference: existing line/area time series use thin straight lines, hollow markers, a faint gradient to the zero baseline, shared tooltips and subtle horizontal/vertical grids. Preserve actual observations; do not insert artificial zero points. Signed changes retain negative values. Comparison and ranking charts retain bars.
- Rankings and long labels use horizontal bars. Comparisons use adjacent grouped bars. Limit comparisons to four series; use filters or separate panels for additional series.
- To make all statistical charts follow these references, replace donuts, radial gauges, scatter plots and statistical heatmaps with appropriate bar presentations. Preserve underlying detail tables.
- Start magnitude axes at zero. Signed changes may extend below zero. Keep SSA scores on a consistent 0–10 scale and percentages on a consistent scale where applicable.
- Counts, percentages, currency and score changes must not share a magnitude axis. Split mixed-unit charts into separate panels.
- Missing measurements must remain missing, not become zero. Show cohort sizes for outcome comparisons and explain denominators.
- Mobile charts need readable labels and adequate bar widths; reduce visible categories or paginate rather than squeeze an entire desktop plot into a narrow card. Values must be available without hovering, with an accessible data table.

## Existing charts

Paths below are relative to the repository. Each row identifies a chart or related chart family, rather than a count of every rendered instance.

### Analytics and reports

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| Performance Overview | Planned/completed bars with achievement line | Grouped count columns; separate achievement columns | `templates/partials/analytics/performance_overview.html` |
| CD Performance vs Target Over Time | Mixed counts and achievement percentage | Grouped count columns; separate percentage panel | `templates/partials/analytics/cd/performance_vs_target.html` |
| Target Achievement by PL and CCEO | Comparison bars | Standard grouped bars | `templates/partials/analytics/cd/target_by_pl.html` |
| PL Staff & Partner Performance | Comparison bars | Standard grouped bars | `templates/partials/analytics/pl/staff_partner.html` |
| Core & Champion School Performance | Two score lines | Grouped columns by period | `templates/partials/analytics/pl/core_champion.html` |
| SSA Performance by Intervention, general/PL/CD variants | CSS horizontal score bars | Standard horizontal bars, 0–10 | `templates/partials/analytics/ssa_performance.html`, `pl/ssa_interventions.html`, `cd/ssa_interventions.html` |
| Staff & Partner Performance summary | Two CSS percentage bars | Grouped horizontal bars | `templates/partials/analytics/staff_partner_performance.html` |
| CD Budget and Finance Health | Utilization radial gauge and budget bars | Utilization bar plus separate currency comparison | `templates/partials/analytics/cd/budget_finance.html` |
| Target progress timeline | Per-period donut gauges | Chronological percentage columns | `templates/partials/analytics/panels/reports.html` |
| Cumulative Progress Trend | Comparison bars | Standard grouped columns | `templates/partials/analytics/panels/reports.html` |
| Achievement vs Target | Donut | Actual/target bars with explicit units | `templates/partials/analytics/panels/reports.html` |
| Dose–response: support intensity vs improvement | Grouped bars | Standard grouped bars; retain exposure buckets and cohort sizes | `templates/partials/analytics/impact_workspace.html`, `static/js/alpine-components.js: impactChart` |
| Funding vs improvement | Scatter plot | Median improvement by defined spending band; retain individual records in table | Same impact workspace/component |
| Geography: district × intervention improvement | Heatmap | Horizontal district bars with intervention filter | Same impact workspace/component |
| SSA change by intervention | Baseline/follow-up grouped bars | Standard grouped horizontal bars | `templates/partials/analytics/visit_effectiveness_workspace.html`, `static/js/alpine-components.js: visitFxChart` |
| Delivered visits vs SSA change | Core/client scatter plot | Grouped score-change bars by visit-count band | Same visit-effectiveness workspace/component |
| Visit purpose mix | Donut | Ranked horizontal counts | Same visit-effectiveness workspace/component |
| School outcomes | Category columns | Standard columns | Same visit-effectiveness workspace/component |
| Visit alignment funnel | Horizontal bars | Standard horizontal counts in workflow order | Same visit-effectiveness workspace/component |

Scatter replacements are new aggregations, not a chart-type toggle. Define bands, show sample sizes, and avoid implying that support or spending caused an improvement.

### Role dashboards

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| CD Country Performance Overview | Planned/completed bars and achievement/prior-year lines | Count comparison columns; separate achievement panel | `templates/partials/dashboards/cd/operations.html` |
| CD PL achievement and target indicators | Compact percentage bars | Consistent horizontal bars | Same CD template |
| CD Cluster SSA Heatmap | Colored score matrix | Cluster bars filtered by intervention; retain detailed matrix table | Same CD template |
| RVP Regional Performance Overview | Mixed bars and lines | Grouped count columns; separate percentage panel | `templates/partials/dashboards/rvp/operations.html` |
| RVP resource allocation share | Compact horizontal bars | Standard horizontal allocation bars | Same RVP template |
| PL delivery by month | Stacked activity columns and cumulative percentage line | Grouped activity columns, filtered to four series; separate cumulative panel | `templates/partials/dashboards/pl/programmes_view.html` |
| Admin Planning Progress | SVG line/area | Period columns | `templates/partials/dashboards/admin/_planning_progress_body.html` |
| Admin Cluster Performance trend | Identical hardcoded SVG curve per row | Remove decorative trend; show bars only when real historical scores exist | `templates/partials/dashboards/admin/operations.html` |
| Admin SSA Performance Snapshot | Best/weakest intervention bars | Standard ranked horizontal bars | Same admin template |
| Admin Partner Support Overview | Decorative miniature columns | Replace with actual period delivery data or remove | Same admin template |
| RPL Programme delivery | Completed/planned CSS bars | Grouped horizontal bars per programme | `templates/partials/dashboards/rpl/delivery_mix.html` |
| IA Eight-week activity flow | Planned/verified lines | Grouped weekly columns | `templates/partials/ia/operations.html` |
| IA SSA coverage | Stacked progress indicator | Horizontal counts by coverage state | Same IA template |
| IA Evidence quality | CSS percentage bars | Standard horizontal percentages | Same IA template |

### People and professional development

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| Workforce through the year | Headcount line, joined/left columns | Headcount columns; separate joined/left comparison | `templates/partials/dashboards/hr/operations.html` |
| Recruitment | Horizontal funnel bars | Standard bars in recruitment-stage order | Same HR template |
| Review cycle | CSS stage progress bars | Standard horizontal counts, percentages in labels | Same HR template |
| Final ratings | 100% stacked horizontal bars | Grouped rating percentages by category | Same HR template |
| Leave by type | Donut | Ranked horizontal days | Same HR template |
| Headcount by role | CSS horizontal bars | Standard ranked headcount bars | Same HR template |
| Course Status Distribution | Donut | Horizontal course counts | `templates/partials/hr/pd_dashboard/body.html` |
| Fund Utilization | Donut | Currency bars with utilization percentage alongside | Same PD template |

### Targets, debriefs and verification

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| My Targets: cumulative progress | Actual/expected pace lines | Grouped percentage columns by period | `templates/partials/targets/my_body.html` |
| Team performance trend | Line | Period columns | `templates/partials/targets/team/body.html` |
| Debrief Trend Over Time | Four lines | Four-series grouped columns using requested palette | `templates/partials/debriefs/dashboard_body.html` |
| Debriefs by Activity Type | Donut | Ranked horizontal counts | Same debrief template |
| Debriefs by Risk Level | Donut | Category count bars; retain explicit risk labels | Same debrief template |
| Return rate by month | HTML horizontal bars | Chronological percentage columns | `templates/pages/ia/verification_analytics.html` |

### Schools, SSA and projects

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| SSA performance trend by year | Line | Annual score columns | `templates/partials/ssa/performance_workspace.html` |
| District performance and intervention gaps | Colored tiles/matrix | District score bars with intervention filter; retain table | Same SSA workspace |
| School Data Quality Score | SVG donut gauge | Horizontal completeness percentage | `templates/pages/schools/detail.html` |
| School confirmed SSA by intervention | CSS horizontal score bars | Standard horizontal scores | Same school detail template |
| School Annual SSA Progress | CSS horizontal bars | Annual columns | Same school detail template |
| Core School Outcomes by Staff | Horizontal score bars | Standard ranked bars | `templates/partials/core_schools/performance_insights.html` |
| Core School Outcomes by Partner | Horizontal score bars | Standard ranked bars | Same core insights template |
| Core Performance by Region | Horizontal scores with average marker | Region/overall grouped bars | Same core insights template |
| Staff vs Partner by Intervention | Paired miniature horizontal bars | Standard grouped horizontal bars | Same core insights template |
| Verified Assessment Outcome Trend | SVG line/area | Period columns | Same core insights template |
| Champion graduation formula score | SVG donut gauge | Score bar with threshold stated in text | `templates/partials/core_schools/champion_review_drawer.html` |
| Project Budget & Execution | Utilization progress bar | Consistent utilization indicator | `templates/pages/projects/index.html` |
| Project Impact by Intervention | Staff/partner stacked horizontal bars | Grouped bars; label delivered activity counts accurately | Same project index template |
| Partner Delivery | Completion bars | Standard horizontal completion bars | Same project index template |
| Annual Project Impact Overview | CSS columns | Separate improved-school counts from mean score change | `templates/partials/projects/analytics_workspace.html` |
| Annual SSA Performance | Paired baseline/latest bars | Standard grouped horizontal scores | Same project analytics template |
| Project Spend Efficiency | CSS bars currently sized by delivery rate | Actual cost-per-improved-school bars; separate delivery percentage panel | Same project analytics template |

The project impact columns currently use improved-school counts for height while displaying average delta. Spend-efficiency bars use delivery rate while surrounding labels describe spend and outcomes. Both require metric corrections as well as styling.

### Partners and finance

| Existing chart | Current presentation | Proposed presentation | Source |
|---|---|---|---|
| Partner Scheduling Status Breakdown | Donut | Horizontal status counts | `templates/pages/partners/index.html` |
| Fund allocation/approval progress | Horizontal progress indicator | Consistent progress bar with currency and percentage labels | `templates/partials/finance/fund_workspace.html` |
| Approval Rate This Month | SVG donut | Decision-count bars with approval percentage stated | Same fund workspace |

### Other visualizations and compact indicators

- Geographic school/subregion maps: `templates/partials/analytics/regional_performance.html` and `_regional_performance_script.html`, reused by role views. Keep these as maps for location tasks; include any adjacent statistical summaries in the bar standard.
- Leave/team availability grids: `templates/pages/leave/leave_tracker.html`, `team_availability.html`, `personal_time_off.html`, and `templates/partials/leave/impact_panel.html`. These are scheduling/availability views, not statistical plots; preserve their calendar function.
- Activity tracking, target priorities, contribution summaries and dashboard cards contain additional compact progress indicators. Apply consistent colors, readable labels and real denominators without turning every KPI into a full chart.
- `templates/partials/analytics/pl/district_performance.html` and `target_by_district.html` are table-oriented views, not additional plotted charts. Finance accountant insights and business-transformation impact reports should likewise not be counted as charts merely because they contain chart icons.

## Recommended graph coverage

These are additions or improvements, subject to verifying that the underlying data is available and consistently defined. Keep actionable record tables below the graphs.

| Priority | Area | Recommended graph and decision it supports |
|---|---|---|
| 1 | My Plan, Team Planning, Work Plan | Planned/completed/overdue activities by week or month; identify delivery gaps. Show overdue as a clearly defined subset to avoid double counting. |
| 1 | Planning oversight | Planned versus target by district, CCEO, activity type and cluster; find areas without sufficient coverage. |
| 1 | PL Today | Small current-period planned/completed comparison and overdue counts; keep action lists prominent. |
| 1 | Core school oversight | Planned/delivered visits by officer or district, and schools visited versus eligible schools. |
| 1 | Cluster oversight | Planned/completed meetings and trainings by cluster; invited/attended participants as a separate comparison. |
| 1 | Training oversight | Planned/completed trainings and invited/attended participants, filtered by in-school/cluster training. |
| 1 | Budget and fund requests | Budget/requested/approved/spent comparison by period or district, with disbursements in a separate panel where needed. All currency measures must use the same accounting scope. |
| 1 | Staff daily activity costs | Allocated staff cost by activity/district and daily total. Use the agreed shared daily-cost allocation across all activities; do not multiply a full daily allowance by each visit. |
| 1 | Targets | Actual versus target by priority, plus period progress columns; retain one definition of verified achievement. |
| 2 | Team and partner debriefs | Expected/submitted/reviewed counts, submission timeliness, top challenges and open/closed follow-up actions. |
| 2 | Verification | Pending/returned/verified counts, aging bands and ranked return reasons. Separate stock in the queue from period decisions. |
| 2 | SSA and school improvement | Baseline/latest scores by intervention; improved/unchanged/declined counts with assessed cohort sizes. |
| 2 | Projects and programme rollout | Planned/delivered outputs, school reach, outcomes and cost efficiency in separate panels with accurate units. |
| 2 | Partner management | Planned/completed activities and debrief completion by partner, with portfolio size available for context. |
| 2 | HR and Team Leave | Leave days by month/type and staffing availability by team; keep the operational leave calendar. |
| 2 | Professional development | Planned/in-progress/completed courses and budget/spend comparisons. |
| 3 | Country and regional leadership | Country/district target achievement, coverage and funding comparisons using consistent filters and periods. |
| 3 | Business transformation | Measured outcome counts by programme, period and district, with unmeasured cases explicit. |
| 3 | Data quality | Missing evidence, stale assessments and incomplete school records by district/officer. |

## Implementation sequence and verification

1. Standardize shared bar configuration in `templates/base.html` (`EdifyChartSystem`) and the four-series palette. Build horizontal, vertical and grouped variants.
2. Convert line/area/mixed charts, splitting incompatible units. Convert donuts/gauges and redesign scatter aggregations.
3. Migrate independent CSS/SVG charts and the `impactChart`/`visitFxChart` renderers. Remove fake admin trends.
4. Correct project metric mismatches. Add priority-1 planning and oversight graphs after verifying query definitions and access scope.
5. Verify desktop/mobile, all themes, empty/missing/negative values, many categories, filters, role scope, HTMX refresh and exports. Ensure labels and bar dimensions encode the same metric.
6. Update existing chart contract tests deliberately: some currently require line/mixed/radial charts and conflict with the new requirement. Check `apps/frontend/test_bar_chart_system.py`, `apps/frontend/test_chart_system_coverage.py`, and `apps/system_health/test_charts_render_detached.py`.

## Implementation status

### 21 September 2026 — people as series, right-sized cards

The Programme Lead's charts now read the team as people. On Team Oversight
(planning lens), Cluster Oversight, Core School Oversight and the Team Core
Oversight card, every chart has one series per person — the lead's own work
first, then each supervised officer — and the PL dashboard's Team Execution
Progress shows completed work by month per person rather than per delivery
family. The Country Director's counterparts read one series per Programme
Lead. A person's series position is their colour: `--edify-series-1..8` are
assigned in row order and never re-assigned across pages or panels, and the
renderer reads the tokens live so dark and blue themes draw their own
validated steps (light and dark palettes both pass the categorical checks:
worst adjacent CVD ΔE 10.8 / 9.6, worst normal-vision pair 24.9 / 19.3).

Shared geometry, in `static/js/chart-standard.js`: a 220px plot (plus a 28px
legend row for comparisons), bars capped at 22px thick with a 2px surface gap,
rectangular ends, one hairline grid, 11px muted value labels that stay silent
when a bar has no room for them, a top-left legend, and pages sized by series
count (12 categories for one or two series, 8 for up to four, 6 above that)
so a bar never drops below a readable width. Cards carry a quiet 14px title
and 12px subtitle and fold their data table under a "View chart data" link.
Per-school charts were retired from the core-school tables in favour of the
per-officer chart above them; the school rows remain the record.

Earlier status follows.


The shared rendering boundary now converts chart-library plots to the bar standard, separates rate/count axes, uses the four-color palette, and provides range selection and accessible data tables. Scalar donut/gauge payloads become horizontal category bars. Heatmap data becomes bar panels. Scatter data becomes per-observation bars, preserving duplicates and missing values without introducing new statistical aggregations; the spending/exposure bins proposed above remain a future analytical enhancement.

Independent admin/core trends and shared ring gauges now use rectangular bars; decorative admin sparklines were removed. Project bars now label improved-school counts consistently and compare allocated budget per improved school (not actual expenditure). District SSA tiles became a score comparison chart. Detailed score matrices, calendars and maps remain available.

Added scoped charts: team/country planning progress, core-school scheduled and completed visits/trainings against targets, cluster activity coverage, and cluster/district SSA comparisons. Other graph coverage recommendations above remain a prioritized backlog, not a claim of delivered functionality.

Validation includes normalization tests for missing/negative values, duplicate observations, unit separation and large comparisons; Django payload/escaping and compatibility tests; project analytics tests; and a browser regression for the palette, data tables, range changes, teardown and mobile overflow across light/dark/blue themes.

