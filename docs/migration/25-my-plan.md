# 25. My Plan (M4), read by Go, in pieces

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "Activity planning and scheduling". My Plan is the page field
staff open every day, and two other pages wait on it: Core School
Oversight's Core School Visits and Core School Trainings tabs are My Plan's
own tables (22-core-schools-oversight.md). It is far too large to move at
once — `get_frontend_context` alone is 2,640 lines, and the page reads the
planning monitor, the training ceilings, the cluster planning status, the
costing service and the money chain — so it moves in pieces, as the Planning
page did (24-planning-page.md).

| Piece | What moves | State |
|---|---|---|
| 1 | The page as it opens for a member of staff who holds nothing yet and has no visit target: header, period tabs, the filter row, Plan progress, the four plan tables' empty states, Plan Breakdown by Period, the bar for ticked activities | Done, 25.2 |
| 2 | Plan progress and the breakdown counted (the period tiles, counted visits by school type, outreach, the completed share, the past-due note), still with nothing listed | Not started |
| 3 | The plan's rows: School Visits, Trainings (with the cluster expansion), Group Trainings, Cluster Meetings, Core School Visits, Core School Trainings, programme and Programme-school work; cost, budget status, verification, status pill, row tone, completion columns, row Actions, ticks, pagers; and the Returned, day-off and attention cards | Not started — the shared rows Core School Oversight's two tabs need |
| 4 | A Programme Lead's or CCEO's own Planned and remaining (`readiness.own`, `planning_monitor.own_monitor`), the visit-target helper and ceiling notice, and the readiness list (`?list=`) | Not started |
| 5 | My Training Summary (`training_ceilings.own_summary`) and Cluster Planning Status (`clusters.planning_status`) | Not started |
| 6 | The partner's own My Plan (`partner_views.partner_plan_context`): five sections, facilitated clusters, training facilitations, Invoices & Payments | Not started |
| — | Every drawer and save the page opens, the export drawer and the workbook | Still the existing application's |

## 25.1 The map

The feed (`apps.mobile_feed`) reads `/my-plan` (`my_plan_views.my_plan_view`
under `require_page_permission("my_plan")`) and inlines the part it loads
later (`/my-plan/readiness`, `my_plan_panel_views.my_plan_readiness_view`).
As the app receives it, in order:

| Block | When it is there | Source |
|---|---|---|
| Header: "My Work", "My Plan", Export (opens `/my-plan/export-drawer` with the page's query) | always | `pages/my_plan/index.html` |
| Period tabs This Week / This Month / This Quarter / This FY, Open Calendar beside | always | `partials/my_plan/filters.html` |
| Filters: Fiscal year, Quarter, Month, District, Staff member, Activity type, Status; hidden `period`, `fy_prev`, `quarter_prev` | always | same |
| Reschedule — On a Public Holiday or Leave Day | listed work on a day off | `attention.html`, `activities.day_off` |
| Returned — Needs Correction (and the other attention cards) | listed work sent back | `attention.html` |
| Plan progress: eight tiles | always | `kpi_cards.html`, metric registry |
| "What needs you now" note | planned work past its date, not delivered | `kpi_cards.html` |
| Planned and remaining · FY | a Programme Lead or CCEO by any role held | `readiness.html` (loaded later), `readiness.own` |
| My training summary FY, its table and note | the reader has a ceiling or committed schools | `trainings/my_summary.html` |
| School Visits / Trainings / Group Trainings / Cluster Meetings Planned for This … | always (empty state when none) | the four table partials |
| Cluster Planning Status | the reader leads a cluster | `cluster_planning_status.html` |
| Core School Visits / Core School Trainings Planned for This … | core work in the period | the two core partials |
| Programme-school work, programme activities | such work in the period | their partials |
| Plan Breakdown by Period | always | `period_breakdown.html` |
| Selection: Reschedule, Cancel | always | `activities/selection_bar.html` |

**Who sees it.** `my_plan` in `PAGE_ACCESS` and the feed's `can_open_url`:
everyone but Business Transformation, Cluster Leader, Human Resources, the
two MFI roles, Regional Programme Lead and Regional Vice President, who are
not found. A Programme Lead or a CCEO (by any role held, not only the one in
use: `country_oversight.rules.planning_role`) also gets Planned and
remaining and a visit target (280 / 560) under the visits tile.

**The partner variant.** When `scoping.resolve_partner_ids` finds the login's
partner (its own login, or an active team membership), the view draws
`pages/partner/my_plan.html` instead: Needs Attention, In Progress, Due
Today, Planned This Week, Planned Later, the clusters it facilitates, its
training facilitations, and Invoices & Payments for the partner's admin only
(`member_scope.sees_money`). It shares nothing with the staff page but the
header.

**The seed.** Of the 29 accounts, one (`cceo@edify.org`) has rows; 23
planners (cceo1–19, pl1–4) have Planned and remaining over no schools; four
(Admin, Country Director, Impact Assessment, Project Coordinator) hold
nothing; Business Transformation is refused.

## 25.2 What moved (piece 1)

`PageScreenService.GetPage` is answered by `platform/backend/internal/myplan`
for `/my-plan` when the reader works in their own role, may open the page,
is neither a Programme Lead nor a CCEO by any role held, and holds nothing
the page would list or summarise. Everyone else is passed to the existing
application, as before:

| Passed to the existing application | Why |
|---|---|
| Any other address (`/my-plan/`, `/my-plan/readiness`, an activity) | not this page |
| A request carrying an Export options period key (`from_month`, `to_month`, `start_date`, `end_date`, `period_type`) | the view answers with a workbook |
| A year, month or week the view fails on (not a whole number; a year before 1 or after 9999 once the month is placed; a month outside 1–12; a week outside 1–5 or past the month's end, such as the fifth week of a February of 28 days) | `int()`, `calendar.monthrange` and `date()` raise: the page is an error |
| A Programme Lead or CCEO by any role held | Planned and remaining, the target (pieces 2 and 4) |
| Anyone who holds anything: an activity they own or monitor (any year, any state, deleted ones too), a school they hold, a cluster they lead, a partner hand-over they made or follow, a training ceiling set for them, or a partner organisation the login is or belongs to | rows, counts, summaries or the partner's page (pieces 2–6); asked of every row, so a page Go answers has none of them |
| `PARTNER_ROLE_BRIDGE` on | every reader is a partner |
| Anyone in an acting capacity | the gateway passes them before any page |

A `?format=` other than `json` is not found for everyone, before the page is
asked: the feed is a REST framework view with only the JSON renderer.

| Part | Existing rule it ports |
|---|---|
| The period (`myplan.ReadPeriod`) | `get_frontend_context`: the year as sent, else today's in Kampala; a wider year (`fy_prev` and `fy` both sent and different) clears quarter and month, a wider quarter clears the month; "", all, any, none (stripped, any case) are no choice; a quarter opens at its first month (Q1 October, Q2 January, Q3 April, Q4 July), case-sensitive; an explicit `?period=` (stripped) wins, else a month makes it "month", else "fy" |
| The tabs (`Period.Tabs`) | `{% querystring period=… month=None quarter=None %}`: the request's query in the order the page receives it (key order), the period set in its place or added last, month and quarter dropped for Week, month for Quarter and FY; active by the period read, This FY also for a period that is none of the four |
| The filters (`Period.PeriodFilters`, `filters`) | the selects as the feed reads them (the first option marked selected, else the first option): the year, quarter, district and staff as sent, unstripped (" 2026 " and an unoffered year show the menu's first year); the month as read; activity type and status "all" when absent; every district by name; every active, undeleted user by name ("None" for a missing name) |
| Hidden | `period` when asked, `fy_prev` the year as sent, `quarter_prev` the quarter or "all" |
| Plan progress | the metric registry's eight labels (`MY_PLAN_TILES`), each linking to `/my-plan`; counts of 0; the visits tile's line "0 Core, 0 Client" (a reader with no target); the completed share of nothing "No data" |
| The four tables | "School Visits / Trainings / Group Trainings / Cluster Meetings Planned for This Week / This Month / This Quarter / This FY", a count of 0, the empty sentence and Open Planning (`/planning`) |
| Breakdown, bar | "Plan Breakdown by Period", "All activity types combined", four "0 activities"; Reschedule and Cancel for ticked activities |

The vocabularies are exported to `internal/myplan/rules.json` by
`manage.py export_my_plan_rules` (drift test
`apps/my_plan/test_my_plan_rules_export.py`): each role's door, the strip's
keys and labels and its "No data", the month and quarter choices, the
quarter's first month, the unset words, the export period keys, the feed's
withheld keys, the planning roles and their targets, the partner bridge and
the feed's renderer formats. Three literals were lifted to module constants
with no change in behaviour (the feed of all 29 accounts was dumped before
and after and was identical): `services.MY_PLAN_TILES`,
`services.MONTH_OPTIONS`, `services.QUARTER_OPTIONS` and
`my_plan_views.EXPORT_PERIOD_KEYS`.

**Shared with the pages that list My Plan's tables.** `myplan.ReadPeriod`,
`Period` (its tabs, its three period selects, its hidden inputs and the
words a table names its slice by), `myplan.Query` (Django's
`{% querystring %}`), `PlanTables` (the four always-drawn tables' titles and
empty states) and `PlanCounts` are exported for Core School Oversight's two
tabs; they are not wired there.

## 25.3 Found by comparing and reading

- **The Status filter shows a Core slot's status.** In `get_frontend_context`
  the loop over Core activity slots names its loop variable `status`
  (`for activity_id, slot_kind, sequence, status, … in slot_rows`), which
  overwrites the Status filter read earlier. Every page with Core work
  therefore returns `selected_status` as the last slot's status: the seed's
  officer opens My Plan with Status showing "Scheduled", and `filters_active`
  true, though no status was asked. It changes only what the filter shows
  (the list was filtered before the loop). Left as it is; Go will draw what
  the existing page draws when piece 3 moves.
- **A `?format=` is "not found".** The feed's REST framework view negotiates
  the renderer before the page runs, so `format=readiness-json` or
  `format=csv` is not found for everyone, Business Transformation included.
- **Empty values.** The gateway drops a query value that is empty before any
  page sees it; the existing feed passes it on, and `{% querystring %}` then
  writes it (`?month=&period=week`). The questions do not send empty values.
- **The filters show what was sent, not what was used.** " 2026 " reads FY
  2026, but the select shows the menu's first year; "q3" is no quarter.

## 25.4 Proving it is the same

`cmd/parity -screen page -path /my-plan` asks 67 questions of each account:
the page as it opens; each period tab, one that is none and one padded;
years 2025 to 2028, 1999 and " 2026 "; each quarter, "q3", " Q2 ", "all",
"Q9"; months 10, 1, 9, " 3 ", "all", "ALL"; weeks 1 and 4; a district and
a staff member offered and not; every activity type and status offered, and
two that are not; three searches; the readiness list key; a key the page
does not read; `export`, and `format` as readiness-json, json and csv; and
eleven combinations (a month or quarter with its period, the week of a
February, a quarter with "all" or a month, the form sent back with the same
or a wider year or quarter, and every filter at once).

Against a gateway with no existing application behind it, the five accounts
piece 1 answers or refuses (Admin, Country Director, Impact Assessment,
Project Coordinator, and Business Transformation, refused):

```
335 answers compared, 0 differing
```

All 29 seed accounts against the same Go-only gateway, the run's own last
line:

```
1943 answers compared, 1560 differing
```

Every one of the 1,560 is an account Go passes to the existing application
(the 23 planners and the officer with rows: 24 accounts, 65 questions each),
which a gateway with nothing behind it answers "This screen is not available
here yet"; the other two questions of theirs are the two `format` refusals,
equal. The five accounts above are 0 differing (335 of the 383 equal
answers). So piece 1 is proved for the readers it answers, and not yet for
the 24 it passes.

The same 29 accounts and questions against the same gateway with the
existing application behind it, where what Go passes is answered by the
existing page through the gateway:

```
1943 answers compared, 0 differing
1560 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

The 1,560 are the passed accounts' pages, each with a table whose second
column repeats a value from one row to the next (the comparison's tie rule
reads any such run as rows sharing a name); they are the existing page on
both sides. This shows the passes reach the existing page
unchanged; it does not prove anything of theirs in Go.

Integration tests (`internal/integration/my_plan_test.go`): the empty page
for an account that holds nothing, the refusal and the `format` refusal,
and a training ceiling filed for the reader leaving the page to the existing
application. Unit tests (`internal/myplan/page_test.go`): the period read
(widening, padding, case, quarters' first months, Kampala's day at the turn
of the year), every value the view fails on and the leap-year February,
`{% querystring %}`'s edits, the tabs and filters for a quarter and for an
unoffered year, the empty page's titles and strip, `|intcomma`, and the
passes and refusals Build makes before it reads the database.

## 25.5 What is left

Pieces 2 to 6 above. The seed reaches little of them: one account has rows
(13 activities, one returned, Core visits, a cluster expansion, a training
summary and 22 clusters on Cluster Planning Status), so piece 3 needs the
golden method of 22 and 18 (the existing code run over generated records)
for cost, budget status, the money chain, day-off marks, verification and
the completion columns. Planned and remaining (piece 4) reads every school
a planner holds and is the slowest part of the page today.
