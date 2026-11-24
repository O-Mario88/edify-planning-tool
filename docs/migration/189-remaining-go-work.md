# 189 · Remaining Go migration work (measured 2026-11-23)

Measured by comparing what each of the 16 roles can open with Django running and with a Go-only gateway and Django stopped, on private development copies. A gap is something that opens with Django and not without it.

| Surface | Works without Django | Remaining |
|---|---|---|
| Default page views (role and page) | 903 of 915 (98.7%) | `/cpd-learning`, `/fund-requests/weekly`, `/loans`, `/team-planning-oversight` |
| Forms linked from those pages (role and form Django really opens) | 25 of 63 (39.7%), measured before the field forms below | This samples 12 forms. The inventory has 58, listed below |
| Detail pages with record ids, tabs and filters | Not measured yet | Next measurement |
| Saves, one by one | Not measured yet | Each proved against Django before cutover |

`188-uganda-cutover-disposition.json` records this migration as complete. These measurements do not support that, and it must not be used to switch Django off.

### Forms that now open from Go

Each was compared with Django for all 16 roles on private copies: same fields, options, wording and refusals. Opening a form is not its save. Every save below still goes to Django.

| Form | Compared | Result |
|---|---|---|
| The five export option forms | 160 role and URL checks | 64 identical, 96 same refusal |
| `/core-schools/strategy-playbook`, `/my-professional-development/allocation-history` | 32 | 15 identical, 17 same refusal |
| `/partners/<id>/members/drawer` | 48 | 30 identical, 3 same refusal, 15 same not found |
| `/projects/create` | 16 | 4 identical, 12 same refusal |
| `/work-plan/add` | 32 | 14 identical, 18 same refusal |
| `/extra-work/assign-drawer` | 32 | 10 identical, 22 same refusal |
| `/pl/review-queue/<id>/return-drawer` | 256, over 16 staged rule cases | 48 identical, 208 same refusal |
| `/pl/review-queue/<id>/drawer` | 272, over the same cases, a missing record and an uploaded form | 49 identical, 221 same refusal, 2 deliberate |
| `/projects/capacity/set`, `/projects/capacity/withdraw` | 224, then 176 over staged block, holder and allocated cases | 36 identical, 158 same refusal, 30 same not found; then 36, 113, 27 |
| `/projects/monitoring/school` | 224 | 48 identical, 140 same refusal, 36 same not found. Only a school with nothing planned: a project with work answers "not available here yet" |
| `/schools/<id>/assign-to-project` | 119 (17 accounts, 7 staged cases) | All same. Core, client, held elsewhere, unheld, enrolled and missing schools, with full, managed and team allocations. A 403's wording differs on purpose: Django's feed says only "Something went wrong" |
| `/partners/create` | 16 | 3 same form, 13 same refusal. Its tick lists are compared with Django's catalogue groups, not its phone reader |
| `/core-schools/schedule-activity`, `/schedule-visit`, `/schedule-training`, `/assign-partner` | 884 (17 accounts, 13 staged schools) | 209 same form, 652 same refusal, 23 same not found. Compared with the data Django gives its templates, because the feed's reader drops their conditional fields and buttons |
| `/planning/schedule-modal` (Schedule Visit, through `GetPlanningDrawer`) | 476 (17 accounts, 14 staged schools, two planning-year setups) | 168 same form, 294 same refusal, 14 same not found. Compared field for field with the drawer Django's reader produces |

The 2 deliberate differences on the Verify form are one fact seen by two roles: Go keeps the line break in a multi-line Observations value, which the mobile feed's reader runs together.

`/partners/create` differs on purpose in one way. The feed's reader loses every intervention's name and repeats one field name per group, so Go draws one labelled intervention list and one activity list, each activity naming its interventions.

The Core forms' staged cases were a package not yet made for the year, taken and complete slots, a closed school, a school with no SSA this year, full staff and partner halves, a completed training, a project enrolment, a partner with recorded courses, client and Champion schools, and a missing school. Opening them wrote nothing: the staged data was restored to an identical fingerprint. The comparison found and fixed one fault in Go's shared visit rule: a Champion school's visit and SSA hand-overs were not refused with Django's sentence.

Three things differ from the Django page on purpose. The Assign form asks for the partner before the training, because the list of trainings depends on the partner. The training ceiling counter is not drawn in these forms; the save must enforce the ceiling. A selected training's details are shown as text lines for that training.

### Field forms still to port

- `/activities/<id>/evidence` needs a new capability. No client drawer has a file field and Go has no upload, page-joining or stored-file path. An upload form must not be drawn until those exist.
- `GetPlanningDrawer`'s `assign`, `group-training` and `cluster-meeting` kinds are still placeholders in `getPlanningDrawerInGo`. They offer invented purposes and focus areas and every partner, including held and loan partners. They must be rebuilt as `schedule` now is.

The Core Schools visit, training and partner hand-over forms now save in Go when Django is absent. While Django is present it keeps these saves, because the forms have no form-only door.

- **Against Django (Go's writes, Django's pricing):** the visit form matched on 25 saves, the training form on 17 (13 made by Go) and the hand-over on 29 (21 made by Go). Every changed business table matched.
- **With Django stopped:** 69 saves across the three forms were replayed on a Go-only gateway, using Go's own pricing. All 59 answered saves matched, 33 of them writing rows; 4 refusals are still handed on, and 6 steps never reached a form. `activity`, `partner_assignment`, `core_activity_slot`, `core_plan`, `daily_visit_batch` and `activity_schedule_cost_line` are identical, and the planned cost is the same (UGX 620,000).
- **Costing bugs that replay found, now fixed:** Go's Django-off day settlement counted every activity as a visit in the day's School Visit allocation, stamped every budget line `day_pool` instead of `transport`, `lunch` and so on, left package slots at the wrong status, and wrote a differently shaped cost audit row.
- **Still handed on:** a second partner at a school, a facilitated training, a loan or held partner, a partner purpose the form does not offer, and everything the Schedule Visit list below names.

**The money follow-up now runs in Go with Django absent.** When Go settles a priced day, it writes the transport company's obligation and each staff advance in the same transaction as the day's costs. When the costs-to-follow row ends, it rebuilds each owner's weekly request and monthly draft once, and writes a move's audit trail on the budget lines. Every write goes through the narrow functions in `deploy/db/day_money_roles.sql`, so the gateway holds no direct write on a money table.

- **Proved with Django stopped:** the 69 Core saves made the same 21 advances, 5 weekly requests (21 lines), 3 monthly drafts (21 items) and 10 transport payments as Django, with identical amounts. A 15-save run of schedules, moves (same day, same week, another week, another month, twice) and cancels also matched on every money table and every budget line.
- **Refusals, checked on a private copy:** a confirmed or disbursed advance, a submitted week, a submitted month and a paid transport day each refuse in Django's words. Rebuilding a week twice gives the same lines.
- **Fixed on the way:** Go's list of statuses that draw no money now includes `rejected` and `awaiting_owner_approval`. A `draft` weekly request no longer counts as rebuildable. A re-priced line keeps Finance's hotel booking, and the facilitator's partner sits on the fee line only.
- **Monthly carry-along (2026-11-24):** a monthly request other than the owner's own draft now follows the plan in Go. A planner's own change (a move, a group action) passes a request in its approval chain. That request's lines are repointed at the re-priced costs and its total follows; an audit row records it, and the preparer and any approver are told when the total moves. A save that is no planner's change (a new visit or a single cancel) is refused in Django's words, judged on the day as the save will leave it. Proved with Django stopped over staged requests sent to the PL, approved by the PL and returned: request totals, items, audit rows and notices (including the two-person one) match Django.
- **Weekly take-back (2026-11-24):** a move into or out of a week whose request was sent and not paid (with the PL or CD, with the accountant, or set to No Advance) now takes that request back to its owner in Go, inside the move's transaction, instead of refusing or handing the move on. Its advances go back to pending unless their money has moved. The owner's days in that week that are priced for a split that no longer holds are re-priced. The owner is told, and so is whoever had the request on their list. A week frozen for any other reason (paid, disbursed) still refuses in Django's words. Proved with Django stopped: weekly statuses and totals, advances, the withdrawn request and all five notices match. Not yet in Go: a group move that would take a week back is handed on, and Edit's take-back (Go's Edit changes no date or cost).
- **Visit request decisions (2026-11-24):** a school owner's approve and decline on `/planning/visit-requests` save in Go with Django absent. Approval runs the school's client rule, puts the visit on the requester's day, and prices it with its money. Decline needs a reason and hands a Core slot back. Both close the owner's request notice and tell the requester. Proved with Django stopped on four requests (two approvals, a decline, a decline with no reason): every business and money table matches. Handed on: requests at Core schools, partner work, multi-day work, a visit paired with a training, and roles without the page.
- **Start activity (2026-11-24):** an officer starting their own staff school visit saves in Go with Django absent: the status, the first start's moment and the `start_activity` audit row. Starting work already started refuses in Django's words. Proved with Django stopped. Handed on: Core schools, partner work, someone else's visit, and other roles.
- **Integration tests:** the visit test's cleanup now removes the money its days create; before, it left rows that broke its next run. The IA verify test now picks an activity with a Salesforce ID, which verifying may legally close.
- **Still not written by Go:** route recommendation rows, and the snapshot's `calculation_inputs`, `warnings` and reference cost. Cost Review reads the inputs.

**Before deploying this code, run `apply-roles.sh`.** It adds `day_money_roles.sql`. That file creates new database objects, so production needs the owner's approval at cutover.

**Schedule Visit.** Its staged cases were a used visit in one or both open years, a universal training, a partner holding the school, two partners, partner plans, no verified SSA, an all-Strong SSA, a stale SSA, existing plans, a completed training, a closed school, Core, Champion and a missing school. Opening it writes nothing. One difference is deliberate: the Programme Accountant opens the form with its approval request, as on Django's web page. Django's mobile feed refuses that role at its `school_profile` gate.

**The Schedule Visit save is in Go for every ordinary case.** It covers a named or prefilled focus; visits at someone else's school by the five visit roles; a school a colleague holds, filed on their plan with their notice; Training Follow Up with or without a source session; the governed Business Transformation items a follow-up can be pinned to, including an item's first catalogue version; In-school Training, including at a colleague's school and at Core schools; Accountant visit and training requests; and Core school visits, with their package slots and the two-staff limit.

Proof, on private copies only:

- Each case ran through Django on one copy and Go on another, then every changed table was compared. The only differences are the `user` presence fields and `document_acknowledgement`, because the harness signs people in on Django's side only.
- All 151 staged saves were then replayed together on a Go-only gateway with Django stopped, using Go's own pricing. All 151 answers matched, all 92 saved activities matched on 17 compared fields, the total cost matched (972,811), the 26 Core slots and 32 notices matched, and the audit chain verifies.

Still handed on, so with Django absent they answer "not available" and write nothing: someone working in an acting appointment; a school with no assigned owner; a Core school whose package for the year is not made yet, is not active, or has no free slot; catalogue items priced per participant or counted through an eligibility rule; a training with a ceiling set, a course with several mappings, or a profile with no version; a follow-up whose school has no SSA and borrows the session's; a source activity on work that is not a follow-up; a day that does not pool. The saved scenarios for the first ordinary cases are in `cmd/shadow/scenarios/schedule_visit_focus.json`.

With Django absent, `SavePlanningDrawer` and `SaveDrawer` now make the person's presence stamp themselves (doc 65), since no form-only post reaches Django's middleware.

**Before deploying this code, run `apply-roles.sh`.** The Core and Schedule Visit forms read `activity_catalogue_item.certified_agency_delivery_allowed` (`roles.sql`), and the save now needs its new grants in `activities_roles.sql`: the follow-up link, catalogue versions, and the Core package's plans and slots.

The review rule (`plreview.Reviewable`) now matches `_check_reviewable` and serves both forms and Go's approve and return saves. Seven disallowed saves were tried against the Go-only gateway (Country Director, Impact Assessment, partner work, another team's work) and all were refused with no record changed.

Found while porting, to fix before these saves are used without Django:

- **Go's approve and return save now makes every decision itself** (`.do/uganda-go-staging.yaml` turns it on as `pl_review`). It writes the decision, ticked reasons, notices, audit rows, follow-on events, ledger marks, milestone credit and revival, period targets, the visit's SSA confirmation, the school's readiness and data quality issues, the Core package, SSA recommendations, the loan-use link and phone copies.
- **Proof.** 21 decisions ran through Django's views and through Go on identical private copies. All 14 business tables matched row for row. The 47 `outbox_event` rows match once the moment and generated notification id in their keys are set aside. The other two differing tables are Django's bookkeeping for the test sign-in (`user`, `document_acknowledgement`). Targets, credits, loans and recommendations were staged, because the development data has none.
- **What still needs Django's worker.** The decision raises durable events for Business Transformation, project impact, SSA recommendation generation, baseline capture, Salesforce sync and phone delivery. Only the existing application's outbox worker processes them. With Django fully stopped they wait safely and nothing is lost, but those follow-ups do not run until their handlers move to Go.
- **Small known differences.** Django also advances the cached analytics revision after each save. Go does not, so cached analytics can lag by up to five minutes. When two rules on one milestone both match, Go takes the oldest; Django's query names no order.
- **Before deploying this code, run `apply-roles.sh`.** It adds the functions and grants the save needs. Without them the save fails and writes nothing.
- The Verify form names an uploaded form but cannot open it, because the feed's reader drops the button and `/api/evidence/activity/<id>/form` is still Django.
- **`addToProjectInGo`, the save behind Add to Project, is not aligned with its form.** It does not check the project's status, focus, country or the person's allocation, and it returns a raw database error to the client. It is reachable only with Django absent, and must be fixed before that mode is used.

Limits of this proof: the development data has no PD requests and no partner team-member logins, so those paths are covered by unit tests or the existing Go helper only. The partner-on-hold rule was checked in a rolled-back transaction. The review cases were staged on the private copies and put back afterwards. An acting leader is refused by these Go forms until the acting page policy is ported.

Only 7 of the 18 field forms are listed in the mobile feed (`DRAWER_VIEWS`). The other 11 are compared by rendering the Django view directly and reading it with the feed's own form reader.

Detail pages in `internal/detailpages` serve Admin only until each has its record scope (12dbd14d1). Every other role is handed on to Django.

## Order of work

Each form needs its Go read, its Go save, its role and record checks, a test, and a shadow proof against Django on fresh private copies. Money comes last.

### Export option forms (4)

| Form | Django view | Lines | Roles |
|---|---|---|---|
| `/budget/export-drawer` | `budget_views.budget_export_drawer_view` | 23 | 8 |
| `/finance/fund-allocation/export-drawer` | `finance_views.export_drawer_view` | 12 | 5 |
| `/fund-requests/weekly/export-drawer` | `budget_views.fund_requests_export_drawer_view` | 37 | 7 |
| `/team-planning-oversight/export-drawer` | `oversight_views.planning_export_drawer_view` | 88 | 7 |

### Field operations and planning (18)

| Form | Django view | Lines | Roles |
|---|---|---|---|
| `/activities/<id>/evidence` | `my_plan_views.evidence_upload_drawer_view` | 62 | 2 |
| `/core-schools/assign-partner` | `core_schools_views.core_assign_partner_drawer` | 92 | 4 |
| `/core-schools/schedule-activity` | `core_schools_views.core_schedule_activity_drawer` | 38 | 4 |
| `/core-schools/schedule-training` | `core_schools_views.core_schedule_training_drawer` | 45 | 4 |
| `/core-schools/strategy-playbook` | `core_schools_views.core_strategy_playbook_drawer` | 9 | 5 |
| `/extra-work/assign-drawer` | `extra_work_views.extra_work_assign_drawer` | 39 | 2 |
| `/my-professional-development/allocation-history` | `pd_views.pd_allocation_history_view` | 9 | 9 |
| `/partners/<id>/members/drawer` | `partner_views.partner_member_drawer` | 12 | 2 |
| `/partners/create` | `partner_views.create_partner_view` | 104 | 3 |
| `/pl/review-queue/<id>/drawer` | `my_plan_views.pl_review_drawer` | 100 | 1 |
| `/pl/review-queue/<id>/return-drawer` | `my_plan_views.pl_return_drawer` | 59 | 1 |
| `/planning/schedule-modal` | `planning_views.schedule_modal_view` | 8 | 2 |
| `/projects/capacity/set` | `project_capacity_views.project_capacity_set_view` | 46 | 3 |
| `/projects/capacity/withdraw` | `project_capacity_views.project_withdraw_school_view` | 63 | 3 |
| `/projects/create` | `extended_views.project_create_drawer_view` | 27 | 4 |
| `/projects/monitoring/school` | `extended_views.project_monitoring_school_view` | 31 | 3 |
| `/schools/<id>/assign-to-project` | `school_views.assign_to_project_drawer_view` | 5 | 3 |
| `/work-plan/add` | `work_plan_views.non_school_activity_drawer` | 28 | 6 |

### Oversight, settings and impact (15)

| Form | Django view | Lines | Roles |
|---|---|---|---|
| `/acting-leadership/appoint` | `acting_views.acting_appoint_view` | 54 | 2 |
| `/country-planning-oversight/drawer` | `country_oversight_views.drawer_view` | 121 | 3 |
| `/ia/framework/areas/new` | `ia_framework_views.area_drawer` | 36 | 1 |
| `/ia/impact-reports/new` | `impact_report_views.report_detail` | 115 | 1 |
| `/ia/school-evidence/learning/new` | `ia_school_evidence_views.record_drawer` | 86 | 1 |
| `/priorities/ssa-mapping/<id>/history` | `ssa_mapping_views.rule_history_drawer` | 44 | 3 |
| `/programme-rollout/schools` | `programme_rollout_views.school_list_drawer` | 26 | 3 |
| `/settings/activity-catalogue/<id>/edit` | `catalogue_views.activity_catalogue_edit_action` | 74 | 2 |
| `/staff-activity/follow-ups` | `staff_activity_views.follow_up_queue_view` | 11 | 1 |
| `/staff-activity/people/<id>/follow-up` | `staff_activity_views.follow_up_new_view` | 46 | 1 |
| `/team-planning-oversight/detail` | `oversight_views.oversight_detail_view` | 40 | 7 |
| `/team-targets/matrix` | `staff_views.team_targets_matrix_view` | 27 | 1 |
| `/team-targets/recovery` | `staff_views.team_targets_recovery_view` | 29 | 1 |
| `/team-targets/sfid-backlog` | `staff_views.team_targets_sfid_backlog_view` | 44 | 1 |
| `/team-targets/validation-backlog` | `staff_views.team_targets_validation_backlog_view` | 53 | 1 |

### HR, compliance and coaching (12)

| Form | Django view | Lines | Roles |
|---|---|---|---|
| `/candidate-pipeline/new` | `hr_programme_views.application_record_drawer` | 40 | 3 |
| `/cce-leadership/engagements/new` | `cce_leadership_views.engagement_new_drawer` | 46 | 1 |
| `/cce-leadership/reports/new` | `cce_leadership_views.report_new_drawer` | 35 | 1 |
| `/compliance-register/new` | `hr_programme_views.compliance_evidence_drawer` | 12 | 3 |
| `/compliance-register/requirement` | `hr_programme_views.compliance_requirement_drawer` | 46 | 3 |
| `/employee-relations/new` | `hr_programme_views.er_open_drawer` | 73 | 3 |
| `/health-safety/new` | `hr_programme_views.incident_new_drawer` | 62 | 3 |
| `/offboarding/new` | `hr_programme_views.offboarding_start_drawer` | 51 | 3 |
| `/pulse-surveys/new` | `hr_programme_views.pulse_new_drawer` | 36 | 3 |
| `/recognition/new` | `hr_programme_views.recognition_new_drawer` | 39 | 3 |
| `/recovery-plans/new` | `hr_programme_views.recovery_new_drawer` | 45 | 4 |
| `/team/coaching/new` | `coaching_views.coaching_new_drawer` | 48 | 1 |

### Forms touching money (9)

| Form | Django view | Lines | Roles |
|---|---|---|---|
| `/compensation-benefits/new` | `hr_programme_views.compensation_new_drawer` | 12 | 3 |
| `/cost-settings/add` | `finance_views.add_linked_cost_view` | 54 | 1 |
| `/cost-settings/row/<key>` | `finance_views.cost_setting_row_view` | 115 | 1 |
| `/country-budget/plan-sources` | `finance_views.country_budget_plan_sources_view` | 10 | 5 |
| `/finance/fund-allocation/admin-budget-drilldown` | `finance_views.admin_budget_drilldown_view` | 33 | 5 |
| `/my-professional-development/request` | `pd_views.pd_request_view` | 208 | 9 |
| `/projects/planning/bulk-partner` | `planning_views.special_projects_bulk_partner_view` | 196 | 4 |
| `/recruitment/new` | `hr_programme_views.vacancy_request_drawer` | 62 | 4 |
| `/settings/activity-catalogue/new` | `catalogue_views.activity_catalogue_create_action` | 67 | 2 |
