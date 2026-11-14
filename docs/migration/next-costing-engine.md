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

Next: the country Budget (approval workflow, Finance Health).
