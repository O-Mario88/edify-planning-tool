# 46. Partner Monitoring, read by Go (first piece: a workspace with no partner work)

Partner Monitoring (`/partner-oversight/`, `apps.frontend.views.oversight_views.partner_oversight_view`,
`apps.planning.partner_oversight_service`, `pages/oversight/partner_oversight.html` with
`partials/oversight/partner_workspace.html`) is one Partner at a time: the schools, clusters and
activities handed to it, by team member, where each stands, the headline tiles, withdrawal requests and,
for the Programme Lead, the Country Director and the operational admins, the partnership register.

The page is large: its rows come from a 2,400-line service (handovers, Partner work made without one,
facilitated group trainings, risks, invoices, Core support), its first tile carries the Partner target
from the Planning Monitor (`apps.planning.planning_monitor`, not yet in Go), and the register reads
engagements and Regional Lead observations. This piece moves the part every seed reader without partner
work sees, exactly, and passes everyone else to the existing application. The rest is backlog item
`partner-oversight-2`.

Go: `platform/backend/internal/partneroversight/` (rules.go, period.go, read.go, service.go, page.go,
page_test.go), one line in `internal/server/server.go`, parity questions in
`cmd/parity/page_partner_oversight.go`, integration tests in `internal/integration/partner_oversight_test.go`.

## 46.1 Who Go answers

| Reader | Go's answer |
|---|---|
| A role without `PARTNER_MONITORING_VIEW` (Business Transformation, Project Coordinator, HR, partners, MFI, Cluster Leader) | not found (`pagegate.ErrNotAvailable`), the feed's 404 |
| CCEO or Programme Lead in their own role, nothing in reach (below) | the page, built by Go |
| CCEO or Programme Lead with anything in reach | passed on (served=false) |
| Country lens (CD, IA, Admin, Accountant, RVP), region lens (RPL), anyone acting | passed on |
| A link with an Export-drawer period (`period_type`, `from_month`, `to_month`, `start_date`, `end_date`), a register drawer to open on load (`engagement`, `step`, `record`, `source`), a register page (`engagement_page`), a year that is not four digits, a week not written `YYYY-Wnn` (01–52), or any non-ASCII text | passed on |

"In reach" is one statement (`read.go anyPartnerWork`), each arm at least as wide as the page's own
source, so when it finds nothing the page has nothing. The ids are the reader and the people they
supervise, in both id spaces (`_both_id_spaces`; a CCEO's supervisees are added too, as the Planning
Monitor counts them):

| Page source | Go's wider condition |
|---|---|
| `build_items` handovers (`_assignment_team_q`, `left_partner_q`, `_still_open` / `_assignment_fy`) | a `partner_assignment` monitored, assigned, at a school held or a cluster run by the ids, not left the Partner, and unscheduled (any date) or scheduled into a year read |
| `_unassigned_partner_activities` | a live partner-delivered `activity` with a Partner, in a year read, monitored/responsible/at a held school/at a run cluster |
| `facilitated_trainings` | a live `activity` with a facilitating Partner, in a year read, responsible or at a run cluster |
| `withdrawal_requests` | a `requested` withdrawal whose supervising PL is in the ids |
| the Partner target (`planning_monitor` → `_monitored_schools`) | a live school held by the ids or in the reader's scope |
| the register (`engagements_visible_to`, `open_observation_follow_ups`), register readers only | an engagement the reader authored, or any strengthen/replace Regional Lead observation |

The years read are the page's FY, and every later year when it is the operational FY
(`planning_horizon` reads it forward to the latest offered or plannable year; Go reads every later year).
No period, status, member or type narrows the guard.

## 46.2 The page Go draws

- Header: eyebrow, title and description; Add Partner Organisation (drawer `/partners/create`) where
  `may_create_partner_organisation` (exported; none of the served roles has it).
- Filters (`period_filter_bar.html` + `partner_filter_fields.html`): the period select has no selected
  option (Alpine sets it), so the feed reads its first, `week`, whatever the period; FY reads the option
  equal to the page year, else the first; Month and Quarter read the defaulted month and quarter; Status
  lists the exported phases with `(0)` and reads the one asked for exactly (no strip), else All. Hidden:
  `member`, `work`, and `program_lead` when given (the view keeps the raw value for a team reader).
- `_period_filters` as `period.go`: year default `get_operational_fy()` (UTC); the reference day is
  Kampala's today when its FY is the page year, else 1 October before it; the week, month and quarter
  default from it; an explicit `period` wins, else month, quarter, then FY.
- Team-member tabs: All team members, then `program_lead_members(team_lead_user_id)` — the first live
  profile of the reader's account holding Program Lead, by key, then their reporting lines by name — each
  with count 0; `member` not on the strip reads All. Hrefs as the template writes them.
- Work tab: `work_tabs` with no tables — the one asked for (not Core), else Schools assigned.
- Tiles: `_partner_kpis` over no work, as `professional_kpis` splits them, exported as rendered
  (`zero_tiles`, `zero_tiles_with_target`). The target sentence is there when the reader leads a team in
  the planning roster (`country_oversight.rules.roster`: live profile, active account, planning role
  Programme Lead): the monitor then has people and, with no school, every total is 0. A CCEO has none.
- The empty state (`components/empty_state.html`, the feed reads its message).
- Register readers (here the Programme Lead): its title; its tiles (`ENGAGEMENT_METRIC_WORDS`, lifted, the
  observations tile for the Programme Lead) through `schoolprofile.Strip`; the empty table with the
  recorder's or the reader's words.

## 46.3 Rules exported, not restated

`manage.py export_partner_oversight_rules` writes `internal/partneroversight/rules.json`; drift test
`apps/planning/test_partner_oversight_rules_export.py`. Per role, by the page's own gates: page,
lens, own work only, Add Partner Organisation, register, records engagements, observations tile. Also:
Status phases, work tabs and the Core tab, planning and roster lead roles, partner delivery, the
requested withdrawal state, the left-the-Partner statuses and `returned_to_staff`, the partner-action
recommendations, the register's words, autoload and page params, the rendered zero tiles, the feed's
unpassed query keys.

Behaviour-neutral lifts to module constants: `oversight_views.PARTNER_STATUS_FILTER_KEYS`,
`partner_engagement_views.ENGAGEMENT_METRIC_WORDS`, `support_responsibility.LEFT_PARTNER_STATUSES`.

Grants (appended to `platform/deploy/db/roles.sql`): `activity.facilitating_partner_id`,
`partner_assignment_withdrawal (state, supervising_pl_id)`, `partner_engagement.author_id`,
`cce_regional_engagement.recommendation`. Ids, states and one word; no reasons, notes or text.

## 46.4 What was found by comparing

- The seed's field officers are not empty: cceo1 (Moses K. on pl2's team) holds five completed FY 2026
  handovers. A first guard with no year passed every officer on; the guard now reads the page's years, so
  the officers are Go's for FY 2027 and later and passed on for FY 2026 (where the existing page lists
  that work), and so is pl2's team.
- `fy=abc` is a 500 on the existing page (`get_fy_date_range`); Go passes it on rather than copy a crash.

## 46.5 Proving it is the same

`cmd/parity/page_partner_oversight.go` asks each account 36 questions (42 where the strip names team
members): the page as it opens, every period, FY (2025, 2026, 2028, 1999, `abc`, padded), month (3, 13,
`abc`), quarter (Q3, `q2`, Q9), week (`2026-W02`, `2026-W2`, nonsense), status (two phases, `xyz`), work
tab (visits, clusters, core, bogus), member (all, nobody, each on the strip), `program_lead`, `partner`,
`period_type=fy`, `engagement_page=2` and two combinations. Own Django on 8182 over `edify_gorn_dev`.

Go-only gateway (no existing application behind it), all 29 accounts, `-pause 20s`:

```
coordinator@edify.org              36 questions, 0 differing

1062 answers compared, 356 differing
```

Every one of the 356 is a reader or question Go passes on (`go error: unavailable: This screen is not
available here yet`); none is a Go answer that differs. Go's own answers: cceo1–cceo19 28 of 36 each,
pl2–pl4 34 of 42 each (634 answers), plus the 72 refusals of Business Transformation and the Project
Coordinator, all equal. Passed on: cceo, pl1, cd, ia, admin (all questions; partner work in reach or a
country lens), and for the served accounts `fy=2026` and the FY 2026 month question (cceo1's FY 2026 work,
on pl2's team), `fy=abc`, `fy= 2026 ` (Python strips it; Go reads it too but FY 2026 is passed on),
`week=2026-W2`, `week=nonsense`, `period_type=fy`, `engagement_page=2`.

The same gateway with my Django behind it, all 29 accounts:

```
coordinator@edify.org              36 questions, 0 differing

1087 answers compared, 27 differing
```

All 27 are `fy=abc`, one per account that opens the page: the existing page answers 500 and the gateway,
passing it on, words the same failure as "This screen could not be loaded" while the tool prints
"status 500" — the existing application's crash in both columns, not a Go answer.

Unit tests (`page_test.go`): `_period_filters` over 16 queries including the Kampala/UTC day edge
(30 September 22:30 UTC), quarters, work tabs, queries passed on, who is drawn (acting, country and
region lenses refused), status words, and the page for a Lead, an officer, a reader who adds partners and
a register reader. Integration (`partner_oversight_test.go`, on `edify_gorn_a20_test`): cceo1's page,
pl2's page in FY 2028 with team tabs, target and register, and passing on cceo1 in FY 2026, a custom
period and pl1, refusing Business Transformation.

## 46.6 What is left (`partner-oversight-2`)

Everything with rows: handover items (`_item_for`, risks, next actions, costs, withdrawal actions,
Core support, invoices), Partner tabs with follow-up (`partners_needing_follow_up`), the partner header
and its summary chips, work tabs with counts, `workspace_tables` and the facilitated trainings table,
non-zero tiles, the Partner target from the Planning Monitor, the withdrawal queue, the country and region
lenses with Programme Lead tabs, acting readers, register rows, observations and counts, custom periods,
the export drawer, and the other partner pages the backlog item names (Partners list, allowance drawer).
A superuser in a team role reads the country on the web; Go cannot read `is_superuser` (it is protected)
and would draw them as a team reader — there is none in the seed.
