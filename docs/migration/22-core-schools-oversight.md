# 22. Core School Oversight, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application's only backend. After Cluster Oversight
(15-cluster-oversight.md), this is the oversight page beside it: Core School
Oversight, as the app opens it.

| Piece | What moves | State |
|---|---|---|
| 1 | Core School Oversight (`/core-schools-oversight/`): its filters, its strip, its tabs, and the Schools, Groups, Attention, Recommendations and Champion Readiness tabs with the table's pages | This document |
| — | The Core School Visits and Core School Trainings tabs (`?tab=core_visits`, `?tab=core_trainings`) | Still the existing application's: they are My Plan's own tables (22.5) |
| — | The CSV and Excel downloads, a recommendation's Accept / Defer / Reject, the Champion review drawer | Still the existing application's |

## 22.1 What the app's feed opens

`apps.mobile_feed.views.NATIVE_PAGES` names `core_schools_oversight`, the URL
`/core-schools-oversight/`. Nothing else under it is a page: the address
without its slash and every address below it resolve to nothing, and the
feed answers "This page is not available" (404) for every account. `format`,
`export`, `download` and the other keys of a download never reach the page
(`NOT_PASSED`). Go answers the same.

The page is refused (`core_schools_oversight` in `PAGE_ACCESS`, and the feed's
`can_open_url`) to every role but CCEO, Program Lead, Country Director,
Regional Vice President, Regional Program Lead, Impact Assessment and Admin.

## 22.2 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/coreoversight` for `/core-schools-oversight/`, for
someone working in their own role, on every tab but the two of planned work.
Anyone in an acting capacity is passed to the existing application as before.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("core_schools_oversight")` and `can_open_url` |
| Whose schools | `intelligence.scoped_core_schools`: operating schools (not deleted, `active` or `reopened`) of the Core lifecycle (Core, Core Trained, Core Graduate, Champion), in the School model's order (newest made first). A Programme Lead reads the schools held by them or their live supervisees, in either id space, or in a cluster any of them holds (`oversight_service.scoped_core_queryset`); everyone else `scoping.scoped_school_queryset` (`schooldirectory.AnalyticsReach`) |
| Names | The officer as `clusters.oversight_service._label` names them through `_staff_directory` (live profiles, by profile id and user id; "Unassigned" otherwise), the cluster if it is not deleted, the sub-region |
| SSA | Latest and previous: each year's newest confirmed record's own average to two places, else the mean of its scores (`year_comparison.school_year_scores`); the weakest intervention, the lowest of the year's newest record's scores, the first by key on a tie (`school_current_scores`); trajectory and change: the school's verdict over its comparable pairs under the published rules (`impact_engine.improvement_rows`, `change_rules.classify_pairs` and `school_verdicts`), judged by Cluster Oversight's own port (`clusteroversight.SchoolVerdicts`, 22.4) |
| The package | The year's Core plan, filed under the school's id or its School ID, the last read speaking for it: done and target, complete, the share done each kind capped at its target, "No package", "None%" for a plan with no target |
| Hand-overs | Partner hand-overs made in the year (1 October to 1 October, UTC) by state: unscheduled, scheduled, done |
| Participation | The delivered cluster sessions' register in the year (invited, came, teacher and leader headcounts of those who came) and the school's own delivered trainings that are not cluster sessions |
| Outcomes | Enrolment in the two years, and the learning score of each (`clusters.outcomes._school_scores`: confirmed class results as a share of the marks, weighted by learners tested, rows in the model's order) |
| Champion readiness | `_read_champion` over `ChampionEligibilityService.scan`: a Core profile, a live plan (the running year's, else the newest; closed plans aside), confirmed SSAs oldest first, the latest one's scores, the school's closed activities and those with accepted evidence; the official formula and its bar (8.0 average, nothing below 7.0, 8 package slots done); stored Champion statuses and the Champion type |
| What a school needs | `_attention`: declined, a Critical weakest area (below 5.0 by `ssa_score_band`), no current-year SSA, an unscheduled hand-over, a package incomplete, a Potential Champion |
| Filters | Year (one of `fy_options()` newest first, else the operational year), district and type (from every school in scope), trajectory, need, readiness, search by name or School ID; each read stripped as `_choice` reads it, each select shown with the value as sent |
| Sort | School, latest SSA, SSA change, package, attendance; a missing figure last; stable, as Python's sort is |
| The strip | `intelligence.summarise` over the schools shown: a rate is its totals' ratio; "of n in your scope" when filters narrow it; each tile's link keeps the page's own query (`QueryDict.urlencode`, tab and page aside) |
| The tabs | Schools (21 columns, fifty rows a page, `make_pagination_window(window_size=1)`, the pager's links keeping the rest of the query as `pager_query` keeps it), Groups (by CCEO, district, sub-region or cluster, largest first, "Not recorded" for none), Attention (each need's schools), Recommendations (`intelligence.recommendations`: open or planned, by rank), Champion Readiness (the Review button for a Potential Champion, for a reader of the Core Schools page) |
| A school's name | A link to its profile for a reader `/schools/0` lets in (`{% school_link %}`); a Regional Vice President's or Regional Programme Lead's lists carry no name at all, because the feed does not read a line of text beside an element (22.3) |

Each role's three doors (the page, school links, the Champion review), the
tabs, filters, sorts and groupings, the trajectory words and tones, Champion
readiness and what a school needs, the statuses and activity types each
figure counts, the Champion rule's statuses, the intervention labels, the
school types and the recommendation states are exported to
`internal/coreoversight/rules.json` by `manage.py export_core_oversight_rules`;
`apps/core_schools/test_core_oversight_rules_export.py` fails when the two
differ. The Critical line is read off `ssa_score_band` itself, in
hundredths. Four literals were lifted to module constants so the export reads
them, with no change in behaviour: `intelligence.STORED_CHAMPION_STATUSES`
and `champion_services.CONFIRMED_SSA`, `CLOSED_STATUS`, `CLEAN_EVIDENCE`.

Every statement is issued in the shape and order the existing page issues it:
the schools by `-created_at` (the order a name sort keeps for schools sharing
a name), the learning results by `-assessed_on, school_id` (a float sum
depends on its order), the SSA records newest first with the same ties. The
Champion formula and the learning sums are computed with every product
rounded on its own: Go fuses `a += x * y` into one multiply-add on arm64,
which Python never does (22.4).

## 22.3 Found by comparing

- **A one-word heading is lost.** On the Attention and Champion Readiness
  tabs each card's heading and its count are read as one word with nothing
  between them ("Champion39"), and the feed draws no part of fewer than two
  words. So "Champion" and "Progressing" arrive with no heading, their
  schools under the previous card's. Go answers as the feed does.
- **Names disappear for a reader without school links.** Where the school's
  name is plain text beside a caption (Attention, Champion Readiness), the
  feed reads only the caption; the recorded item's catalogue training on the
  Recommendations tab is lost the same way, for everyone.
- **The table's note is the pager's caption** with more than fifty schools,
  as on Cluster Oversight.
- **The filters show what was sent, not what was used.** " declined " filters
  to the declined schools, but the select shows "Any".

## 22.4 Proving it is the same

**Against the existing feed, every seed account.** `cmd/parity -screen page
-path /core-schools-oversight/` asks the Go-only gateway and the existing
feed 73 questions each: the page as it opens; years 2028, 2027, 2026, 2025,
1999, " 2026 " and "abc"; each tab Go draws, one that is not a tab and one
with spaces; every trajectory, need and readiness value the seed reaches,
with spaces and nonsense; a district, a type, each sort; searches by name,
School ID, in capitals with spaces, and for nothing; `page` 1, 2, 3, 999, 0,
-1, "abc" and " 2 "; every grouping; two sorts on each list tab; filters,
tabs and pages together; and a download's keys. The two other kinds of
address were asked as they open, 29 accounts each.

Each is the run's own last line, 29 seed accounts, against a gateway with no
existing application behind it:

```
/core-schools-oversight/         2117 answers compared, 0 differing
/core-schools-oversight            29 answers compared, 0 differing
/core-schools-oversight/xyz        29 answers compared, 0 differing
```

The last two are "not found" from both for every account; the 2,117 are 73
questions for each of the 29, the two refused accounts (Business
Transformation, Project Coordinator) "not found" from both every time.

**Against the existing code, for records the seed does not hold.** The seed
holds 141 Core schools, all one officer's, in one district, none compared on
SSA, enrolment or learning, no published change rule, no Potential Champion,
no register, 20 partner hand-overs and 3 recommendations. `internal/coreoversight/testdata/golden.py` reaches the
rest without writing a record: it makes sets of records from a seeded random
source (SSA records with and without their own average, older records of the
same year, scores at 4.99 and 7.0, pairs under published rules and under the
fallback, plans under a school's id and its School ID, plans with no target
and over-delivered, hand-overs, registers with missing headcounts, the
schools' own trainings, enrolment from nothing, weighted class results,
every stored Champion status, live plans of the running year and others,
Champion candidates and near misses, recommendations in every state, names
shared in different case, 130 and 420 schools) and has the existing
application's own code make the page of them: `intelligence`,
`champion_services`, `change_rules`, `year_comparison`,
`impact_engine.improvement_rows`, `clusters.outcomes`, the view, the template
and the feed's reader, unmodified, with only the statements stood in for (and
`package_splits`, whose figures the page does not show). `page_golden_test.go`
gives Go the same records and expects the same page: 40 pages, among them a
Regional Vice President's and a Regional Programme Lead's (roles the seed has
no account for), every tab and grouping, every sort, 44 Potential Champions
with their Review buttons, and tables of three and nine pages. They were
equal on the first run; changing a rule in Go (the two places of an SSA
average, the sustainability part of the Champion score, which class results
count) fails between 5 and 26 of them.

What the golden pages do not pin is in `page_test.go`: the running year's
plan speaking for a school over a newer one, the Champion formula at its
edges (checked against `_score_values` itself), a Decimal score written half
up, the page number and the pager's window, a one-word heading, a label and
its figure read as a data row, a filter read stripped and shown as sent, and
the two tabs left to the existing application.

Neither proves the statements beyond what the seed holds: which statuses and
types a statement keeps are exported, not restated, but a statement's joins
are Go's own writing. For the seed's Core schools four of them return
nothing at all (no register rows, learning results, enrolment figures or
published rules), so those four are proved against the seed only in that
they run and return nothing; their reading of rows is proved by the golden
pages alone.

## 22.5 What is left

- **Core School Visits and Core School Trainings.** Both tabs are
  `apps.my_plan.table_export.core_school_plans`: My Plan's own rows
  (`my_plan.services.get_frontend_context`, 2,600 lines: costs, budget and
  verification states, Salesforce IDs, package progress) for the schools the
  filters keep. They are passed to the existing application (`served` is
  false) until My Plan is Go's, and are not among the questions above.
- The downloads, a recommendation's decision and the Champion review.
