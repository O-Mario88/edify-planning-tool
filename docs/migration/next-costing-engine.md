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
