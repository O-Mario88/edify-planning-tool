# 67. Merge regressions: Go follows the merged feed reader

After page-header-actions (60), web-clusters/web-fixes (39.6/52) and
web-fixes-3 (64) merged into `feature/edify-go-rn-migration`, the feed reader
(`apps/mobile_feed/page_blocks.py`) reads more of each page than the Go pages
that those branches did not cover were built to give. The coordinator's
parity (five accounts, `$SP/m28_*.txt`) showed four Go pages behind. The
Django reader was not changed: each reader change was the intended one, so Go
was brought to it.

| Page | What the merged reader reads | What Go now does |
|---|---|---|
| `/projects/monitoring` | The whole header band (60): Consolidated tables (`edify-action-button` link), and while a project tab is open and the reader may export, Export all projects and Export this project (`/export` paths: downloads); hrefs in name order, blanks dropped (`_resolved`) | `projectmonitoring.headerActions` with `pageheader.Link/Download/Href`; two new doors exported by `export_project_monitoring_rules`: `consolidated` = `can_view_page(country_planning_oversight)`, `export` = `can_export(user, /projects/monitoring)` |
| `/work-plan` | Export Excel's href `/work-plan/export.xlsx?{{ request.GET.urlencode }}` normalised: an empty query leaves no `?` | `pageheader.Href("/work-plan/export.xlsx", query)` (the package's own `requestQuery` removed) |
| `/team-performance/` | Words of a part's own around its elements read whole (`_mixed`/`_sentences`, 39.6): the officer card's footer "Enrollment: —" is one text item, so "Cohort: 0 · Client: 0" no longer pairs with "—" | `teamperformance/dom.go` ports `INLINE`, `_mixed`, `_sentences` (lead, textLinks, tone of the part, blocks inside read in turn) and `_paired`'s rule that only a bare text (text and tone) pairs |
| `/partner-oversight/` | A select's caption (`_filter_caption`, 39.6): the short word drawn beside it when it differs from its name: View, FY, Quarter (Month's "Month" does not) | The three captions on the period filter bar |

Integration tests `TestTheClustersPageListsTheOfficersOwnClusters` and
`TestTheStaffActivityLogCountsAnOfficersDay` now expect the header keys the
feed reads (Clusters: create_cluster, schedule_group_training,
schedule_cluster_meeting, export; Staff Activity: export, follow_up_queue).

## Parity

Go-only gateway (127.0.0.1:8082) against the existing application from this
branch (127.0.0.1:8182, edify_gorn_dev), all 29 seed accounts, `-pause 21s`,
after merging `feature/edify-go-rn-migration` at b682e1a31. Last lines:

| Run | Last line |
|---|---|
| /planning | 1605 answers compared, 0 differing (124 held rows) |
| /my-plan | 1943 answers compared, 65 differing (all cceo@ pass-ons) |
| /calendar | 1961 answers compared, 0 differing |
| /work-plan | 3993 answers compared, 0 differing |
| /clusters | 1044 answers compared, 0 differing |
| /partials/clusters/{id}/schools (4 clusters) | 464 answers compared, 0 differing |
| /cluster-oversight/ | 928 answers compared, 0 differing |
| /core-schools-oversight/ | 3712 answers compared, 25 differing (core-recommendations: admin, cceo, cd, ia, pl1 × 5) |
| /staff-activity | 1632 answers compared, 18 differing (pass-ons, admin 9, cd 9) |
| /team-performance/ | 3494 answers compared, 0 differing |
| /team-planning-oversight/ | 2117 answers compared, 0 differing |
| /country-planning-oversight/ | 696 answers compared, 69 differing (pass-ons, admin/cd/ia 23 each) |
| /projects/monitoring | 603 answers compared, 0 differing |
| /partner-oversight/ | 1062 answers compared, 356 differing (all pass-ons; 990 before the captions) |
| /todos | 145 answers compared, 15 differing (pass-ons, cd/ia/pl1 5 each) |
| /decision-log | 783 answers compared, 0 differing |
| /escalations | 551 answers compared, 0 differing |
| /actions/mine | 406 answers compared, 0 differing |
| /actions/sent | 406 answers compared, 0 differing |
| /programme-schools | 891 answers compared, 0 differing |
| /schools/closed | 580 answers compared, 0 differing |
| navigation | 29 answers compared, 0 differing |
| profile (details) | 3822 profiles compared (3233 not Core), 0 differing |

Every difference left is a pass-on (Go hands the reader to the existing application, which a
Go-only gateway cannot reach) or the known core-recommendations defect
(doc 22, backlog core-recommendations).

## Left

- The existing application answers 500 for `fy=abc` on `/partner-oversight/`
  (admin, cceo) and `/country-planning-oversight/`; Go passes those readers on,
  so the answer stays the existing one.
- Pages whose readers are passed on (My Plan for cceo@, Staff Activity for
  admin/cd, To-Dos for cd/ia/pl1, Country Oversight for admin/cd/ia, Partner
  Oversight with rows) will meet the same reader rules when they are built.
