# 17. Programme Schools, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. Programme Schools is the list of
Core Trained, Core Graduate and Champion schools with what each has taken of
its year (owner, 2026-09-21).

| Piece | What moves | State |
|---|---|---|
| 1 | The Programme Schools page (`/programme-schools`): whose schools, the four figures, the three filters, the search, the table and its pages | This document |
| — | Scheduling from a row (the planning drawer and its save) | Still the existing application's |

## 17.1 What moved

`PageScreenService.GetPage` is answered by
`platform/backend/internal/programmeschools` for the path
`/programme-schools`, for someone working in their own role. Go builds the
blocks the existing feed reads from
`templates/pages/schools/programme_schools.html`.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("programme_schools")` and the feed's `can_open_url`: CCEO, Program Lead, Impact Assessment, Country Director, Admin. Anyone else is not found, as the feed answers |
| Whose schools | `programme_schools._scoped`: live schools of the three types that are operating, within the reader's analytics reach (`scoped_school_queryset`, `schooldirectory.AnalyticsReach`) |
| Filters | School type (one of the three; anything else filters nothing, though the page then says its filters matched nothing), District (every district, by name), Fiscal year (`fy_options`, an unknown year read as the operational one), and the search: the text anywhere in the name or the School ID |
| The type filter's counts | The filtered list by type, counted in the database, so a chosen type shows the others as 0 |
| The four figures | Programme schools: the whole filtered list. With a visit planned, No visit planned and Attached to a training: counted over the rows the page holds (at most 500, `programme_schools(limit=500)`), as the existing code counts them |
| A row | School ID (written by the page's script, read empty), name and official ID (always a link), type, district or a dash, the owner's name (`_owner_names`: a live staff profile's user, else a live user, else "Unassigned"), the average of the latest confirmed assessment of any year in its band's colour or "Not assessed" (`_ssa_averages`), staff support visits used of allowed with what is left (`visit_gate`: `staff_visits` of `staff_cap`), the visit status and its day (`visit_statuses`), the training coverage (`cluster_training_coverage`; red unless a session is planned) |
| The row's action | Schedule for a planner (`can_schedule_activity`: CCEO, Program Lead), View for anyone else. The feed reads a link only from View: Schedule is a button it reads as text, so whether this school may be scheduled, and why not, never reaches the app |
| Pages | Fifty rows, `programme_page`, the same pager as the archive's (16.1), read as a panel under the table; then the line about partner delivery |
| Nothing to list | The filters' line when a search, a type or a district is on, otherwise the page's own |
| The header | "Clear search" with the search cut to 24 characters, while one is on |

Each role's two doors, the three types with their labels in the page's
order, the operating statuses, the row limit, the page size and the query
keys the feed drops are exported to `internal/programmeschools/rules.json` by
`manage.py export_programme_schools_rules`;
`apps/schools/test_programme_schools_rules_export.py` fails when the two
differ. The limit is read from `programme_schools`' own signature.

Nothing about a visit, a status or a training is restated here. The row
reads the visit rule through `visitgate.Of` with the school profile's
exported rules (`schoolprofile.GateRules`, `export_programmeschools.go`), and
the status, the coverage and the SSA summary through the directory's own
functions, given list forms in `schooldirectory/export_programmeschools.go`
(`VisitStatusesOf`, `CoveragesOf`, `LatestSSAAverages`). The pager, the
"Clear search" button and the feed's text rules are the archive's
(`closedschools/shared.go`).

Two things were found by comparing, not by reading:

- **Schools with the same name have no order between them.** The list is
  sorted by name alone. On the seed, where eight names are shared, both sides
  returned them in the same order for every account. On a varied copy of the
  database a Program Lead's list came back with two same-named schools
  swapped (twelve of their 31 answers; every other account's matched),
  because Postgres is free to return ties either way and the two statements
  were planned differently. Once the shared names were made distinct, every
  answer matched (17.2). Go cannot follow an order the existing page does
  not define; the fix is a second sort key in `programme_schools`, which is
  the existing application's to make.
- **The figures above the list are not all of the same list.** "Programme
  schools" counts every matching school; the two visit figures and the
  training figure count only the first 500 by name. Past 500 schools "No
  visit planned" (the total less the planned) overstates. Go does the same.

## 17.2 Proving it is the same

`cmd/parity -screen page -path /programme-schools` asks the Go-only gateway
and the existing feed the same questions as each account: the page as it
opens; each type, a type the page does not list and one that is not a type;
every year offered and one that is not; eight searches (by name, by School
ID, upper case, padded, matching nothing, `%`, `_`, longer than the header
shows); `programme_page` 2, 0 and "abc"; a district that is not one and a key
the page does not read; three combinations; and, for a reader of the page,
the first district offered and Mukono, each alone and with a type and a
search.

All 29 seed accounts and the Regional Vice President against a gateway with
no existing application behind it. The run's last lines:

    coordinator@edify.org              27 questions, 0 differing
    rvp@edify.org                      27 questions, 0 differing

    918 answers compared, 0 differing

31 answers for each of the 27 readers of the page (27 questions and the four
district ones), 27 for each of the three roles turned away (the Project
Coordinator, the Business Transformation Officer and the RVP).

The seed's programme schools are 39 Champion schools, all one officer's, all
assessed, none with a visit or a session this year (eleven have visits in FY
2026, which the year questions reach: "Visit Completed", "1/1 entitlement
used"). It holds no Core Trained or Core Graduate school, no school without
an owner, a district or an assessment, and too few for a second page.

**A varied private copy.** The development database was copied to a private
local one (`edify_gorn_agent2_test`, dropped afterwards) and varied there by
`agent2_private_mutate.py` (session scratchpad): 80 client schools made Core
Trained (45) and Core Graduate (35); some with no district, no owner, an
owner filed under a user id, an owner id nobody has, no cluster, or their
assessments deleted; 24 visits of the year cloned onto them (scheduled,
submitted, in-school trainings, cancelled); 24 of them named on the year's
live cluster sessions; a donor visit at a Champion; one name with markup and
runs of spaces. The existing application and a Go-only gateway were both
started against that copy and compared by the same tool, as ten accounts
(Admin, Country Director, Impact Assessment, the seeded officer and their
lead, two officers and a lead with no schools, a Project Coordinator and the
RVP). With the shared names made distinct (17.1) it printed:

    302 answers compared, 0 differing

That run holds 119 schools on three pages and rows reading "Training
Planned", "Cluster Meeting Planned", "No Training Planned", "Not assessed",
"Unassigned", "2/1 entitlement used", "Scheduled for Visit", "Visit
Submitted" and "Visit Canceled" with their days. Before the names were made
distinct the same run printed `302 answers compared, 20 differing`, every
difference a pair of same-named schools exchanged.

**Unit tests** (`internal/programmeschools/page_test.go`) hold the row in
each shape, the entitlement by rule, the figures against a list longer than
the page, each filter's selected value, the two empty lines and the list's
WHERE; `internal/integration/programme_schools_test.go` asks the gateway as
an Admin, a planner and a role the page refuses.

## 17.3 What is left

- The visit rule is asked one school at a time (`visitgate.Of`), where the
  existing code asks it for the whole list in a few statements
  (`visit_gates`). A full page of 500 schools is about two thousand small
  reads. It is correct and, on the seed, quick; a list form of the gate is
  the next thing to write before a country with hundreds of programme
  schools opens the page through Go.
- Same-named schools (17.1) wait on a second sort key in the existing code.
- Scheduling from a row stays the existing application's.
