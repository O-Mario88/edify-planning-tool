# 40. My Plan, the rest (M4), read by Go, in pieces

Backlog item `my-plan-rest`: what 25-my-plan.md (25.5, 25.9 "What is
left") left of My Plan. It moves in pieces, each proved and committed on
its own; this file grows a section a piece.

| Piece | What moves | State |
|---|---|---|
| 3c | Work still to be delivered: its rows (Start Activity, a tick, the overdue tint), the day-off marks (holidays and approved leave) beside the planned day, the row's day-off tint, and the card "Reschedule — On a Public Holiday or Leave Day" | Done, 40.1 |
| 3d | The attention cards: Returned — Needs Correction, Waiting on Approval, Finance / Accountability Pending, over `compute_next_action` in full and the loop's urgency sections | Done, 40.1 |
| 3e | Trainings and Group Trainings (the cluster expansion into every school it reached), programme school rows from a session, My Training Summary | Done, 40.3 (a session reaching a Core School, and Core School Trainings rows, still passed) |
| 3f | Core package slots on My Plan (V/T numbers, "n/8 Completed", the Status select the slot loop overwrites), SSA visits awaiting scores in a table, a meeting delivering a training, programme activities, pagers | Not started |
| 4, 5, 6 | Planned and remaining over held schools, My Training Summary, Cluster Planning Status, the partner's page (25's table) | Not started |

## 40.1 Pieces 3c and 3d: work still to deliver, days off and the attention cards

Before this, a page listing any activity still waiting for its day, sent
back, handed in, verified by IA, with money disbursed or an advance waiting
on somebody was passed to the existing application. Go now draws all of
them, for every reader 25.9 already answers (no school held, no project
place). On the seed nothing changes for an account: the 28 accounts Go
answered before are still Go's, and `cceo@edify.org` is still passed (700
schools held; pieces 4 and 5).

| Part | Existing rule it ports |
|---|---|
| The day-off marks | `activities.day_off.day_off_marks` over the listed activities: only `AWAITING_DELIVERY` work; its days `activity_span` (the plan day, the planned date else the scheduled time's day in Nairobi, to the end date when that is later); a public holiday (`public_holidays_between`: the national calendar and recorded days, read through `internal/calendarpage`'s holiday book), or a day inside the responsible person's approved leave (either id; a pending request marks nothing). A day in a year the national calendar does not hold passes the page |
| The mark on a row | `day_off_flag.html` after the planned day, read by the feed as " <label>: reschedule" (the include opens on a line break: one space); the row's tone `dayoff` unless done or overdue (`_row_tone`) |
| The card | `attention.html`'s first card, in the loop's order (the rows of every table and of none): School ID (`{% school_code %}`, a token the feed reads as nothing, "—" without one), the place (the school by its School ID, a name with no School ID plain, a cluster, else "General"), Type, Day Off (`DayOffMark.summary`: "Mon 16 Nov · Public holiday", "+n more"), Reschedule for staff delivery (any other delivery's "The partner reschedules" is not read); a tick for a row in a table only; past 50 rows passed |
| `compute_next_action` | every branch for work not a partner's (the staff plan lists no partner delivery; one would be passed): owner approval, sent back, due today, in progress, begun with nothing in, the Salesforce ID, Submit (with people for the types that need them), an SSA to upload (`SSA_UPLOAD_TYPES` and the school's `current_fy_ssa_status`), with IA, accounts clearance, and branch 9 over the activity's advances (cost lines in table order, each line's newest first); two of the last loop's three states on one activity pass the page (which comes first is the table's order). A visit awaiting its SSA scores in no table takes `enter_scores_action` and an amber pill |
| Returned — Needs Correction | sent-back statuses; Returned By (`return_notes.RETURNED_BY`), the reason `"<pl_review_note stripped>"` else "Correction required", Fix Now at the action's address |
| Waiting on Approval | the loop's urgency sections in order (sent back, a partner's, `WAITING_ON_ME_ACTIONS`, due today and the next seven days for `_DATED_AND_OPEN`), then `awaits_approval` (handed in; else a `view_status` action on work not approved, or approved with a payment or an advance waiting on the Lead or the Accountant); planned and completed days `M j, D`, the Salesforce ID ("Not in SF" for a row in no table: the completion columns are written only on table rows), and `row_badges.html` (one pill is a badge of its tone, several are their words) |
| Finance / Accountability Pending | `FINANCE_PENDING_PAYMENT_STATUSES`; the payment state as a pill, the next action's words and description (another delivery's "Monitoring — partner-owned") |
| Submit for Review | the row menu's Submit now reads the ported `compute_next_action` (`nextIsSubmit` is gone) |

Three literals were lifted to module constants with no change in
behaviour: `services.SSA_UPLOAD_TYPES`, `WAITING_ON_ME_ACTIONS`,
`FINANCE_PENDING_PAYMENT_STATUSES`; they, `_DATED_AND_OPEN`,
`return_notes.RETURNED_BY` and `visit_scores.ENTER_SSA_TEXT` are exported
to `internal/myplan/rules.json` (`tables`, `rows`). The day-off marks are
read through a new exported wrapper, `calendarpage.DayOffMarks`
(`internal/calendarpage/export_myplan.go`).

Still passed, for a row: a partner's delivery, an SSA visit awaiting scores
in a table, a meeting delivering a training, a meeting at no cluster, a Core
package slot, a training, programme work; a card or table past one page.

### Proving it

**Against the existing feed, for records the seed does not hold.**
`internal/myplan/testdata/plan_tables_golden.py` (25.9's) now also files a
recorded public holiday three days out, approved leave for the officer (with
a cover) and the Lead, a pending request for the third person, end dates,
the states still to deliver and sent back or handed in (planned,
rescheduled, scheduled, returned, returned by IA, awaiting IA verification,
IA verified), reviewers' notes (padded, empty), payments in seven states,
advances in eight (NetSuite codes in and out), schools with and without the
year's SSA and an SSA collection type, and five narrower queries. It now
runs on an agent's own copy of the test database (`edify_gorn_aNN_test`, the
guard widened in both golden scripts). The last run:

```
plan_tables_golden_test.go:139: 220 pages compared (200 rows of the plan's tables), 0 differing; 108 passed to the existing application
```

Those pages held 82 Finance rows, 39 Returned rows, 14 Waiting on Approval
rows and 23 day-off card rows (22 on the holiday, one "On leave +1 more"),
20 table rows tinted `dayoff`. The first run found the one space between the
planned day and its mark, the second the "Partner" execution role of work
with a blank delivery (no Reschedule on the card, "Monitoring —
partner-owned" on Finance) and the SSA visit in no table whose action is
"Enter SSA Scores" (it kept a row off Waiting on Approval).

**Against the existing feed, the seed accounts.** The 67 questions of
25.4, on a gateway with no existing application behind it, my own Django
(8125) as the existing feed. The run of all 29 was cut by a PostgreSQL
outage on the development machine (13:05–13:10, not this work's) after 24
accounts; its own last lines:

```
1608 answers compared, 65 differing
1235 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

The 65 are `cceo@edify.org`'s pages, passed by Go (700 schools held) and
answered "This screen is not available here yet" by a gateway with nothing
behind it (its two `format` refusals equal); the other 23 accounts are 0
differing. The five the outage stopped (pl1–4, coordinator), re-run on
restarted servers:

```
335 answers compared, 0 differing
260 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

So 28 accounts are 0 differing and `cceo@` is still passed, as before this
piece: the seed has no account whose page this piece newly opens (its
work to deliver, returns and payments are all `cceo@`'s). The lift of the
three constants was checked by dumping `cceo@`'s feed (as it opens and FY
2026, with its Returned card) with the old and the new `services.py`:
identical.

Not re-run: the Core sheets golden of 25.8 (`coreRows` does not read the
changed `readExtras`) and the counts golden of 25.6 (`ReadPlan` unchanged).

Unit tests: `dayoff_test.go` (the flag, the tint under done and overdue, the
card's cells, tick and actions), `cards_test.go` (every branch of
`compute_next_action`, the two-states pass, the Waiting card's sections and
`awaits_approval`, the badge strip, the reason), `plantables_test.go`'s
passes and Submit cases on the ported function. Integration
(`my_plan_test.go`): `TestMyPlanCountsClosedWorkAndDrawsWorkStillToDeliver`
now files an undated scheduled visit and a visit sent back by the Lead and
expects Start Activity on the one and the Returned card's Fix Now on the
other (it used to expect the undated visit's page passed).

Grants added (`platform/deploy/db/roles.sql`, applied additively to
`edify_gorn_dev` and `edify_gorn_a25_test`): `activity.pl_review_note`,
`advance_request (created_at, reimbursement_receipt_confirmed_at,
accountability_netsuite_id)` (the development database already had the
last three from another branch).

## 40.3 Piece 3e: Trainings, Group Trainings and My Training Summary

Before this, a reader who owned or monitored any training (or a cluster
meeting delivering one), whatever its year or state, was passed whole:
their page carries My Training Summary. Go now draws the trainings and the
summary for every reader 25.9 answers otherwise (no school held, no cluster
led, no open hand-over, no training ceiling, not a partner).

| Part | Existing rule it ports |
|---|---|
| Which table | The loop's `MY_PLAN_TRAINING_TYPES` branch: a training not at a Core or programme school is on Trainings (a programme school's on its section, as before) |
| The cluster expansion | `get_frontend_context`'s invited-school expansion (`expandSessions`, generalised from the Core sheets' `expandClusters`): a session (at a cluster, no School ID) is copied once to Group Trainings, then replaced on Trainings by one row a school it reached: the schools invited or attended (`ClusterActivityAttendance`, by school name), else, when no invitation was ever recorded, the cluster's confirmed members (clustered and operating), else every live member; the school's School ID (else its key), name, district ("Unknown" without one), `/schools/<School ID>`, "Invited"; heads per school (`participants_per_school`, `teachers_per_school`, else the total over the schools, at least 1; an invitation's own composition wins); cost = heads × the session's meal rate (its snapshot, else the catalogue), 0 online, none without heads. A session that reached no school is one row named by its cluster. A programme school's row moves to its section, with `place_url` the school |
| What a session's own row is | On the cards only, no tick and no completion columns (the copies are the table rows) |
| Trainings cells | `cluster_trainings.html`: School / Cluster (place link, else School ID link, else the cluster's name), District (`plan_row_district`, the reached school's first), Cluster Planned From ("<cluster> Invited", "School Visit" for an in-school type — the row carries no `delivery_type`, so only the type decides — else the cluster), Training Name or "Not yet named", Mode of Delivery, Participants ("—" for none or 0), Cost with the in-school pair's note |
| Group Trainings cells | `group_trainings.html`: the cluster, its district, `{% firstof training_name activity_name purpose "Group Training" %}` (`activity_name_snapshot` read beside the row) |
| My Training Summary | `my_summary.html` over `training_ceilings.own_summary`, read through `internal/trainingsummary` (`OwnSummary`, its `summaryForStaff`): the heading panel (its figure line is a definition list the feed does not read), the table (each figure linked to `/training-summary/schools?…&figure=`, 0 plain; Awaiting Partner warning, Excess danger, Remaining "View" without a ceiling, Utilization `round()` half-even, Status in the flag's tone) and the note; after Planned and remaining, for planners and others alike; past 50 rows passed |
| The past-due note | Since `agent/web-fixes-3` the feed reads `kpi_cards.html`'s note as a warning item with its words and link ("n planned activit(y is/ies are) past (its/their) date …"); `pastDueNote` drew only the link and was brought up to date |

The summary lives in `internal/trainingsummary`, which already reads this
package, so it is given to the service (`Service.WithTrainingSummary`,
wired in `server.go`); without one a reader with a training is passed as
before. `agent/training-summary-2` (unmerged) was merged into this branch
first, for its `summaryForStaff`.

Still passed: a session reaching a Core School, and a Core School's own
training (Core School Trainings rows, with the slot T-numbers: 3f), an SSA
collection training awaiting scores, a training meeting, and pages whose
trainings or summary exceed one page.

### Proving it

**Against the existing feed, for records the seed does not hold.**
`internal/myplan/testdata/trainings_golden.py` (ids `g57…`, on
`edify_gorn_a23_test`) files three people, four clusters (one holding a
Core School), schools of every type, standing and district (blank School ID,
no district, closed, unclustered, one deleted), 150 trainings of every kind
at a cluster, a school or nowhere, in thirteen states, with names, courses,
online and in-person delivery, head counts and meal snapshots, and for the
sessions named invitations (with and without composition, guests from other
clusters), invitations recorded with nobody invited, and none; then asks the
feed for 38 queries per person. The same test as 40.1 compares:

```
plan_tables_golden_test.go:139: 103 pages compared (815 rows of the plan's tables), 0 differing; 11 passed to the existing application
```

Those rows: 488 Trainings, 149 Group Trainings, 178 programme section rows
(87 Champion, 75 Core Graduate, 16 Core Trained), 474 ticked. The 11 passed
are pages with a session at the Core School's cluster. The first runs found
the Cluster Planned From's `delivery_type` (absent from the row) and the
past-due note.

The earlier goldens, re-made and re-run on the same database after the
change: 40.1's `220 pages compared (200 rows of the plan's tables), 0
differing; 108 passed to the existing application` and 25.8's Core sheets
`78 sheets (589 rows) compared, 0 differing` (the expansion they read was
generalised).

**Against the existing feed, the seed accounts.** The 67 questions of
25.4 for all 29 accounts, a gateway with no existing application behind it
(8085), my own Django (8185) as the existing feed:

```
1943 answers compared, 65 differing
1495 answers held rows with the same name, compared in School ID order (the existing page gives them none)
```

The 65 are all `cceo@edify.org`'s, still passed by Go (700 schools held:
pieces 4 and 5) and answered "not available here yet" by the Go-only
gateway; the other 28 accounts are 0 differing. The seed has no account
this piece newly opens (its trainings are `cceo@`'s and a partner's).

Unit tests: `trainings_test.go` (the place and Planned From cells, the
Group Training name, the summary's cells and links, the past-due words),
`plantables_test.go` (the tables a training lands on). Integration:
`TestMyPlanDrawsAGroupTrainingOnceAndOnceASchoolItReached` files a
cluster training for `ia@edify.org` at a cluster without a Core School and
expects one Group Trainings row and one Trainings row a member reached.

## 40.2 What is left

Appended to the backlog as `my-plan-rest-2` (3e done, 40.3; what remains
is `my-plan-rest-3`): Core School Trainings rows (a session reaching a Core
School, a Core School's own training), 3f (Core package slots on My Plan, SSA visits awaiting
scores in a table, meetings delivering a training, programme activities,
pagers), and pieces 4 to 6. `cceo@edify.org` needs 3e, 3f, 4 and 5 before
its page is Go's.
