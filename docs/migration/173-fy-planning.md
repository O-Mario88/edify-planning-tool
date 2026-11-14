# 173. Fiscal Year Planning, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". Fiscal Year
Planning (`/planning/fiscal-years`,
`fy_planning_views.fiscal_year_planning_view`, `apps.planning.fy_policy`,
`pages/planning/fiscal_years.html`) is answered by
`platform/backend/internal/fyplanning`. Opening a year and changing its
follow-up rule still post to the existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("fy_planning_policy")` and the feed's `can_open_url` (Admin, Country Director, Impact Assessment), with `fy_policy.may_manage` per role, exported by `manage.py export_fy_planning_rules` (`apps/planning/test_fy_planning_rules_export.py`) |
| Header | The operational year (`get_operational_fy`, UTC) in the description |
| The table | Every policy, every country, by year descending. "FY" and the year (strong); `window_state` (Operational, Closed year, Open for planning once its opening moment has passed, else Not open, and Not open for a year that is not a number); when planning opens (`j M Y`, Nairobi, else "—"); the delivery window; and Yes or No for the follow-up rule. For a manager that last cell is followed by the words of the button that flips it: the feed reads the cell's form as its text. With no policy, the empty line in one cell |
| The form | For a manager, "Open FY<next> for planning", unless `is_planning_open(next)`, which is true when the default country's policy for that year has an opening moment that has passed |

`deploy/db/roles.sql` grants `edify_gateway_ro` a policy's delivery window
and follow-up rule, but never its notes or who opened it.

Proof: `cmd/parity -screen page -path /planning/fiscal-years` for all 29
accounts. The seed has no next year, so the form is drawn.
`internal/fyplanning/testdata/golden.py` files the next year opened (the form
gone), a later year not open in another country, and earlier years with and
without an opening moment. `internal/integration/fy_planning_test.go` compares
Go's answers whole (`EDIFY_FY_PLANNING_GOLDEN`, the same day).
