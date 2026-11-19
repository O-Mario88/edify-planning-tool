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

Still to do in C2: `/finance/fund-allocation`, the country scope of
`budget_workspace` (its activity cost plan and time views), which `budgetpage`
does not port.

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

Left in C6: `/settings/activity-catalogue/`.
Left in C5: `/ia/school-evidence/` and `/priorities/ssa-mapping`.

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

