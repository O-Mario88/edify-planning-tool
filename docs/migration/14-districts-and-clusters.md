# 14. Districts and clusters (M2), first piece: the Clusters page, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "District and Cluster management". The migration plan's M2
(04-migration-plan.md) asks for parity on cluster lists and membership per
account. It moves in pieces, each proved against the existing page before
the next.

| Piece | What moves | State |
|---|---|---|
| 1 | The Clusters page (`/clusters`): whose clusters, its filters, strip, cards, doors and pages | This document |
| 2 | A cluster's schools, loaded when its card opens (`/partials/clusters/<id>/schools`) | Next |
| 3 | The Cluster Page and Cluster Profile (`/clusters/<id>`, `/clusters/<id>/profile`) | Planned |
| 4 | District profiles (`/districts/<id>`) | Planned |
| — | Every drawer and save (create, edit, delete, facilitator, add schools, schedule) | Still the existing application's |

## 14.1 What moved

`PageScreenService.GetPage` (`platform/proto/edify/screens/v1/page_screen.proto`,
unchanged) is now answered by `platform/backend/internal/clusterpage` for the
path `/clusters`, for someone working in their own role. Every other page,
and anyone in an acting capacity, is passed to the existing application as
before.

The contract is the existing generic page (`PageHeader`, `PageBlock`), which
the existing application fills by reading its own HTML
(`apps.mobile_feed.page_blocks` and `records`). Go builds the same blocks
directly from the data.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("clusters")` and the feed's `can_open_url`: CCEO, Program Lead, Admin, Country Director, Impact Assessment. Anyone else is not found, as the feed answers |
| Whose clusters | `cluster_queryset(scope, direct_only=True)` over active clusters: a country reader's country (the cluster's region, or its district's); every cluster for a summary reader; otherwise the clusters filed under the reader's user or staff profile id (either id space, `cluster_owner_ids`), those of their own schools, and the ownerless ones in their own schools' districts |
| Filters | Fiscal year (`fy_options`, an unknown year read as the operational one), Quarter, District and Sub-county (from the reader's own clusters), Staff (every live staff profile), SSA status, Cluster risk, Activity status, and the search (name or district) |
| The strip | `get_dashboard_data`'s eight figures over the listed cards, shares rounded half to even, the weakest intervention averaged over each card's four weakest and abbreviated as the strip abbreviates it |
| A card | `build_cluster_cards` and `cluster_planning`: location (covered sub-counties in the order they come back, then the cluster's own, its given name, or "District-level cluster"), leader, phone, facilitating partner, schools (operating, Champion left out), assigned staff, the average of each school's latest confirmed assessment, meetings this year, last meeting and training, SSA coverage, schools without an SSA, needing a baseline, needing clean-up, ready for planning, the risk (`get_cluster_risk`) and its next action; each fact in the colour its holder gives it |
| Its menu | Schedule Group Training, Schedule Cluster Meeting and Partner to Facilitate for a planner (`can_view_page("planning")` and `can_schedule_activity`); Add Schools for a reader of Planning |
| Opened | The intervention scores grouped as `build_ssa_score_summary` groups them, and the schools list it loads (still the existing application's) |
| Pages | Five cards a page, `Paginator.get_page` (not a number: the first; out of range: the last), `get_elided_page_range(on_each_side=1, on_ends=1)` |

Each role's doors, the statuses and activity types each figure counts, the
interventions and the strip's labels are exported to
`internal/clusterpage/rules.json` by `manage.py export_cluster_page_rules`;
`apps/clusters/test_cluster_page_rules_export.py` fails when the two differ.
The planning statuses were local to `cluster_planning`; they are now module
constants there (`PLANNING_DONE_STATUSES` and the rest) so the export reads
them rather than restating them. Nothing they count changed.

Two things were found by comparing, not by reading:

- **Averages are added in the order Postgres reads the rows.** Six scores
  averaged 5.1499999999999995 by the page's statement (shown 5.1) and 5.15 by
  a differently shaped one (shown 5.2). Go reads the latest assessments first
  and then averages over that list with the page's own statement shape
  (`IN (SELECT unnest($1::varchar[]))`), so the plan, and the sum, are the
  same.
- **Covered sub-counties have no order.** The page lists them as its prefetch
  returns them; a join re-sorted them. Go reads the links on their own, as
  the prefetch does.

## 14.2 Proving it is the same

`cmd/parity -screen page -path /clusters` signs each account in and asks the
Go-only gateway and the existing feed (`/api/mobile/v1/page`) the same
questions: the page as it opens; pages 2, 3, 999, 0, "abc" and " 2 "; years
2026, 2025 and 1999; quarters Q2 and Q9; four searches; every SSA status,
risk and activity value; an unknown district; risk and page together; and
every district, sub-county and the first staff choices the page offers.

All 29 seed accounts against a gateway with no existing application behind
it: 870 answers (44 for each reader of the whole country or the seeded
officer, 28 for an officer or lead with no clusters of their own, 25 for the
two roles turned away), none differing. The first full run differed in 60
answers, every one the order of covered sub-counties (14.1); the run after
the fix differed in none.

The seed's clusters have no leader, no facilitating partner and no
sub-counties of their own beyond one, and fill three pages. Seven clusters
were added to the development database through the existing services as the
CCEO, each named "[Go parity check] Cluster n": covered sub-counties out of
alphabetical order, one with none, leaders with stray spaces, a phone, and
one handed to Literacy Uganda to facilitate. They make five pages, so the
pager's gaps are compared too. Every seeded cluster is still Critical (under
half its schools assessed), so Needs Attention and Healthy are proved by unit
tests built from `get_cluster_risk`'s order.

## 14.3 What is left

- A card's schools, loaded on opening (piece 2), and the Cluster Page and
  Profile (piece 3).
- Every drawer and save stays the existing application's.
