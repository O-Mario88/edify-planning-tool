# 35. The Work Plan (M4), read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11), M4: "Read: My Plan, Work Plan, calendar". The Work Plan is the
one scoped ledger of planned activities over a period: the CD → RVP
approval, the period tabs and filters, the Activity Plan Summary, the
strip, the month bands and the Detailed Activity Plan.

| Piece | What moves | State |
|---|---|---|
| 1 | The whole page (`/work-plan`, and `/work-plan/`) for every role that may open it | This document |
| — | Add Non-School Activity, the row drawers (Complete, Reschedule, Cancel), Send to …, the Excel export and the CD → RVP submission | Still the existing application's: the page only links to them |

## 35.1 What moved

`PageScreenService.GetPage` is answered by `platform/backend/internal/workplan`
for `/work-plan` for someone working in their own role (an acting capacity
is passed to the existing application by the gateway, as for every page).
Go builds the blocks the feed reads from
`apps.frontend.views.work_plan_page.build_work_plan_context` and the page's
templates (`pages/work_plan/index.html`, `partials/work_plan/plan_summary.html`,
`partials/work_plan/detail_tables.html`), straight from the database. There
is no pass to the existing application: every reader the page admits is
answered by Go.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("work_plan")` and the feed's `can_open_url`: CCEO, Program Lead, Country Director, Regional Vice President, Impact Assessment, Accountant, Human Resources, Project Coordinator, Admin. Anyone else is not found |
| The year | The planning year once it is open (`fy_policy.next_open_fy`: the nearest later year whose `planning_open_at` has passed), else the running one; a year the selector does not offer (`fy_options`) is the default. Other pages stay on the operational FY |
| The period | `view` month / quarter / fy (anything else is month); a month as Python's `int()` reads it (`" 3 "`, `"1_2"`), out of range or the year changed with the form (`fy_prev`) → this month in the running year, else October; a quarter `Q1`–`Q4` (case-sensitive), else this quarter or Q1 |
| Whose activities | `_scoped_activities`: the country for Admin, Country Director and Accountant; the RVP's regional reach by the school's, cluster's or event's district (everything without one); a coordinator's `scoped_projects`; otherwise the reader's work in both id spaces, partner work they monitor, and on a Program Lead's **My Plan + Team** their live supervisees' |
| Filters | Status (a terminal or awaiting-owner status only when asked for), responsible person, project, activity type and executor (an unknown type or executor is ignored but kept in the links), and the drill-down flag (pending approval, cost setup required, at risk) |
| The window | `_window_q`: planned in the window, begun before it and running into it, or (no planned date) scheduled in it on Kampala's day; ordered planned date, made, id |
| Bands and cost | Every activity in exactly one band (a spill-over clamped to the window's edge); each cost line in its own service month's band, counted once; a line without a date or month counted only when the activity's day is in the window |
| Strip | Activities Planned, Activities This Month (the scoped year over this calendar month), Plan-Derived Budget (a million or more short, `kpi_value`), Pending Approval (a weekly request with the PL or CD), Cost Setup Required, Activities At Risk (open work whose last day has passed) |
| Summary | One line per executor and type (a non-school activity by its planned name or catalogue item; the UGX 0 half of an in-school pair on a line of its own), by cost then name; the unit cost the average to the cent, half up; "Cost setup required" where any is missing; the note of the free half kept only while its line is UGX 0 |
| Detailed Activity Plan | 15 fixed columns (owner, 2026-10-05): Activity Visit / Training / Meeting / the programme type; Activity Purpose and Delivery Mode in the owner's words; SSA Intervention General for non-school work and work under a project no SSA measures; the SSA verdict and the planner's reason; Previous SSA Score to one place; the cost with its breakdown; Status Scheduled / Complete / Planned / Cancelled; 50 rows a page |
| Row actions | `work_plan_action` and `compute_next_action`: the reader's own open work as Complete (dated and scheduled), Reschedule or Schedule, Cancel and View details; somebody else's as Send to the person (the Country Director: Send to PL, to the Program Lead over them); closed work as View; anything else the next action; each link only for a role `can_open_url` lets in |
| Ticks | A tick box on the reader's own open staff work, the bar (Reschedule, Cancel) when any row has one |
| Day-off marks | `day_off.day_off_marks`: work still waiting for its day on a public holiday (the national calendar, a recorded `PublicHoliday`, a `PUBLIC_HOLIDAY` calendar block, a recorded Eid replacing the expected one within seven days) or on its responsible staff member's approved leave: "Public holiday: reschedule" in the date cell and the row's day-off tone |
| Approval | `approval_context`: the year's `CountryAnnualBudget` status and the line under it (the RVP's note; the readiness issues for the CD and Admin while it can be submitted; submitted; approved) |
| Workspace strip | The Project Coordinator's Finance strip (Budget, Weekly Advance Request, Work Plan) from `build_workspace` |

Every role's doors (the page, Add Non-School Activity, Export, the
operational-admin and no-action roles, each row link's `can_open_url` and
the workspace strip), the statuses, types and their labels, the flag,
tab and scope labels, the readiness issues, the strip's labels and units,
the pair notes, `compute_next_action`'s lists and the national holiday
calendar for 2015–2045 are exported to `internal/workplan/rules.json` by
`manage.py export_work_plan_rules`; `apps/frontend/test_work_plan_rules_export.py`
fails when the two differ. The flag, tab and scope labels were local to
`build_work_plan_context` and the readiness issues to `readiness_issues`;
they are now module constants (`FLAG_LABELS`, `VIEW_TAB_LABELS`,
`SCOPE_TAB_LABELS`, `SCOPE_LABELS`, `NO_ACTIVITY_ISSUE` and the rest) so the
export reads them. Nothing they say changed. The pair notes are
`myplan.PairNotes` (a wrapper over My Plan's own port, `internal/myplan/export_workplan.go`);
the projects no SSA measures are `visitgate.ProjectsOutsideSSA`; the strip
is `schoolprofile.Strip`.

## 35.2 Found by comparing and reading

- **The Responsible person select had no order of its own between two ids
  with one name.** The view sorted a set of (id, name) by name alone, so a
  person's staff-profile id and account id ("Paul N." twice in the seed)
  came out in a different order from one Python process to the next (five
  runs of the same view gave both orders). The sort key is now (name, id);
  any order was possible before, so nothing a reader relied on changed, and
  Go sorts the same way.
- **The Undated band can never show.** The page's window only selects
  activities with a planned or scheduled date, so an activity reaching the
  band loop always has a day: the Undated band and "Not dated" are
  unreachable. Go keeps the rule and the golden data (undated activities in
  every month) confirms it never shows.
- The strip writes a budget of a million or more short ("UGX 3.83M"), as
  every strip does; the band and summary figures stay whole.
- The feed collapses every text it reads: a name with stray spaces
  ("  G19   Bare  ") reads with single spaces, in the row and in its Send to
  label, but not in an action's title.

## 35.3 Proving it is the same

`cmd/parity -screen page -path /work-plan` signs each account in and asks the
Go-only gateway and the existing feed the same questions: the page as it
opens; each view and one that is none or padded; months 10, 12, 1, 3, 9, 0,
13, "abc", " 3 ", "1_1" and "Q2"; each quarter, "q2", "Q9" and "11"; years
2025–2028, 1999 and " 2027 "; `fy_prev` alone and with a changed and an
unchanged year; a bad status and a padded one; an unknown type and
executor, each executor; an unknown person and project; each flag and a bad
one; `scope` own, team and bogus; `wp_page` 2, 0, "abc", 999; a download key
the feed never passes (`export`) and a key the page does not read; eighteen
combinations; then every status the select offers (with and without the FY
view), every activity type with the FY view, and every person and project
the page offers. For this page the comparison keeps each side's row order
exactly (`exactOrder` in `cmd/parity/page_work_plan.go`; other pages still
re-sort rows that share a name).

All 29 seed accounts against a gateway with no existing application behind
it (the Django on 8181 from this worktree, over `edify_gorn_dev`):

```
3993 answers compared, 0 differing
```

That is 146 questions for each reader with rows (Admin, the officer with
rows, the Country Director, the first Program Lead), 144 for Impact
Assessment and the coordinator, 139 for each officer or lead with none, and
63 for Business Transformation, refused. A first run on two officers ended
`285 answers compared, 0 differing`; one on seven more accounts ended
`928 answers compared, 4 differing`, every one the FY 2026 budget tile, which
the existing strip writes short (35.2). The run above is after that fix.

**The golden comparison.** The seed reaches one officer's rows, a Program
Lead's team and the country readers; it has no partner rows of the reader's
own, no day off, no SSA verdict, no approval envelope, no money in a weekly
request or advance, no page past 50 rows and no RVP, Accountant or HR
account. `internal/workplan/testdata/work_plan_golden.py` files synthetic
people in every role the page serves (a CCEO and a peer sharing a name, a
Program Lead over both, a Country Director, an Admin, an RVP with a region,
an Accountant, HR, a coordinator with two projects, one no SSA measures,
IA, and accounts with no profile and no name), a live and a soft-deleted
partner and cluster, four schools (a School ID with a slash, an empty one,
one padded, one with no district), 377 activities of every type and status
over the year and either side of it (dated, scheduled only on either side
of Kampala's midnight, undated, several days long, on Christmas, a recorded
holiday, a calendar block, the expected and the recorded Eid and approved
and pending leave), in-school pairs priced either way and one whose visit
was called off, an online training, non-school work, cost lines in and out
of the period with months and fiscal years, weekly requests and advances in
every state, SSA verdicts and the planner's reason, and the FY 2025, 2026
and 2028 approval envelopes (approved, submitted, returned with a note),
into this worktree's Go integration database (`edify_gorn_a19_test`), asks
the unmodified feed for 25 queries and each person's and project's choices
as each person, and `page_golden_test.go` compares Go's page with each,
field for field:

```
313 pages compared (5151 rows of the Detailed Activity Plan), 0 differing
```

The records were removed afterwards (`MODE=remove`).

Unit tests (`internal/workplan/page_test.go`): the year and period read
(planning year, padded and underscored months, case-sensitive quarters, the
year changed with the form), a Program Lead's two audiences, the links'
query edits, the unit cost's rounding, the date labels, `str.title()`, every
branch of `compute_next_action`, `work_plan_action`, an exported answer for
every row link, the panel pairing, Eid spellings and the day-off labels, the
holiday calendar's years, and thousands separators. Integration tests
(`internal/integration/work_plan_test.go`): the page as it opens for an
officer (approval, tabs, filters, the 15 columns), the refusal, and an
officer's own visit with its cost line, menu, tick and strip.

## 35.4 What is not proved, and what is left

- The Activity Plan Summary's own pager (more than 50 summary lines in one
  section) is drawn but was not reached by the seed or the golden data; its
  page parameter (`section_rows_page-1`) is not a key the feed passes, so
  only its first page can ever be asked for.
- The Impact Assessment workspace strip and a workspace divider are not
  drawn: no role has either on this page today, and `rules.json` refuses to
  load if one appears.
- Every drawer, the export workbook and the CD → RVP submission and RVP
  decision stay the existing application's.
