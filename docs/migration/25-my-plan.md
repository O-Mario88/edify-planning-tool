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
| 2 | Plan progress and the breakdown counted (the year's and the period's tiles, counted visits at Core and other schools, the completed share, the past-due note) for a member of staff with no target whose tables list nothing | Done, 25.6 |
| 3a | The Core School Visits and Core School Trainings rows (the cluster expansion into Core schools, cost, budget status, verification, Status, completion columns, order), as Core School Oversight's two tabs list them | Done, 25.8 |
| 3 | The rest of the plan's rows (25.7): School Visits, Trainings, Group Trainings, Cluster Meetings, programme and Programme-school work; row tone, day-off marks, row Actions, ticks, pagers; and the Returned, day-off and attention cards; a partner's completed work (its evidence) | Not started |
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

Pieces 3 to 6 above. The seed reaches little of them: one account has rows
(13 activities, one returned, Core visits, a cluster expansion, a training
summary and 22 clusters on Cluster Planning Status), so piece 3 needs the
golden method of 22 and 18 (the existing code run over generated records)
for cost, budget status, the money chain, day-off marks, verification and
the completion columns. Planned and remaining (piece 4) reads every school
a planner holds and is the slowest part of the page today.

## 25.6 Piece 2: the plan counted

Go now answers My Plan for a member of staff with no visit target whose
tables list nothing, whatever else their plan holds: closed work, work
dated in another part of the year, work a filter or search leaves off the
tables. The page carries the plan's figures; anyone whose tables would list
a row is still passed to the existing application.

| Part | Existing rule it ports (`get_frontend_context`) |
|---|---|
| Whose work | `my_plan_activities`: not deleted, of the year as sent, owned under either id (`owner_ids`), not a partner's delivery and not in a partner's two statuses (`staff_my_plan_q`; `PARTNER_ONLY_STATUSES`) |
| The plan the tiles count | that work less what is cancelled, rejected, waiting for its owner, deferred or not planned; closed work stays. A Status filter of one of the left-out states (closed among them) leaves nothing out |
| The filters | `_narrow`, on the plan and the list alike: the search (stripped) in the school's name, School ID, the cluster's name, the school's district or the purpose, any case, its own `%` and `_` matched as themselves; the school's or the cluster's district; the owner; the type; the status, with Submitted and Returned standing for their groups and Planned (not started), In progress and Overdue (not started) read as Home reads them (`plan_state_q`); "all" and "All" are no choice |
| The slice | `period`: the week of the month (`get_week_date_range`), the month, the quarter chosen or today's, or the year; a date is the planned date, else the scheduled time's day in Nairobi |
| The year's tiles | over the whole plan: this week of today's month, this month, today's quarter, the year (`period_totals`) |
| The period's tiles | counted visits (`staff_plan.counted_visits`, the statement `internal/planningpage` counts by), split by the school's type into Core and the rest ("n Core, n Client" under the figure); trainings and cluster meetings by type (`MY_PLAN_TRAINING_TYPES`, `MY_PLAN_MEETING_TYPES`); the completed share `round(n / d * 100, 1)` written without a trailing ".0", "No data" for nothing |
| The past-due note | work of the period not handed in, approved or sent back whose day has passed (`staff_plan.past_due_q`), unless the Status filter is In progress or Overdue; the feed reads only its link, What needs you now (`/dashboard`) |
| What the tables list | the list (the plan less closed work too) narrowed to what is ahead, undated, handed in or approved, or sent back; all of it under In progress, Overdue or a left-out state. Go answers only when this is nothing |

Also passed: a reader whose visits line would be longer than a tile keeps
(28 characters, `HELPER_FIGURE_CHARS`): its whole sentence becomes the note,
with the outreach visits Go does not count. The gate of piece 1 now asks of
activities only those the reader monitors, or the trainings and cluster
meetings they own (My Training Summary's work); the rest is counted.

The lists were lifted to module constants with no change in behaviour (the
feed of all 29 accounts dumped again: identical): `MY_PLAN_VISIT_TYPES`,
`MY_PLAN_TRAINING_TYPES`, `MY_PLAN_MEETING_TYPES` (each used twice),
`SUBMITTED_FILTER_STATUSES`, `RETURNED_FILTER_STATUSES` and
`PARTNER_ONLY_STATUSES`. They, the plan states, the completed, officer-
completed and returned statuses, the counted-visit rules (the Planning
page's own export) and the training summary's types are in `rules.json`
under `plan`.

**Proving it.** No seed account reaches piece 2 through the page: the one
with work is a CCEO. So the counting is proved against the existing code
itself. `internal/myplan/testdata/counts_golden.py` asks
`get_frontend_context` for 54 queries each of three accounts (the officer
with 13 activities, an Admin and a Programme Lead, both with none): every
period, years, quarters, months and weeks, searches (with `%`, `_`, padding
and capitals), a district, a staff member, each status (the left-out ones
too) and six activity types. `counts_golden_test.go` counts the same plans
through the gateway's read-only role on the development database:

```
counts_golden_test.go:94: 162 plans counted, 0 differing
```

Two of its rules the seed does not reach (it has no closed and no undated
work: changing either rule still passes the golden comparison), so
`TestMyPlanCountsClosedWorkAndLeavesListedWorkToTheExistingApplication`
files them in the test database: a closed visit yesterday is counted (FY
tile 1, completed share 100%, This FY 1 activities) and listed nowhere, so
Go answers; an undated scheduled visit is listed, so the page is passed.

Through the gateway with no existing application behind it, the accounts
Go answers (each with an empty plan in the seed) and the refusal:

```
268 answers compared, 0 differing
```

All 29 accounts on the same gateway, the run's own last line:

```
1943 answers compared, 1560 differing
```

As for piece 1: the five accounts Go answers or refuses are 0 differing;
the 1,560 are the 24 passed accounts' pages, which a gateway with nothing
behind it answers "This screen is not available here yet" (checked line by
line).

## 25.7 What the rows need (piece 3)

Each listed activity becomes a row through `get_frontend_context`'s loop
and the table partials, and each column reads its own module:

| Column or part | Reads |
|---|---|
| School ID, name, its link, district, cluster | the school or cluster, `plan_row_district`; a cluster training is expanded into its invited or attending schools (`ClusterActivityAttendance`, else the cluster's clustered operating schools), a Core school among them moved to Core School Trainings with its slot's T-number |
| District Type | `daily_visit_batches.district_marks.district_type_labels` (Primary / Secondary / Mixed by the day's districts) |
| Activity, Purpose, Focus intervention, Training name, Mode of delivery, Meeting topic | `choice_label`, `visit_purpose_label`, `training_names.course_name_of` / `mode_of_delivery`, the meeting kind |
| Planned date, Completed date, the day-off mark | `activities.day_off.day_off_marks` (holidays and leave), `completion_columns` |
| Executor | the partner, else the owner's name by either id |
| Cost | `budget.costing_service.planned_minimum_amounts` (frozen cost components re-priced, shared days split), an in-school pair's note (`pair_costing.pair_cost_notes`), a cluster school's meals (`planned_meal_rates`) |
| Budget status | the first cost line's weekly request (`money_chain`): eight states |
| Verification | `verification_label` with `pl_review.lead_verified_owner_ids` |
| Salesforce ID, Status | `completion_columns.completion_fields`, `get_activity_status_label_and_class`, `visit_scores.awaiting_scores`, `plan_row_tone`, finished early |
| V1–V4 / T1–T4 and n/8 Completed | `CoreActivitySlot` by activity and by plan |
| Actions | `partials/my_plan/activity_row.html`: twenty conditions over the reader's doors, `editing.edit_state`, `_can_reschedule`, `_can_cancel`, facilitator, Salesforce entry and completion |
| Ticks, order, pages | `group_actions.may_tick`, `completed_last_key`, fifty a page |

The seed holds rows for one CCEO only, and that CCEO's page also needs
Planned and remaining, My Training Summary and Cluster Planning Status, so
no account can prove the rows through the page until pieces 4 and 5 move
with them; the rows' own proof will need the golden method of 22 (the
existing loop run over generated activities with costs, weekly requests,
returns, days off and Core slots).

## 25.8 Piece 3a: the Core rows, on Core School Oversight

Core School Oversight's two tabs of planned work (`?tab=core_visits`,
`?tab=core_trainings`) are now Go's. Both are
`apps.my_plan.table_export.core_school_plans`: My Plan's own Core School
Visits and Core School Trainings rows (`get_frontend_context` over the
activities `core_school_activity_ids` chooses, period "fy"), for the schools
the page's filters keep, written as the export writes them
(`CORE_SCHOOL_VISITS.columns`, `CORE_TRAINING_PLAN_COLUMNS`, `shown`). The
rows are built in `internal/myplan` (`CoreSchoolPlans`) so My Plan's own
page can list them when its other pieces move; `internal/coreoversight`
draws the tab around them. My Plan's own page is served to no more readers
than before.

| Part | Existing rule it ports |
|---|---|
| Which work | `core_school_activity_ids`: live activities of the year, not set aside (cancelled, rejected, waiting for its owner, deferred, not planned), at the schools shown, the group sessions one of them is invited to or attended, and the cluster trainings of their clusters planned before invitations were recorded by name; then `context_for`'s queryset by planned date, then made |
| Which table | the loop's own order of tests: programme work and Programme-school work out first; a Core school's (`school_type == "core"`) work by its package slot's kind, else by `VISIT_TYPES` / `TRAINING_TYPES`; a cluster training planned on a cluster (no School ID) expanded into the schools it reached (its invitations by school name, else the cluster's confirmed operating members, else all of them, newest school first), its Core schools moved to Core School Trainings with the slot's T-number and package progress; only the rows whose School ID is one of the schools shown (`mine`) |
| School, district, activity | the school's School ID, name and district ("—" with none); `choice_label` of the type, with the slot's V-number and "n/m Completed" (`CoreActivitySlot` by activity, the 4 + 4 package of its plan, the onboarding slot outside it, a slot's status read stripped and in any case) |
| District Type | `district_marks.district_type_marks`: a shared costed day's mark from all its live fundable members (`day_district_mark`), else the work's own district's type for the person responsible (`district_type_for_staff`: a field role held, by roles or the active role, against the profile's primary district; head office against Kampala, Wakiso and Mukono; the district's own type when nobody resolves) |
| Executor | the partner (live partners) for a partner's work, else the owner's name by profile or account id ("Staff" otherwise) |
| Purpose, intervention, training | the purpose written, else the visit purpose's label, else the type's; the focus intervention's label, "General" with none; `training_names.course_name_of` ("Not yet named"), `mode_of_delivery`; participants as recorded, else planned; an expanded school's people from its invitation, else the session's per school, else the session's total split |
| Cost | `costing_service.planned_minimum_amounts`: each current snapshot component re-priced at its card's approved minimum (`minimum_share`: Decimal half up, shared-day and allocated shares, retired rates at their own amount, renamed keys through `RATE_ALIASES`); an in-school pair's note (`pair_cost_notes`); an expanded school's people × the session's meal rate (`planned_meal_rates`, else the live published card's `group_training_meals`), 0 online |
| Budget status | the first cost line's first weekly request (`money_chain`): the eight states, "Cost Setup Required", "Budget Created", the pair's "In School Visit" / "In Training", "No Budget" |
| Verification | `verification_label` with `lead_verified_owner_ids` (live profiles holding CCEO or Programme Lead, or supervised by a live Programme Lead) |
| Status | `get_activity_status_label_and_class` (Kampala's day), "Awaiting SSA Scores" (`visit_scores.awaiting_scores`), then the completion gap ("Not Complete", "Missing Salesforce ID", "Missing evidence") or "Completed Early" (`completion_columns`) |
| Dates, Salesforce ID | the day planned before completion, else the planned date ("Unscheduled"); the day done (recorded, else the day Complete was pressed in Kampala) for work its status calls done; the stored ID stripped, "Not in SF" |
| Order | `completed_last_key`: work not complete first by planned date, undated last, complete work after; stable |
| The tab | "<sheet>, FY <year>", "n planned", the empty sentence, fifty rows a page with the Schools tab's pager and its caption as the note |

Every vocabulary is exported under `rows` in `internal/myplan/rules.json`
(type and intervention labels, visit purposes, the type and status lists,
the SSA and online rules, the cost keys, aliases and retired keys, the live
card's country, kind and status, the words, the district rules, the two
sheets' titles and headings); the Budget status and the pill's words are
written in Go, as `get_frontend_context` writes them inline.

**A partner's completed work.** Such work is complete only with its form
uploaded and not quarantined (`completion_columns._records`). The gateway
may not read `evidence_record` (`TestGatewayRoleCanNeitherWriteNorReadSecrets`
names it as a table the gateway must not read), so it reads
`gateway_read.activity_evidence_kind` (`platform/deploy/db/evidence_roles.sql`,
made by the coordinator): each activity's uploaded, unquarantined kinds and
nothing else of the record, checked by `TestTheEvidenceViewShowsOnlyUploadedKinds`.
The expected kind is `expected_evidence`'s, exported (`evidence_attendance_types`,
`evidence_attendance_kind`, `evidence_visit_kind`). It is a new database
object, so production needs the owner's approval at cutover. (The agent's
commit first passed such a tab on; the coordinator added the view and
re-proved it.)

**Passed to the existing application.** A stored cost component the
existing code reads as a float or would fail on (a breakdown that is not a
list, an allocation out of range, a label that is not text), and a district type with no label. A `?format=` other than
`json` is not found for everyone (the feed's renderer negotiation), before
the page is asked; Core School Oversight's own questions had not asked it.

### Found by comparing and reading

- **The seed's partner visits.** FY 2026's Core School Visits holds four
  partner visits marked completed with no form ("Not Complete"): that tab
  in that year is left to the existing application for every reader who
  sees those schools.
- **An activity in two package slots** is numbered by whichever slot the
  table returns last, on the existing page as in Go; booking puts school
  work in one slot, so the golden data does too.
- **A Core school's work at another year's plan.** The slots are read by
  the school, not the year (as the existing code says), so a visit dated
  into the next year keeps its number.

### Proving it

**Against the existing feed, every seed account.** `cmd/parity -screen page
-path /core-schools-oversight/` now asks 119 questions of each account: Core
School Oversight's 73 (22.4) and 46 of the two tabs
(`page_core_plan_tabs.go`): each tab as it opens, in FY 2026, 2025, 2028 and
1999, with searches, a district offered and not, each type, a trajectory,
a need and a readiness value, a sort, pages 2, 999 and "abc", FY 2026 with
a search and with page 2, a download's `format=xlsx`, a tab with spaces and
a grouping beside a tab. On a gateway with no existing application behind
it, all 29 accounts, the run's own last lines:

```
3451 answers compared, 15 differing
80 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

The 15 are one tab in one year: FY 2026's Core School Visits (as it opens,
searched "central", page 2) for the five readers who see the officer's
schools (Admin, the officer, the Country Director, Impact Assessment,
Programme Lead 1). That sheet holds the seed's four completed partner
visits, so Go passes it, and a gateway with nothing behind answers "This
screen is not available here yet" (all 15 checked). Every other answer is
equal, the two tabs' FY 2027 rows, FY 2026's empty Core School Trainings
and every refusal among them. With the existing application behind the same
gateway, those five accounts:

```
595 answers compared, 0 differing
80 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

**Against the existing code, for rows the seed does not hold.** The seed has
two FY 2027 Core visits and FY 2026's seventeen, one district, no trainings
at Core schools, no cluster session reaching one, no weekly requests beyond
"Budget Created", no pairs, slots or visit days.
`internal/myplan/testdata/core_plans_golden.py` files synthetic records in
`edify_gorn_test` (ids `g7…`; three districts, five accounts with and
without profiles, roles and home districts, a supervision line, three
clusters, sixteen schools of five types, 171 activities of eleven types and
fifteen states from a seeded random source, with days today, this week,
later, past and undated, padded and missing Salesforce IDs, reschedules,
recorded and pressed delivery days, the day before completion, attended and
planned people, catalogue courses, online delivery; cost lines in eight
weekly request states, some in two; cost snapshots priced pro rata, on a
shared day, by allocation, at a retired or a renamed rate, missing, with no
minimum and empty; Core plans in two years with slots in every state;
invitations, uninvited sessions and their package slots; SSA records;
visit days) and asks `table_export.core_school_plans` itself, unmodified,
for 39 sets of schools and years (every school, the Core schools, five,
none, the year before, each school alone in each year, and all but the
first). `coreplans_golden_test.go` reads the same records through the
gateway's read-only role and expects the same cells in the same order:

```
coreplans_golden_test.go:103: 74 sheets (423 rows) compared, 0 differing; 4 sheets left to the existing code (a partner's completed work)
```

The four are the sheets holding the one partner visit the script marks
completed. Changing a rule in Go fails it: Decimal half up read as floor
(6 sheets), the head-office zone (3), an account's roles read before its
active role (3). The records were removed afterwards (none left). A first
run, with `evidence_record` still granted, compared 322 rows of the partner
completions too, all equal; that grant was then withdrawn (above).

Unit tests (`internal/myplan/coreplans_test.go`) hold what neither reaches:
`minimum_share` at its edges (half up and below, a shared day, the last
share of an allocation, a retired rate with and without its amount, no
minimum, no unit, a zero unit at a zero rate, and the three shapes Go
passes), Python's truth of JSON values, every weekly request state, the
pill's 7-day edge, "Activity ID Missing", the completion words, the day
mark, money with thousands and a minus, and floor division.
`internal/coreoversight/page_test.go` draws a tab of 51 rows (page 2, the
pager's caption as the note, a filter narrowing the schools asked), the
empty tab, an unported sheet and the `format` refusal.
`internal/integration/core_plan_tabs_test.go` opens both tabs through the
gateway for the Admin and refuses `format=xlsx`.

Grants added (`platform/deploy/db/roles.sql`, applied additively to both
databases): activity's people, cost, completion and visit-day columns,
`district.district_type`, `staff_profile.primary_district_id`, the cost
lines' ids, the weekly request lines and requests' status, cost settings,
cost snapshots' components, the live card's columns, `cluster_activity_attendance.other`
and the visit days.

### What is left

- The rest of piece 3 (My Plan's own tables, Actions, ticks, row tones,
  day-off marks and the cards), and pieces 4 to 6; the downloads.
