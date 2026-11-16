# Next: the costing engine, /cost-settings and /budget

Status: planned 2026-11-14. Owner: "proceed" (after "Next: … then start the
costing engine").

## What there is

| Python | Lines | Role |
|---|---|---|
| apps/budget/costing.py | 620 | `calculate`: one activity's cost lines from its planned quantities and the rate card |
| apps/budget/costing_service.py | 2050 | rate-card reads (`active_catalogue`, `_read_rate_card`), dual pricing (operational + minimum viable), previews, `apply_to_activity(ies)` (writes snapshots and lines), money guards, coverage |
| apps/budget/session_costing.py | 696 | group sessions (trainings, cluster meetings): participants, meals, venues, facilitation |
| apps/budget/school_visit_costing.py | — | the visit's own recipe |
| apps/daily_visit_batches/* | — | a day's visits share one day's travel and allowance (the pool) |
| apps/budget/services.py | 2610 | `budget_workspace` (the /budget ledger), `visible_rates`, rollups |

Go today: the visit saves write the activity and leave its pricing to Django
(`daily_visit_costs_to_follow`, settled after commit: see Platform Health).

## Order of work (least risk first)

1. **/cost-settings and /cost-intelligence (read).** The rate card, its rates
   with their reference rates, activity coverage (each activity's cost
   recipe), the review queue, the reserves; every drawer stays with Django.
2. **/budget (read).** `budget_workspace` over the stored cost lines and
   snapshots: monthly, quarterly and annual; my / team / country scopes;
   the country workflow and Finance Health panels.
3. **Pricing in Go, read-only.** Port `calculate` / `calculate_dual` /
   session and visit recipes / the day pool. Prove it with an oracle: for
   every activity on the test database, Go's computed lines equal Django's
   (`calculate_dual` on the same input), no writes on either side.
4. **Go saves price their own work.** Only with the owner's explicit
   go-ahead: it writes money (snapshots, lines, day batches) and retires
   costs-to-follow. Shadow scenarios at both levels, as for every save.

Each stage: rules exported with a drift test, goldens filed by the
integration tests, parity for all 29 accounts, hand-ons listed.

## Done so far (2026-11-14)

- **The recipe in Go** (`internal/costing`, ahead of stage 3 because stage 1
  needs it): `CostForActivity` and `FacilitationFeeCost`, ports of
  `apps.budget.costing`, from `manage.py export_costing_rules` (drift test
  `apps/budget/test_costing_rules_export.py`). Proved by an oracle:
  `internal/costing/testdata/oracle.py` prices 30,000 seeded random
  activities on seven cards (the live card, two with rates dropped, one that
  still carries only renamed keys, renamed and new together, ones, empty);
  `oracle_test.go` (EDIFY_COSTING_ORACLE) found 0 differing lines, and a
  planted fault was caught. Nothing reads or writes money yet.
- **Stage 1, /cost-settings and /cost-intelligence** (`internal/costsettings`,
  rules from `manage.py export_cost_settings_rules`): the header and its Add
  button (Country Director), the year filter, the review queue (readers of the
  reference layer), the published card, the register (fifty a page, Edit for
  the Country Director) and the activity coverage, each activity priced by
  `internal/costing`. Golden: 15 answers of 6 accounts, 0 differing. Hand-ons:
  no published card, an empty register or catalogue, a provisional card, a
  year the filter does not offer, any other query key, more than seven pages
  in a table, an unknown costing profile.
- **The feed now names Cost Intelligence**: the page's request carries its
  URL match (`apps/mobile_feed/views.py`), so the RVP and the Accountant read
  "Cost Intelligence" in the app as on the web, not "Cost Catalogue".

- **Stage 2, /budget for CCEOs and Program Leads** (`internal/budgetpage`,
  rules from `manage.py export_budget_rules`): the period tabs, the year, the
  Program Lead's team cost summary, and the ledger of planned cost lines
  grouped by activity and by item and rate (a shared day's rate from its own
  snapshot, trainings and meetings counted by sessions and participants, the
  partner lump sum shown as the facilitation fee, a line dated only by its
  month in the months wholly inside the period, the week that crosses
  1 October reading both years). Golden: 15 answers of 4 accounts, 0
  differing. Hand-ons: the five country roles (their Budget carries the
  monthly approval workflow and Finance Health, the next part of stage 2),
  the Project Coordinator (a section strip), a reader whose scope is the
  country, any other query (district, staff, search, week, month), a date or
  year that is not plainly one, more than 50 groups, a day rate int() would
  refuse. The ledger's training and meeting sets and the country roles were
  lifted to module constants (`LEDGER_*` in `apps/budget/services.py`,
  `COUNTRY_BUDGET_ROLES` in `budget_views.py`) so the export reads them.
- **The app reads the whole ledger**: the feed read a table's first body
  only, so the app showed the first activity group and dropped the rest and
  the grand total. A table without a head is now read whole when it has
  several bodies or a footer (only the budget ledger has either), in the
  feed and in Go's `feeddom` alike.

- **Stage 2, the country's Budget** (`internal/budgetpage/country.go`; the
  CD, RVP, Accountant, IA and Admin): the national ledger and the district
  filter, Finance Health (the year's advance pipeline and the requests by
  quarter), and for a month the approval status and its links (the RVP's
  Return on a submitted month), the country request, the pending earlier
  month and the reconciliation (committed, disbursed, accounted, returned,
  reimbursed, the approved operating limit). The existing read writes (it
  creates the month's budget and stores its live totals); Go does not
  (owner, 2026-11-14: "Go reads it anyway", doc 68 §68.6) and shows what
  that read would store. Golden: 28 answers of 9 accounts, 0 differing
  (live, locked, approved and unrecorded months); a planted fault fails all
  10 country month answers. Hand-ons added: a deployment of several
  countries.

- **Stage 3a, an activity priced on its own** (`internal/pricing`, rules from
  `manage.py export_pricing_rules`): `StoredInput` builds what the single
  cost writer prices a stored activity with (`_costing_input`: the district
  type by who travels, field staff against their primary district and head
  office against the Kampala, Wakiso and Mukono zone; the traveller's night
  rate by the roles held; a field event's destination; the materials, the
  headcount and the days), and `Price` is `calculate_dual` (the operational
  and reference cards in force on the activity's day, the linked costs, the
  below-minimum, missing-reference and material-difference warnings, the
  viability). Oracle: `internal/pricing/testdata/oracle.py` files a newer
  operational card in force for ten days of April (a threshold, a rate below
  its minimum, a rate left out, a linked cost) and a dearer reference card,
  and prices every live activity; `pricing_oracle_test.go` (EDIFY_PRICING_ORACLE)
  prices them with Go through the gateway's role: 264 activities, 0
  differing; a planted fault in the threshold failed the 91 it touches. The
  seed has no secondary-district work, so those district and night-rate
  branches are held by unit tests. `costsettings` now resolves its card
  through `pricing.Resolve` (its golden still 15/0). Not yet: the day a
  visit shares with others (the Daily Visit Batch pool and its shares), an
  in-school Training carried by its visit, an online training's zero.

- **Stage 3b, the day a visit shares** (`pricing.PlanDay`): the day's live
  members by id, Primary, Secondary or Mixed from where each happens for the
  day's traveller, the rates a Mixed day fetches (the secondary district's,
  its transport named Mixed), the day the traveller comes home (away the day
  before, not the day after: no night and no dinner), the pool and the
  refusal of a day whose card lacks one of its rates, each rate split exactly
  across the members (the remainder to the first), and each member's own
  lines that are not the day's. Oracle:
  `internal/pricing/testdata/day_oracle.py` files seven days (a primary day
  split three ways with a cancelled member left out, a Mixed day, two
  secondary days in a row, a day refused for its missing lunch, an empty day,
  a day of a OneTest visit and a cluster meeting) and plans them with
  `_plan_day`; `day_oracle_test.go` (EDIFY_DAY_ORACLE): 7 days, 0 differing; a
  planted fault in the split failed the three-way day. Go does not settle a
  neighbouring day (a write); it reads the neighbours only to know whether
  this day is the trip home.

Next: stage 3c, which way a stored activity is priced (an online training at
nothing, an in-school Training carried by its visit, a pooled visit by its
day, anything else on its own), then stage 4 needs the owner's go-ahead.
