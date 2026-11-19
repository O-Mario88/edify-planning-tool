# 178 · What is left of the Go migration (2026-11-19)

Owner, 2026-11-19: "when you are done with porting every role, check on the
remaining Go migration, complete and then work on the redesign proposed above
with focus on mobile first experience."

## How it was counted

With the coverage probe (`internal/server/zz_probe_test.go`, build tag
`probe`, never committed), which asks every Go page builder, for one seeded
reader per role, whether it answers each route of
`docs/platform-page-inventory.json`. The probe had fallen behind the gateway:
it lacked six builders (the scope profiles, Visit Requests, the staff logs,
the closure pages, partner users and Platform Health); the first four were
added before counting.

    PROBE_DB=postgresql://edify_gateway@localhost:5432/edify_gorn_dev \
      go test -tags probe -run TestZZProbe -count=1 -v ./internal/server

Result over the dev database: 347 inventory routes, 147 answered by a Go page
builder, 66 detail routes (with an id) not claimed, 134 static routes not
claimed. Every role's Home and To-Do queue is Go's (176.31–176.33). The 134
static routes split as follows.

## A. Answered by Go outside the page builders

Not unported; the probe asks page builders only. Each is confirmed when its
group is next touched.

| Route | Answered by |
|---|---|
| `/home`, `/home/queue`, `/home/todo-figures` | HomeScreenService (`internal/home`) |
| `/messages`, `/messages/new` and its parts | MessagingService (176.28) |
| `/settings` | SettingsScreenService (176.28) |
| `/notifications` | NotificationCenterService |
| `/login`, `/login/verify` | SignInService; the web app's `/auth/*` routes |
| `/partner/users` | `partnerusers` (175; outside the probe's list) |
| `/loan-applications/apply` | the public school loan portal (`internal/loans`) |
| `/offline` | the apps' own offline screen |

To check: `/reset-password`, `/change-password`, `/settings/two-step/app`
(sign-in and account services), `/profile`.

## B. Stays outside Go by design

| Route | Why |
|---|---|
| `/system-health`, `/system-health/notifications` | Django keeps System Health; Go has `/platform-health` |
| `/ia/learning` | Python analytics (owner: Python only for analytics) |

## C. Pages to port (read first; each save cuts over on its own, shadow-proved)

Ordered by family, so one family's services are ported once.

1. **Accounts desks** (Accountant; `finance_operating_views`):
   `/accounts/accountability`, `/advances`, `/audit-log`, `/blocked`,
   `/budget-amendments`, `/cleared`, `/returned`, `/variance-review`,
   `/weekly-requests`.
2. **Finance overviews**: `/budgets/overview`, `/finance/fund-allocation`,
   `/country-budget/history`.
3. **Field work**: `/today`, `/activities/closure`, `/planning/schedule`,
   `/debriefs/submit`, `/debriefs/weekly-report`, `/map`, `/search`.
4. **Partners**: `/partner/activities`, `/partner/assignments`,
   `/partner/schools`.
5. **SSA and data quality**: `/ssa/manual`, `/ssa/upload`,
   `/ssa/upload/history`, `/ssa/unmatched`, `/data-quality/duplicates`,
   `/priorities/ssa-mapping`, `/ia/notifications`, `/ia/school-evidence`.
6. **Admin panel**: `/admin-panel`, `/audit-log`, `/notifications-mgmt`,
   `/page-access-matrix`, `/region-district-setup`, `/school-upload-history`,
   `/workflow-rules`; `/settings/activity-catalogue`.
7. **HR**: `/culture-engagement`, `/payroll-readiness`,
   `/performance-conversation`, `/succession-planning`, `/wellness`.
8. **Business Transformation workspace**: `/business-transformation`.
9. **Knowledge Center and documents**: `/help` and its eight sub-pages,
   `/policy-agreement`, `/policy-agreement/restricted`, `/uploads/new`,
   `/support`.

Each is proved as 176.1 describes: `webpages/testdata/web_page.py` runs the
page's own view for each reader and reads it as the feed reads pages; the Go
builder's answer is compared whole. Readers or queries Go does not build are
handed on, never approximated.

## D. Parts (HTMX fragments, drawers, previews)

About sixty partial routes (dashboard actions, drilldowns, previews, option
lists, drawers). They are ported with the page that loads them, as RPCs of
PageDrawerService or as `later` parts of the page's answer, not as pages of
their own.

## E. Depth still handed on inside Go pages

- pl1's To-Do queue: `_pl_analytics_todos`, the team's core-school
  follow-ups, coverage (176.33).
- The guards in `internal/todos` that pass a reader on whenever a kind of
  record exists (listed per builder in 36-todos and 176.33).
- The hand-ons listed per page in 176 and earlier notes.

## Order of work

C1 → C9, then D with each page, then E. After that the mobile-first redesign
(177, Stage A first).

## Done

### C1 · The Accounts desks (2026-11-19)

`internal/financedesks` builds all nine desks as the existing pages draw
them: Accountability Pending (with its NetSuite drawer form), Ready for
Advance Disbursement (with its disbursement dialog), the Finance Audit Log,
the Finance Blocked directory (FinanceBlockedReasonService's four rules in
one query, counted and paged in the database), Budget Amendments, the Cleared
ledger, Returned corrections (`returned_correction_queue`), Variance Review
and the Weekly Staff Fund Requests registry. The doors (`disbursements`:
Accountant, Admin, Impact Assessment), the school-link rule, the activity
types and the status lists come from `manage.py export_finance_desks_rules`
(`apps/fund_requests/test_finance_desks_rules_export.py` fails on drift). A
budget amendment already decided is handed on (its reviewer line is the
existing page's). The gateway reads the new columns through
`deploy/db/roles.sql`.

Proved by `financedesks/testdata/golden.py`, which files an accountability
record, an audit event, a variance review and an amendment on one completed
activity, a closed activity, and an advance to disburse and one returned,
then runs the unchanged oracle (web_page.py) for the Accountant, the Admin,
IA and three readers the desks are refused to, on the first page and on the
Blocked directory's and weekly requests' last pages;
`integration/finance_desks_test.go` files the same records and asks Go:
108 answers of 6 accounts, 0 differing.

### C2 · The Budget Overview and Submitted Budgets (2026-11-19)

The same package builds `/budgets/overview` (fy_budget and monthly_budgets:
the FY's cost lines summed over a LEFT JOIN to their advances, as the
existing aggregate counts a line once per advance; the fundable figures over
live work, the money moved over every line; the notice of weekly requests
awaiting approval; the months with planned or requested money) and
`/country-budget/history` (the year's locked budgets, newest month first,
with their submitter's name). The "Scheduled Activities" figure is always
"—": the template reads `fy_data.activity_count`, a key fy_budget does not
carry. A search or another year on the history is handed on. Rules:
`manage.py export_finance_overviews_rules` (`financedesks/overviews.json`);
the Budget Overview's awaiting statuses are now a named constant in
`finance_views` rather than inline. The desks golden files a weekly request
awaiting approval and a budget submitted to the RVP, and gives the cost lines
a month: 154 answers of 7 accounts across eleven pages, 0 differing.

### C2 · The Consolidated Fund Allocation (2026-11-19)

`/finance/fund-allocation` is Go's (budgetpage/fundallocation.go): the
country's roll-up for a week (its default), month, quarter or year around a
date, each horizon's total on the period rail (the admin plan counted in the
month, quarter and year, never split into a week), the activity cost plan's
groups with the country admin plan as its own "Country Admin Plan" group (a
row an item and unit cost, its quantity summed as Decimals print), the
district filter (the activity's school, cluster or event district, or the
line's school; it leaves the admin plan out), and the footer of program and
admin costs. `budgetpage`'s line filter is now one builder the ledger and the
period sums share, and its periods are set in one place. Handed on: exports,
a search of the groups (it reads owners' names the ledger does not carry),
a year or date that is not plain, a reader whose Budget is not the
country's, several countries with no request country, more than one page of
groups. Golden (budgetpage/testdata/fund_allocation_golden.py, `gfa` rows
around today): 54 answers of 6 readers, 0 differing; the footer's "Updated"
minute is masked in the compare (`compareGoldenMasked`), the only part
drawn from the clock.

### C3 (part) · The School Map and the empty Search page (2026-11-19)

`internal/fieldpages` builds `/map` (map_view over school_queryset: the
reader's operating schools, the team's included, now exported as
`schooldirectory.ReadScope`; the count without coordinates, a verified geo
point first, then the upload's) and `/search` with no query. Once any school
in reach has coordinates the existing feed reads the map's inline script and
yields three panels of its string literals ("Map could not be loaded",
"' + message + '", "' + p.name + '"); Go gives the same, so the apps see what
they see today. A search with a query is handed on (its scoped school, staff
and activity lists are not built yet). Rules: `manage.py
export_field_pages_rules`. Golden: `web_page.py` for `/map` and `/search`
over eight readers, 16 answers, 0 differing.

`/planning/schedule` with nothing chosen (the visit form: a school is typed,
no cluster is listed) is Go's too; a chosen action, school or cluster is
handed on. With it the golden is 24 answers over three pages, 0 differing.

`/debriefs/submit` (the Daily Debrief) is Go's in `internal/debriefs`
(submit.go): the reader's work for today ticked as get_state ticks it, the
activity they came to discuss carried in through the same ownership, a
draft's or returned debrief's answers in the form, the read-only summary
once submitted, and the roles that open it but may not submit. Its golden
(debriefs/testdata/submit_golden.py) is 24 answers over eight readers, 0
differing. The form's saves stay the existing page's.

`/debriefs/weekly-report` (the Weekly Debrief Report) is Go's too
(debriefs/weekly.go): the report each role lands on (a Lead's team report,
the country's for the Director, HR, the RVP and the Admin; HR and the RVP
only once finalized), drawn from the snapshot locked when it was generated:
the week's figures, missing teams, each theme under its kind with its trend,
confidence and two sources, the team's submissions, the commentary and the
PDF link. A Lead or Director with no report for the week has the existing
page generate one as it opens: Go hands that on. Its golden
(debriefs/testdata/weekly_golden.py, reports built by the service itself)
is 36 answers over nine readers, 0 differing.

`/activities/closure` (the Closure Readiness Workspace) is Go's in
`internal/closurepages` (queue.go): the reader's work past its doing, newest
first to the queue's 300, each activity's closure facts read in the listing
query as with_facts annotates them (evidence, cost lines, NetSuite expense,
cleared, moved and unaccounted advances, the publish record) and sorted into
Ready, Finance, Accountability, Analytics and Blocked; called-off work stays
only while money it was paid is out. Its golden
(closurepages/testdata/queue_golden.py) is 8 readers, 0 differing. The list
of not-yet-done states the view leaves out is now
`closure_views.QUEUE_NOT_STARTED_STATUSES`, exported with the rest.

Left in C3: `/today` — only the Admin opens it (field roles and Impact
Assessment are redirected, which Go hands on): the desk queue with each
row's decision buttons (today_actions adapters), snoozes and the cleared
count.

Looked at again (2026-11-19, after C2): the Admin's desk is the To-Do queue
Go already builds (`todos.Service.HomeQueue`), split into exceptions
(critical or blocked) and the actionable rest, less the rows the reader
snoozed, each row decorated by `today_actions` (a decision adapter matched
on the To-Do's id, else an activity drawer link) with the Snooze choices.
Go's queue rows carry no To-Do id, so neither the snoozes (`TodoSnooze`,
keyed by id) nor the adapters can be matched: `/today` waits for the
builders to carry their ids, part of E.

`/planning/schedule` with a choice is Go's (fieldpages/schedule.go): a
training or meeting over the clusters the reader may plan in
(cluster_queryset direct_only, by name; the chosen one selected when it is
among them), the meeting's purpose category and the participants field, any
other action read as the meeting title over the cluster list; a visit for a
chosen direct-portfolio school fills its School ID. A chosen school with a
confirmed SSA carries the SSA's recommended focus areas: handed on (the
golden writes those answers as 302). Its golden
(fieldpages/testdata/schedule_golden.py) is 60 answers over six readers and
ten choices, 0 differing. Two gaps: every school in the test data has a
confirmed SSA, so a chosen school without one (code filled, no
recommendations) is built as the template draws it but not proved; and an
empty `?action=` (Django: a meeting) reaches Go as no action, since the
gateway drops empty query values, so Go draws the visit form there.

`/search` with a query is Go's (fieldpages/search.go): the reader's
direct-portfolio schools of that name, staff for the staff directory's roles
(a country's own unless Admin, HR or the RVP, none without a country), and
the work list_activities reaches at a school or cluster of that name (a
country reader's country; else their schools, their staff-profile id, and a
partner's organisation and the schools it holds), ten each, newest first.
Its golden is 70 answers over ten readers and seven queries (wildcards, a
padded query, nothing found), 0 differing. `_searches_every_country`'s roles
are now `extended_views.EVERY_COUNTRY_SEARCH_ROLES`, exported.

### C4 · The partner portal's lists (2026-11-19)

`/partner/schools` (Assigned Schools), `/partner/activities` (the Activity
Log) and `/partner/assignments` (Assigned Activities) are Go's in
`internal/partnerassigned` (portal.go), over the organisation the login acts
as (resolve_partner_ids): the schools it has work at that was not called
off, by name; the log's assignments awaiting its date (Return and Schedule
read as drawer links) and its work, the status asked for or else what was
not called off, latest planned first, sixty of it, fifty a page; the newest
two hundred assignments split into awaiting and scheduled. With no work but
assignments waiting, the feed reads the log's card as one panel (the
heading, the first assignment's name, the empty note), and Go draws that.
The view's limits and states are now named
(`partner_views.PARTNER_LOG_LIMIT`, `PARTNER_ASSIGNMENTS_LIMIT`,
`PARTNER_AWAITING_STATUSES`) and exported, and the log orders same-day
work by id (it fell to the query plan). Golden
(partnerassigned/testdata/portal_golden.py): 108 answers over six readers,
six queries and the three pages, 0 differing.

Left, in order: `/today` (Admin's desk queue, with E), C2
`/finance/fund-allocation`, C5–C9, D, E.

### C5 (part) · Verification Notifications and the Duplicate Review Queue (2026-11-19)

The C5 pages live at their trailing-slash paths (`/ssa/manual/`,
`/ssa/upload/`, `/ssa/upload/history/`, `/ia/notifications/`,
`/ia/school-evidence/`); without the slash Django has no route.

`/ia/notifications/` is Go's in `internal/iapages` (notifications.go): the
reader's newest fifty notices under the verification categories, each its
title (a link to its record when it has one), its time and its words.
Golden (iapages/testdata/notifications_golden.py): 4 readers, 0 differing.

`/data-quality/duplicates` is Go's in `internal/dataquality`
(duplicates.go): the open duplicate risks at operating schools, newest
first, fifty a page, each school's name and duplicate state, its district
and the suggested fix. Golden (dataquality/testdata/duplicates_golden.py):
20 answers over five readers and four pages, 0 differing. Marking a school
unique stays the existing page's.

`/ssa/unmatched` is Go's in `internal/iapages` (unmatched.go): the imported
SSA rows no school matched, in the reader's country (by the batch's uploader
or the suggested school), by status (pending and held unless one is asked),
batch, district, School ID, confidence and upload dates, newest first, fifty
a page with the existing page's own pager. A confidence float() refuses or a
date that is not one hands on (the existing page fails). The default states
are now `unmatched_service.QUEUE_DEFAULT_STATUSES`, exported. Golden
(iapages/testdata/unmatched_golden.py): 55 answers over five readers and
eleven queries, 0 differing. Linking, creating a school, holding and
ignoring stay the existing page's.

`/ssa/upload/history/` is Go's in `internal/iapages` (upload_history.go):
the SSA import batches the reader may open (the Admin all of them, Impact
Assessment its country's uploaders' and its own, anyone else their own),
each with the rows it imported, left unmatched and refused, filtered to
batches with refused rows or the reader's own, newest first, fifty a page.
A role the page opens to without the SSA upload permission is refused by
the existing page: handed on. Golden
(iapages/testdata/upload_history_golden.py): 36 answers over six readers and
six queries, 0 differing.

`/ssa/manual/` (Add SSA Score) is Go's in `internal/iapages` (manual.go):
the school typed (the one asked for written in), today's date and the eight
intervention scores, for the roles that may upload official SSA; a role the
page opens to without that permission is sent away by the existing page and
handed on. 24 answers over eight readers, 0 differing. Saving stays the
existing page's.

`/ssa/upload/` (Upload SSA Scores) is Go's in `internal/iapages`
(upload_center.go): the sheet's columns, one per intervention, the two notes
and the file picker, for the roles that may upload official SSA (others are
sent away by the existing page and handed on). 8 readers, 0 differing.
Uploading stays the existing page's.

### C6 (part) · Workflow Rules and School Upload History (2026-11-19)

The Admin Panel's pages live in `internal/adminpanel`, from
`manage.py export_admin_panel_rules` (doors and the listed workflow rules;
`extended_views.WORKFLOW_RULES` is now a named constant).
`/admin-panel/workflow-rules` is the reference list of the rules enforced in
code (4 readers, 0 differing). `/admin-panel/school-upload-history` is the
newest fifty upload batches the reader may see (the Admin every batch,
anyone else their country's uploaders' and their own), each with its file,
type, row breakdown and state; a state with an error under it reads as one
line. Golden (adminpanel/testdata/upload_history_golden.py): 8 answers, 0
differing. Marking a batch failed stays the existing page's.

`/admin-panel` (the Admin Dashboard) is Go's too (adminpanel/hub.go): the
user directory's figures, the links, the actions centre and the live alerts,
the missing cost lines counted as system_health.missing_cost_lines_count
counts them (its exempt states are now
`system_health.services.MISSING_LINE_EXEMPT_STATUSES`, exported with the pair
and online-training rules). Golden (adminpanel/testdata/hub_golden.py, both
alerts raised) 3 readers and the clean state 4, 0 differing.

`/admin-panel/audit-log` is Go's too (adminpanel/audit.go): the newest
hundred audit rows, each its action and time in Django's default wording
("Nov. 20, 2026, noon"), fifty a page. Its golden
(adminpanel/testdata/audit_golden.py) dates its rows tomorrow, so rows the
suite writes meanwhile stay older: 12 answers, 0 differing.

`/admin-panel/region-district-setup` is Go's too (adminpanel/geography.go):
the districts not yet classified, every region's districts, the Secondary
District Groups (read as their create form when there are none, as a panel
of each group's state and districts when there are) and the new-district
form. Golden (adminpanel/testdata/geography_golden.py) 3 readers with groups
and the clean state 2, 0 differing.

`/admin-panel/notifications-mgmt` is Go's too (adminpanel/notifications.go):
the newest fifty notifications to anyone, each its title, words and time,
its recipient and role, priority and read state. Golden
(adminpanel/testdata/notifications_golden.py, dated tomorrow): 6 answers, 0
differing.

`/admin-panel/page-access-matrix` is Go's too (adminpanel/access_matrix.go):
every routed page by path and a column per role, from the list the view now
builds with `extended_views.access_matrix_pages()` and the exporter writes;
each cell is a grant icon the feed reads alike whether granted or not. 12
answers over three readers and four pages, 0 differing.

`/settings/activity-catalogue/` is Go's (internal/catalogue): the governed
catalogue under its five filters (every item for a reader who manages it, the
items in force today for anyone else), each card written as the template
writes it and read by the feed's own rules (feeddom): its use count, the
active mappings' interventions, evidence, cost and Salesforce profiles,
eligibility and version history, a training's Edit drawer; for a manager the
New activity button and the Catalogue Mapping Review card (its one form when
a single correction waits). A reader without the catalogue's view
permission is refused (403); ?new= (the drawer opened) is handed on. The
project choice reads `workplan.ScopedProjects`. 30 answers of 6 readers over
five filters, 0 differing.
`/priorities/ssa-mapping` is Go's (iaframework/mapping.go) for the readers
who keep the read-only register (the Programme Lead, the RVP, the Project
Coordinator): rules_register's rows, fifty a page, each with its History
drawer; a reader of the framework is redirected to its rules tab, which Go
hands on, and an empty register is handed on. rules_register's rows are now
built once (`ruleRows`) for the framework's rules tab and this page. The
exporter writes who opens the register and who reads the framework. 32
answers of 8 readers over four pages, 0 differing; and a framework compare
(rules tab, its filters and paging, the default and indicators tabs) to
prove the shared rows: 18 answers, 0 differing.

`/ia/school-evidence/` is Go's for its Learning results tab (internal/
schoolevidence): the reader's section strip, the figures over every kind of
evidence in their scope (nothing for a summary-only reader), the tab rail,
the year, state and subject filters, Impact Assessment's CSV upload form and
Record button, the year-on-year comparison of confirmed class results
(learning_comparisons: pooled by school, assessment, class and subject,
weighted by learners, a side under ten learners withheld, the change in
points of score or of proficiency, Python's rounding and number writing)
and the register of results, newest first, fifty a page, each Open or, where
the reviewer rules allow (iaframework.Reviewer, now exported), Verify. A
status's tone sits on a span the feed does not read. Handed on: ?open= (a
record's drawer). Golden (schoolevidence/testdata/learning_golden.py, `gsev`
results): 28 answers of 4 readers over seven filters, 0 differing.

The Discipleship and EdTech tabs are Go's too (2026-11-19). Discipleship:
each school's latest confirmed record this year beside its latest last year
(the share of learners in groups, Python's half-to-even rounding, the
change in points) with its approved spiritual change stories
(iapages.SpiritualStoriesBySchool, shared with the stories page), then the
register. EdTech: every confirmed deployment in scope, of any year and
state, with its latest confirmed check (deleted checks never count) and its
checks awaiting verification, Impact Assessment's Record check on each; the
register of deployments filtered by technology; and the year's checks of
use, newest first, up to fifty. The three registers share one Recorded by /
Status / Open-or-Verify helper. The technology and funding labels are in
the exported rules. Goldens: discipleship_golden.py (`gsed` records and
stories) 28 answers, 0 differing; edtech_golden.py (`gset` deployments and
checks) 32 answers, 0 differing. Both ask with sorted keys, because Django
writes pager links in the request's order and Go sorts them.

### C7 (part) · Four HR programme registers, and the registers' header buttons (2026-11-19)

`/culture-engagement`, `/payroll-readiness`, `/succession-planning` and
`/wellness` are Go's (hrregister/programmes.go), drawn by the same register
shell as the other seventeen: teams by country and department with their
activation beside the employee-relations cases the viewer may see; the
payroll checks of the People in reach, the latest period counted; named
successors by position with each nomination's UTC day; leave newest first
with who covers it. They are web-only pages (the phone feed answers 501), so
their golden goes through the web oracle
(hrregister/testdata/programmes_golden.py, `gprg` rows): 180 answers over
five readers and nine questions, 0 differing.

Found on the way: the seventeen HR registers Go already answered had drifted
from the existing pages without a test saying so — their golden was not in
the suite run. The feed now reads a register's header link buttons: the
view's lead link (`primary_action`, " →", primary unless the first header
button is drawn, and only for a role that may open its page; HR Today only
where `can_view_page("hr_today")` holds) and the way back (HR overview, or
My Team on a team register). The shell draws them; the exporter writes, per
role, which lead-link pages it may open. A figure's line naming an
intervention is shortened to its code as components/context_metrics.html
does (schoolprofile.HelperAndNote, now shared). The goldens' "other country"
moved from Kenya to Tanzania: Go's regional reach is every registered country
(owner, 2026-11-18) and Kenya is registered, so HR read Kenya's people in Go
and not in the existing app; a country no registry holds is outside both.
With that, all 562 register answers, 0 differing; Employee Relations 9, 0
differing, its 8 audited readings sealed as the existing app seals them.
The register golden reads the HR audit log, which Employee Relations' reads
append to, so the suite writes it after the main run and compares it alone.

### C7 · The Performance Conversation (2026-11-19)

`/performance-conversation` is Go's (internal/perfconversation): whose
conversation the reader opens (their own; with `?staff=` someone in their
People reach or whose reviewer they cover, `is_reviewer_of` with its live
states and active cover), the channels they write (employee, manager,
functional manager, HR), the year's window, the agreement waiting on the
reviewer, the distributed summary (now drawn by `allocations.SummaryBlocks`,
which My Targets shares), a card a priority and the values. The cards are
written as the template writes them and read by the feed's own rules,
ported to `feeddom.CardForm`: a card holding one form with little around it
is that form, anything else a panel whose forms are skipped, a lone label
before a figure a data row. The rating columns declare no choices, so a
stored rating shows as it is stored.

Handed on, never approximated: a reader the page refuses (it redirects), a
reader in an acting appointment, and in an open window a conversation its
snapshot froze, a measured priority (its live figures and milestones,
`live_progress`/`milestone_metrics`), an inherited priority carried under a
role rule, and a contract longer than one page. Golden
(perfconversation/testdata/golden.py, `gpcv` officers who sign in): 18
answers in the open window (2 handed on) and 4 with it shut, 0 differing.
The window labels and HR roles moved out of the view into constants the
exporter reads (`CONVERSATION_WINDOW_LABELS`, `CONVERSATION_HR_ROLES`).

Left in C7: the conversation's handed-on depth (snapshots, the live engine,
role-rule inheritance).

### C9 (part) · Report a Problem (2026-11-19)

`/support` is Go's (adminops/report.go) for every role that opens it: the
ticket form (its categories in their order, Medium urgency chosen) and the
reader's own twenty newest tickets, written as the template writes them and
read by the feed's own panel rules (`feeddom`). The save stays with the
existing application. The exporter writes who opens it and the categories
in order. Golden (adminops/testdata/report_golden.py, `garp` tickets): 8
answers of 4 readers, 0 differing.

`/uploads/new` is Go's too (uploadcenter/newdocument.go): New Policy or
Manual as the feed reads its one form (the document's details, the audience
by role, the acknowledgement it asks of readers, how it is delivered), and
with `?kind=training` New Training Resource (its two training types, no
acknowledgement). A reader without the kind's create permission is
redirected, which Go hands on; every save stays with the existing
application. 10 answers of 5 readers, 0 differing.

### C9 · The Knowledge Center's reading pages (2026-11-19)

`/help` and its reading pages are Go's (internal/helpcenter) for every role
the view's page permission lets read them: the home (the reader's own role
guide, the documentation areas, end-to-end workflows, common problems and,
for an Admin or staff account, the manual download), an article with its
meta, sections, walkthrough, related guides and feedback buttons (and the
role-guide, workflow, feature and Getting Started addresses that open one;
404 for no such article, 403 for one the role may not read), a category,
troubleshooting, the glossary with its search, release notes and search
(the synonyms, the match reason and the excerpt as services write them).
Each page carries the role-aware table of contents (knowledge_tree) and is
written as its template writes it, then read by the feed's own rules. Two
of those rules were missing from feeddom and now are: a `dl` of terms is a
facts block, and an `edify-surface rounded-surface` card is a panel of its
own (and a part holding one is read inside). Lists sort title ties as the
view's DISTINCT does: by slug in the contents, by the article's own columns
in a list.

Handed on, because the view writes on the read: the home and an article
while no article exists (the canonical content is installed), the home
while a published article is past its review date (it is marked) or no route
has its article (the routes are mapped), and search when a result has no
search document (it is rebuilt). Also handed on: the contextual help (its
route sync is timed by a cache Go cannot read), the print view, the exports,
the Help manager's pages, every save, and a reader the page permission
refuses (the refusal is audited). The exporter writes who opens the pages,
each role's guide, the role each guide address names, the synonyms and the
readable states. Golden (helpcenter/testdata/golden.py, a `gshc` guide open
to two roles with a walkthrough, a related guide and a glossary term, plus
the route mappings): 182 answers of 7 readers over 21 pages and 10 searches,
0 differing. The oracle cannot read a view's 404, so the not-found
addresses are not in it.

### C9 · The Policy Agreement Center (2026-11-19)

`/policy-agreement` is Go's (uploadcenter/agreement.go) for every signed-in
reader: each required policy waiting for their answer (its version,
effective and due dates, why it is required, Read and Download, the active
reading time against the minutes required with its completion, the
response form and the outside-the-viewer attestation), or "Nothing is
waiting for you", then their fifty newest completed answers. The audience
reader is shared with the Upload Center (audienceRules). Handed on: a
reading that would first give the reader a pending agreement
(ensure_pending_for writes one for each mandatory policy in force whose
audience holds them and that they have none of), and a reader with
Safeguarding or the Apostles' Creed pending, whom the view sends to that
document; every save stays with the existing application. Golden
(uploadcenter/testdata/agreement_golden.py, `gpag` policies and answers): 4
readers, 0 differing (two drawn, two handed on).

Left in C: `/today` (it waits for the To-Do rows to carry ids, part of E).

### C8 · The Business Transformation workspace (2026-11-19)

`/business-transformation` is Go's (btpages): the existing application
routes it and `/business-transformation/overview` to one view
(`workspace_page`), so Go answers both with the overview's builder under
each path's own door (the exporter now lists the workspace's). A golden over
both paths, eight readers and three filters (the seed's portfolio): 48
answers, 0 differing, now in the suite, which had no BT compare before.

`/policy-agreement/restricted` is Go's too (uploadcenter/restricted.go): the
page a reader who disagreed with a required policy lands on, in base.html's
own chrome (not the shell), with each policy in force that gates the
application and that they disagreed with, newest first (the model's
ordering), each card read by the feed's form rule (a short card is its
"Change my answer to Agree" form, with the policy's statement as a line;
a long one a panel). The save stays with the existing application. Golden
(uploadcenter/testdata/restricted_golden.py, `gprd` policies): 3 answers,
0 differing.

### Found on the way (2026-11-19): stale generated artefacts on this branch

Only Platform CI runs on `feature/edify-go-rn-migration`; Django's suite runs
on pull requests. Running `apps.system_health` here showed generated
artefacts that drifted on the branch before today, failing on its own base:
the KPI inventory (two Go rule exporters' zero-figure dicts read as tiles —
the scan now skips the exporters' tile dicts, keeping their payload groups,
and the manifest is rebuilt), the page inventory and the permission matrix
(not rebuilt here), and the payload-group ratchet (178 audited items, floor
180: something on the branch removed payload groups, to be judged before a
merge, not lowered blindly). Before any pull request to `main`, rebuild them
in the order the repository memory gives (page inventory first, traceability
last) and settle the ratchet.

