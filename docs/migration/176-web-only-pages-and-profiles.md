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

## 176.16 The Fiscal Year Overview (2026-11-18)

`/fy` (`extended_views.fy_overview_view`, `pages/fy/index.html`) is drawn
in Go by `schoolprofile` (`fy_overview.go`), behind the `planning` door the
Districts directory uses.

- The operating schools; the schools with a live SSA record this
  operational year (SSA Pending is the difference); the work in the plan
  (not cancelled or otherwise out of it) and the completed work, and the
  rate between them, `round()` as Python rounds it (half to even).
- The KPI strip ("Performance overview") and the `FY<year> Summary` line.

Proof: two queries for ten readers, three of them refused: **20 answers,
0 differing**.

## 176.17 Visit Requests (2026-11-18)

`/planning/visit-requests` (`visit_request_views.visit_requests_page` over
`apps.planning.visit_requests`, `pages/planning/visit_requests.html`) is
drawn in Go by the new `visitrequests` package. Its rules come from
`export_visit_requests_rules` (each role's page, whether it files requests,
whether school and district names open their profiles; the awaiting
status), kept current by `apps/planning/test_visit_requests_rules_export.py`.

- The owner's queue: requests awaiting the reader under either of their ids,
  by planned day then filing, each read as "<requester> asks to visit
  <school>" over "<kind> • <day> • <district>". The decision forms are the
  existing application's; with none, the empty state's sentence.
- The requester's own (the Accountant by role, anyone by rows already
  filed): newest first, fifty at most, with the owner asked and the
  decision and its note. The School ID is written in after the page is
  drawn, so the feed reads it empty. The queue is shown to a requester only
  when something waits on them.
- Names: the requester by staff or user id, else "A staff member"; the
  owner by staff profile, else "the school's owner".

The gateway reads `activity.owner_decision_note`. Proof: five requests
seeded from one real visit (edify_gorn_test only, removed after): two
awaiting (one filed by the Country Director), one declined with a note, two
approved with and without one. For ten readers, two refused, and two
queries: **20 answers, 0 differing**; and with none, in the suite.

## 176.18 The visits log (2026-11-18)

`/visits` (`staff_views.visits_log_view`, `pages/visits/index.html`) is
drawn in Go by the new `stafflogs` package. Its rules come from
`export_staff_logs_rules` (each role's door, `my_plan`, and whether a
school's name opens its profile; the visit types; the completed and
not-yet-finished statuses; the hundred-row limit; `status_label`'s
initialisms), kept current by `apps/frontend/test_staff_logs_rules_export.py`.

- The reader's own visits, by user id as the view asks, latest planned
  first (an undated visit first, as `DESC` sorts), the first hundred,
  filtered by `status` (as given) and by school or cluster name (`q`
  trimmed, `icontains`).
- The header counts the hundred: completed, and pending (scheduled,
  rescheduled, in progress, completion started; "started" is neither).
- Each row: the School ID (written in after the page is drawn, so the feed
  reads it empty; `—` without a school), the school or "No school" with the
  cluster or `—`, linked to the school for a reader who may open one, else
  to the cluster; the type and status as `status_label` writes them, as
  badges; the planned day (`N j, Y`, else `—`); and View to the plan.
- Fifty a page under `visits_page`. With none, the empty card, which the
  feed reads with the page's Schedule link.

Proof: 61 visits seeded from one real visit (edify_gorn_test only, removed
after): every status the page reads, no school, no date, a training, a
deleted visit, fifty more for a second page, and two for a Partner who may
not open schools. Nine queries for seven readers, two refused: **63
answers, 0 differing**; and over the seed's own visits, in the suite.

## 176.19 The trainings log (2026-11-18)

`/trainings` (`staff_views.trainings_log_view`, `pages/trainings/index.html`)
is drawn in Go by `stafflogs` (`trainings.go`), beside the visits log. The
export adds each role's door to it, the training types, and the roles the
view sends elsewhere.

- **The Programme Lead and the CCEO are handed on.** The view redirects
  them (to Programme Rollout and to My Plan). The redirected roles are
  written in the export by hand: the view names them in its code, not in a
  constant the export could read.
- Everyone else: their own trainings under either id (`owner_ids`), latest
  planned first, the first hundred, filtered by `status` (Scheduled or
  Completed offered) and by school or cluster name.
- Each row: the session's name (else "Training") over where it is: the
  school (linked for a reader who may open it), else "<cluster> Cluster"
  (linked), else "Programme activity". Then the catalogue's category (else
  "Legacy training") as a badge, its SSA indicator (else `—`), the planned
  day, the status, "N teachers" (else `—`), and View.
- The header counts sessions and completed ones; the empty card carries
  the page's Schedule link, as the visits log's does.

Proof: 57 trainings seeded from one real visit (edify_gorn_test only,
removed after): the Admin's by user id and the coordinator's by staff id;
with and without a school, a cluster, a catalogue item, a name and an
attendance; a visit, a deleted training, and fifty more for a second page.
Six queries for eight readers (two handed on, one refused): **48 answers,
0 differing**; and over the seed's own work, in the suite.

## 176.20 The Blocked Closures directory (2026-11-18)

`/activities/closure/blocked` (`closure_views.blocked_closure_view`,
`pages/closure/blocked_closure.html`) is drawn in Go by the new
`closurepages` package, behind the `planning` door
(`schoolprofile.MayPlan`).

- **Ordered longest blocked first (owner, 2026-11-18).** The model has no
  ordering, so the existing page listed blockers as the query plan
  happened to return them (a hash join over `school` left them in the
  school table's physical order). The owner chose longest blocked first;
  the view now orders by `created_at`, then activity, then blocker, and Go
  the same. `apps/frontend/test_blocked_closure_order.py` holds it.
- The reach is `_in_scope`: a country reader every live activity's
  blockers; anyone else those on work they hold under either id or at their
  schools. Deleted activities are out, as Activity's manager leaves them.
  Partner ids never reach this page: no partner role holds `planning`.
- Each row: `#` and the activity id's first eight characters over its type,
  the reason (a badge), the responsible role, the holder's id (else
  "Unassigned"), the age as `timesince` writes it
  (`debriefs.Timesince`), the next step the reason names (Evidence, IA,
  NetSuite, else reconcile), and Resolve Blocker. With none, the one-cell
  "Perfect compliance!" row, which the feed also reads as the table's
  empty message (the empty state component sits in the row).

The gateway reads `closure_blocker (id, activity_id, blocking_reason,
responsible_role, created_at)`. Proof: four blockers seeded on existing
activities (edify_gorn_test only, removed after): two on cceo1's work, one
on another officer's, ages from forty minutes to over a year. For nine
readers, two refused, and two queries: **18 answers, 0 differing**, the
oracle written and compared within the minute because the ages move. With
none, in the suite.

## 176.21 Analytics Publishing Status (2026-11-18)

`/analytics/publishing` (`closure_views.analytics_publishing_status_view`
in the analytics workspace, `partials/analytics/panels/publishing_status.html`)
is drawn in Go by `closurepages` (`publishing.go`). Its rules come from
`export_closure_pages_rules` (each role's door, `analytics_publishing`;
whether school names open; the workspace's tab rail for the role, IA's
alone; the status ranks), kept current by
`apps/activities/test_closure_pages_rules_export.py`.

- **Failures first (owner, 2026-11-18).** The model has no ordering. The
  view now ranks failed and recalculation-required records first, then
  pending, then published, anything else last (`PUBLISH_STATUS_RANK`), the
  oldest first within each. Go reads the same ranks;
  `apps/frontend/test_analytics_publishing_order.py` holds the order.
- The workspace's frame (its decision frame, evidence and freshness), then
  for IA the analytics tab rail, then the table: the activity's first eight
  characters, the School ID (read empty) or `—`, the school (linked for a
  reader who may open it) or "Cluster-wide", the type and the status as
  badges, the publication time in Kampala (`M d, Y H:i`, else "Pending"),
  and the error, else the success sentence. With none, the empty row and
  the table's empty message. The provisional note closes the page.

The gateway reads `analytics_publish_record (id, activity_id, status,
published_at, error_message, created_at)`. Proof: six records seeded on
existing activities (edify_gorn_test only, removed after): every ranked
status and an excluded one, created so table order and the page's order
disagree, one without a school. Two queries for six readers, three refused:
**12 answers, 0 differing**; and with none, in the suite.

## 176.22 The Completed Activities ledger (2026-11-18)

`/completed-activities` (`closure_views.completed_activities_view` in the
analytics workspace, `partials/analytics/panels/completed_work.html`) is drawn
in Go by `closurepages` (`completed.go`), on the workspace frame it shares
with the Publishing page (`workspace.go`). The export adds each role's door
(`completed_activities`) and its tab rail on the page (none of the seven roles
that open it is shown one).

- The live closed activities in the reader's reach (`reachOf`, the Blocked
  Closures reach), the latest changed first. The id now settles activities
  changed in the same instant, in the view and in Go alike, so the order
  never falls to the query plan.
- Each row: the id's first eight characters, the School ID (read empty) or
  `—`, the school (linked for a reader who may open it) or "Cluster-wide",
  the holder's id (Python's `None` without one), the type as a badge, the
  planned day (`M d, Y`, blank without one), Verified or Not Verified by the
  closure checklist's IA flag, the snapshot's NetSuite id (else `—`), and
  View Record. With none, the empty row and the table's empty message.

The gateway reads `closure_checklist (activity_id, ia_verified)` and
`completed_activity_snapshot (activity_id, netsuite_expense_id)`. Proof: six
activities copied from one real visit (edify_gorn_test only, removed after):
four closed (cceo1's with and without a school, one with no holder, another
officer's), one deleted and one merely completed, with a checklist each way
and a NetSuite snapshot. Two queries for ten readers, two refused: **20
answers, 0 differing**; and with none, in the suite.

## 176.23 The My Performance sub-pages (2026-11-18)

`/my-performance/development`, `/my-performance/values` and
`/my-performance/documents` (the sidebar's deep links into
`hr_views.my_performance_view`, each with its tab as a URL argument) are
drawn in Go by `myperformance`, the page it already drew at
`/my-performance`. The export adds each path's tab (read from the URL
definitions, `resolve(path).kwargs`), and its doors and strip per role.

- The path's tab wins over `?tab=`, as `tab or request.GET.get("tab")`
  does. The documents link names "conversations", which the page does not
  draw, so it opens on Distributed Priorities whatever `?tab=` says.
- **The oracle now follows a page's later parts.** `web_page.py` read the
  HTML without the feed's `later`, so a part a page loads after it opens
  (the CCEO's guidance inbox here) was missing from the oracle though the
  feed, and Go, draw it. It now passes read_page's own `later`, inside the
  rolled-back transaction, and every web-only golden is read that way.

Proof: three queries (none, `?tab=spiritual`, `?fy=2026`) for eight readers
on each path, one refused each: **72 answers, 0 differing**.

## 176.24 Regional Lead Coaching (2026-11-18)

`/cce-leadership/coaching` (`cce_leadership_views.regional_coaching_view`) is
drawn in Go by `ccelead` (`regionalcoaching.go`) through the register the
other CCE leadership pages share. The export adds the page to its `PAGES`
(`cce_training_feedback`, no drawers, its two figures).

- The reach is `regional_coaching_visible_to`: Admin every Programme Lead
  coaching conversation, the Regional Lead their own, a Programme Lead those
  shared with them (by staff record), nobody else. The Country Director opens
  the page to a notice that the coaching stays between the Regional Lead and
  each Programme Lead.
- Each conversation, latest held first (then latest made), five hundred at
  most: the subject, the day held, the Regional Lead for a Programme Lead
  (else the Programme Leads named, "Programme Lead" for one unknown), the
  actions agreed, the follow-up day ("· passed" once due and still not
  acknowledged), and the state. A Programme Lead's button reads Acknowledge
  until they do, else Open.
- The figures: shared and awaiting acknowledgement, and acknowledged.

The gateway reads `cce_regional_engagement (agreed_actions,
follow_up_due)`. Proof: five engagements seeded (edify_gorn_test only, removed
after): acknowledged, awaiting past its follow-up, never shared, shared with
one lead, and a training observation the page leaves out. Two queries for
eight readers, two refused: **16 answers, 0 differing**; and with none, in
the suite.

## 176.25 The web app's "This page could not be found" (2026-11-18)

The owner reported the Next.js web app answering 404 for Planning Monitor,
Planning Oversight, Country Oversight, the Country Map, Cluster, Core and
Partner Oversight, the Verification Queue, SSA Verification, Partner
Evidence, Team Performance, Returned Activities and more. A sweep of every
role's sidebar through the gateway, under both spellings of each link, found
three causes.

- **A page's spelling.** The existing pages are "/x/" and a browser asking
  for "/x" is moved there (APPEND_SLASH), but the gateway reads a path as
  given, and the sidebar writes these links without their slash. FeedPage
  asked "/x", took the gateway's NotFound as final and never asked "/x/".
  It now asks each spelling in turn (`lib/pageSpellings.ts`): a page wins,
  then "not moved yet" (the page exists and is the reader's; "/settings" is a
  page, "/settings/" no page at all), and it is not found only when every
  spelling is refused.
- **A page Go has not drawn yet, through the fallback.** The feed answered
  404 alike for a page the reader may not open and for a page of the web it
  does not draw. It now answers 501 for the second (`read_page`,
  `_not_moved_yet`), the gateway's feed client reads that as "unavailable",
  and the web app opens the page in the existing web instead of a 404.
- **A route that caught another page.** `/schools/[id]` read "closed" as a
  school's id; `/schools/closed` has a route of its own now.

A gateway started before a page was drawn in Go also falls back for it;
restarting it serves the new pages. Proof: every sidebar link of thirteen
roles, both spellings, through the gateway: all served but `/home` and
`/messages` (not yet in Go) and `/schools` (the web app's own screen); and
every one of the Admin's 118 links fetched in the signed-in web app, after
the fix, 200 but `/home`, `/messages` and `/settings`. The Regional Lead's
sidebar offers Country Oversight and the Country Map, which the existing
application refuses them too: a question for the owner.

## 176.26 Home in the web app (2026-11-18)

`/home` is drawn by the web app from the gateway's `HomeScreenService`, the
same answers the phone app's Home reads (`src/app/(app)/home/page.tsx`,
`src/lib/homeScreen.ts`): the greeting over the day, the financial year and
the role; the overview figures, each filled from the queue (or the To-Do
figures, when the queue says they follow) by its key; the priority actions
with their due day, state and action; the reader's upcoming work when they
have a plan; and their shortcuts. A reader who does not use Home is sent
where they start (`redirect_url`). Home's tone words are read as the page's
(brand and info as info, caution as warning, alert as danger, good as
success, plain as none).

Still not drawn in Go: `/messages` and `/settings`, which the web app now
opens in the existing web instead of a 404. Settings turns on the
reader's two-step state (in force, required by policy, the channels), which
the seeded accounts cannot show without breaking the suite's sign-ins.

## 176.27 The Regional Lead opens Country Oversight and the Country Map (2026-11-18)

The Regional Programme Lead's sidebar offered Country Oversight and the
Country Map, and both pages refused them, in the existing application as in
Go. The owner decided (2026-11-18): "Give them access". `PAGE_PERMISSIONS`
now grants `RPL` `country_planning_oversight` and `country_map`
(`apps/core/navigation.py`), held by `apps/core/test_regional_lead_country_pages.py`.

What follows from the grant, each re-exported for Go:

- Navigation: both links are native for the Regional Lead.
- Planning Oversight's country door and the Country Map's doors open.
- The Country Profile, gated by Country Oversight, opens for them.
- Project Monitoring's consolidated tables follow the same permission.
- My Targets' SSA figure links to the Country Profile rather than Cluster
  Oversight.
- The Regional Lead was on the owner's list of roles who land on Country
  Oversight and landed on Home only for want of the page: they now land on
  Country Oversight, as the CD, IA and RVP do.

The pages are country-wide with no role branch, so the Regional Lead reads
them as the RVP does. Proof: the four pages for the Regional Lead, the RVP
and the CD, three queries each, against the existing pages: the Country Map
and Project Monitoring 9 answers each, 0 differing; Country Oversight's
lenses and the Country Profile's Overview stay the existing application's
for every reader, as before.

## 176.28 Messages and Settings in the new web app (2026-11-18)

The last two sidebar pages every role has, /messages and /settings, were
answered "not moved yet" by the new web app. Both are now drawn there.

**Messages** (`platform/web/src/app/(app)/messages/page.tsx`) is drawn from
`MessagingService.ListThreads`, which Go already read and doc 42 proved
against the existing page (78 threads, 0 differing): the header, the inbox
tabs with their counts, the sort, the conversation list, the pager and the
Message Rules. Opening a conversation marks it read, a save Go does not make
yet (doc 42, piece 2), so the open conversation's card links to it in the
existing web app, as does New Message.

**Settings** is read by a new Go service, `SettingsScreenService.GetSettings`
(`internal/settingspage`, `proto/edify/screens/v1/settings.proto`): the
reader's email, whether they owe a new password, their two-step
verification (`mfa_service.enrolment_state`: in force, required by policy,
the channel degraded to one that works, the app and text messages
available, why not, and the masked email and phone) and the idle session
length (`SESSION_COOKIE_AGE // 60`). Who may open it, the session and SMS
settings it reads, and the page's words for an unavailable channel are
exported by `manage.py export_settings_page_rules`
(`apps/accounts/test_settings_page_rules_export.py` holds the copy current
and checks the words against `enrolment_state`). The two-step policy is the
one Go's sign-in already reads (`EDIFY_MFA_REQUIRED_*`). The account columns
come through the sign-in grant (`identity_roles.sql`); no new grant.

- An account owing a new password never reads the page: the gateway's
  interceptor refuses every call but the password's own, as the existing
  middleware redirects to /change-password.
- An acting appointment is handed on (Unavailable), as on every Go page.
- The Cluster Leader is refused, as the existing page refuses them.
- Changing two-step verification stays in the existing web app; the card
  shows the choice and links there.
- Appearance offers System, Light and Night black, under the same
  per-browser key (`edify_theme`). Edify Blue is not drawn by the new web
  app yet, so it is not offered.
- The existing template marks Email as well as the app for an app user, and
  the browser keeps the later one; the new page marks only the channel in use.

Proof: `internal/settingspage/testdata/golden.py` files eight accounts (no
phone, a phone, a short number, enrolled on each channel, the app with and
without a secret, an unknown channel, required roles held and active, a
refused role, a password owed, letters beyond ASCII) in a rolled-back
transaction, runs the real `settings_view` for each under SMS on and off,
three policies and two session settings, and
`TestTheSettingsPageMatchesTheExistingPage` reads each through the
gateway's own role: 84 answers compared, 0 differing (12 more are the
password-owed account, which the interceptor stops first).

## 176.29 A hand-over is dated the local day (2026-11-19)

The full suite run just after midnight found Partner Oversight differing on
138 of 705 answers: a hand-over made at 00:20 EAT on 18 November read
"Assigned 17 Nov 2026" on the existing page and "18 Nov 2026" in Go. The
existing service dated a hand-over `assignment.created_at.date()`, the UTC
day, a day behind from 00:00 to 03:00 EAT. Every "today" is the Kampala day
(apps.core.clock; the owner's local-day rule), and Go already read it so.
The existing service now takes `timezone.localtime(created_at).date()`
(`apps/planning/partner_oversight_service.py`), held by
`TheAssignmentDayIsTheLocalDayTest` (a hand-over made 21:30 UTC on 8
October is dated the 9th). The same day feeds the page's month, quarter and
week filters and the schedule deadline (`partner_risk_service`), so those
now count a night hand-over in the day it was made. Partner Oversight
compared at 00:30 EAT: 705 answers, 0 differing.

## 176.30 One design system; a phone draws the native app's design (2026-11-19)

The owner asked for "a standard system design (cards, graphs, tiles, layout,
typography)" and then to "use the mobile design in react native and apply it
to the … mobile screen design for the web".

**The standard parts.** `platform/web/src/components/ds` exports every part a
page is built from: the page header and its buttons, the type scale
(`Eyebrow`, `PageTitle`, `SectionHeading`, `CardTitle`, `Caption`), the
registered card (`StandardCard`), `Card`, the figure row, `MiniTile`,
`Meter`, `Badge`, tables, the pager, the tab rail, the filter row and charts.
Each draws the existing web's own markup, so the stylesheets the root layout
links set it as on the live pages. `/design-system` shows them all with
sample figures, beside a sample page as a phone reads it.

**Two readings.** Below the existing web's phone line (64rem, where its own
`desktop_hidden` switches), a page asks the gateway for the phone reading —
the one the app gets — and draws it with web versions of the app's parts
(`components/phone`, after `platform/mobile/src/ui/page`). From 64rem up it
asks for the desktop reading and draws the live system's markup.

- The browser measures itself and keeps the answer in the `edify_view`
  cookie (`ViewportSync`, `lib/viewport.ts`), redrawing when it crosses the
  line. Until it has measured, the device's hints guess (`Sec-CH-UA-Mobile`,
  the user agent).
- `FeedPage` and the school profile follow the reading. The Calendar keeps
  the desktop reading, which its own components draw.
- The phone parts are the app's: the field-coloured page, the header with
  Export beside the title, figure tiles, the segment rail (first and open tab,
  the rest under More) with the square calendar button, three filters and
  More, record tables with the swipe hint, lists, panels, record cards,
  segments and the cut-out bar chart. The palette is the app's `theme.ts`,
  light and dark. Icons are `lucide-react` at the app's lucide version.

**Why a cascade layer.** The existing stylesheets set `!important` rules on
everything under `main` — weights, tab roles, selects, headings, 44px link
targets — and match class substrings. The phone parts therefore style on
`data-ph` attributes only, carry no `role="tab"`, and keep their rules in
`@layer edify-phone` with every declaration important: a layered important
declaration outranks every unlayered one. Their breakpoints are container
queries on the blocks column, so the catalogue's phone frame and a split
screen lay them out as a phone does.

**Not changed:** the app itself already draws every screen from `theme.ts`;
the Smart Route Planner keeps its owner-drawn teal (next-smart-field-routing).
