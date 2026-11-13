# 57. The To-Do page, read by Go (fourth piece: the Admin's queue)

Continues [36](36-todos.md) and [55](55-todos-pl.md). Go now answers the
Admin's `/todos` too (`PortedRoles` = CCEO, Programme Lead, Admin). The
Country Director's queue, the other half of backlog item `todos-cd-admin`,
is still passed to the existing application (backlog `todos-cd-admin-2`).

## 57.1 Who Go answers, and how

The Admin's queue runs 27 builders (`rules.json` `roles.Admin.builders`).
Twenty were already Go's for the officer and the lead and read the same way
for the Admin (activities, partner delays, project SSA, extra work, returned
assignments, own fund requests, school data quality — empty for a country
lens —, reviewer rows, the guards of school actions, visit requests,
completions waiting, invoices, leave, Professional Development, debriefs,
Staff Activity follow-ups). The rest:

| Builder | How Go answers the Admin |
|---|---|
| `_country_budget_todos` | Built, all three desks the Admin sits at (`COUNTRY_BUDGET_CD_ROLES`, `_RVP_ROLES`, `_ACCOUNTANT_ROLES`): "Review <month> General Budget" (this local month's budget in a review status, the lowest id, as `.first()`), "Fix Returned General Budget" (five newest months), "Fix Returned FY<fy> Work Plan" (three), "Approve Team Monthly Request" (ten newest), "Review General Budget" (submitted to the RVP), "Prepare Monthly Disbursement Queue" (approved), each with its link, priority, status and due day |
| `_cost_catalogue_todos` | Built: one "Set Missing Cost Catalogue Rates" row (blocked) while any scheduled, unsettled activity misses a rate |
| `partner_user_setup_todos` | Built: "Configure Partner Users", linked "<n> organisations" (the count read only from four up, as the builder does), for a role that may manage partner users (exported from `may_manage_partner_users`; any other role is passed on: a superuser of another role is offered the row) |
| `_business_transformation_todos` | Built for the Admin's one desk (`BT_VERIFICATION_SCHEDULING_ROLES`): "Schedule Loan-Use Verification" for every verification of a loan on a live school with no visit planned, thirty at most, soonest first, critical and overdue when late. A country-bound lens (the Country Director) is passed on: `school_in_country_q` is not ported here |
| `collection_todos` | The returned-records row as for an officer; the Admin's `_blocked_rows` is guarded: any SSA upload of the reader's passes them on |
| `attendance_todos` | No role gate any more: it reads only the reader's own clusters, for any role ("Planning" category outside the lead) |
| `_cd_flag_todos` | Guard: for any reader but a lead, any flag (the CD's and Admin's desk follows up every overdue open flag) |
| `_hr_exception_todos` | Guard (the "waiting on HR" group): any leave, any Professional Development request, a policy in `POLICY_AWAITING_PUBLICATION_STATUSES`, a probation review due |
| `_accountant_todos` | Guard: any request, advance or partner work at an Accountant's desk (`ACCOUNTANT_QUEUE_STATUSES`), or returned cash nobody verified |
| `_ia_todos` | Guard: the completions guard (`plReviewGuard`) already passes on any activity awaiting IA verification |
| `_escalation_todos` | Guard: any leadership escalation (as the lead's) |

Lifted to module constants (no behaviour change) and exported in a new
`admin` section of `rules.json`: `todo_service.ACCOUNTANT_QUEUE_STATUSES`,
`COUNTRY_BUDGET_*`, `COST_CATALOGUE_SETTLED_STATUSES`,
`BT_VERIFICATION_SCHEDULING_ROLES`, `hr_exceptions.POLICY_AWAITING_PUBLICATION_STATUSES`,
plus `PartnerUserSetupStatus.PENDING` and the roles `may_manage_partner_users`
lets in. Six link shapes were added to the `can_open_url` table
(`/country-budget`, `/budget`, `/disbursements`, `/cost-settings`,
`/work-plan?view=fy`, `/admin-panel/users#partner-directory-title`).

Found while comparing: the first Admin run was passed on by the
Accountant's guard, which first read every activity in `ia_verified`; both
of the Accountant's partner queues read `delivery_type = 'partner'` only,
and the seed's one `ia_verified` activity is staff work. The guard now reads
partner work only.

## 57.2 Proving it is the same

**All 29 seed accounts**, `cmd/parity -screen page -path /todos`, the five
questions of piece 1, against a gateway with no existing application behind
it (every answer Go's own). The run's last lines:

    pl4@edify.org                      5 questions, 0 differing
    coordinator@edify.org              5 questions, 5 differing

    145 answers compared, 25 differing

The Admin, the twenty CCEOs and pl2–pl4: 120 answers, 0 differing, all
built by Go. The Admin's queue on the seed: "Configure Partner Users"
(8 organisations), two "Schedule Loan-Use Verification" rows and "Review
2026-11 General Budget". The 25 differing answers are the five accounts Go
still passes on (Business Transformation, Country Director, Impact
Assessment, pl1, the Project Coordinator), each "unavailable: This screen is
not available here yet" (25 of 25). The same five through the gateway with
the existing application behind it:

    coordinator@edify.org              5 questions, 0 differing

    25 answers compared, 0 differing

(Those 25 answers came from the existing application, not from Go.)

**In the integration database**, `TestTodosAnswerTheAdminsQueue` finds Go's
answer for the Admin with the partner-logins row, files a budget returned by
the RVP, one submitted to the RVP, one approved, an FY work plan returned
(ids `gtad-…`) and marks one scheduled activity as missing its rate, and
finds the five rows; then a policy waiting on HR passes the Admin on. Every
row is removed and the activity restored.

What is not proved against the existing feed: the seed has only this
month's draft budget, so the returned, RVP, Accountant and team-request rows,
the cost catalogue row and an overdue loan verification are proved only by
the integration test and Go's own reading of the builder.

## 57.3 What is left (backlog `todos-cd-admin-2`)

- The Country Director: `_cd_analytics_todos`, `learning_todos`,
  `framework_todos`, `report_todos`, `_strategy_note_todos`, the CD's own
  desks of `_business_transformation_todos` (with `school_in_country_q`),
  `collection_todos`' fallback rows, escalated follow-ups, the escalation
  country filter and the weekly-approver half of `_fund_request_todos`.
- The guards above are wide (any leave, flag, escalation, Professional
  Development request): in production most Admins will be passed on until
  those builders are Go's.
