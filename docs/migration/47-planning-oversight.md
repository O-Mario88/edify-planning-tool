# 47. Planning Oversight and Country Oversight, read by Go (piece 1: the doors)

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Planning Oversight
(`/team-planning-oversight/`) and Country Oversight
(`/country-planning-oversight/`) are two of the largest pages the app's feed
reads (`apps/frontend/views/oversight_views.py` is 5,039 lines, with
`country_oversight_views.py`, `country_execution_views.py`,
`apps/planning/oversight_service.py` behind them), each with several lenses.
They move in pieces.

| Piece | What moves | State |
|---|---|---|
| 1 | Who may open either page: every reader either page refuses is refused by Go, on every lens and query | This document |
| 2 | Planning Oversight's Team Plan lens (the Programme Lead's team lens and the country/region lens by Lead) | BACKLOG `planning-oversight-2` |
| 3 | Planning Oversight's other lenses: Team/Country Portfolio, Schools & Coverage, Target Performance, the IA monitors (Planning Monitor, Execution); Training Summary is `training-summary` / `training-summary-2` | BACKLOG `planning-oversight-3` |
| 4 | Country Oversight: the coverage dashboard it opens on (`country_oversight_views.coverage_page`), the Country Plan lens (`?view=plan`) and Execution (`?view=execution`) | BACKLOG `planning-oversight-4` |

## 47.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/planningoversight` for exactly the two paths
`/team-planning-oversight/` and `/country-planning-oversight/`.

| Part | Existing rule it ports |
|---|---|
| Is the page the feed's | Both URL names (`team_planning_oversight`, `country_planning_oversight`) are in `apps.mobile_feed.views.NATIVE_PAGES`; were either taken out, Go hands that path on |
| Who is refused | `apps.mobile_feed.views._run_page`: `can_open_url(user, path)` false is the feed's 404 "This page is not available." before the view runs. Planning Oversight opens for Accountant, Admin, Country Director, Human Resources, Impact Assessment, Program Lead, Regional Program Lead, Regional Vice President; Country Oversight for Admin, Country Director, Impact Assessment, Regional Vice President. Every other role (CCEO, Cluster Leader, Project Coordinator, Business Transformation, the partner and MFI roles, a role the rules do not know) is refused by Go |
| The view's own decorator | `require_any_page_permission("team_planning_oversight", "team_targets")` and `require_page_permission("country_planning_oversight")`. A reader the feed lets through whom the decorator refused would get the view's refusal page and an audit row; the export shows the two gates agree for every role today, and a unit test fails if they ever part |
| `?format=` | The feed's REST framework view answers a format it has no renderer for as not found, for everyone (`myplan.FeedRefusesFormat`, 25.3) |
| A reader the page opens for | Handed to the existing application (`served=false`) on every lens and query: no lens is Go's yet |
| The person, not the role | A role's answer only narrows for a person (an acting appointment's withheld pages, `apps.core.acting.page_withheld`; a partner team member's, `apps.partners.member_scope`), so a role refused is everyone in it refused, and a role let in is asked again by the existing application |

Each role's two doors per page and whether the feed opens each page are
exported to `internal/planningoversight/rules.json` by
`manage.py export_planning_oversight_rules`;
`apps/planning/test_planning_oversight_rules_export.py` fails when the two
differ. Nothing in Django changed.

The parts the pages load after they open (`/country-planning-oversight/rows`,
`/drawer`, `/table/<key>`, `/team-planning-oversight/detail`, `/export`, the
Send actions) are not this package's; the path without its trailing slash is
not either (it does not resolve, the feed answers 404 for everyone, and Go
hands it on).

## 47.2 What was found by comparing

- The 29 seed accounts (`$SP/agent31_all_*.json`, read through `read_page`):
  Planning Oversight answers 200 for admin, cd, ia, pl1–pl4 and 404 for the
  other 22; Country Oversight answers 200 for admin, cd, ia and 404 for the
  other 26. The exported doors give exactly those answers.
- Both refusals come from `can_open_url`, never from the decorator, so the
  feed's refusal of these pages writes no audit row.

## 47.3 Parity

Go-only gateway (no existing application behind it) on 127.0.0.1:8094 against
the existing application on 127.0.0.1:8125, both over `edify_gorn_dev`; 24
questions per account (`cmd/parity/page_planning_oversight.go`: as it opens;
every lens named, one that is not, one with stray spaces; four periods; a bad
year; an owner tab, an activity strip, a Lead tab; `format=json` and
`format=xml`). A reader the page opens for is "not available here yet" from a
Go-only gateway (handed on), which the tool counts as differing.

| Page | Last line, as printed | Of the differing |
|---|---|---|
| `/team-planning-oversight/` | `696 answers compared, 161 differing` | all 161 are `unavailable: This screen is not available here yet.` (handed on): the 7 readers it opens for (admin, cd, ia, pl1–pl4) × 23 questions; their 24th, `format=xml`, is the same. The 22 refused accounts: 0 differing |
| `/country-planning-oversight/` | `696 answers compared, 69 differing` | all 69 are handed on: admin, cd, ia × 23; the 26 refused accounts: 0 differing |

So every answer Go gives itself (552 + 627) is the same as the existing feed's,
and every other answer is handed on.

## 47.4 Tests

- `internal/planningoversight/service_test.go`: the doors for refused and
  opened roles on both pages, every lens refused alike, an unknown role,
  `?format=`, the parts under the pages and the path without its slash left
  alone; and that no role is let in by the feed and refused by the view.
- `internal/integration/planning_oversight_test.go`: a CCEO refused both
  pages on three lenses, a Programme Lead refused Country Oversight and an
  unrenderable format, and their Team Plan handed on.

## 47.5 What is left

Pieces 2–4 above (BACKLOG). The lenses read the canonical planning items
(`oversight_service.build_items`, partner work excluded), the Lead/owner tab
strips, KPI strips (`_kpi_items`), the period reader (`_period_filters`,
`_plan_period` with `planning_horizon`), the per-person chart, Flagged schools
(`team_flagged_schools`) and, for Country Oversight, the coverage dashboard;
each is its own piece.
