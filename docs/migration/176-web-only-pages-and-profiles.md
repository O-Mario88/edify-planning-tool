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
