# Team Performance report

Owner, 2026-10-20: "Team performance page, replace everything there with" the
FY27 Weekly Report workbook. Its sheets become tabs, Executive Summary first and
the default, and "all the data there should sync with the database data".

Owner's answers the same day:

- The Performance Reviews, Recovery Plans, Professional Development and Policy
  Compliance workspace keeps its own sidebar entry, **Performance Reviews**.
- Who reads what (owner, 2026-10-21): a CCEO their own portfolio and
  performance; a Programme Lead their own and their team's — themselves and
  the CCEOs whose direct line is to them — with the team's approved
  allocations as their targets; Impact Assessment, the Country Director and
  Admin (and the RVP and Regional Programme Lead) everyone, grouped by
  Programme Lead. Only the visible schools are read, and a CCEO's team row is
  their own, so a team's target is never set against one officer's work.
- Targets are the ones Programme Leads and Project Coordinators already set
  (the Uganda Master Priority Plan allocations). Achievements come from the
  work staff planned and completed. Exam scores, enrolment, MSC stories and
  Discipleship Clubs come from the school profile or the Salesforce uploads.

Nothing on the page is typed, stored or cached. Every figure is read from the
records below when the page opens, so a visit or training planned or
completed, or a record uploaded, changes it on the next load or refresh (the platform's
rule since 2026-10-14: pages update on refresh, not by streaming).

## Tabs

| Tab | Workbook sheet | What it shows |
| --- | --- | --- |
| Executive Summary | Executive Summary | Five headline tiles, the four regions and the national total against the end of the previous week, every tracked target area (owner, 2026-10-21: "all targets that are tracked" — each tracked row with a plan milestone or an eligible-schools target, data collected aside, by section): a table of each area's national target, achieved, % and change since the previous period and every Programme Lead team's target, achieved and %; then, one row per area, two charts of it side by side — by region (every region) and by Programme Lead; and the programme delivery milestones with a status. |
| Detailed Country Report | Weekly Report - Country (and its copy) | Every category in the workbook's columns: Monthly Performance for the chosen month, Q1–Q4 Cumulative Performance and Annual Performance against Annual Target (owner, 2026-10-20). Country, one region or one CCEO. |
| Strategic Milestones | Strategic Milestones & Trackers | The live sheet's 54 milestones in its 7 domains, achieved from the records and targeted by the matching Uganda Master Priority Plan milestone (owner, 2026-10-20); rows the platform keeps no record for read "Not tracked". |
| CCEO Officer Performance & Milestones | CCEO Officer Performance and Milestones Dashboard | The live sheet's dashboard: CCEO cards, an Officer Deep-Dive, the milestones, regional roll-ups and the master grid, with region chips, the officer profile and sorting. The year to the end of the chosen month. |
| {Month} {Year} Summary | August 26 Summary | One row per CCEO, grouped by region, with every summary column and the region and national totals. Titled by the chosen month. |
| Core Visits & Training | Core Visit & Training | Each CCEO's Core schools with 2, 3 and 4+ visits and trainings, expected against achieved. |

## Who is counted, and where

- **A CCEO's portfolio** is the schools whose account owner they are
  (`School.account_owner_id`, a staff profile id or its user id, as
  `core.scoping.owner_ids` writes it). Deleted schools are never counted.
- **A region** is a Programme Lead's team: the lead and the CCEOs whose direct
  line is to them (`StaffSupervisorAssignment` rows whose supervisor is a
  Programme Lead; IA and RVP rows are oversight beside it and never move a
  CCEO). It is named after the region most of its schools are in. Officers
  with no lead are listed under "No Programme Lead".
- **Core** is the platform's Core family (`core`, `champion`,
  `hr.target_distribution.CORE_FAMILY`, the family a Core target reaches);
  **client** is every other type, as the workbook's "not Core".
- **Work is credited to the school's account owner**, as the workbook credits
  it, whoever delivered it. Staff and partner delivery are reported apart where
  the workbook does.

## The records behind each figure

| Figure | Record | Counted when |
| --- | --- | --- |
| Visits, trainings, meetings | `Activity` | Achieved "when the officer completes it" (owner, 2026-10-20): submitted to the PL or further (`ledger.ACHIEVED_STATUSES`); returned, cancelled or rejected work is not. Dated by `actual_delivery_date`, else the planned day. |
| Cluster sessions | `ClusterActivityAttendance` | Achieved for each school that attended a completed session (the legacy attended list included). |
| Training topic | `Activity.training_course`, else `catalogue_item` | The catalogue's stable code. Online means delivery method `online`. |
| Cluster meeting held as a Training | `Activity.meeting_kind` | A cluster meeting of kind Training delivers a catalogue course (owner, 2026-10-06): it counts as a training for its course and attending schools, and still as a cluster meeting. |
| Core visits and trainings | `CoreActivitySlot` | A package slot, counted by the status of the work linked to it (achieved as above); a slot with no work linked counts when the slot is done. The year's slots are numbered by date, a slot dated just outside the year being placed on its nearest day, so the nth visit stays the nth. |
| Participants | `Activity.teachers_attended`, `leaders_attended` | Each session's headcount, counted once. "Leaders trained — SIP" counts leaders, "Teachers trained on ECD" teachers; other participant rows both. |
| New schools | `School.created_at` | Any school added to the platform in the year, typed in or uploaded (owner, 2026-10-20); counts toward the NEW_SCHOOLS target. |
| Core recruitment (new Core schools) | `Activity` (Core School Orientation) | A Core school whose Core School Orientation the officer completed in the year (owner, 2026-10-20); counts toward the NEW_CORE_SCHOOLS target, as the Master Plan maps it. An onboarding (`CoreSchoolOnboarding`) marks a Core SSA as a baseline; it is not itself a recruitment, and nor is a Core profile's start year, which rollover rewrites. |
| SSA | `SsaRecord` | Of the year, "once uploaded" (owner, 2026-10-20): pending or confirmed; returned or flagged records are not. |
| Discipleship Club | `DiscipleshipIndicatorRecord` | Pending or confirmed; a club when active groups is above 0. |
| OneTest, exam scores | `LearningAssessmentResult` | Pending or confirmed, by assessment type. |
| Enrolment | `School.last_enrollment_date`, `SchoolEnrollmentHistory` | A figure dated in the year: the school upload or a profile edit, or an SSA Support visit. |
| MSC stories | `MostSignificantChangeStory` | Approved, by story date; the school's owner, else the author. |
| Loans | `MfiLoan` | Disbursed, by disbursement date; EdTech by the loan purpose. |
| Quarterly Cluster Leaders Meeting | `Activity` | The District Meetings (`FIELD_DISTRICT_MEETING`) planned and completed (owner, 2026-10-20), with any cluster meeting held as a Cluster Leaders Meeting (`meeting_kind`). Counted in meetings. |
| Alumni Data | `Activity.project_id` | Schools reached by work under the Alumni project (owner, 2026-10-20: "fetched from project"), planned and completed; the project is found by "Alumni" in its name or code. |
| Active schools | `School.operational_status` | Active or reopened. |

A figure the records cannot give is shown as "Not tracked", and a missing
target as "Not set", never as 0.

### Planned

Each band of the Detailed Country Report shows Planned beside Target and
Achieved (owner, 2026-10-20): the work in the training and visit plans for the
same window, dated by the day it was planned for. Work is planned while it is
not started, under way or done; cancelled, rejected, deferred and unplanned
work, and a visit awaiting its owner's approval, is not. A cluster session is
planned for every school invited to it. The annual band reads the whole
year's plan, and a quarter not yet begun shows the work already booked in it.
Rows nobody plans (SSAs, uploads, stories, loans, recruitment) have no
planned figure.

Each band — the month, Q1, Q2, Q3, Q4 and the year — has its own column
colour down the whole column (owner, 2026-10-20).

## Targets

Targets are set per Programme Lead team and per CCEO, never per region. The
Executive Summary's region charts therefore share each CCEO's approved
target for an area across the regions their eligible schools for it are in —
client schools for a client area and for recruitment, all schools for
Discipleship Clubs; all their schools when they hold none eligible — in whole
schools by largest remainder. An area with no plan milestone (Partner School
Visits) gives each officer their eligible schools. A target whose holder
holds no school, or a country target nobody holds (MSC Stories), is "Not
placed", so the regions add up to the country's target (owner, 2026-10-21:
"Split each CCEO's target"). What was achieved counts in the region its
school is in; a session in the region most of the schools it reached are in,
participants summed; a portfolio figure (Active Schools, Schools in Clusters)
by where those schools are as the window closes. A Core area spreads by Core
schools, a client one by client schools, any other by all schools.

A Strategic Milestones row reads the same target as its Detailed Country
Report row: its plan milestone, else, for a coverage row, its eligible schools.

Targets come from the Uganda Master Priority Plan for the year
(`hr.target_distribution.uganda_master_priorities`):

- **Country:** the target Impact Assessment or Admin set on the Country Targets
  page (`/team-performance/country-targets/`, owner, 2026-10-20: "All country
  target should be set by either IA or Admin"; the Country Director reads
  them). A row they leave blank takes the milestone's target, or its Core or
  Client figure for a Core or client row. Every change is audited.
- **Region:** the Programme Lead's approved team allocation, else the sum of
  their officers' approved allocations.
- **CCEO:** their approved allocation.
- **Months and quarters:** the allocation's approved monthly phasing
  (`MilestonePeriodTarget`). Where nothing is phased the month shows "Not
  phased"; the annual target still shows.
- **Percentage milestones** (coverage) are applied to the scope's eligible
  schools: 90% client visit coverage over 400 client schools is 360 schools.
- **Coverage rows** with no milestone (Core visits 1–4, Core trainings 1–4,
  active schools) take the eligible schools as their target, as the workbook
  does, and say so.

## Period filter

Weekly, Monthly, Quarterly (Q1–Q4) and Annual (owner, 2026-10-20), shown only
on the tabs that read a period: Executive Summary and Strategic Milestones.
The Detailed Country Report, the CCEO dashboard and the {Month} {Year} Summary
read a month;
Core Visits & Training reads the year to date. A period's target is the sum of
its phased months (none for a week, which no plan phases); the comparison is
the figures as they stood at the end of the previous week, month, quarter or,
for the year, at its start.

## Status

The workbook's rule: 100% or more is Achieved (On Track for a running
figure), 75% or more is Progressing, below that Needs Attention. Momentum on
the CCEO dashboard compares this week with the week before: up is
Accelerating, down is Behind, level is Steady.

## The previous week

"Prior week" is every figure as it stood at the end of last week (the Sunday
before this week's Monday), read from the same records with a date cut-off.
"Work done in the week" is the difference.

## How the figures are checked

`apps/team_performance/test_crosscheck.py` builds a seeded random year of
records — every activity status, staff and partner, online and in-school,
cluster registers and legacy attended lists, school-less meetings, the Alumni
project, Core package slots, SSAs in every verification state, dates just
outside the year — and recounts every work, Core package, SSA and new-school
figure, achieved and planned, from a plain restatement of these rules, for the
country, each officer and a pair, over every month, quarter to date and the
year. It must agree with the ledger on all of them.

