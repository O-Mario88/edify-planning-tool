# 55. The To-Do page, read by Go (second piece: the Programme Lead's queue)

Continues [36](36-todos.md). The page itself, its sort, grouping, link gate
and the field officer's builders are Go's since piece 1. This piece makes Go
answer the Programme Lead (`Program Lead`) too, for every lead whose queue
needs nothing Go has not built; anyone else is still passed to the existing
application.

## 55.1 Who Go answers

`PortedRoles` is now the CCEO and the Programme Lead. The lead's queue runs
35 builders (`rules.json` `roles["Program Lead"].builders`, exported by
`manage.py export_todos_rules`): the officer's 22 and thirteen more. Each is
built, or a guard that passes the lead on when they have the records it
reads. Guards are written wide (a superset of what the builder could show),
so a lead Go answers is answered completely; a lead a guard trips is answered
by the existing application.

| Builder | How Go answers a Programme Lead |
|---|---|
| `coaching_todos` | Built: "Hold <Month> one-to-one with <officer>" for each officer on the team (`hr.team_roster.team_members`: direct and covered supervisees holding the CCEO role, by name) with no one-to-one dated this month, from the tenth (`ONE_TO_ONE_DUE_DAY`), eight at most; high from the 20th; due the month's last day. Coaching the lead wrote (drafts to share, follow-ups due) and any Regional Lead engagement pass the lead on |
| `reviewer_todos` | Built over `performance_engine.team_review_rows`: reviewees (supervisees whose active role the lead reviews, `REVIEWER_ROLE_FOR`, by name), the year's reviews by due date then creation, the cycle's window (`PerformanceCycle.first()`, by id). "Review <name>'s priorities" when the agreement waits on the reviewer (overdue when it is itself late), "Complete <name>'s overdue performance review" for every other review past its date, not finished (`REVIEW_DONE_STAGES`) or closed (`REVIEW_CLOSED_STATUSES`). An open conversation window over an agreed review (`hold_needed`, which reads `conversation_progress`) passes the lead on |
| `_fund_request_todos` | Built as for an officer, after a guard: any weekly request at the lead's approval step (`WEEKLY_APPROVER_STATUS`) or any accountability or claim waiting on a lead (`ADVANCE_APPROVER_PENDING_STATUSES`) passes the lead on |
| `_core_school_todos` | Guard: the lead's own schools, or any school assigned to the team |
| `_business_transformation_todos` | Guard: the lead's own schools (a lead's loan visits are their own schools') |
| `collection_todos` | Built as for an officer (returned SSA records), after a guard: a pending SSA record the lead may read (`readable_records`: a country or region lens, or the scope's schools) |
| `evidence_todos`, `fy_planning_todos` | Built as for an officer: the lead is one of `FIELD_ROLES` / `PLANNER_ROLES`, read the same way |
| `attendance_todos` | Built as for an officer, the row filed under "Programme Implementation" |
| `_pl_analytics_todos` | Guard: any school or a country/region lens in the scope (schools without SSA, weak clusters), any school assigned to a supervised officer, or a supervised officer with four or more pieces of work in `CCEO_BACKLOG_STATUSES` this year (an officer without schools reaches High risk only so) |
| `missing_training_todos` | Guard: any school or a country/region lens in the scope |
| `_team_target_todos` | Guard: a catch-up plan sent to the lead, a supervisee with targets (an agreed priorities review or a monthly target), or five completed staff activities of the team this year without a Salesforce ID |
| `guidance_todos` | Guard: guidance the lead wrote |
| `_pl_review_todos` | Guard: any completion at a lead's step (`LEAD_REVIEWABLE_STATUSES`) |
| `_cd_flag_todos` | Guard: a flag assigned to the lead |
| `partner_engagement_todos` | Guard: an engagement the lead wrote, any Regional Lead engagement, a flag assigned to the lead |
| `_cce_leadership_todos` | Guard: any Regional Lead engagement |
| `_partner_invoice_todos`, `_leave_todos`, `pl_escalation_todos` | Guard: any partner invoice, leave request, leadership escalation |
| `distribution_todos` | Guard: a milestone allocated to the lead's team |
| `followup_todos` | Guard: a Planning Oversight follow-up addressed to the lead |

The officer's other builders (activities, partner delays and returns,
project SSA, extra work, data quality, routes, the guards of piece 1) read
the same way for a lead; `_school_quality_todos` and `_route_todos` already
had the lead's branch. Where a builder reads the operational year through
the local day and another through UTC, a guard asks about both.

Lifted to module constants (no behaviour change), and exported:
`todo_service.ADVANCE_APPROVER_PENDING_STATUSES`,
`performance_engine.REVIEW_CLOSED_STATUSES`,
`pl_analytics_service.CCEO_BACKLOG_STATUSES`. The new `lead` section of
`rules.json` also carries `REVIEWER_ROLE_FOR`, the review stages and
windows, the coaching category, row limit, kind and due day,
`LEAD_REVIEWABLE_STATUSES`, both modules' completed statuses and the SSA
pending status; two link shapes were added to the `can_open_url` table.

## 55.2 Proving it is the same

**All 29 seed accounts**, `cmd/parity -screen page -path /todos`, the five
questions of piece 1, against a gateway with no existing application behind
it (every answer Go's own). The run's last lines:

    pl4@edify.org                      5 questions, 0 differing
    coordinator@edify.org              5 questions, 5 differing

    145 answers compared, 30 differing

The twenty CCEOs and pl2, pl3 and pl4: 115 answers, 0 differing, all built
by Go (each of the three leads carries ten rows: five one-to-ones still to
hold this November and five overdue performance reviews). The 30 differing
answers are the six accounts Go passes on (Admin, Business Transformation,
Country Director, Impact Assessment, the Project Coordinator, and pl1, whose
portfolio trips `_pl_analytics_todos`' guard), each "unavailable: This
screen is not available here yet". The same six through the gateway with the
existing application behind it:

    coordinator@edify.org              5 questions, 0 differing

    30 answers compared, 0 differing

**In the integration database**, `TestTodosAnswerAProgrammeLeadsQueue`
(pl2, whose team holds no reviews there) finds Go's answer with the
one-to-one row of the first officer by name from the tenth, files a review
three days late and a one-to-one held today by someone else (ids `gtpl-…`,
"[Go parity check]"), finds the overdue review and no one-to-one row for that
officer, then makes the coaching the lead's own and finds the lead passed
on; the rows are removed. `TestReviewerRowsAreTheExistingOnes` holds the
rules the seed cannot reach: an agreement waiting and late (one row, marked
overdue, not raised twice), waiting and not late, finished and closed reviews,
an undated review, an open conversation window (passed on), a reviewee with
no name ("None", as Python prints it).

What is not proved against the existing feed: the one-to-one rows on a day
before the tenth or after the 20th, and a one-to-one held this month, appear
only in Go's own tests; the guards' records are absent from the seed.

## 55.3 What is left (backlog `todos-pl-2`)

- The lead with a portfolio (pl1 in the seed): `_pl_analytics_todos`
  (`PLAnalyticsService.pl_todos`: schools without SSA, `cluster_performance`
  under 5.0, `cceo_performance` risk with `_cceo_targets_bulk`),
  `_team_core_school_todos`, `collection_todos`' lead rows
  (`verifiable_records`), `missing_training_todos` (`training_coverage`).
- The approver half of `_fund_request_todos`, coaching drafts and
  follow-ups, the conversation a window asks for (`conversation_progress`),
  and the guarded builders above: the seed has none of their records, so each
  needs a golden comparison on synthetic rows.
- The guards are wide (any leave, any invoice, any escalation, any Regional
  Lead engagement): in production most leads will be passed on until those
  builders are Go's.
