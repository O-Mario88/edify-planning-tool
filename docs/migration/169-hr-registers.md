# 169. The HR registers, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". About twenty
Human Capital pages are one register shell
(`apps.frontend.views.hr_views._render_workspace`,
`pages/hr/module_workspace.html`, `partials/hr/module_register.html`) filled
by a view each. `platform/backend/internal/hrregister` ports the shell and the
reach rule once; each register is added to it as it is ported.

| Register | Path | State |
|---|---|---|
| Organization Structure | `/org-structure` | This document |
| Recognition | `/recognition` | This document |
| Health & Safety | `/health-safety` | This document |
| Staff Onboarding | `/onboarding` | This document |
| Staff Offboarding | `/offboarding` | This document |
| Candidate Pipeline | `/candidate-pipeline` | This document |
| Employment Compliance | `/compliance-register` | This document |
| HR System Audit Log | `/hr-audit-log` | This document |
| Workforce Planning | `/workforce-planning` | This document |
| Policies & Documents | `/policies` | This document |
| Performance Recovery Plans | `/recovery-plans` | This document |
| Compensation & Benefits | `/compensation-benefits` | This document |
| Staff Pulse Surveys | `/pulse-surveys` | This document |
| HR Analytics & Workforce Insights | `/hr-analytics` | This document (its second home, the Analytics workspace's `/analytics/people`, is a web page) |
| Performance Reviews (everyone but a Programme Lead) | `/performance-reviews` | This document; a Programme Lead's reviewer's view (`_team_performance_reviews`, built on `performance_engine.team_review_rows`) is passed on until native-performance-reviews-2 |
| The other registers (employee relations, which writes an audit record on every read and waits for Go to write the audit chain, recruitment, …) | | Still the existing application's; each is a backlog item that adds a builder |
| Every save a register's buttons open | | Still the existing application's |

## 169.1 The shell

| Part | Existing rule it ports |
|---|---|
| Who may open a register | `require_page_permission(<the register's permission>)` and the feed's `can_open_url`, exported per role. Anyone else is not found, as the feed answers |
| Header | The register's eyebrow, title and description; each drawer button the role's `can_open` admits (exported per role). Link buttons (HR overview, the primary action) are not read by the feed |
| Breadcrumb | "Human Capital" (to `/dashboard`), "/", the title |
| Strip | The workspace strip the role is shown, rendered and read by the feed's own reader at export |
| Context figures | `components/context_metrics.html`: each figure once by its label, under the label the metric registry draws it with; the line under it kept only when it is a short second figure (`brief_helper`, shared with the school profile's strips), else moved to the note; the figure's tone only beside a line that stays |
| Records | "Current operational records"; while a search (`q`, stripped) is on, a "Clear search" link back to the register; the records 50 a page (`page`), or the register's empty title and body |
| Pager | The register's own pager, as the feed reads it: "Page N of M", then Prev and Next, each a link keeping the search (`?q=<|urlencode>&page=N`) and read again as its two words without a link |
| Reach | `apps.hr.reach.people_reach`: Admin or a superuser reads the organisation; the Regional HR Director the countries of the regions their geography assignments name (directly or through a district), else the country on their own People record, else nothing; a Programme Lead their own team (themselves and those whose supervisor they are); anyone else the country on their own People record, else nothing. Someone working in an acting appointment is passed on to the existing application, as every Go page does |

## 169.2 Organization Structure

`org_structure_view`: the live People records of live accounts in reach and
in the search (name, email, title, department or country, case-insensitive),
not exited, by department (none last) and name. Each row: the name, the title
(else the active role), whom they report to (supervisors' names, sorted, else
"No line recorded"), how many report to them, department, country and the
lifecycle state's label. Figures: People in scope, Active, Departments
(distinct, not blank), No reporting line (no supervisor and not a Country
Director, Regional Vice President or Admin).

## 169.2b Recognition

`recognition_view`: the recognitions of the reach's countries (none for a
team's reach or none: `scope_by_country`) whose person's name, category code
or citation holds the search, the latest award first. Each row: the person,
country, the category's label, the citation's first 90 characters (and "…"
past them) and the day awarded (`YYYY-MM-DD`). Figures, over the searched
recognitions: Recognitions in the last quarter (awarded on or after today
less 91 days) and the People they named, "of N staff, last quarter" where N
counts the live, not exited People records in reach. One drawer button,
"Recognise someone".

## 169.2c Health & Safety

`health_safety_view`: the incidents of the reach's countries whose category
code, location, country or injured person's name holds the search, the
latest first. Each row: the category's label and the person ("No one
injured" when none), country, day, severity, days lost and status, and the
record's own "Open" drawer button (read by the feed as one primary action on
an unlabelled last column). Figures, over the searched incidents: Open (not
closed), Serious (open, high or critical), Near misses and Days lost in the
last 12 months (on or after today less 365 days). One drawer button, "Report
an incident".

## 169.2d Staff Onboarding

`onboarding_view`: the onboarding plans of the live People records in reach
(`_profile_scope`, exited or not) whose person's name, country or status
code holds the search, the newest first. Each row: the person, their title
(else their active role), country, start day, "done of all" checklist tasks,
the status's label, and the record's "Manage" drawer button. Figures over the
searched plans: Plans (not closed), Awaiting supervisor, Ready for
activation; and Overdue over every plan in reach, searched or not
(`overdue_onboarding`: not closed, target day before today). No header
button.

## 169.2e Staff Offboarding

`offboarding_view`: the exits of the live People records in reach whose
person's name, status, reason code or handover owner's name holds the
search, by last working day (none last). Each row: the person, country, last
working day, the reason's label ("Not recorded" when none), the handover
owner ("Unassigned" when none), the status as stored, and the record's
"Open" drawer button. Figures over the searched exits: In progress (not
"Closed"), Handover gaps (in progress with no owner), Voluntary exits
(resignation or retirement); and "Past exit date, still active" over every
exit in reach (`accounts_past_last_working_day`: a last working day before
today and a person not exited), danger when any. One drawer button, "Start an
offboarding".

## 169.2f Candidate Pipeline

`candidate_pipeline_view`: the applications to vacancies of the reach's
countries (`scope_by_country` on the vacancy's country) whose candidate's
name or email, the vacancy's role or the stage code holds the search, the
last changed first. Each row: the candidate, the vacancy's role and country,
the stage's label and the UTC day it last changed (`updated_at.date()`); an
application still in selection carries its drawer button, "Hire" once the
offer is accepted, "Next step" before; a finished one (hired, rejected,
withdrawn) an empty actions cell. Figures over the searched applications:
Applications in selection, Screening, Interviews (interview, assessment or
reference check), Offers (made or accepted), Hired. One drawer button,
"Record a candidate".

## 169.2g Employment Compliance

`compliance_register_view`: first the gaps (`compliance_gaps`): each active,
not exited person in reach, by name, against each mandatory requirement of
their country or of every country ("All"), by name, that they have no record
against: the person, requirement, their country, a dash for expiry, "No
evidence on file", "Missing", and a "Record" drawer button for that person
and requirement. A search keeps a gap whose person's name, requirement's name
or person's country holds it (case-folded), or one the word "missing" holds
(the view's own test: "iss" keeps every gap). Then the records of the People
in reach whose person's name, requirement's name or country, or status holds
the search, the most urgent first (expired, missing, due soon, compliant,
anything else), by expiry day (none last) and name: the person, requirement,
the requirement's country, expiry day, who verified it ("Not verified"), the
status's label, and an "Update" drawer button. Figures: Requirements in reach
(every one for the organisation; else those for every country and the
reach's own, mandatory or not), Compliant and Due soon over the searched
records, and Missing or expired over the searched records plus the searched
gaps. Two drawer buttons: "Record evidence" and "Add a requirement".

## 169.2h HR System Audit Log

`hr_audit_log_view`: the HR trail of the tamper-evident audit chain (actions
starting `hr.`, `pd.`, `pd_`, `leave.`, `documents.`, `admin.user` or
`admin.supervisor`), not narrowed by reach: every reader of the page reads all
of it. A search keeps events whose action, acting role, subject id or subject
kind holds it. The latest 200, each: the action's label (its area, "HR",
"Professional development", "Leave", "Policy", "Accounts" or the area in
title case, then its name readable), the actor's name when a live People
record names them (else their id, else "System"), the acting role, "kind ·
id" of the subject, Success or Refused, and the time in UTC
(`%d %b %Y, %H:%M`, as the view writes it). Figures over every matching
event: Events, Refused actions, Acting roles (distinct, none counted as one),
Showing (at most 200). Never a payload.

## 169.2i Workforce Planning

`workforce_planning_view`: the People records in reach and in the search, not
exited, grouped by country and department ("Unassigned" for none), with the
active headcount and those pending activation; the exits of the searched
people (exited or not) with a last working day, counted as leaving when it is
today to 90 days ahead and the exit is not "Closed", and as left when it is
from the operational year's first day (1 October, the year read in UTC) to
today; and the vacancies of the reach's countries whose status (in lower
case) is open or pending approval. A unit is listed when it has people,
someone leaving, open roles or roles awaiting approval, in country then
department order; one with only leavers is counted but not listed, as the
view does. Figures: Headcount, Open roles ("N awaiting approval"), Leaving in
90 days (warning when any), Turnover this FY (leavers over headcount plus
leavers, to one decimal, "—" with nobody; "N left since Oct YYYY"). One drawer
button, "Request a vacancy" (the Regional Vice President, who reads the
register without Recruitment, is not shown it).

Found: the view groups a department stored as none and one stored as "" apart
and keeps only the last group, so people vanish; Go counts them as one
"Unassigned" unit (OWNER_DEFECTS; an intended difference once that list is
merged). The golden keeps the two apart to compare like with like.

## 169.2j Policies & Documents

`policies_view`: the policies and manuals, not archived, of every country
("" as stored) and, for a reach short of the organisation, of the reach's
countries, whose title, category or country holds the search, by title. Each
row: the title, the type's label, the country ("All countries" for every
one), the current version ("vN", "No version yet"), its review day, "agreed of
asked" acknowledgements of the current version (asked = agreed, pending and
disagreed; by the People records in reach, everyone's for the organisation)
or "Not required", the status's label, and a "Manage" link to
`/documents/<slug>/manage` (read by the feed as a primary button under the key
"button", with no drawer). Figures: Published policies (published or
effective), Policies in review (draft, under review or returned),
Acknowledgement rate (agreed over asked, rounded half to even, "—" with none
asked), Policy reviews due (a review day within 60 days, overdue included),
Disagreements (danger when any). The header's "Publish a policy" is a link,
which the feed does not read.

## 169.2k Performance Recovery Plans

`recovery_plans_view`: the recovery plans of the People records in reach; for
a Programme Lead (`team_view`), the plans of the people they review
(`reviewees_of`: those they supervise whose active role is one the Lead
reviews, `REVIEWER_ROLE_FOR` inverted and exported), never their own, under a
"My Team" breadcrumb with its own empty text. A search keeps plans whose
person's name, cause code or status code holds it; by status code and review
day. Each row: the person, the plan type's and cause's labels, start and
review days, the status's label ("Past review date" for a live plan, active,
in progress review or extended, past its review day), and an "Open" drawer
button. Figures over the searched plans: Awaiting authorisation (draft),
Active (live), Ending in 30 days (live, review day today to 30 days ahead),
Escalated. One drawer button, "Recommend a formal plan".

## 169.2l Performance Reviews

`performance_reviews_view` for every role but a Programme Lead: the reviews
of the People records in reach for the year asked for (`fy`, stripped; else
the operational year) or for no year, whose person's name, period, type code
or stage code holds the search, by due day and name. Each row: the person,
"type · period", the manager's name ("Not recorded"), the due day, for HR and
Admin the manager's rating, the final rating (the rating's label, else as
stored), and the stage's label ("Overdue" for one not done and past due).
Figures: Reviews ("FY <year>"), Completed (closed, acknowledged or archived),
Overdue, Awaiting calibration (calibration, HR quality review, ready for SLT
calibration). No header button read by the feed (the Performance Cycle link
is a link).

## 169.2m Compensation & Benefits

`compensation_benefits_view`: the compensation records of the People records
in reach whose person's name, salary band, pension scheme or status holds the
search, by name. Each row: the person, their country, the salary band, the
medical cover's label, the pension scheme ("None recorded"), the next review
day, the status's label and an "Update" drawer button. Figures over the
searched records: Compensation profiles, Approved, In review, Pay reviews due
(a review day within 30 days, past ones included); and Missing profiles over
the live, not exited People records in reach with no record. One drawer
button, "Add a record". Go never reads a salary, allowance, currency or bank
detail: the register does not show them and the gateway is not granted them.

## 169.2n Staff Pulse Surveys

`pulse_surveys_view`: every survey whose countries the reach all allows (a
survey of no country is everyone's; a team's reach, or none, allows no
country), the latest opening first; the register has no search. Each row: the
title, its countries joined, "dd Mon to dd Mon YYYY", how many answered, the
score ("N of 5" once five have answered: `survey_results`, each statement's
mean of its non-zero answers to one decimal, then their mean to one decimal,
Python's half-to-even rounding of the exact value, written as Python writes a
float; "Too few to show" under five), the status's label and a "Results"
drawer button. Figures: Open surveys, Latest morale score (the first listed
survey with a result shown, else "—"). One drawer button, "Open a survey". Go
reads only the answers' scores, never who answered or what they wrote.

## 169.2o HR Analytics & Workforce Insights

`hr_analytics_view` (`_hr_analytics_workspace`): the People records in reach
and in the search, exited ones included, grouped by country and department in
that order (a department stored as none and one stored as "" are two groups,
both "Unassigned", as the view's GROUP BY keeps them). Each row: country,
department, headcount, active, pending, and the activation rate (active over
headcount, rounded half to even, "0%" with nobody). Figures: Headcount,
Countries (distinct), Reviews due (the people's reviews whose legacy status
is not "Completed" or "Closed"), Compliance gaps (their missing or expired
records). The eyebrow is the shell's default, "Human Capital Operations".

## 169.3 Rules, access and proof

The doors, strips and buttons per register and role, the lifecycle labels,
the figures' labels, the line length and the page size are exported to
`internal/hrregister/rules.json` by `manage.py export_hr_register_rules`;
`apps/hr/test_hr_register_rules_export.py` fails when the two differ.

`deploy/db/roles.sql` grants `edify_gateway_ro` a People record's title,
department and lifecycle state; a recognition's person, country, category,
citation and day (not who awarded it); a safety incident's country, person,
day, place, category, severity, days lost and status (not its description
or the actions taken); an onboarding plan's person, start and target days,
status and age and whether each checklist task is done (not the probation
decision); an exit's person, last working day, reason, handover owner and
status (not its notes or clearances); an application's candidate, vacancy,
stage and last change, a candidate's name and email (the email only to
search it), a vacancy's role and country (not a candidate's phone, CV or
notes, nor a vacancy's salary band or budget); a compliance requirement's
country, name and whether it is mandatory, and an employee's record's
status, expiry day and verifier (not the evidence document); an audit
event's acting role, beside its action, actor, success, time and subject
already granted (never its payload); a vacancy's department and status; a
policy's slug, title, type, category, country, status, whether
acknowledgement is required and its current version, that version's number
and review day, and who acknowledged which version and how (not the file,
owner, audience or comments); a recovery plan's person,
type, cause, start and review days and status (not its evidence, action plan,
support or outcome note); a performance review's period,
year, due day, manager and its two ratings (not the reflection, feedback,
evidence or calibration note); a compensation record's band,
cover, pension, review day and status (NEVER an amount or a bank detail);
a pulse survey's title, countries, window and status and its answers' scores
(never who answered, their key or comment); a review's legacy
status (applied to `edify_gorn_dev` and
`edify_gorn_test`; production needs the owner's approval at cutover).

- `cmd/parity -screen page -path` each register for all 29 seed accounts:
  the page as it opens, searches (that find people, by country, by role,
  nobody, with spaces, LIKE's own wildcards) and pages.
- `internal/hrregister/testdata/golden.py` files 62 accounts and People
  records and 40 reporting lines in `edify_gorn_test` (two pages; every
  lifecycle state; titles, departments and none; two lines to one person;
  another country; a deleted record and a deleted account; 12 recognitions
  and 10 incidents either side of the quarter and the year, another
  country, long citations, no injured person; 10 onboarding plans with
  checklists and 10 exits around today; 12 applications at every stage on
  three vacancies; four requirements, mandatory and not, for every country,
  Uganda and Kenya, and 14 records of every status; the test database's own
  555 HR audit events; five vacancies of every status; six documents of
  every kind and status with 35 acknowledgements; 11 recovery plans, five of
  them on Programme Lead 1's team and one on the Lead; 12 reviews of every
  kind, this year, last year and none; 9 compensation records; five pulse surveys
  under and over the anonymity floor), asks the existing feed 600 questions as Admin, HR, Impact Assessment, the Country Director and a Programme Lead as Admin, HR and Impact Assessment and deletes
  the rows; `internal/integration/hr_register_test.go` compares Go's answers
  whole (`EDIFY_HR_REGISTER_GOLDEN`).

## 169.4 Found

- The feed reads each pager link twice more as plain words ("Next", "›")
  without a link; Go copies it. Cosmetic (OWNER_DEFECTS).
