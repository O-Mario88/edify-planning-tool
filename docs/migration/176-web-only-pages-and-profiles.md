# 176. The web-only pages, and the profiles of many schools

Every page the apps open (the feed's `NATIVE_PAGES`) now has at least its
default view in Go. The Go work left is depth on those pages, plus the pages
only the web opens. The web-only pages are served in the same screens JSON
(PageScreenService builders) that the Next.js and Expo clients read.

## 176.1 How a web-only page is proved

The feed never opens a web-only page, so there is no feed answer to compare
with. `internal/webpages/testdata/web_page.py` makes one:

- it runs the page's own view, unmodified, for each reader, as the feed runs
  one of its own pages (`apps.mobile_feed.views._run_page` with the page's
  URL name, so `can_open_url` is asked);
- it reads the HTML with the feed's own reader (`page_body`).

Each answer runs in a transaction that is rolled back.

Of the inventory's 305 page routes, 213 are web-only, and many of those are
exports and downloads (page type `report`). The probe found 14 of the 100
web-only screens without path parameters already in Go. The school profile
is Go's SchoolProfileService.

The probe also found `/work-plan` failing for Impact Assessment with "column
sc.id does not exist". Inside `country.SchoolIn`, the registry subquery was
called "sc", which shadowed the caller's school. Its aliases are now its own
(`sin_*`), with `internal/integration/country_school_in_test.go`.

## 176.2 The profile engine over many schools

The profiles of a District, a Sub-region, the Country, a Programme Lead's
team, a staff member, a Partner and a Project are one engine
(`apps.analytics.profile_intelligence`, `profile_records`, `profile_rail`)
over a different scope, drawn by `pages/profiles/profile.html`. The School
360 is the same engine over one school, which internal/schoolprofile already
draws.

The profiles of many schools are built in the same package
(`scope_read.go`, `scope_figures.go`, `scope_overview.go`,
`scope_tables.go`, `scope_page.go`), reusing the school's rule book, change
rules, strips, intervention picks and rail. The export
`export_school_profile_rules` gains `engine.scope`:

- the operating statuses;
- each kind's sections and levels;
- the period options and the Schools tab's lists;
- the ranking sentences;
- the school types' order;
- the online mode.

## 176.3 The District profile's Overview (2026-11-18)

`/districts/<id>` (`extended_views.district_detail_view`) is drawn in Go on
its Overview.

**The frame:**

- the header: back to Districts, the scope line with the region first;
- the tabs; the facts (type, sub-region, the Programme Leads and the CCEOs
  holding its schools, the year); the year and period filters.

**The strips:**

- Portfolio, Performance And Impact, Operations;
- Loans And Business Transformation, for a reader of the loan register only.

**The tables:**

- the best and struggling intervention;
- What This Profile Covers, by clusters and schools;
- the four school rankings, and the method under them.

**The rail:** Profile Insights, with each intervention's meter and Needs
Attention.

A reader the page refuses is refused (not found).

**Still the existing application's:**

- every other tab;
- a figure's records (`what=`);
- any query key a profile's links do not carry;
- the other kinds of profile.

Proof: `TestTheDistrictProfileMatchesTheExistingPage` over the seed's
Mukono District (700 schools, with SSA, the FY 2026 work, hand-overs and
partners) and the empty Kamuli District. Each was asked by seven readers,
for the running year, FY 2026 and FY 2025, two periods, and an unknown year
and period: **112 answers, 0 differing**.

## 176.4 The District profile's SSA, Sub-counties, Staff and Schools tabs (2026-11-18)

- **SSA:** the Intervention Matrix, the score by intervention, and the
  Annual SSA Progress, from the same code as a school's SSA tab
  (`ssaSection`, `progressByYear` over a list of schools).
- **Sub-counties and Staff** (`profile_intelligence.groups`): the parts'
  table, fifty a page (`parts_page`), with the schools no part holds said
  under it. With more than one part, their four rankings follow.
  - A holder written as a staff id or a user id is one person.
  - A sub-county has no page, so its name opens the Schools tab for it, and
    in the rankings it links to its id alone, as the existing page writes
    it.
- **Schools** (`school_rows`): the Show filter's lists (no SSA, nothing
  planned, improved, declined, waiting for a Partner, no training or visit
  in the plan) and a sub-county's schools, fifty a page (`schools_page`).
  A District column appears when the scope spans districts.

- **Projects** (`_projects`): each project with schools in the scope.
  - Columns: its status, these schools, the project's whole size against
    the capacity its coordinator set, its work here (planned and done), and
    the schools' SSA.
  - The note under the table is drawn only when a project is listed.

Proof: the district golden adds each tab, the pages and every Show list:
SSA **40/0**, the parts tabs **60/0**, Schools **112/0**, Projects
**30/0**.

## 176.5 The Sub-region profile (2026-11-18)

`/sub-regions/<id>` (`profile_views.sub_region_profile_view`) is drawn in
Go on the same tabs as a District. Its schools are those whose district
lies in the sub-region, plus, where the district names no sub-region,
those whose own record names it.

- **The page:** back to the Country profile, the region first on the scope
  line, and facts for its region, country, districts, Programme Leads and
  CCEOs.
- **The Overview:** Portfolio counts its districts. What This Profile
  Covers reads districts as parts, by `groups`, beside clusters and schools.
- **The Districts tab:** its parts.

The gateway now reads `sub_region.region_id` (`roles.sql`).

Proof: `TestTheProfilesOfManySchoolsMatchTheExistingPages`, renamed from
the District test and keyed by `EDIFY_SCOPE_PROFILES_GOLDEN`. It asks the
Central sub-region (Mukono's) and an empty one, as seven readers, across
nine queries and tabs: **126 answers, 0 differing**.

## 176.6 The Country profile's tabs (2026-11-18)

`/country-profile` (`profile_views.country_profile_view`) is drawn in Go on
every tab but its Overview.

- **Whose country:** the reader's profile's, else the platform's
  (`training_ceilings.country_of`, `fy_policy.default_country`). Its schools
  are those whose region is the country's, plus those no region places.
- **The page:** titled "<country> Profile" under "Edify Operations", with
  no back link. Facts give the sub-regions, the districts, the Programme
  Leads and the staff holding schools.

**The Overview** carries the decision review (`profile_decisions`, the
leadership and budget boards) for a reader who holds it, and every role the
page opens to holds it (the Admin, the Country Director, Impact Assessment,
the RVP). It is still the existing application's. Its Needs Attention line
for districts whose Leadership score averages below 5.0
(`_low_leadership_districts`) is written, but has no proof until the
Overview is drawn.

Proof: the Country profile's SSA, Sub-regions, Districts, Staff, Schools
and Projects tabs, for the four readers and two it refuses: **42 answers, 0
differing**. The test now takes several golden files.

## 176.7 The Clusters tab (2026-11-18)

A profile's Clusters tab (`cluster_management`) is drawn in Go for
Districts, Sub-regions and the Country:

- **Cluster Sessions:** the clusters and the schools in one, the sessions
  held, attendance, the schools absent three sessions or more in a row, and
  the teachers and leaders reached.
- **Cluster Impact:** enrolment growth, learning results, approved stories.
- **The table:** each cluster's schools here with their SSA and work, then
  the whole cluster's card (sessions, attendance, absences, Health,
  Impact, maturity), fifty a page (`clusters_page`). Its rankings follow.

The cards are Cluster Oversight's own (`clusteroversight.Cards`, over
`readClusters`, which `read` now calls with the reader's clusters). The
existing attendance read gains the teachers and leaders recorded at the
sessions a school attended, and the learning results gain the declined
count. schoolprofile cannot import clusteroversight (a cluster page reads
the school profile), so `server.go` lends the cards to `ScopePages`
(`WithClusterCards`).

Proof: Mukono, Kamuli and the Central sub-region's Clusters tab, for five
readers and four years and periods: **60 answers, 0 differing**.

## 176.8 The Activities tab (2026-11-18)

A profile's Activities tab is drawn in Go:

- **The year's work by kind:** visits, trainings and cluster meetings,
  each with:
  - what is expected (the visits and trainings each school's type is due);
  - what is in the plan, completed, outstanding, upcoming and past its day;
  - who delivers it (staff or partner);
  - the schools reached, and coverage of the schools due.
- **Training By Channel and Cluster Meetings:** the school profile's own
  reads (`channels`, `meetings`), now over a list of schools. A profile
  with a Clusters tab adds that tab's sentence to the meetings note.
- **The District's list** (`profile_activities.for_district`): fifty a
  page for each segment (`district_acts_planned_page`,
  `district_acts_done_page`) and the segment asked for (`district_acts_tab`).
  - The pager stands apart from its table, so the feed reads it as a panel
    (`tablepager.Panel`). The bar for ticked activities shows where a
    planned row can be ticked.
  - A link that carries only the list's own keys opens this tab, as Django
    does.
  - `visible_to` keeps every activity for a country reader. A narrower
    reader's list is still the existing application's, since their team's
    staff, clusters and partners are not read yet.

A profile page now ignores query keys it does not read, as Django does,
instead of handing them on. Its pagers carry them along, the same as
Django's.

Proof: the districts' Activities tab for the Admin, the Country Director and
Impact Assessment, with the second page, a page past the end and the
Completed segment, plus the Central sub-region's for the field readers:
**54 + 18 answers, 0 differing**.

## 176.9 The records behind a figure (2026-11-18)

A figure's records (`?what=`, `profile_records.records`) open under the
figure's own tab, with `what` kept among the filters' hidden fields. Each
table is fifty records a page (`rec_<key>`), and a table of sums closes
every page with its totals, which do not count as records. Go draws:

- **The work:** the eighteen kinds of visit, training, meeting and project
  work (`_work_kinds`), newest first, each with who delivered it.
- **Enrolment and its growth:** school by school, the year before, this
  year, the change and the figure on the profile.
- **Learning results:** the assessments.
- **SSA:** the year's confirmed records, and one intervention's school by
  school with the work that named it. An unknown intervention shows that no
  record is open.
- **Stories:** all, or the approved only.
- **Hand-overs:** at each stage.
- **Partners:** those serving the schools.
- **Teachers and leaders:** those trained (the schools' own in-school
  trainings, then the attendance register of group sessions), and those at
  cluster meetings, each table closing with its sums.
- **Loans and Business Transformation cases:** for a reader of the loan
  register, who sees the loans `scoped_loans` gives them; anyone else is
  told no record is open to them.

**Still handed on:** the cluster sessions, attendance and absences. The gateway now reads `cluster_activity_attendance.id`, the
register's own order.

The record titles, their home tabs and the activity types' labels are
exported (`engine.scope.records`, `work_records`, `activity_type_labels`).

Proof: every work kind for FY 2026 plus the other kinds, with their pages,
over Mukono, Kamuli and the Central sub-region, for the Country Director
and a Programme Lead: **126 + 126 answers, 0 differing**. The trained, case
and loan records, over Mukono and the sub-region for four readers: **48
answers, 0 differing**. The seed has no rows for these, so only their empty
tables are proven; the closing sums' shape is the cluster register's.

## 176.10 The Districts directory (2026-11-18)

`/districts` (`extended_views.districts_list_view`,
`pages/districts/index.html`) is drawn in Go by
`schoolprofile.ScopePages` (`district_list.go`), next to the district
profiles it opens.

- One query, as the view's: every district by name with its region (`—`
  without one), its live schools, and the mean SSA of their live records in
  the operational year, `round(avg, 2)` written as Python writes a float
  (`5.91/10`, `6.0/10`). A mean of nought shows `—`, as `if d.avg_ssa`
  does.
- `q` is trimmed and matched as Django's `icontains`: `UPPER(name) LIKE
  UPPER(%q%)` with `\`, `%` and `_` escaped.
- Fifty a page under `districts_page`; the pager stands apart from the
  table, so it is the pager panel (`tablepager.Panel`). No match is the
  "No districts found" card.
- The door is the district profile's (`open_district`, the `planning`
  page); the Country Profile button follows `country_profile`.

Proof: 11 queries (search, wildcards, pages, a bad and a negative page)
for twelve readers, five of them refused: **132 answers, 0 differing**.

## 176.11 Graduated Champion Schools (2026-11-18)

`/core-schools/champions` (`core_schools_views.champions_list_view`,
`pages/core_schools/champions.html`) is drawn in Go by `coreschools`
(`champions.go`), behind the Core Schools door.

- The operating champions (`active_schools()`, `school_type =
  'champion'`) by name, with region and district (`Unknown` without one).
- The Core start year is the Core profile's, found by the School ID as
  the view looks it up, else `Unknown`. The latest SSA average is the live
  record with the latest `date_of_ssa` (`DESC`, so a record without a date
  comes first, as Django's `-date_of_ssa` does), else `0.0`.
- A name links to the school's profile for a reader who may open one
  (`schoolprofile.MayOpenSchools`, `school_links._may_open`): the
  Accountant reads plain names.
- The count is its own panel above the table; the pager is the pager
  panel; with no champion the table carries the page's empty sentence.

The gateway reads `core_school_profile (school_id, core_start_fy)`.

Proof: three queries for eleven readers, five of them refused: **33
answers, 0 differing**; and over the seed of §176.12, where one champion
has a Core profile (its start year, 2025, shows), for twelve readers:
**36 answers, 0 differing**.

## 176.12 The Champion Candidate Queue (2026-11-18)

`/core-schools/champion-candidates` (`core_schools_views.
champion_candidates_view`, `pages/core_schools/champion_candidates.html`)
is drawn in Go by `coreschools` (`candidates.go`) over
`coreoversight.ChampionCandidates`, the scan Core Oversight already ran
(`ChampionEligibilityService.scan`), now kept as `judge` with the inputs
the queue shows: the latest average, the delta (`round(latest − earliest,
1)`), the first lowest score of the latest record with its intervention,
and the package slots.

- Every Core profile in the table's own order (the model has no ordering;
  the read takes a second column so it is not served off the School ID
  index), judged, the eligible kept, then the reader's portfolio unless
  their scope is the country's.
- **A write on the read is handed on.** `evaluate_all` moves an eligible
  profile to Potential Champion; when any eligible profile's stored status
  is not Champion, Approved Champion or Potential Champion, the page is the
  existing application's.
- The feed reads the header's link to the champions outside the header,
  the Review button (an `hx-get` drawer) as its label, every pill as a
  primary badge, and the `{% empty %}` row as a one-cell row; the
  Graduated Champions page's empty row is drawn the same way.

The seed (in `edify_gorn_test` only, filed and removed by scratch SQL):
Core plans, the eight package slots and a later confirmed SSA for four
schools. One is eligible and stored Potential Champion, one eligible and
stored Champion, one a slot short, one on an archived plan, and an older
live plan stands beside this year's. Over it, for twelve readers, five of
them refused: **36 answers, 0 differing**. With the first candidate's
status set back to Not Eligible, Go hands the page on for every reader
while the Graduated Champions list still matches.

## 176.13 Public Holidays & Blackout Dates (2026-11-18)

`/public-holidays` (`leave_views.public_holidays_view`,
`pages/leave/public_holidays.html`) is drawn in Go by `personaltimeoff`
(`holidays.go`).

- The exported rules give each role the page, its Leave strip (Holidays &
  Blackouts active) and whether it edits (`is_editor`: CD, HR, Admin),
  which offers Seed Default Blocks and Add Block. The add drawer is on the
  page for every reader.
- Public Holidays: the active PUBLIC_HOLIDAY blocks ending today or later,
  by start (`N j, Y`, `start to end` when they differ), then the national
  calendar's next forty days that no recorded day names
  (`calendarpage.Upcoming`, `l j F Y`, "National calendar"). An announced
  Eid takes the expected one's place.
- Blackout dates and conference weeks with their description; regional
  events with "Applies to: Region …" (`All` without one). The view's
  custom blocks are not drawn by the template, so not by Go. The Remove
  forms are not read by the feed.
- **An editor's `?action=seed` is handed on**: it files the default
  blocks and redirects. Anyone else's is the ordinary page. The page
  comparison now reads a 302 as "Go hands this on".

The gateway reads `calendar_block.region_id`. Proof: over the seed's ten
blocks (two upcoming holidays, a past one, blackouts with and without a
description, a conference, regional events with and without a region, a
custom block and an inactive one), for ten readers and both queries:
**20 answers, 0 differing**; and with no blocks, in the suite.

## 176.14 Temporary Leave Coverage Assignments (2026-11-18)

`/leave/coverage` (`leave_views.leave_coverage_view`,
`pages/leave/leave_coverage.html`) is drawn in Go by `personaltimeoff`
(`coverage.go`).

- The exported rules give each role the page (`leave_coverage`) and its
  Leave strip.
- Every assignment, newest made first. A Programme Lead's are those they
  cover or are covered in, by their staff profile; without one, none.
  `q` (trimmed) matches either side's name or email as `icontains` does.
- Each side is the name over the active role; the window is written in
  Kampala time (`Y-m-d H:i`); the scope and the status are badges. The
  status is `active` inside a live window, else `revoked` once revoked,
  else `expired`. A live one carries the Revoke confirmation as the feed
  reads it, the rest "No actions". Revoking is the existing application's.
- Fifty a page under `coverages_page`; no assignment is the one-cell
  "No coverage assignments configured." row.

The gateway reads `temporary_coverage_assignment (scope, revoked_at,
created_at)`. Proof: over four seeded assignments (live, revoked, ended,
not yet begun; edify_gorn_test only, removed after), six queries for
eleven readers, two of them refused: **66 answers, 0 differing**; and
with none, in the suite.

## 176.15 The Team Availability Calendar (2026-11-18)

`/leave/calendar` (`leave_views.leave_calendar_view`,
`pages/leave/leave_calendar.html`) is drawn in Go by `personaltimeoff`
(`calendar.go`). The grid is drawn in the browser from its events; what
the feed reads is the month's activity panel
(`partials/leave/calendar_activity_panel.html`), and that is what Go draws.

- The month is `?month=&year=` as `int()` reads them (`+3`, ` 1_2 `), else
  today's in Kampala; a month or a year out of range, or either unreadable,
  is today's month.
- The work is the month's by its scheduled day in the platform's zone, or
  its planned day when it has none, neither cancelled, rejected nor
  completed (`off_calendar_done`), in the query's order. The Admin's is
  everyone's; anyone else's is the work they hold (user or staff id) and
  the partner work they monitor (`_calendar_staff_audience`).
- The feed reads each day's list item as one link: its first activity's
  type label to `/my-plan/<id>`. With nothing, "Nothing scheduled in
  <Month>." The count is every activity.
- `calendarpage` lends the type labels, the completed statuses and the zone.

Proof: nine activities seeded from one real visit (edify_gorn_test only,
removed after): planned-only, in progress, completed, cancelled, partner
and staff work the officer monitors, a December visit, and two either side
of midnight on 30 November. Eight queries for nine readers: **72 answers,
0 differing**; and over the seed's own work, in the suite.
