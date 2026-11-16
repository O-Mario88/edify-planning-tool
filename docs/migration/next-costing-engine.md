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

- **Stage 3c, which way a stored activity is priced** (`pricing.PriceStored`,
  `_price_activity` read-only): an online training at nothing, an in-school
  Training whose visit still makes the journey at nothing or its partner's
  fee, a visit that pools (a funding owner, staff delivery, a pooled type)
  by the day it would join (that day's members and itself; a locked week and
  a day without its rates refused, a day that does not exist yet and lacks
  its rates priced alone, a visit that draws no money left as priced), and
  anything else on its own. Oracle from the writer itself:
  `internal/pricing/testdata/stored_oracle.py` files day_oracle's days, runs
  `reprice_activity` for every live activity in a rolled-back transaction
  and reads the lines it writes; `stored_pricing_test.go`
  (EDIFY_STORED_ORACLE): 276 activities, 0 differing (132 by their day, 142
  alone, 1 left as priced, 1 refused); with pooling turned off 13 differ.
  The seed holds no online training and no in-school Training pair, so those
  two paths are not yet compared with the writer.

Stage 3 is done but for those two paths.

## Stage 4: Go saves price their own work (owner, 2026-11-16: "Yes, start stage 4")

Today a Go save (the nine in `config.GoSaves`) asks the existing application
twice: `visit-day-check` before its transaction (what the pricing would
refuse, whether the visit pools, an online training's zero), played in a
transaction rolled back; and `costs-to-follow` after it commits, which
settles the rows Go wrote (`costs_follow.settle`): it prices the days the
save kept (`price_kept_days` → `_write_day_lines` → `apply_to_activities`:
the day's row, each member's cost lines, cost snapshot and "cost
calculated" audit entry, its advance requests, the route twin and the
transport company's obligation), refiles the owner's weekly request and
monthly draft (`fund_requests.follow.refile`), and sends the planner-change
notes.

Order, least money first; each behind its own `EDIFY_GO_SAVES`-style switch,
off by default, development and the shadow databases only, proved by
shadow scenarios at both levels (every changed table equal to the existing
save's) before the next starts:

1. **4a. Go answers the day check itself** (`pricing`: the preview's
   blockers, whether the visit pools, the day's refusals, the online zero),
   writing nothing; the relay stays as the comparison.
2. **4b. Go writes one activity's price**: its cost lines (with the card's
   id and version, line item types, period fields, owner and partner), its
   cost and cost-missing flags, its cost snapshot (the operational and
   reference figures and breakdowns) and its audit entry, for work priced
   on its own; the existing finance locks asked first.
3. **4c. Go writes a day**: the day's row (its pool, rate snapshot, counts
   and shares) and every member's price, and settles the neighbouring days
   whose trip home moved.
4. **4d. Go files the money that follows**: advance requests, the weekly
   request and the monthly draft, the route twin and the transport
   obligation, and the planner-change notes; then `costs-to-follow` retires
   for the saves that no longer need it.

### 4a so far (2026-11-16)

`pricing.DayCheck` (internal/pricing/check.go) answers `gateway_relay._probe`
read-only: an online training (no preview, no day); the preview's refusal
(`_preview_refusal`, the missing rates named as `_KEY_LABEL` names them, the
head count asked for first); whether the day pools the visit; then, for the
day it joins, `attach_activity_to_batch`'s refusals (the week sent for
approval, a missing rate on a day that exists; a day not yet made with its
rates missing, or a district that is neither primary nor secondary, does not
pool) and `_assert_days_can_follow` for that one day (the day's own rates,
a paid transport the day would now owe differently, then each member's
finance guards in order: money moved on an advance, an advance with the
accountant, a weekly or a monthly request carrying its lines that has left
its owner's hands). The day join is shared with `PriceStored` (`attach`).

The rules it reads are exported (`export_pricing_rules`: the rate labels, the
advance and monthly states, the transport members, the paid-transport
words); the guard's two status lists became named helpers
(`repriceable_monthly_statuses`, `advance_with_accountant_statuses`) and
`_school_transport`'s statuses `vendor_channel.TRANSPORT_GONE_STATUSES`,
unchanged. The gateway reads three more finance columns (roles.sql).

Proved: `testdata/check_oracle.py` asks the probe of 239 saves on the test
database (every filed day, each finance guard, a sent week, a paid transport
at the wrong and the right amount, every catalogue item at a school or a
cluster with and without a head count and online, every member of staff at
three schools); `integration/day_check_test.go` asks Go: 0 differing. Three
planted faults (the transport share, the weekly guard, the head count) were
each caught.

Not covered yet: the preview's missing-rate wording is reached only for the
head count (the test card is complete); an online training's cost revision
is still the relay's (it is written, so it goes with 4b). Go's check orders
the visit among the day's members by the id the save will insert, where the
probe used the id Django gave its rolled-back copy; only a paid transport's
remainder shilling can depend on it. Next: the switch, asking both and
logging any difference, before Go's answer is used.

Production stays as it is: no deploy, no production database, no merge into
`main` without the owner's approval.
