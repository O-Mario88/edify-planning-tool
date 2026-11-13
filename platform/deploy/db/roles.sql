-- Least-privilege roles for the Go gateway. Applied by apply-roles.sh to a
-- development, test or staging database; never to production.
--
-- Roles and grants only. Nothing here creates, alters or drops a table,
-- column, index or constraint, and no row is read or written.
--
--   edify_gateway_ro   NOLOGIN. Holds the grants: SELECT on exactly the
--                      columns the gateway's queries name. No password hash,
--                      MFA secret, reset token or lockout column is readable.
--   edify_gateway      LOGIN, member of edify_gateway_ro. The gateway connects
--                      as this role. Its password is set out of band:
--                        ALTER ROLE edify_gateway PASSWORD '...';
--
-- Schema migration permission stays with the existing application's owner
-- role; neither role here can run DDL on the existing tables.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_gateway_ro') THEN
    CREATE ROLE edify_gateway_ro NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_gateway') THEN
    CREATE ROLE edify_gateway LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

GRANT edify_gateway_ro TO edify_gateway;
ALTER ROLE edify_gateway SET default_transaction_read_only = on;

-- Start from nothing, so re-running after a query changes never leaves a
-- grant behind that the code no longer needs.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_gateway_ro;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM edify_gateway_ro;
REVOKE CREATE ON SCHEMA public FROM edify_gateway_ro;
GRANT USAGE ON SCHEMA public TO edify_gateway_ro;

-- internal/identity: the account behind an access token.
GRANT SELECT (id, email, name, roles, active_role, status, is_active, deleted_at, must_change_password)
  ON "user" TO edify_gateway_ro;
GRANT SELECT (id, user_id, deleted_at) ON staff_profile TO edify_gateway_ro;
GRANT SELECT (appointee_id, cancelled_at, expired_at, start_date, end_date)
  ON acting_assignment TO edify_gateway_ro;

-- internal/schools: the direct portfolio.
GRANT SELECT (staff_id, school_id) ON staff_school_assignment TO edify_gateway_ro;
GRANT SELECT (
  id, school_id, name, school_type, operational_status, cluster_status,
  current_fy_ssa_status, planning_readiness, region_id, district_id,
  sub_county_id, parish_id, cluster_id, enrollment, salesforce_account_id,
  deleted_at
) ON school TO edify_gateway_ro;
GRANT SELECT (id, name) ON region TO edify_gateway_ro;
GRANT SELECT (id, name) ON district TO edify_gateway_ro;
GRANT SELECT (id, name) ON sub_county TO edify_gateway_ro;
GRANT SELECT (id, name) ON parish TO edify_gateway_ro;

-- internal/schooldirectory: the School Directory (2026-11-11), read only.
GRANT SELECT (
  id, school_id, name, school_type, operational_status, cluster_status, region_id, district_id,
  sub_county_id, cluster_id, enrollment, deleted_at, shipping_address, school_phone,
  primary_contact_name, account_owner_id, account_owner_name_raw, uploaded_district_text,
  uploaded_sub_county_text
) ON school TO edify_gateway_ro;
GRANT SELECT (id, name, country) ON region TO edify_gateway_ro;
GRANT SELECT (id, name, region_id) ON district TO edify_gateway_ro;
GRANT SELECT (id, name, district_id) ON sub_county TO edify_gateway_ro;
GRANT SELECT (id, name, deleted_at, status, responsible_staff_id) ON cluster TO edify_gateway_ro;
GRANT SELECT (id, user_id, deleted_at, country) ON staff_profile TO edify_gateway_ro;
GRANT SELECT (id, name, active_role, roles, deleted_at) ON "user" TO edify_gateway_ro;
GRANT SELECT (supervisor_id, supervisee_id) ON staff_supervisor_assignment TO edify_gateway_ro;
GRANT SELECT (covering_staff_id, original_staff_id, start_datetime, end_datetime, status)
  ON temporary_coverage_assignment TO edify_gateway_ro;
GRANT SELECT (staff_id, region_id, district_id) ON staff_geography_assignment TO edify_gateway_ro;
GRANT SELECT (id, name, status, deleted_at, manager_staff_id) ON project TO edify_gateway_ro;
GRANT SELECT (id, project_id, school_id, assigned_staff_id, created_at) ON project_school_assignment TO edify_gateway_ro;
GRANT SELECT (project_id, staff_id, is_active) ON project_staff_assignment TO edify_gateway_ro;
GRANT SELECT (project_id, staff_id, max_schools) ON project_staff_capacity TO edify_gateway_ro;
GRANT SELECT (id, school_id, fy, verification_status, deleted_at, date_of_ssa, created_at) ON ssa_record TO edify_gateway_ro;
GRANT SELECT (ssa_record_id, intervention, score) ON ssa_score TO edify_gateway_ro;
GRANT SELECT (id, school_id, activity_type, status, deleted_at, fy, planned_date, scheduled_date, attended_school_ids)
  ON activity TO edify_gateway_ro;
GRANT SELECT (activity_id, school_id, invited, attended) ON cluster_activity_attendance TO edify_gateway_ro;

-- internal/schoolprofile and internal/visitgate: a school's profile, its
-- Details tab and the year's support visit (2026-11-11), read only.
GRANT SELECT (
  planning_readiness, parish_id, latitude, longitude, core_cohort_year, core_cohort_number,
  director_name, headteacher_name, last_enrollment_date, data_quality_score, data_quality_status
) ON school TO edify_gateway_ro;
GRANT SELECT (id, name) ON parish TO edify_gateway_ro;
GRANT SELECT (district_id) ON cluster TO edify_gateway_ro;
GRANT SELECT (school_id, cluster_id, started_at, ended_at, start_reason, end_reason)
  ON school_cluster_membership TO edify_gateway_ro;
GRANT SELECT (average_score, verification_source, source_activity_id) ON ssa_record TO edify_gateway_ro;
GRANT SELECT (
  cluster_id, delivery_type, project_id, purpose_type, catalogue_item_id, training_course_id,
  paired_school_visit_id, assigned_partner_id, created_at
) ON activity TO edify_gateway_ro;
GRANT SELECT (id, counts_toward_client_visit, universal_training, is_training_course)
  ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (catalogue_item_id, counts_toward_entitlement) ON activity_eligibility_rule TO edify_gateway_ro;
GRANT SELECT (id, name) ON partner TO edify_gateway_ro;
GRANT SELECT (
  school_id, partner_id, project_id, training_course_id, expected_activity_type, purpose_of_visit, status, created_at
) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (intervention, target_interventions) ON project TO edify_gateway_ro;
-- Only whether a school has a case or a loan: its panel stays with the
-- existing application.
GRANT SELECT (school_id) ON bt_case TO edify_gateway_ro;
GRANT SELECT (school_id) ON bt_mfi_loan TO edify_gateway_ro;

-- internal/schoolprofile, the profile engine's tabs (2026-11-12), read only:
-- the school's sub-region, its stories, enrolment by year, learning
-- results, and the published SSA change rules.
GRANT SELECT (sub_region_id) ON district TO edify_gateway_ro;
GRANT SELECT (id, name) ON sub_region TO edify_gateway_ro;
GRANT SELECT (
  id, school_id, cluster_id, title, story_date, status, intervention, outcome_area, evidence_uri, created_at
) ON mscs_story TO edify_gateway_ro;
GRANT SELECT (school_id, fy, enrollment, recorded_at) ON school_enrollment_history TO edify_gateway_ro;
GRANT SELECT (
  id, school_id, fy, assessed_on, assessment_type, subject, grade_level, learners_tested, mean_score,
  max_score, verification_status, deleted_at
) ON impact_learning_result TO edify_gateway_ro;
GRANT SELECT (intervention, country, expected_direction, min_meaningful_change, effective_from, version, updated_at, status, active)
  ON activity_intervention_mapping TO edify_gateway_ro;
GRANT SELECT (id) ON ssa_record TO edify_gateway_ro;
GRANT SELECT (planned_date) ON activity TO edify_gateway_ro;
-- The Overview: people trained, the online channel, the work naming each
-- intervention, and the register's teachers and leaders.
GRANT SELECT (teachers_attended, leaders_attended, programme_delivery_mode, focus_intervention)
  ON activity TO edify_gateway_ro;
GRANT SELECT (teachers, leaders) ON cluster_activity_attendance TO edify_gateway_ro;
-- The SSA tab: the verified support between two assessments.
GRANT SELECT (activity_name_snapshot, actual_delivery_date) ON activity TO edify_gateway_ro;
-- The Participation tab: the school's planned and completed activities and
-- who may run each, cluster meetings by kind, what follow-up visits found,
-- and the support handed to partners with its cost.
GRANT SELECT (
  end_date, purpose_intervention, activity_purpose_text, venue, meeting_kind, evidence_status, payment_status,
  follow_up_of_activity_id, monitored_by_staff_id, reschedule_count, responsible_staff_id, salesforce_activity_id
) ON activity TO edify_gateway_ro;
GRANT SELECT (region_id) ON cluster TO edify_gateway_ro;
GRANT SELECT (deleted_at) ON partner TO edify_gateway_ro;
GRANT SELECT (activity_id, finding, improvements, created_at) ON school_visit_feedback TO edify_gateway_ro;
GRANT SELECT (id, scheduled_activity_id, monitoring_staff_id, assigning_staff_id, cluster_id, resolved_at, return_reason)
  ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (activity_id, amount) ON activity_schedule_cost_line TO edify_gateway_ro;
-- A Core school's profile: its package's 2 + 2 split for the year's doors,
-- and V1..V4 / T1..T4 on its Details.
GRANT SELECT (id, school_id, fy, status, visits_target, trainings_target) ON core_plan TO edify_gateway_ro;
GRANT SELECT (id, core_plan_id, activity_type, sequence_number, status, activity_id) ON core_activity_slot TO edify_gateway_ro;
GRANT SELECT (support_type, visit_number, training_number) ON partner_assignment TO edify_gateway_ro;
-- The Core School tab: the plan's recorded completion, the Core profile's
-- Champion status, and the school's SSA recommendations.
GRANT SELECT (visits_completed, trainings_completed) ON core_plan TO edify_gateway_ro;
GRANT SELECT (school_id, champion_status) ON core_school_profile TO edify_gateway_ro;
GRANT SELECT (school_id, intervention, score, score_band, reason, state, rank) ON ssa_recommendation TO edify_gateway_ro;
-- A closed school's profile: its banner (status, effective date, and the
-- latest closure's reason and what it took).
GRANT SELECT (closure_effective_date) ON school TO edify_gateway_ro;
GRANT SELECT (school_id, reason_category, reason, enrollment_at_closure, activities_cancelled, effective_date, created_at)
  ON school_closure TO edify_gateway_ro;
-- A school's Business Transformation panel and the Overview's loans strip:
-- the cases and their response, the loans with their latest repayment and
-- verification, and the practice and compliance assessments. The gateway
-- shows a loan's figures only to a reader of the register's sensitive view.
GRANT SELECT (id, status, deleted_at, created_at) ON bt_case TO edify_gateway_ro;
GRANT SELECT (case_id, kind, created_at) ON bt_case_recommendation TO edify_gateway_ro;
GRANT SELECT (
  id, purpose_id, mfi_id, status, salesforce_status, impact_status, external_loan_reference, currency,
  disbursed_amount, term_months, disbursement_date, deleted_at, created_at
) ON bt_mfi_loan TO edify_gateway_ro;
GRANT SELECT (id, label, is_edtech) ON bt_loan_purpose TO edify_gateway_ro;
GRANT SELECT (id, name) ON bt_mfi_organization TO edify_gateway_ro;
GRANT SELECT (loan_id, status, outstanding_amount, as_of_date, created_at) ON bt_repayment_snapshot TO edify_gateway_ro;
GRANT SELECT (loan_id, status, due_date) ON bt_loan_verification_requirement TO edify_gateway_ro;
GRANT SELECT (id, loan_id) ON bt_loan_disbursement TO edify_gateway_ro;
GRANT SELECT (disbursement_id) ON bt_loan_disbursement_reversal TO edify_gateway_ro;
GRANT SELECT (case_id, assessed_on, verification_status, practices) ON bt_financial_practice_assessment TO edify_gateway_ro;
GRANT SELECT (case_id, requirement_id, status) ON bt_school_compliance_assessment TO edify_gateway_ro;
GRANT SELECT (id, label) ON bt_compliance_requirement TO edify_gateway_ro;
-- The Clusters page: a cluster's leader and facilitating partner on its card,
-- and the sub-counties it covers.
GRANT SELECT (cluster_leader_name, cluster_leader_phone, facilitating_partner_id) ON cluster TO edify_gateway_ro;
GRANT SELECT (cluster_id, sub_county_id) ON cluster_sub_county TO edify_gateway_ro;
-- A cluster's schools list: whether a catalogue item counts as training (the
-- planning badges) and the planning calendar (the planning horizon).
GRANT SELECT (counts_toward_client_training) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (country, fy, planning_open_at) ON fiscal_year_planning_policy TO edify_gateway_ro;
-- The Closed Schools page: each closure's type, the owner it was recorded
-- against, whether it has been reopened, and what it gave back.
GRANT SELECT (id, closure_type, owner_at_closure, owner_name_at_closure, reopened_at, partner_assignments_withdrawn, budget_released)
  ON school_closure TO edify_gateway_ro;
-- Cluster Oversight's Command Center: the weights and maturity rules its
-- scores are made with (the newest row), where the Country Director or
-- Impact Assessment has set any.
GRANT SELECT (health_weights, impact_weights, teacher_weights, leader_weights, maturity_rules, created_at)
  ON cluster_score_setting TO edify_gateway_ro;
-- The Planning page: whether the country's operational rate card is published
-- (active_catalogue), which Cost Blocked counts.
GRANT SELECT (country, kind, status, is_active) ON cost_catalogue TO edify_gateway_ro;
-- The Planning page's SSA-Informed Plans: each live plan's recorded verdict.
GRANT SELECT (ssa_alignment) ON activity TO edify_gateway_ro;
-- The Decision Log reads the audit chain only through the narrow view
-- gateway_read.decision_audit (decision_log_roles.sql), never audit_log.
-- A partner's team member is refused the pages the Partner Admin keeps
-- (apps.partners.member_scope): the login's roster entries and whether the
-- partner's own login is theirs.
GRANT SELECT (id, user_id, partner_id, active, role, name) ON partner_member TO edify_gateway_ro;
GRANT SELECT (user_id) ON partner TO edify_gateway_ro;
-- Escalations: the upward decision channel's rows, and which supervisor link
-- comes first when a raiser has more than one.
GRANT SELECT (id, raised_by_user_id, raised_by_name, addressed_role, assigned_to_user_id, country_id, category, subject,
  detail, requested_decision, severity, due_date, status, decision, decision_note, resolved_at, created_at)
  ON leadership_escalation TO edify_gateway_ro;
GRANT SELECT (id) ON staff_supervisor_assignment TO edify_gateway_ro;
-- My Actions: the school actions handed to a person, their state, due date,
-- route and how each closed.
GRANT SELECT (school_id, issue_type, requested_action, workflow_route, state, returned_reason, sender_id, recipient_id,
  due_date, resolved_by_system, created_at)
  ON team_action TO edify_gateway_ro;
-- Core School Oversight (internal/coreoversight): the Core schools in the
-- School model's order, and each school's sub-region for the grouping.
GRANT SELECT (created_at, sub_region_id) ON school TO edify_gateway_ro;
-- My Plan (internal/myplan): whether a training ceiling has been set for the
-- reader (My Training Summary), which leaves their page to the existing
-- application until the summary is Go's.
GRANT SELECT (staff_id) ON training_ceiling TO edify_gateway_ro;
-- My Plan's counts (internal/myplan): an activity's quarter, which the
-- quarter tiles and This Quarter count by.
GRANT SELECT (quarter) ON activity TO edify_gateway_ro;

-- My Plan's rows (internal/myplan, docs/migration/25-my-plan.md 25.8), which
-- Core School Oversight's two tabs of planned work list: the activity's
-- people, cost, completion and district-day columns, its cost lines, weekly
-- requests, cost snapshots and rates, and the visit days. Not evidence:
-- the gateway may not read evidence_record, so a partner's completed work,
-- whose form decides whether it is complete, is left to the existing
-- application.
GRANT SELECT (other_participants, expected_participants, participants_per_school, teachers_per_school, planning_source, cost_missing, ia_verification_status, ssa_collection_expected, daily_visit_batch_id, event_district_id, execution_started_at, submitted_to_ia_at, pl_reviewed_at, planned_date_before_completion) ON activity TO edify_gateway_ro;
GRANT SELECT (district_type) ON district TO edify_gateway_ro;
GRANT SELECT (primary_district_id) ON staff_profile TO edify_gateway_ro;
GRANT SELECT (id) ON activity_schedule_cost_line TO edify_gateway_ro;
GRANT SELECT (activity_budget_line_id, weekly_fund_request_id) ON weekly_fund_request_line TO edify_gateway_ro;
GRANT SELECT (id, status) ON weekly_fund_request TO edify_gateway_ro;
GRANT SELECT (catalogue_id, key, approved_minimum, unit_cost) ON cost_setting TO edify_gateway_ro;
GRANT SELECT (activity_id, operational_rate_card_id, operational_breakdown, operational_cost, missing_configuration, is_current) ON activity_cost_snapshot TO edify_gateway_ro;
GRANT SELECT (other) ON cluster_activity_attendance TO edify_gateway_ro;
GRANT SELECT (id, responsible_user, visit_date) ON daily_visit_batch TO edify_gateway_ro;
-- The live rate card a cluster session not yet costed reads its meal rate
-- from (costing_service.catalogue_rate).
GRANT SELECT (id, country, kind, status, is_active, fy, version) ON cost_catalogue TO edify_gateway_ro;
GRANT SELECT (catalogue_item_id) ON cost_setting TO edify_gateway_ro;

-- My Plan's own tables (docs/migration/25-my-plan.md, 25.9): whether a
-- listed activity's cost lines carry an advance request waiting on somebody
-- (it would put the row on Waiting on Approval). Ids and status only.
GRANT SELECT (id, budget_line_id, status) ON advance_request TO edify_gateway_ro;

-- The Calendar (internal/calendarpage): approved and pending leave (whose,
-- what kind, which days, who covers), organization events and recorded
-- public holidays. No reason, notes, contact or attachment of a leave.
GRANT SELECT (staff_id, status, type, start_date, end_date, covering_staff_id) ON leave TO edify_gateway_ro;
GRANT SELECT (title, description, start_date, end_date, block_type, is_active, country) ON calendar_block TO edify_gateway_ro;
GRANT SELECT (date, name) ON public_holiday TO edify_gateway_ro;
-- The To-Do page, read by Go (docs/migration/36-todos.md): a field officer's
-- queue (activities and their advances, fund requests, partner returns and
-- delays, project enrolments, extra work, route days, core slots, loan-use
-- verifications, returned SSA and evidence, OneTest results, the next
-- planning year, cluster attendance) and the records whose presence passes
-- the reader on to the existing application.
GRANT SELECT (approval_owner_id, costing_profile_snapshot) ON activity TO edify_gateway_ro;
GRANT SELECT (returned_at) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (assigned_by, baseline_score, impact_classification, follow_up_due_on, follow_up_ssa_id) ON project_school_assignment TO edify_gateway_ro;
GRANT SELECT (due_date, status, title, urgency, assignee_id, reviewer_id, assigner_id, submitted_at) ON hr_extra_assignment TO edify_gateway_ro;
GRANT SELECT (week_start_date, responsible_user, receipt_confirmed_at, disbursed_at) ON weekly_fund_request TO edify_gateway_ro;
GRANT SELECT (period_key, submitted_by_user_id, period, status, reviewed_at, receipt_confirmed_at, disbursed_at) ON fund_request TO edify_gateway_ro;
GRANT SELECT (visit_date, confidence, feasible, status, responsible_user) ON daily_visit_route_batch TO edify_gateway_ro;
GRANT SELECT (staff_id, review_type, stage) ON hr_performance_review TO edify_gateway_ro;
GRANT SELECT (user_id, target) ON monthly_personal_target TO edify_gateway_ro;
GRANT SELECT (id) ON pd_request TO edify_gateway_ro;
GRANT SELECT (deleted_at) ON daily_debrief TO edify_gateway_ro;
GRANT SELECT (owner_user_id) ON daily_debrief_action TO edify_gateway_ro;
GRANT SELECT (assignee_id, created_by_id) ON staff_usage_follow_up TO edify_gateway_ro;
GRANT SELECT (acknowledged_at, cceo_user_id, cceo_staff_id) ON cce_cceo_coaching TO edify_gateway_ro;
GRANT SELECT (acknowledged_at, recipient_user_id, recipient_staff_id) ON cce_team_guidance_receipt TO edify_gateway_ro;
GRANT SELECT (activity_id) ON bt_loan_verification_requirement TO edify_gateway_ro;
GRANT SELECT (collected_by_user_id, returned_at) ON ssa_record TO edify_gateway_ro;
GRANT SELECT (recorded_by_user_id, source_activity_id) ON impact_learning_result TO edify_gateway_ro;
GRANT SELECT (verification_status, recorded_by_user_id) ON impact_discipleship_record TO edify_gateway_ro;
GRANT SELECT (verification_status, recorded_by_user_id) ON impact_edtech_check TO edify_gateway_ro;
GRANT SELECT (verification_status, recorded_by_user_id) ON impact_edtech_deployment TO edify_gateway_ro;
GRANT SELECT (costing_profile) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (execution_start) ON fiscal_year_planning_policy TO edify_gateway_ro;
GRANT SELECT (reimbursement_receipt_confirmed_at, accountability_netsuite_id, created_at) ON advance_request TO edify_gateway_ro;
-- The Work Plan (docs/migration/35-work-plan.md): the columns its Detailed
-- Activity Plan, summary and month bands show (the month an undated row is
-- filed under, the programme type and delivery method, the SSA score and the
-- planner's reason), each cost line's label and service month, whether an
-- advance waits on its owner (compute_next_action), the year's CD → RVP
-- approval status and note, and the approved leave and recorded holidays the
-- day-off marks read. No payload, and nothing of a leave but its dates.
GRANT SELECT (month, programme_activity_type, delivery_method_snapshot, source_score, ssa_deviation_reason) ON activity TO edify_gateway_ro;
GRANT SELECT (label, planned_date, month, fiscal_year) ON activity_schedule_cost_line TO edify_gateway_ro;
GRANT SELECT (reimbursement_receipt_confirmed_at, accountability_netsuite_id, created_at) ON advance_request TO edify_gateway_ro;
GRANT SELECT (id, fy, country_id, status, rvp_review_note) ON country_annual_budget TO edify_gateway_ro;
GRANT SELECT (staff_id, start_date, end_date, status) ON leave TO edify_gateway_ro;
GRANT SELECT (date, name) ON public_holiday TO edify_gateway_ro;
GRANT SELECT (block_type, is_active, country, start_date, end_date, title) ON calendar_block TO edify_gateway_ro;
