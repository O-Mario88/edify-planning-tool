# 45 — Project Monitoring, piece 1 (read)

Go answers `PageScreenService.GetPage` for `/projects/monitoring` (Project
Monitoring) in `platform/backend/internal/projectmonitoring`, for every role
the page admits (CCEO, Programme Lead, IA, Country Director, Admin, Project
Coordinator; every other role is NotFound, as the feed's 404). The page is
`apps.frontend.views.extended_views.project_monitoring_view`, its service
`apps.projects.monitoring`, its templates `pages/projects/monitoring.html` and
`partials/projects/monitoring_school_table.html`.

## Scope of this piece

Go builds the page while **no project work exists in view**: no project
activity of the reader's projects (any year, any state — they also decide the
withdrawal blocks), no partner hand-over, and no school allocation of those
projects or of the reader. Every school is then "Awaiting Project Coordinator
Action", which is exactly what the development seed holds (5 projects, 26
enrolments, 0 project activities, 0 hand-overs, 0 allocations). A page holding
any of those, a measured impact cohort (the four-figure grid), or an open
table past one page (the pager) is **passed on** (`served=false`) to the
existing application, never guessed. The rest is backlog item
`project-monitoring-2`.

What Go draws: header (three lens descriptions + "Activities read for FY
2027–2028" from `planning_horizon`/`horizon_label`), the seven filters
(district, stage, fiscal year, partner, training, purpose, activity status;
column filters offer the reader's own rows' values, casefold-sorted, plus a
picked value), the hidden open project, the Project Coordinator's workspace
strip, the KPI strip (six lens figures + the open project's four), the
CCEO/PL workload line (`planningpage.WorkloadLine`, the same
`staff_plan.own_workload`), one tab per project with its filtered count, the
open project's 19-column table (title, pills subtitle, row details: Added by,
the impact verdict, each focus intervention's readings), the coordinator's
tick boxes and Schedule/Assign doors, Withdraw from project for the readers
`may_withdraw` admits, the CD's View-only cell, the empty-row messages, the
"Not measured yet" footnote, the read-only note and both empty states.

## Rules ported

| Rule | Python | Go |
|---|---|---|
| Who opens it, profile links, the strip | `require_page_permission("project_monitoring")`, `can_open_url`, `build_workspace` | `rules.json` doors (computed per role by the export) |
| Lens | `WHOLE_PROJECT_ROLES`, `controls_project_work`, `owner_ids` | `lens` |
| Projects | `_projects_for` (+ `_scoped_projects` for the coordinator), live statuses, by name | `projectsFor` |
| Enrolments | `_visible_assignments` over `current_enrolments` (operating schools), by school name | `enrolments` |
| Project's schools | `_activity_totals` enrolled_total (bounded by the watcher's schools) | `enrolledTotals` |
| Targets | `target_intervention_list`, `intervention_plan`, `measured_by_ssa` | `project.targetList/plan/measuredBySSA` |
| SSA readings | `_focus_readings` (same statement shape, `ORDER BY 4`), `_reading`, `_attach_ssa`, `_attach_scores` | `focusReadings`, `readingOf`, `schoolRowOf` |
| Verdict | `IMPACT_LABELS`, "No focus set", "Previous FY SSA missing", "Awaiting delivery" | `schoolRowOf` |
| Cohort | `ssa_impact.project_impact` (whole readers: every enrolment incl. closed schools; watchers: their own) | `projectImpact` |
| Withdraw door | `may_withdraw` (`WITHDRAW_ANY_SCHOOL_ROLES`, lifted to a module constant) | `projectRows` |
| Tick boxes | `can_tick` with `past_school_rules(project_id="any")` | open project + coordinator; rules load refuses if the lift is withdrawn |
| Filters / stage | `STAGE_FILTERS`, `ROW_FILTERS`, `row_picks`, `row_filter_options`, `ProjectSchoolRow.matches` | `filters`, `schoolRow.matches` |
| Year | `_monitoring_fy` (FY selector's years, else operational) | `build` |

Exported by `python manage.py export_project_monitoring_rules`
(`apps/projects/management/commands/export_project_monitoring_rules.py`),
drift test `apps/projects/test_project_monitoring_rules_export.py`.

## Found by comparing

The first three-account run (`cceo`, `coordinator`, `cd`) was 0 differing once
the grants were in; no rendering difference had to be fixed. Notes:
`enrolled_on` falls back to the UTC day of `created_at` (Django's aware
datetime `.date()`); SSA dates likewise read in UTC; the reader skips the
blocked "Withdraw from project" (no `hx-get`) and reads the CD's lone View
button as a plain "View" cell; the header's Export and Consolidated tables
links are plain anchors the feed does not read.

## Parity (Go-only gateway 127.0.0.1:8081, Django 127.0.0.1:8181 over edify_gorn_dev)

- 3 accounts: `85 answers compared, 0 differing`
- All 29 accounts (`-pause 20s`): `603 answers compared, 0 differing`

## Tests

- `go test ./internal/projectmonitoring/`: targets and General, enrolment
  intervention, readings (baseline at enrolment, snapshot, latest since),
  verdict branches, scores/improvement/details text, stage and column
  filters, pass-on of a measured cohort and of a second page, actions by
  reader (watcher, paused project, coordinator), Python formatting.
- Integration (`internal/integration/project_monitoring_test.go`): the
  coordinator's page, refusal for Business Transformation, and pass-on when an
  allocation exists.

## Grants

Appended to `platform/deploy/db/roles.sql`:
`project (code)`, `project_school_assignment (assigned_by,
participation_type, matched_intervention, support_area,
impact_classification, start_date, baseline_score)`.

## Left (backlog `project-monitoring-2`)

The work lines (activities, partner hand-overs, cancelled work), their
Status/Activity Status/Activity Cost/Planning Stage/Planned By/Execution, the
coordinator's Withdraw/Reassign and Resolve doors, withdrawal blocks, overdue
chips, project activity counts, allocations (table and capacity pill), the
measured cohort grid, the table pager, and the Special Projects pages
(`/projects/planning`, `/projects/my-plan`). All need golden comparison on
synthetic rows: the seed reaches none of them.
