# 37. Team Performance, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application's only backend. This piece moves the
Team Performance page (`/team-performance/`, "My Performance" for a CCEO):
the FY27 Weekly Report's six tabs, read from the records when the page opens
(docs/team-performance-report.md).

| Piece | What moves | State |
|---|---|---|
| 1 | The page as the app opens it: its filters, its tabs, the Executive Summary (strip, breakdown table, every section's charts, delivery milestones), the Detailed Country Report, Strategic Milestones, the CCEO dashboard's five views, the {Month} {Year} Summary and Core Visits & Training; and one section's charts on their own (`?charts=`) | This document |
| — | The Country Targets editor (`/team-performance/country-targets/`) and its save | Still the existing application's (the feed never opens it) |

## 37.1 What the app's feed opens

`apps.mobile_feed.views.NATIVE_PAGES` names `team_performance`, the URL
`/team-performance/`. The address without its slash and everything under it
(the Country Targets editor among them) is "This page is not available"
(404) for every account, and so it is in Go. The keys of a download never
reach the page (`NOT_PASSED`).

The page opens for CCEO, Program Lead, Country Director, Impact Assessment,
Human Resources, Regional Vice President, Regional Program Lead and Admin
(`require_page_permission("team_performance")` and the feed's
`can_open_url`); every other role is not found. A role the page's own gate
would turn away with its access-denied page while the feed still opens the
URL is left to the existing application (none today).

The Executive Summary loads each section's charts as the reader reaches it
(`hx-get … &charts=<section>`, `hx-trigger="intersect once"`); the feed
fetches each of those parts and reads them in their place. Go builds the
same parts from the same report in the same answer.

## 37.2 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/teamperformance` for `/team-performance/`, for
someone working in their own role. Anyone in an acting capacity is passed to
the existing application as before.

| Part | Existing rule it ports |
|---|---|
| Who reads what | `roster.reach_of`: CD, IA, HR, RVP, RPL and Admin everyone, grouped by Programme Lead; a Programme Lead themselves and the CCEOs whose direct line is to them (`visible_staff`, `direct_leads`: the first Programme Lead supervisor assigned); anyone else only their own row. The ledger is narrowed to the visible officers' schools (`Ledger.load(owners=…)`) |
| The roster | Active users holding CCEO or Program Lead, by name; a lead listed when they hold schools; teams keyed by lead, the lead first then officers by name; a team's place is where most of its schools are (by name on a tie); teams in the workbook's region order, then by lead name, "No Programme Lead" last; two leads of a name told apart by place. An officer's region is where most of their schools are, else their primary district's |
| The records (`ledger.Ledger`) | Schools (not deleted; newest first), the owner read in either id space; work achieved from submission to the PL on, planned while in somebody's plan, dated by the day done else the planned day (the scheduled moment read on Nairobi's calendar); cluster registers (invited or attended), legacy attended lists, work at no school credited to the responsible officer and planned only when it has no register; Core package slots numbered by date with a slot just outside the year placed inside it; onboardings marking a Core SSA a baseline; SSAs pending or confirmed (the year's latest score); Discipleship and learning records; enrolment from the school's dated figure and its history; approved stories; disbursed loans; the Alumni project by name or code |
| Measures | Every Weekly Report row (`measures.MEASURES`): label, section, unit, source, milestone and slice, basis, tracked, and the work each one matches — the predicate's maker and the values it was made with, read from its closure by the export |
| Targets (`targets.TargetBook`) | IA's or Admin's country target first; else the Uganda Master Priority Plan milestone for the year (country level, Uganda, with a cycle): a percentage milestone as that share of the eligible schools (`round`, half to even), a count milestone's Core or Client slice, a team's approved allocation else its officers' added up, an officer's own; monthly phasing from the approved month targets, a slice's share of each; a coverage row with no milestone takes its eligible schools; otherwise "Not set" |
| Periods (`periods.ReportPeriod`) | Week, month, quarter or year of the chosen FY (a year from a link read only when it is four digits; a past year opens on September, a future one on October); the week's Monday from an ISO date or week; to date, before, through a quarter, the month to date |
| The tabs | `report.Report`: `executive_summary` and `breakdown.resolve` (a CCEO by district, a lead by CCEO, everyone else by region, lead, CCEO, narrowed by a region or a lead), `place_split` (achieved where its school is, a session where most of the schools it reached are; each holder's target shared by largest remainder across their eligible schools' places; "Not placed"), `delivery_milestones`, `row` (the month, Q1–Q4 cumulative and the year, Planned beside each), `milestones` (the 54 rows: count, rate, score, untracked), `cceo_board` and `deep_dive`, `month_summary` and `summary_columns`, `core_package` |
| Words | Status (100% Achieved or On Track while running, 75% Progressing, else Needs Attention), the dash for no figure, `num`, `pct` and `signed` as `team_performance_tags` writes them |

The vocabularies are exported to `internal/teamperformance/rules.json` by
`manage.py export_team_performance_rules` (the command lives in
`apps/frontend`, beside the view, because `apps.team_performance` is not an
installed app); `apps/team_performance/test_team_performance_rules_export.py`
fails when the two differ. Nothing in the existing code changed.

The page is written as its templates write it, as a tree of elements
(`page.go`), and read into blocks by a port of the part of
`apps.mobile_feed.page_blocks` and `css_charts` this page reaches
(`dom.go`): the walk, the fallback panels (headings, lines, link lists and
the label-and-figure pairing), bare tables, empty states and the indicator
cards' charts read from their bars' titles. That is how the dashboard's
cards come out as one panel per grid, as the feed reads them, and how an
indicator card whose chart has no bars falls apart into its heading, its
caption and its table.

Found by reading, kept as the feed does:

- **A chart's series follow the first bar read.** A bar whose figure is a
  dash has no title figure, so a Programme Lead chart with no targets has
  only an Achieved series, and one whose first target is missing lists
  Achieved before Target.
- **A card's footer loses its words.** "Enrollment:" sits beside its figure
  in one span, so the feed keeps the figure and pairs it with the line
  before it ("Cohort: 0 · Client: 0" = "—").
- **The year in a link is kept as typed.** `str(fy)` keeps " 2027" or
  "+2027" as given once it reads as a year; the filters then select no year
  and show the first, and the links carry the text.

## 37.3 Proving it is the same

### On the development database

`cmd/parity -screen page -path /team-performance/`
(`cmd/parity/page_team_performance.go`) asks the Go-only gateway and the
existing feed the same questions for every seed account: every tab as it
opens and for FY 2026, 2028, 1999 and "abc"; every period kind with weeks
(ISO date, ISO week, out of the year, nonsense), quarters and months in and
out of range; the Detailed Country Report for every scope the reader is
offered; every dashboard view, sort, lead chip and the first officers'
deep dives; the summary at each level, narrowed by region and by each lead;
a section's charts on their own, an unknown section, and charts asked on
another tab.

All 29 seed accounts against a gateway with no existing application behind
it, each run's last lines exactly as printed. The full set (109 questions
for a CCEO or a role turned away, 121 for a Programme Lead, 146 for a reader
of the whole country):

    run 1 (cceo2, cceo1, cceo, pl1, admin):
    594 answers compared, 0 differing
    443 answers held rows with the same name, compared in School ID order (the existing page gives them none)

    run 2 (the other 24): business-transformation and cceo10 to cceo18
    each "109 questions, 0 differing"; PostgreSQL was stopped at 13:05 by
    another worktree's process cleanup, so cceo19 failed half way (21
    answers lost to the dropped connections) and the rest could not sign
    in; the run printed no total.

    run 3 (cceo19, cceo3 to cceo9, cd, ia, pl2, pl3, pl4, coordinator, after the restart):
    1636 answers compared, 0 differing
    1135 answers held rows with the same name, compared in School ID order (the existing page gives them none)

A smaller set first (`EDIFY_PARITY_TEAM_PERFORMANCE=lean`: every tab, view,
period kind and level, 28 to 33 questions an account), all 29 accounts:

    847 answers compared, 1 differing
    568 answers held rows with the same name, compared in School ID order (the existing page gives them none)

The one was cceo2's page as it opens, which the existing application
answered with a 500 ("connection timeout expired" from the database, the
machine loaded by six agents); asked again in run 1, it is the same.

`cmd/parity` puts runs of table rows that share their second cell in first-
cell order before comparing (a rule made for name-ordered lists). Most of
this page's rows share a second cell ("—"), so the run above does not prove
row order on its own. A strict comparison was run beside it
(`agent21_strict.py`, not committed: every field, rows in their order,
defaults dropped on both sides as protojson drops them):

    90 answers compared strictly, 0 differing

(admin, pl1, pl2, cceo, cceo1, cd; every tab and view, by lead, by CCEO,
narrowed to Central, a week and a quarter). The golden comparison below is
order-strict too (`proto.Equal`).

### On a synthetic year (the Go integration database)

The seed has no FY 2027 country-level master milestones, no allocations,
phasing or country targets, one officer holding every school, no Core
package, no cluster registers, Discipleship or learning records, and no
stories at a school. So
`internal/integration/testdata/team_performance_rows.sql` writes a year into
`edify_gorn_a21_test` (ids "tpg…", removed after by
`team_performance_rows_cleanup.sql`): ten schools across four regions and
none, owned by two CCEOs (one by user id), a Programme Lead and no one,
closed and reopened ones and new ones; 21 activities of every kind and many
statuses, staff and partner, online and in-school, with a register (attended
and invited only), a legacy attended list, work at no school, a meeting held
as a training and one as Cluster Leaders, the Alumni project; a Core package
with linked and unlinked slots and one dated before the year; an onboarding;
SSAs confirmed, pending, returned and dated across the year's edge;
Discipleship, OneTest and exam records; enrolment history; stories at a
school and at none; nine master milestones (count, percentage, Core and
Client slices), ten approved allocations (team and employee, rate and count)
with monthly (and a quarterly, ignored) phasing; three country targets IA
and Admin set (with months, without, and one a strategic row's rate).

The existing feed's answers over that year were taken from
`edify_gorn_a21_test` for eleven accounts (Admin, IA, CD, Programme Leads
1–3, the seeded CCEO, the two CCEOs holding the synthetic schools, a CCEO
holding none, and the Project Coordinator), 36 questions each: every tab,
every dashboard view, sorts, a lead's grid, both officers' deep dives,
every summary level narrowed by region and by lead, week, quarter and year
periods, October, scopes for a team, each officer and "No Programme Lead",
the previous year, and two sections' charts. The rows were then removed and
`TestTeamPerformanceMatchesTheExistingFeedOverASyntheticYear` filed them
again and compared Go's answers with `proto.Equal` (rows in order):

    team_performance_test.go:215: 396 answers of 11 accounts compared, 0 differing

The synthetic rows were removed after (0 "tpg" schools left).

### Tests

- `internal/teamperformance/page_test.go`: figures and status words, half-
  to-even shares, the largest-remainder spread, families, every predicate
  shape on work at a school and at none, periods (week, ISO week, quarter,
  year, past and future years, bad values, week options), the target book
  (rate, Core and Client slices, team and officers' allocations, phasing,
  eligible schools, country targets), stored month order, a chart's series
  order, panel pairing, an empty chart card, a session's place, the doors.
- `internal/integration/team_performance_test.go`: each reach's header,
  tabs and total; refusals; a CCEO's Core package over the synthetic year;
  and, with `EDIFY_TEAM_PERFORMANCE_GOLDEN`, Go's answers against the
  existing feed's over the synthetic year.

Runs (2026-11-13): `go test -race -count=1 ./...` in `platform/backend`
all ok; `gofmt -l .` empty; `go vet ./...` clean; the integration tests
above and `TestGatewayRoleCanNeitherWriteNorReadSecrets` PASS on
`edify_gorn_a21_test`; `ruff check`, `ruff format --check` and `bandit -q -r`
clean on the export command and its test; the drift test OK.

## 37.4 Grants

Appended to `platform/deploy/db/roles.sql` and applied additively to
`edify_gorn_dev` and `edify_gorn_a21_test`: figures, dates, statuses and ids
only (the project's code, a school's closing moment, the catalogue's stable
code and method, Core slots, onboardings, Discipleship records, a story's
author, a supervision's date, the master priorities, milestones, approved
allocations and phasing, and the country targets).

## 37.5 What is left

- The Country Targets editor and its save.
- Not reached by the seed or the synthetic year, and covered by unit tests
  only: two Programme Leads of the same name (told apart by place), a
  monthly_targets value that is not an object, an edtech loan (the
  integration database has no lender to file one against; the development
  database's two development loans are compared).
- Figures that read "today" move with the date: the golden answers are
  compared on the day they are made.
