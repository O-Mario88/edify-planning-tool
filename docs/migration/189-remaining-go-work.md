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

Found while porting, to fix before these saves are used without Django:

- `plreview.checkReviewable` does not match Django's `_check_reviewable`. Go lets a Country Director review, and always refuses a lead's own work, which Django allows under `lead_clears_own_work`. Its refusal wording also differs.
- `getAddToProjectInGo` offers every open project and all staff as coordinators. Django offers only projects the school may join (`projects_open_for_enrolment`, with capacity) and only Project Coordinators.
- `/core-schools/schedule-activity` and `/core-schools/schedule-training` create the school's yearly package when opened (`ensure_core_plan`). Go must not write on a read, so these need the package worked out in memory.

Limits of this proof: the development data has no PD requests and no partner team-member logins, so those paths are covered by unit tests or the existing Go helper only. The partner-on-hold rule was checked in a rolled-back transaction. An acting leader is refused by these Go forms until the acting page policy is ported.

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
