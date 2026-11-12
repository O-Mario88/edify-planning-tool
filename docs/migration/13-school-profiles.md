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
| 2b | The Overview: performance, operations and loans, the best and struggling intervention, the latest stories, the insights rail | Done, 13.7 |
| 3a | SSA | Done, 13.8 |
| 3b | Participation | Done, 13.9 |
| 4a | Core schools: the package rule in the header, a Core school's Details, and every engine tab at a Core school | Done, 13.10 |
| 4b | The Core School tab (Core School Intelligence) | Done, 13.11 |
| 5a | Closed schools | Done, 13.12 |
| 5b | The Business Transformation panel and the Overview's loans strip (the loan register's scoping) | Next |

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

Updated as the pieces moved (2026-11-12):

- The Details tab and
  the Overview of a school with a Business Transformation case or an MFI
  loan, anyone working in an acting capacity, and a Participation table
  longer than one page (50 rows).
- Every door's drawer and save (Edit Details, Schedule, Assign to Partner,
  Enter SSA Score, Add to Project, Reassign Owner, Close School), and every
  activity drawer the Participation rows open (View, Edit, Complete,
  Reschedule, Cancel, and the bar for ticked activities).

## 13.5 What the database role may do

`platform/deploy/db/roles.sql`, section `internal/schoolprofile`: column
SELECT on the school's own fields, `parish`, `school_cluster_membership`,
the activity, catalogue, eligibility, partner, hand-over and project columns
the visit rule counts by, the SSA record's average and source, and only
`school_id` of `bt_case` and `bt_mfi_loan` (whether the school has one).
No write; the source scan in `internal/dbguard` allows these packages none.
The engine's tabs added the columns each reads (stories, enrolment history,
learning results, the published SSA rules, the register's teachers and
leaders); the Participation tab adds the activity columns its list and
checks read, a cluster's region, `school_visit_feedback`, the hand-over's
own columns and only `activity_id` and `amount` of a cost line.

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

## 13.7 The Overview

The Overview is the profile's first tab, and what a request with no tab (or
one the school does not have) opens. Go now answers it for the same schools
as the Details tab: open, not Core, no Business Transformation case or MFI
loan. Those two keep the loans strip honest: the register's own visibility
rules (`scoped_loans`) are not ported, so a school the register could show
anything for is passed on, and every other school's strip reads nothing — and
shows only to a role that may open the loan register, as on the web.

| Part | What it reads |
|---|---|
| Performance And Impact | the school's enrolment; its SSA overall this year and last and the change, by the SSA change rule; whether it is assessed (a Champion school is not); teachers and leaders trained, at its own completed trainings and by the register of completed group trainings; enrolment and learning compared year on year; its stories |
| Operations | visits, trainings and cluster meetings in the plan and completed (its own, and its cluster's sessions); visits expected of its type; online training and attendance by the register; teachers and leaders at cluster meetings; nothing planned |
| Loans And Business Transformation | for a reader of the loan register: nothing, for the schools Go answers |
| Best Performing And Struggling Intervention | `engine._intervention_picks` over the eight interventions: by the change where one rose (or fell), else by this year's score, the first of equals kept; the work that named each as its focus; what to do next |
| Latest Change Stories | the five newest, with the count by intervention |
| Profile Insights (rail) | the SSA score and each intervention's out of 10, and Needs Attention: no SSA, nothing planned, a decline (the school's, its cluster's, an intervention's), no training or visit in the plan where one is due, a partner's date awaited, and work past its date |

Days are Kampala's: "past its date" is a planned day before today in
Kampala, or a scheduled moment whose Kampala day is.

Proved with `cmd/parity -screen profile -tab overview`: all 700 of the CCEO's
schools for FY2027, FY2026 and FY2026 Q3, and all 29 accounts that may open a
profile (3,826 compared), none differing. In the all-accounts run one CCEO's
session expired partway; both sides refused the same four requests alike, and
the account compared again showed no difference. Before the run, dev was
given the work the seed lacked, with the existing models and marked
"[Go parity check]": a completed in-school training (6 teachers, 2 leaders,
focus Leadership) and an overdue donor visit at Central Division Primary
School, and a completed online cluster training with its register at
Kimenyedde's cluster.

## 13.8 The SSA tab

Go answers the SSA tab for the same schools as the other tabs.

| Part | What it reads |
|---|---|
| Intervention Matrix | each intervention's score in the year before and the year (the school's latest confirmed record of each), the change and what the change rule calls it, the target of 10.0 and what is left to it, and the school overall; the schools assessed in each year and at the target |
| SSA score by intervention | the same two years as bars, last year's only where it was measured |
| Annual SSA Progress | the average of every confirmed record of each year (not only the latest), with the schools assessed |
| SSA change between confirmed assessments | `ia_workflow.school_progress`: the latest confirmed records of consecutive years, up to four pairs, newest first; a pair is compared only when its readings are 120 days apart or more, each intervention by the rule of the school's country first, then the deployment's, the school's verdict by the mean of the comparable moves and the mean of those interventions' thresholds; the verified activities delivered between the two readings |
| SSA history | every record, newest first, its status, whether it counts, where its scores came from, its average; a note where newer records are not confirmed yet |

Every SSA in the seed was dated 9 November 2026, so no pair was ever far
enough apart to be compared. School 1000 was given, with the existing models
and marked "[Go parity check]" (the activity) or visible in its history: a
confirmed FY2027 SSA dated 15 March 2027 with all eight scores, a completed
coaching visit between the two readings, and a pending FY2028 SSA newer than
both.

Proved with `cmd/parity -screen profile -tab ssa`: all 29 accounts that may
open a profile (3,826 compared, 3,308 of non-Core schools) and all 700 of the
CCEO's schools for FY2026, none differing. After the change the other tabs
were compared again on the CCEO's 700 schools (Overview, Details, Projects,
Stories, Academic), none differing.

## 13.9 The Participation tab

Go answers the Participation tab for the same schools as the other tabs,
unless one of its two activity tables is longer than a page.

| Part | What it reads |
|---|---|
| Visits, trainings and cluster meetings | `engine._execution` for the school and its cluster's sessions in the year and period: in the plan, completed, outstanding, upcoming, past its date, by staff and by partners, the schools reached; `engine._expected`: what the school's type is due and its coverage |
| Training By Channel | `profile_records.channels`: in-school, group and online training, staff and partner, the register of completed sessions, and the training hand-overs a partner still holds |
| Cluster Meetings | `profile_records.meetings`: meetings by kind, held, still to come and past their date; the school's attendance at those held; the next five |
| Planned & Completed Activities | `profile_activities.for_school` and `profile_activities`: work at the school and the cluster sessions it was invited to or attended, split by status, each row's day, place, executor, status and purpose; each row's menu by the same checks the actions run (`_assert_in_scope`, `_assert_may_schedule`, `_assert_may_execute`, the Edit rule and the My Plan page gate); tick boxes and the bar for ticked activities where a row can be moved or cancelled |
| School Visit Feedback | the 20 newest findings and improvements recorded at the school's visits, with the training paired with the visit or the visit it followed up |
| Partner Support | `partner_oversight_service.build_items_for_school`: every hand-over the partner still holds, its stage, date, cost and the one next step |

The reader's scope gained what those checks read: a lead's supervisees and
the districts of the direct portfolio (`internal/schooldirectory`).

The seed's activities at schools were only completed or scheduled. School
1578 was given, with the existing models and marked "[Go parity check]
participation", one activity in each other state the list reads (in
progress, evidence uploaded with and without its Salesforce ID, returned by
the Programme Lead, awaiting the owner's approval, dated by a partner, due
today, rescheduled over three days with a long purpose, verified), a cluster
leaders' meeting it is invited to, a completed group training it attended,
and two hand-overs (one returned to staff, one dated). School 1000 was given
one visit finding with two improvements.

Proved with `cmd/parity -screen profile -tab activities` against a gateway
with no existing application behind it, so an answer Go passes on shows as
refused and cannot pass as Go's: all 29 accounts that may open a profile
(3,826 compared), every answer Go gave identical, the only others the
profiles Go passes on by design (426, Core schools; a school outside an
account's reach was refused alike); the CCEO's 700 schools again for
FY2026, Q2, November and an unknown year and period, 597 answered by Go and
identical, the 103 Core schools passed on. The other tabs were compared the
same way on the CCEO's 700 schools after the change: Overview and Details
597 answered and identical (105 passed on: the Core schools and two with a
Business Transformation record), SSA, Projects, Stories and Academic 597
answered and identical. The earlier all-account runs (13.2, 13.7, 13.8) used
a gateway that falls back to the existing application; they prove Go's
answers matched, and these runs prove which answers were Go's.

## 13.10 Core schools

Go answers every tab of a Core school (the Core School tab in 13.11).

| Part | Existing rule it ports |
|---|---|
| The package split | `core_schools.package_split.package_splits`: the school's live package for the year (or, while it has packages, the year's still to be made); the visits and trainings at the school dated in the year by who delivers them (`package_credit.slot_kind_for`: the follow-up and SSA Support visits staff deliver, the trainings at the school, the visit an in-school training writes beside itself; never outreach visits, a partner's SSA Support, a universal training or an Alumni project's work), with the existing query's joins; the group trainings filling the package's training slots; and the running year's hand-overs still waiting on the partner (`package_credit.assignment_kind`) |
| The doors | `visit_gate._decide_by_rule` for a Core school: two visits a side; staff's half full locks the staff visit ("Staff visits complete"); the partner's two visits and two trainings held close Assign to Partner with the sentence the page says; SSA Support to a partner only while the year has no SSA |
| The doors' addresses | a reader of Core Schools opens the Core Schools drawers (`/core-schools/schedule-activity`, `/core-schools/assign-partner`), anyone else the Planning drawers (`profile_core_routes`) |
| Details | V1..V4 and T1..T4 of the school's live package for the year, else its newest: the slots taken (dated or handed to a partner) of the package's targets (`_core_package_marks`) |

The seed's Core packages were all open. At Kimenyedde Church of Uganda
Primary (1006), through the existing web app as the CCEO and marked
"[Go parity check]": two staff core visits (a Training Follow Up and an SSA
Support) and four hand-overs to Literacy Uganda (visits 3 and 4, trainings 1
and 2), so the staff half is full and the partner's half is taken.

Proved against a gateway with no existing application behind it: every
engine tab and Details on all 700 of the CCEO's schools, Core schools
included, every answer Go gave identical, the only ones passed on the two
schools with a Business Transformation record (Overview and Details); and
for all 29 accounts that may open a profile, Details (3,826 compared, 8
passed on: those two schools) and Participation (3,826 compared, none passed
on), none differing. School 1006's header was also read side by side: the
"Staff visits complete" lock and its sentence, Assign to Partner greyed with
"The partner's half of this package is taken: 2/2 visits and 2/2
trainings.", the Core Schools drawers' addresses, and "4/4 V1V2V3V4".

## 13.11 The Core School tab

Go answers the Core School tab of a Core, Core Trained, Core Graduate or
Champion school: the school's row of Core School Intelligence
(`core_schools.intelligence.performance`), the same figures Core School
Oversight shows for it.

| Part | What it reads |
|---|---|
| SSA Trajectory | the latest confirmed records of the year and the year before, 120 days apart or more; each intervention by the country's rule first, the school's verdict by the mean change against the mean of those rules (`impact_engine.improvement_rows`, `change_rules.school_verdicts`) |
| Package and Support | the year's Core plan as it records its completion; the package's 2 + 2 split (13.10); the hand-overs made in the year, by stage |
| Participation | the register of the year's delivered cluster sessions and the school's own delivered trainings, as headcounts |
| Outcomes | enrolment and learning results this year and last, each year on its own |
| Recommended Support | the school's SSA recommendations still open or planned, by rank; Plan support for someone who may change the school's record (`may_write_school`) |
| Champion Readiness | `ChampionEligibilityService.scan`'s inputs for the school (its Core profile, its live package, its confirmed SSAs) and `_read_champion`'s words; the Champion review for a Potential Champion, for a reader of Core Schools |

The page reader keeps the sentence explaining the trajectory as its link
alone, and drops the recommended training's name and the Accept, Defer and
Reject forms (they are forms, which it does not read); Go matches today's
text. School 1006 was given three SSA recommendations through the existing
service (one accepted, one deferred, one as generated). Potential Champion,
Progressing and a compared trajectory are not in the seed and are covered
by unit tests built from the page's own words.

Proved against a gateway with no existing application behind it: all 29
accounts that may open a profile (3,826 compared), every answer Go gave
identical, the only ones passed on the two schools with a Business
Transformation record (where "core" opens their Overview), for the four
accounts that reach them; the Programme Lead also over all 700 of the
team's schools, none differing. School 1006's tab was read side by side as
the CCEO, block for block.

## 13.12 Closed schools

Go answers every tab of a closed school (temporarily or permanently closed)
for anyone who may open it (the scope's closed schools, `get_one`).

| Part | Existing rule it ports |
|---|---|
| The way back | "Back to Closed Schools", to the archive |
| The banner | above every tab: the status and the day the school stopped; the latest closure's reason in its words, the learners at closure and the future work it cancelled. The page's reopening form is not read by the app |
| The doors | Edit Details, Add to Project and Reassign Owner as for any school; no Schedule, Assign to Partner, Enter SSA Score or Close School, and no visit lock (`_profile_planning_controls`) |
| The facts | "Status: Closed" on every engine tab |

The seed had no closed school. Central Division Church of Uganda Primary
(1078, a Core school) was closed temporarily through the existing web app as
the CCEO, its reason marked "[Go parity check]".

Proved against a gateway with no existing application behind it, school by
school because the comparison tool lists open schools: 1078 for all 29
accounts on all eight tabs, 232 answers, none differing (the refusals of the
accounts that may not open it included).
