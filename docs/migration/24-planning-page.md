# 24. Planning (M4): the Planning page, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "Activity planning and scheduling". The migration plan's M4
(04-migration-plan.md) reads first: My Plan, Work Plan and the calendar, and
this page, where staff choose the schools they plan for. It moves in pieces.

| Piece | What moves | State |
|---|---|---|
| 1 | `/planning`'s Client Schools and Core Schools tabs: the filters, the strip, the workload line, the rows, their doors, pages and the selection bar | Done, 24.1 |
| 2 | The Clusters, Assigned to Partner and Scheduled / In My Plan tabs | Done, 24.3 |
| 3 | A page opened from a priority allocation (its banner and the allocation carried into Schedule) | Still the existing application's |
| — | Every drawer and save the page opens (Schedule, Assign, bulk scheduling, Plan Field Event, Recent changes) | Still the existing application's |

## 24.1 What moved

`PageScreenService.GetPage` is now answered by
`platform/backend/internal/planningpage` for `/planning` on its Client and
Core tabs, for someone working in their own role. Another tab, a
`priority_allocation`, a page or page size that is not a number (where the
existing view fails), and anyone in an acting capacity are passed to the
existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("planning")` and the feed's `can_open_url`: CCEO, Program Lead, Admin, Country Director, Impact Assessment, Project Coordinator, Accountant. Anyone else is not found |
| Whose schools | `direct_portfolio_schools(scope)` (`school_queryset(direct_only=True)`, Go's directory `scopeBase`): the reader's own schools, or a country reader's country (a Country Director only while operational planning is allowed) |
| Filters | year, quarter (the local day's), district (the portfolio's), staff (the portfolio's holders by Program Lead, `owner_filter_groups`, either id space), grouping (by PL & CCEO, the default for a country reader, or by name), readiness (and `data_cleanup_required`), the support filter (`planning_support.filter_queryset`: partner support, staff managed, my scheduled visits, visit or training not planned, both planned, awaiting verification, completed, needs replanning, each by the badges' own classification), SSA status (done and not done from the year's records), and the query's school type, sub-county, cluster status, partner and search |
| The table | the tab's types (Client: client, Core Trained, Core Graduate; Core: core), clustered, never Champion; less the schools with work only while the Partner-supported school rule is off; by name, or by holder (`owner_order`: Program Lead, then officer, then name) with a heading row per holder |
| A row | ID, name, cluster (or "Cluster missing"), the Visit and Training planning badges over the planning horizon (`internal/schoolplanning`), the visit lock (`visitgate`), Responsible; Schedule, and Assign where the visit rule lets the school go to a partner; opened: district, shipping address, type, cluster, enrolment, phone, contact, owner, the year's latest confirmed SSA and its colour, completed visits and trainings (with the cluster sessions it attended), Next Activity, and the year's score groups |
| The strip | Ready for Support, SSA Required, Not grouped in cluster, Clusters Needing Action, Core Package Gaps, Partner Pending Schedule, In My Plan, SSA-Informed Plans (half to even), Cost Blocked, Data Cleanup Required, over the whole portfolio |
| The workload line | `staff_plan.own_workload`: "Your FY… visits: n of 280/560 planned." for a Program Lead or CCEO, their counted visits (`country_oversight.rules.counted_visit_q`) by either id; the rest of the note never reaches the app |
| Pages | `make_pagination_window(page, total, 1)`, addresses carrying every filter as written; an empty list's card read with its footer as one panel |

The page's inline lists were lifted to module constants in
`apps/planning/planning_service.py` (no behaviour change) and exported with
the doors, menus, strip labels and the counted-visit rules to
`internal/planningpage/rules.json` by `manage.py export_planning_page_rules`
(drift test `apps/planning/test_planning_page_rules_export.py`).

## 24.2 Proving it is the same

`cmd/parity -screen page -path /planning` asks every account the page as it
opens, both tabs and groupings, three other years, a quarter, later pages and
page sizes, four searches, a school type, a cluster status, every readiness,
support and SSA filter value (and one that is not), and every district and
the first people the page offers.

All 29 seed accounts against a gateway with no existing application behind
it: 1,170 answers (42 for each account that plans, 40 for an officer or lead
with nothing to list, the refusals included), none differing. The four
accounts whose lists hold schools sharing a name were asked again after the
comparison's own tie handling was corrected (it had sorted one side only):
168 answers, none differing. 100 answers held such rows.

Found by comparing: two schools with the same name and holder ("Kasawo
Primary School", "KCCA UMEA Primary School") came back in either order. The
existing page orders by holder and name and nothing after it, so Postgres
returns equal names in the order its plan reads them; Django's statement and
Go's are planned differently. The comparison now puts each run of rows with
the same name in School ID order on both sides and says how many answers
needed it, instead of hiding or failing them.

## 24.3 The other three tabs

| Tab | Existing rule it ports |
|---|---|
| Assigned to Partner | the same rows, of the schools a partner holds: the live-support rule the Responsible column reads (`active_assignment_q`), or with the rule off a hand-over in a live status; its own empty card ("No partner assignments pending.") |
| Scheduled / In My Plan | the same rows, of the schools with work in the year's plan (anything but cancelled, rejected, deferred, not planned or waiting for its owner's approval); the List View / Calendar View switch; and its bar is the calendar's bar for ticked activities (Reschedule, Cancel), which the feed finds before the bar for ticked schools. The calendar itself is drawn by a script and never reaches the app |
| Clusters | the reader's clusters, any status (`cluster_queryset`: a Program Lead's or other supervisor's team's too), less those with a meeting or training this year under "not scheduled", searched by name and filtered by district, by name, as the Clusters page's cards. `cluster_planning` reads only the reader's own active clusters, so a team cluster's card has no planning figures, as on the existing page |

All 29 accounts on the gateway with no existing application behind it, every
tab: 1,431 answers, none differing (104 held rows with the same name,
compared in School ID order).
