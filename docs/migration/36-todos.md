# 36. The To-Do page, read by Go (first piece: the field officer's queue)

Owner brief "Final backend responsibility and language boundaries"
(2026-11-11): Go as the application backend. The To-Do page is every
reader's derived action queue (`apps.command_center.todo_service.get_todos`):
nothing is stored, each row is computed from the record it is about and goes
when the work is done.

The queue is built by 51 builders (32 in `_get_todos`, 19 in
`MODULE_TODO_BUILDERS`), each reading a different part of the application:
activities and their next action, fund requests, partner returns, Core plans,
loans, SSA, evidence, coaching, guidance, Professional Development, Field
Debriefs, HR, analytics and more. The 29 seed accounts alone reach 29 kinds of
row. The page therefore moves role by role, agreed with the coordinator
(2026-11-13):

| Piece | What moves | State |
|---|---|---|
| 1 | The page itself (header, Do next, strip, chips, grouping, the link gate, the sort and counts) and every builder the CCEO role reaches | This document |
| 2–5 | The builders the Programme Lead, Impact Assessment, Country Director and Admin, Project Coordinator and Business Transformation reach | Backlog `todos-pl`, `todos-ia`, `todos-cd-admin`, `todos-pc-bto` |
| — | Marking a To-Do done, and every action a row opens | Still the existing application's (backlog `todo-done`) |

## 36.1 Who Go answers

`PageScreenService.GetPage` is answered by `platform/backend/internal/todos`
for `/todos` when all of these hold, and passed to the existing application
otherwise:

1. the reader works in their own role (an acting reader is passed on, as on
   every page);
2. their role is one Go has built (`PortedRoles`, today the CCEO);
3. every builder the role reaches is one Go has (`Handled`);
4. none of those builders answers "pass on" for this reader (below).

A role the page refuses (the Cluster Leader) is not found, as the feed answers.

**Which builders a role reaches is not a hand list.** `manage.py
export_todos_rules` reads `_get_todos`' own `todos +=` lines (in order) and
`MODULE_TODO_BUILDERS`, then runs each builder as a principal of each role
with the database replaced by a tripwire (a `BaseException`, so a builder's
`except Exception` cannot hide it): a builder that reads anything for the role
is reached. The answer is in `rules.json` (`roles.<role>.builders`). A builder
added to the queue, or one that starts reading for a new role, changes the
export, `apps/command_center/test_todos_rules_export.py` fails until it is
exported again, and from then on Go passes that role on rather than answer
without it (`TestEveryBuilderGoHasIsOneOfTheQueues` holds the other
direction).

The CCEO reaches 22 builders. Go builds rows for fourteen of them and stands
guard for eight: a guard looks for the records its builder reads and, if the
reader has any, passes the reader on; without them the builder has nothing to
add, so Go's answer is complete.

| Builder | How Go answers it |
|---|---|
| `_activity_todos` | Built: the reader's live activities this FY (responsible, or monitoring partner delivery), newest first, 120 at most; `compute_next_action` over them with their advance requests read as the prefetch reads them (cost lines as they come back, each line's advances newest first); a row where the next action is the reader's to take or wait on |
| `_partner_delay_todos` | Built: partner work the reader monitors past its date and not handed in, ten |
| `_returned_assignment_todos` | Built: partner work handed back, undecided, newest return first, ten |
| `_project_ssa_todos` | Built: project enrolments the reader made with no baseline, and follow-ups whose window opened (statement shape kept: no order, as Django issues it) |
| `_extra_work_todos` | Built: open extra work, reviews waiting, overdue work the reader assigned |
| `_fund_request_todos` | Built for a reader who approves no fund requests: weekly requests to confirm or fix, returned monthly plans, disbursed funds to confirm. An approver (Programme Lead, Country Director) is passed on |
| `_school_quality_todos` | Built: own operating schools (or the scope when none) with no contact, no cluster, no SSA this year, eight of each |
| `_route_todos` | Built: coming visit days with weak location data, and the first that is not feasible |
| `_core_school_todos` | Built for the CCEO: per core plan (40, in table order, as Django issues the statement) its returned slots (two) and each kind's next unscheduled slot; twelve rows |
| `_business_transformation_todos` | Built for the CCEO: loan-use verifications to plan at the scope's schools |
| `collection_todos` | Built for the CCEO: SSA records returned to the reader, as one row due a week after the oldest return |
| `evidence_todos` | Built for the CCEO: delivered OneTest visits with no results, ten; evidence returned to the reader passes them on |
| `fy_planning_todos` | Built: the nearest future FY open for planning while nothing of the reader's is planned in it |
| `attendance_todos` | Built: the reader's clusters with schools that missed three or more delivered sessions in a row (`attendance_by_cluster`'s run of misses, newest first, equal days in the order the sessions came) |
| `_school_action_todos` | Guard: a school action handed to the reader (its row opens the route recorded with it, which Go cannot gate yet) |
| `_visit_request_todos` | Guard: a visit request waiting on the reader |
| `_my_target_todos` | Guard: an agreed annual-priorities review or a legacy monthly target (without either the focus list is empty) |
| `_pd_todos` | Guard: any Professional Development request |
| `_field_debrief_todos` | Guard: any live debrief, or a debrief action the reader owns |
| `follow_up_todos` | Guard: a Staff Activity follow-up sent to or by the reader |
| `coaching_todos`, `guidance_todos` | Guard: coaching or guidance addressed to the reader and not acknowledged |

`_partner_assignment_todos`, which the CCEO does not reach, is also Go's: it
reads the partner ids the scope resolves for the two partner roles only, so
those roles are passed on.

Two builders write while the page is read: `follow_up_todos` resolves
follow-ups the audit log shows were met, and `_my_target_todos` rebuilds the
reader's target ledger. Go writes nothing; a reader with a follow-up or a
target is passed on, so the existing application still does both for them.
For everyone else neither write has anything to do that the page reads. (The
page is already served from a short snapshot cache, `get_cached_todos`, so the
existing page itself skips both on a cache hit.)

## 36.2 The page

| Part | Existing rule it ports |
|---|---|
| The queue | `_get_todos`' end: a row whose link the role may not open (`can_open_url`) is dropped; the rest sorted by priority (`PRIORITY_ORDER`, unknown last) then due day (none last), a stable sort, so equal rows keep their builders' order |
| The header | "My work", "Action queue", the line under it, "N open", and "Do next: <first row>" opening its link |
| Do next | The first three rows (`mobile-home-section`), when there are any |
| The strip | Critical, Due today, Overdue, Waiting on me (actionable and not blocked) |
| The chips | Category: All Categories and every category with its count, by name; Priority: All, Critical, High, Medium, Low; the page opens on "all" |
| A row | Title, then its second line without the place the title already names (`todo_groups.context_line`), its icon's tone by category, its link (primary when actionable). The due column and priority pill are hidden on a phone, so the feed does not read them |
| Grouping | Three or more rows with the same title, category and priority are one entry where the first stood: "N · first three places and N more", the count, the rows inside (owner, 2026-09-30) |
| Nothing to do | "You're all caught up" and its sentence, under the strip |

The page's query is ignored, as the view ignores it.

Exported to `internal/todos/rules.json` by `manage.py export_todos_rules`
(drift test `apps/command_center/test_todos_rules_export.py`): each role's
door and builders, `can_open_url`'s answer for every link shape Go builds,
each category's icon tone (the row template rendered and read by the feed's
own reader), the priorities, `ACTIONABLE`, `WAITING`, `ACTION_META`,
`GROUP_MIN`, activity type labels, and every status list the built builders
filter on. Four status lists that were local to their functions are now
module constants in `todo_service` (`ACTIVITY_TODO_SETTLED_STATUSES`,
`WEEKLY_CONFIRM_STATUS` / `WEEKLY_RETURNED_STATUSES` /
`WEEKLY_APPROVER_STATUS`, `MONTHLY_RETURNED_STATUSES`,
`PARTNER_DELAY_SETTLED_STATUSES`); nothing they filter changed.

`compute_next_action`, `_act_priority` and `_act_status` are not restated as
a table: the export writes their answers over 3,900 activities
(`internal/todos/testdata/next_action_cases.json`: every status against every
delivery, evidence, date and ID state, and 1,500 fixed-seed samples over type,
participants, school SSA, verification, payment and advances), and
`TestNextActionIsTheExistingOne` holds Go's port to every one.

## 36.3 Proving it is the same

**All 29 seed accounts**, `cmd/parity -screen page -path /todos`, five
questions each (the page as it opens and four keys it does not read), against
a gateway with no existing application behind it. The run's last lines:

    coordinator@edify.org              5 questions, 5 differing

    145 answers compared, 45 differing

The twenty CCEOs: 100 answers, 0 differing (`cceo@edify.org` alone carries
56 rows: next actions, fund requests, partner delays and a return, 24
data-quality rows grouped, 12 Core slots, loan-use verifications). The 45
differing answers are the nine accounts of the roles Go does not build yet
(Admin, Business Transformation, Country Director, Impact Assessment, the four
Programme Leads, the Project Coordinator), every one of them answered
"unavailable: This screen is not available here yet": passed on, not
answered.

The same nine accounts against the gateway with the existing application
behind it (so the pass-on is followed through):

    coordinator@edify.org              5 questions, 0 differing

    45 answers compared, 3 differing

The three were the first question of pl2, pl3 and pl4, where the gateway's
call to the existing application timed out ("This screen could not be
loaded") while the Django suite ran on the same machine: the Programme Lead's
queue is slow on a cold snapshot cache. Those three accounts asked again
once it had finished:

    pl4@edify.org                      5 questions, 0 differing

    15 answers compared, 0 differing

**The kinds the seed lacks**, by a golden comparison in the agent's own
integration database (`edify_gorn_a20_test`). `agent20_todos_golden.py` (kept
in the session scratchpad) files 48 synthetic records for the seeded officer
through the models (ids `gtd…`, names "[Go parity check]"): activities at
every next action (returned, in progress, due today, begun, no ID, ready to
submit, waiting on IA, waiting on accounts, an SSA visit, partner evidence to
submit (dropped: the officer cannot open the partner's page), a partner
booking to prepare, a late partner visit with no school, two OneTest visits),
advances disbursed, reimbursed and with the lead, three cluster sessions with
a school absent from all, a returned weekly request and a disbursed one, a
returned monthly plan and a disbursed one, six pieces of extra work, two
project enrolments, two route days, a returned SSA, and an FY 2028 planning
year. It asks the unchanged feed (snapshot cache bypassed) as three officers,
two questions each, writes the rows as the database held them and the
answers, and removes every row. `TestTodosMatchTheExistingFeedOverSyntheticRecords`
(`EDIFY_TODOS_GOLDEN`) files the same rows (`json_populate_record`), asks Go
and compares whole messages; it is skipped on any day but the one it was made
on. It printed:

    todos_test.go:80: 6 answers of 3 accounts compared, 0 differing

**The page over synthetic queues.** `TestThePageIsTheExistingOneOverSyntheticQueues`
compares Go's page with the existing feed's for ten queues of up to 40 rows
(`testdata/page_golden.json`, made by `agent20_page_golden.py`: every builder
replaced by one handing back the rows, the rest the existing application's):
the empty state, every category's icon, unknown priorities, rows with no link
or a link the role may not open, places with spaces, quotes and markup, and
groups of two, three, five, twelve and interleaved.

`TestTodosPassAReaderOnWhenAGuardedRecordIsTheirs` files a school action for
the officer and finds the page passed on; the officer without one, and a
Programme Lead (passed on), are checked in the same test.

## 36.4 What is left

- The other roles' builders (36.1's backlog items). The guards are written
  wide (any PD request, any debrief): in production they will pass most
  officers on until those builders are Go's.
- A Core plan with a returned slot is in unit tests only (the integration
  database's officer holds no core school); its twelve open slots are proved
  on the development data.
- Two activities created at the same instant, or two plans read in a
  different physical order, have no order between them in either system.
- A builder that fails is swallowed by the existing queue ("one source never
  breaks the queue"); in Go the page fails.
- Marking a To-Do done, and every page a row opens, stays the existing
  application's.
