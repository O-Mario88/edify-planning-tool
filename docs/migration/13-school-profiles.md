# 13. School Profiles, first piece: the Details tab, read by Go

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): "School Directory and School Profiles". After the
[School Directory](12-school-directory.md), the profile (School 360). It is
the largest page the brief names: eight tabs over a shared profile engine
(`apps.analytics.profile_intelligence`, `profile_records`, `profile_rail`,
some 3,300 lines), the one-visit-a-year rule (`apps.planning.visit_gate`,
1,100 lines), the Core package rule (`apps.core_schools.package_split` and
`package_credit`, 1,500 lines) and the loan register. It moves in pieces, each
proved against the existing page before the next.

| Piece | What moves | State |
|---|---|---|
| 1 | Opening a school (who may), the header with its badges and doors, the tab strip, the Details tab, and the visit rule those read | This document |
| 2a | The profile engine's frame (scope line, facts, year and period) and its Projects, Stories and Academic tabs | Done, 13.6 |
| 2b | The Overview: performance, operations and loans, the best and struggling intervention, the latest stories, the insights rail | Next |
| 3 | SSA and Participation | |
| 4 | Core School: the package rule, the Core tab, a Core school's Details | |
| 5 | Closed schools and the Business Transformation panel with the loan register | With the school record changes and loans |

## 13.1 What moved

`SchoolProfileService.GetSchoolProfile`
(`platform/proto/edify/screens/v1/school_profile.proto`, unchanged) is now
answered by `platform/backend/internal/schoolprofile` for the Details tab of
an open school that is not Core and has no Business Transformation case or
MFI loan, for someone working in their own role. Everything else is passed
to the existing application as before, so the app sees one profile.

The contract is the existing generic page (`PageHeader`, `PageTab`,
`PageBlock`), which the existing application fills by reading its own HTML
(`apps.mobile_feed.page_blocks`). Go builds the same blocks directly from the
data, so the app draws the profile exactly as it did.

| Part | Existing rule it ports |
|---|---|
| Who may open a profile | `can_view_page(…, "school_profile")`; then `schools.services.get_one`: the whole scope's operating schools (a Program Lead's team included, unlike the directory's own list), the scope's closed schools, and for a CCEO or Program Lead a school nobody holds in their country. By School ID first, then record id. Anything else is not found |
| Header | Back to School Directory, the name and School ID; Readiness; the year's SSA (`ssa.creation.year_record`: confirmed first, then the latest; its source and status in the title) or "No FY SSA" where the reader may enter one; the visit lock with its reason |
| Doors | Edit Details; Schedule; Assign to Partner, greyed with the rule's reason where the year is taken; Enter SSA Score, greyed once the year has an SSA; Add to Project; Reassign Owner; Close School. Who sees which is computed by the existing gates for each role and exported |
| The visit rule | `platform/backend/internal/visitgate`, the client rule of `visit_gate`: one staff support visit a year (a Training Follow Up or an In-school Training), or a partner holding it, dated or waiting; SSA Support handed over only while the year has no SSA; a Champion school never handed over. The counting query is Django's own, joins included |
| Tabs | Overview, SSA, Participation, Academic, Stories, Projects, Core School for a Core lifecycle school (Core, Core Trained, Core Graduate, Champion), Details |
| Details | Demographics and assignment (region, district, sub-county, parish, enrolment, coordinates, type, cohort, assigned staff, the year's visit status and cluster training, the cluster), cluster history, contacts; the verified SSA signals and Business Transformation's empty sentences; the data quality score; an Admin's Danger Zone |

Labels, the visit rule's vocabularies and each role's doors are exported to
`internal/schoolprofile/rules.json` by `manage.py export_school_profile_rules`;
`apps/schools/test_school_profile_rules_export.py` fails when the two differ.
Figures and dates are printed as the templates print them: Django's
`floatformat` (half up on the shortest decimal), Python's `str(float)`
("6.0"), and dates on Kampala's clock.

## 13.2 Proving it is the same

`cmd/parity -screen profile` signs each account in and compares the Details
tab, field by field, for every school in the account's own directory and a
spread of 40 of the Admin's schools (a lead's team, the refusals).

| Accounts | Profiles compared | Of non-Core schools | Differing |
|---|---|---|---|
| All 29 accounts that may open a profile (Admin, Country Director, Impact Assessment, Business Transformation, 4 Program Leads, 20 CCEOs, Project Coordinator) | 3,826 | 3,308 | 0 |

The comparison includes the refusals: an officer with no schools asked for
another officer's school is refused alike by both. The directory's own
comparison was run again after this piece (46 compared, 0 differing).

Before the run, two schools were put in the states the seed did not have,
through the existing web app as the CCEO: an In-school Training scheduled at
one ("Staff visit scheduled", Assign to Partner greyed with both reasons)
and an In-school Training handed to Literacy Uganda at another ("Awaiting
schedule from partner"). A visit a partner has already dated cannot be made
from a staff account; that lock is covered by the unit tests.

## 13.3 Differences

None in what the app shows. Two findings about the existing page, left as
they are there and reproduced here:

- **"Required Cleanups" never shows.** The Data Quality card asks the school
  for `data_quality_issues`; the relation is named `quality_issues`, so the
  list of open fixes is always missing (3,405 open issues in the seed).
- **Run-together text.** The page blocks join a label and its caption with a
  space, so the app reads "No Training Planned School not attached to a
  cluster", and a Core school's package marks read "V1V2V3V4". Go matches
  today's text; separating them is a small improvement for later.

## 13.4 What still happens in the existing application

- Every other tab, and a request with no tab (Overview).
- Core and closed schools, schools with a Business Transformation case or an
  MFI loan, and anyone working in an acting capacity.
- Every door's drawer and save (Edit Details, Schedule, Assign to Partner,
  Enter SSA Score, Add to Project, Reassign Owner, Close School).

## 13.5 What the database role may do

`platform/deploy/db/roles.sql`, section `internal/schoolprofile`: column
SELECT on the school's own fields, `parish`, `school_cluster_membership`,
the activity, catalogue, eligibility, partner, hand-over and project columns
the visit rule counts by, the SSA record's average and source, and only
`school_id` of `bt_case` and `bt_mfi_loan` (whether the school has one).
No write; the source scan in `internal/dbguard` allows these packages none.

## 13.6 The profile engine, first tabs

`internal/schoolprofile` now also answers the Projects, Stories and Academic
tabs, for any year the page offers and any quarter or month. They are the
profile engine's (`apps.analytics.profile_intelligence`, `profile_records`,
`clusters.outcomes`) over one school, under the same frame every engine tab
draws:

- **Frame.** "Single school, FY 2026/27" (and "· work in Q1 (Oct–Dec)" for a
  period); the facts (School ID, Type, Cohort, District and Sub-region with
  their links, Sub-county, Cluster, the CCEO and Programme Lead holding it,
  the partners holding work there, Status, Fiscal Year); the year and period
  filters. A year the page does not offer is the running year; a period it
  does not know is the whole year.
- **Projects.** Each project with the school on it: its status, the school
  here, every school on it, the capacity set for it, its work at the school
  in the plan and completed (in the period), and the school's SSA on it,
  judged by the SSA change rule (the published thresholds, else any move).
- **Stories.** Most Significant Change stories about the school (or its
  cluster) dated in the year, drafts left out: the counts, by intervention,
  and the records.
- **Academic.** Enrolment and learning results this year against last, a
  school compared only with a figure in both years, and the records.

Figures are written as the page writes them: a strip's line under a figure
is cut to a second figure and the sentence kept as its note
(`kpi_metrics.professional_kpis`), counts with thousands, scores to two
places, a period's days read on Kampala's clock. A table longer than a page
(50 rows) is passed to the existing application, which pages it.

Proved with `cmd/parity -screen profile -tab <tab>` on all 700 of the CCEO's
schools for each tab, and again for FY2026, Q1, November and an unknown year
and period: none differing. Stories, enrolment by year and learning results
were empty in the seed, so one school (Central Division Primary School,
1000) was given four stories (approved, submitted, returned, and a draft that
must not show), enrolment for both years and four learning results (three
confirmed, one pending) with the existing models, each marked
"[Go parity check]".
