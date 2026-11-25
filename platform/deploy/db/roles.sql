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
-- A cluster's Add Schools: the districts it serves today (its catchment).
GRANT SELECT (cluster_id, district_id, active, effective_from, effective_to) ON cluster_service_district TO edify_gateway_ro;
-- The Planning page's Recent changes: who opened a cluster membership, and a
-- hand-over that replaced another partner's.
GRANT SELECT (id, started_by) ON school_cluster_membership TO edify_gateway_ro;
GRANT SELECT (replaces_assignment_id) ON partner_assignment TO edify_gateway_ro;
-- A school's Add to Cluster: each of the owner's clusters with its school count.
GRANT SELECT (id, cluster_id, school_id) ON school_cluster_assignment TO edify_gateway_ro;
-- A cluster's schools list: whether a catalogue item counts as training (the
-- planning badges) and the planning calendar (the planning horizon).
GRANT SELECT (counts_toward_client_training) ON activity_catalogue_item TO edify_gateway_ro;
-- The school scheduling forms: whether a training may go to a certified agency.
GRANT SELECT (certified_agency_delivery_allowed) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (country, fy, planning_open_at) ON fiscal_year_planning_policy TO edify_gateway_ro;
-- The Closed Schools page: each closure's type, the owner it was recorded
-- against, whether it has been reopened, and what it gave back.
GRANT SELECT (id, closure_type, owner_at_closure, owner_name_at_closure, reopened_at, partner_assignments_withdrawn, budget_released)
  ON school_closure TO edify_gateway_ro;
-- Cluster Oversight's Command Center: the weights and maturity rules its
-- scores are made with (the newest row), where the Country Director or
-- Impact Assessment has set any.
GRANT SELECT (health_weights, impact_weights, teacher_weights, leader_weights, maturity_rules, set_by, note, created_at)
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
-- The Verify form shows why the plan did or did not follow the SSA.
GRANT SELECT (recommendation_reason, recommendation_source) ON activity TO edify_gateway_ro;
-- What a review decision reads of the credits, targets and devices it moves.
GRANT SELECT (ia_confirmed_at, catalogue_version) ON activity TO edify_gateway_ro;
GRANT SELECT (id, kind, endpoint, user_id, revoked_at) ON notification_push_subscription TO edify_gateway_ro;
GRANT SELECT (weight, school_level, created_at) ON hr_milestone_activity_rule TO edify_gateway_ro;
GRANT SELECT (id, created_at) ON hr_milestone_progress_credit TO edify_gateway_ro;
GRANT SELECT (id, milestone_id, scope, employee_id, team_id) ON hr_milestone_period_target TO edify_gateway_ro;
-- A partner on hold is not offered new work (assignable_partners).
GRANT SELECT (partner_id, lifted_at) ON partner_hold TO edify_gateway_ro;
GRANT SELECT (active_status, partner_role) ON partner TO edify_gateway_ro;
GRANT SELECT (display_name, stable_code, delivery_method, status, effective_from, effective_to, project_delivery_allowed,
  non_school_allowed, programme_category, activity_type)
  ON activity_catalogue_item TO edify_gateway_ro;
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
-- The Work Plan's Add reads what a non-school catalogue item allows.
GRANT SELECT (non_school_allowed, requires_participant_counts, multi_day_allowed) ON activity_catalogue_item TO edify_gateway_ro;
-- The Complete drawer and its save hand on a register holding a visiting school.
GRANT SELECT (is_guest) ON cluster_activity_attendance TO edify_gateway_ro;
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
GRANT SELECT (id, guidance_id, acknowledged_at, recipient_user_id, recipient_staff_id, created_at) ON cce_team_guidance_receipt TO edify_gateway_ro;
GRANT SELECT (id, title, author_id, issued_at, withdrawn_at, review_on) ON cce_team_guidance TO edify_gateway_ro;
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

-- The Staff Activity Log (internal/staffactivity): who signed in and when,
-- the active time by part of the platform, where each person is now (their
-- last page and beat), and the meaningful actions the audit chain records.
-- Of the audit chain only what counts and names an action, never its payload,
-- hash, address or browser: a row whose school is named only in its payload
-- passes the reader to the existing application. Of a sign-in, never its
-- address or browser.
GRANT SELECT (created_at, last_seen_at, last_seen_path, last_seen_action, last_seen_login_id) ON "user" TO edify_gateway_ro;
GRANT SELECT (id, user_id, at, last_active_at, ended_at, device) ON login_event TO edify_gateway_ro;
GRANT SELECT (user_id, day, section, seconds) ON presence_time TO edify_gateway_ro;
GRANT SELECT (id, action, actor_id, success, created_at, correlation_id, subject_kind, subject_id) ON audit_log TO edify_gateway_ro;
GRANT SELECT (status, subject_id) ON staff_usage_follow_up TO edify_gateway_ro;

-- My Plan's attention cards (docs/migration/40-my-plan-rest.md): the
-- reviewer's note on a returned activity (return_notes.note_for).
GRANT SELECT (pl_review_note) ON activity TO edify_gateway_ro;
-- compute_next_action's money branches: which advance comes first (newest),
-- a reimbursement receipt confirmed, an accountability's NetSuite code in.
GRANT SELECT (created_at, reimbursement_receipt_confirmed_at, accountability_netsuite_id) ON advance_request TO edify_gateway_ro;

-- Training Summary (internal/trainingsummary): what its figures count and who reads them.
GRANT SELECT (partner_date_set_by, executor_type) ON activity TO edify_gateway_ro;
GRANT SELECT (activity_type) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (catalogue_item_id, project_id, active) ON activity_project_mapping TO edify_gateway_ro;
GRANT SELECT (source_activity_id, catalogue_item_id) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (is_superuser) ON "user" TO edify_gateway_ro;
GRANT SELECT (id, staff_id, training_id, ceiling, fy) ON training_ceiling TO edify_gateway_ro;
GRANT SELECT (id, training_id, ceiling, fy, country) ON training_country_ceiling TO edify_gateway_ro;
-- The Team Performance page (docs/migration/37-team-performance.md): the
-- report's records, the Uganda Master Priority Plan milestones and their
-- approved allocations and phasing, and the country targets IA or Admin set.
-- Figures, dates, statuses and ids only.
GRANT SELECT (code) ON project TO edify_gateway_ro;
GRANT SELECT (closed_at) ON school TO edify_gateway_ro;
GRANT SELECT (delivery_method_snapshot) ON activity TO edify_gateway_ro;
GRANT SELECT (stable_code, delivery_method) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (school_id, completed_at) ON core_activity_slot TO edify_gateway_ro;
GRANT SELECT (school_id, fy) ON core_school_onboarding TO edify_gateway_ro;
GRANT SELECT (school_id, observed_on, discipleship_groups_active, fy, deleted_at, verification_status) ON impact_discipleship_record TO edify_gateway_ro;
GRANT SELECT (user_id) ON mscs_story TO edify_gateway_ro;
GRANT SELECT (created_at) ON staff_supervisor_assignment TO edify_gateway_ro;
GRANT SELECT (id, country_id, cycle_id, fy, level, sequence, title) ON hr_strategic_priority TO edify_gateway_ro;
GRANT SELECT (id, priority_id, code, measurement_type, target_value, core_target, client_target, source_order) ON hr_priority_milestone TO edify_gateway_ro;
GRANT SELECT (id, allocated_to_type, team_id, employee_id, milestone_id, allocated_target, core_target, client_target, status) ON hr_milestone_allocation TO edify_gateway_ro;
GRANT SELECT (allocation_id, period_start, planned_value, period_type) ON hr_milestone_period_target TO edify_gateway_ro;
GRANT SELECT (key, annual_target, monthly_targets, set_by_role, fy) ON country_report_target TO edify_gateway_ro;

-- Project Monitoring (internal/projectmonitoring): the projects' codes and
-- each enrolment's who-added-it, purpose, focus, start day, baseline and
-- impact verdict.
GRANT SELECT (code) ON project TO edify_gateway_ro;
GRANT SELECT (assigned_by, participation_type, matched_intervention, support_area, impact_classification, start_date, baseline_score) ON project_school_assignment TO edify_gateway_ro;

-- The notification centre (internal/notificationcenter, docs/migration/43):
-- the reader's own notifications as the page shows and filters them, and
-- their delivery settings, and a notice's words (body), which the page shows
-- and searches (coordinator, 2026-11-13: the words are ordinary text to their
-- recipient, no token, code or link was found in them, and Go reads only the
-- reader's own). Not the provenance, reminder or expiry columns.
GRANT SELECT (id, recipient_id, sender_id, title, category, context_type, context_id,
  target_route, action_label, action_required, priority, status, created_at, resolved_at, body)
  ON notification TO edify_gateway_ro;
GRANT SELECT (id, user_id, email_enabled, push_enabled, email_muted_categories)
  ON notification_preference TO edify_gateway_ro;

-- The Messages inbox for the web app (internal/messaging, docs/migration/42):
-- the reader's thread memberships, the threads' subjects and records, the
-- latest message's sender and the first 90 characters of its text, and the
-- leave a thread may be about. No attachment, draft or file column.
GRANT SELECT (thread_id, user_id, recipient_type, last_read_at, archived_at, starred) ON messaging_messageparticipant TO edify_gateway_ro;
GRANT SELECT (id, subject, context_type, context_id, context_label, priority, created_by, last_reply_at, updated_at, is_system_generated) ON messaging_messagethread TO edify_gateway_ro;
GRANT SELECT (thread_id, sender_id, body, created_at) ON message TO edify_gateway_ro;
GRANT SELECT (id) ON leave TO edify_gateway_ro;

-- Partner Monitoring (internal/partneroversight, docs/migration/46-partner-oversight.md): whether a reader's
-- workspace holds partner work — a group training a Partner facilitates, a withdrawal waiting on the reader, an
-- engagement the reader recorded, a Regional Lead observation asking for work with a partner. Ids, states and the
-- recommendation word only; no withdrawal reasons, notes or engagement text.
GRANT SELECT (facilitating_partner_id) ON activity TO edify_gateway_ro;
GRANT SELECT (state, supervising_pl_id) ON partner_assignment_withdrawal TO edify_gateway_ro;
GRANT SELECT (author_id) ON partner_engagement TO edify_gateway_ro;
GRANT SELECT (recommendation) ON cce_regional_engagement TO edify_gateway_ro;

-- The HR registers (internal/hrregister, docs/migration/169-hr-registers.md):
-- Organization Structure lists the People records in the viewer's reach
-- with their title, department and lifecycle state. No staff number, Drive
-- folder or any compensation column.
GRANT SELECT (title, department, onboarding_state) ON staff_profile TO edify_gateway_ro;
-- Recognition: who was recognised, where, for what (the category and the
-- citation the register shows) and when. Not who awarded it.
GRANT SELECT (staff_id, country, category, citation, awarded_on) ON hr_staff_recognition TO edify_gateway_ro;
-- Health & Safety: each incident's country, the person affected, its day,
-- place, category, severity, days lost and status. Not its description or
-- the actions taken.
GRANT SELECT (id, country, affected_staff_id, incident_date, location, category, severity, days_lost, status) ON hr_safety_incident TO edify_gateway_ro;
-- Staff Onboarding: each plan's person, start and target days, status and
-- age, and whether each checklist task is done. Not the probation decision.
GRANT SELECT (id, staff_id, start_date, target_completion_date, status, created_at) ON hr_onboarding_plan TO edify_gateway_ro;
GRANT SELECT (plan_id, is_completed) ON hr_onboarding_task TO edify_gateway_ro;
-- Staff Offboarding: each exit's person, last working day, reason, handover
-- owner and status. Not its notes or clearances.
GRANT SELECT (id, staff_id, last_working_day, exit_reason, handover_owner_id, status) ON hr_offboarding TO edify_gateway_ro;
-- Candidate Pipeline: each application's candidate, vacancy, stage and when
-- it last changed; a candidate's name, and their email only to search it; a
-- vacancy's role and country. Not a candidate's phone, CV or notes, nor a
-- vacancy's salary band or budget.
GRANT SELECT (id, candidate_id, vacancy_id, stage, updated_at) ON hr_application TO edify_gateway_ro;
GRANT SELECT (id, name, email) ON hr_candidate TO edify_gateway_ro;
GRANT SELECT (id, role, country) ON hr_vacancy TO edify_gateway_ro;
-- Employment Compliance: each requirement's country, name and whether it is
-- mandatory; each employee's record against one, its status, expiry day and
-- who verified it. Not the evidence document or a requirement's description.
GRANT SELECT (id, country, name, is_mandatory) ON hr_compliance_requirement TO edify_gateway_ro;
GRANT SELECT (id, staff_id, requirement_id, status, expiry_date, verified_by_id) ON hr_employee_compliance_record TO edify_gateway_ro;
-- The HR System Audit Log: an HR event's acting role, beside the action,
-- actor, success, time and subject already granted. Never its payload.
GRANT SELECT (actor_role) ON audit_log TO edify_gateway_ro;
-- Workforce Planning: a vacancy's department and status, beside its role and
-- country already granted.
GRANT SELECT (department, status) ON hr_vacancy TO edify_gateway_ro;
-- Policies & Documents: a policy or manual's slug, title, type, category,
-- country, status, whether acknowledgement is required and its current
-- version; that version's number and review day; who acknowledged which
-- version and how. Not a document's file, owner or audience, nor an
-- acknowledgement's comment.
GRANT SELECT (id, slug, title, document_type, category, country, status, acknowledgement_required, current_version_id) ON document_asset TO edify_gateway_ro;
GRANT SELECT (id, version_number, review_date) ON document_version TO edify_gateway_ro;
GRANT SELECT (id, document_id, version_id, user_id, state) ON document_acknowledgement TO edify_gateway_ro;
-- Performance Recovery Plans: each plan's person, type, cause code, start
-- and review days and status. Not the evidence, the action plan, the support
-- or the outcome note.
GRANT SELECT (id, staff_id, plan_type, cause, start_date, end_date, status) ON hr_pip_plan TO edify_gateway_ro;
-- Performance Reviews: a review's period, year, due day, manager and the two
-- ratings the register shows (the manager's to HR and Admin only), beside
-- its person, type and stage already granted, and its legacy status (HR
-- Analytics counts the reviews not yet "Completed" or "Closed"). Not the reflection,
-- feedback, evidence or calibration note.
GRANT SELECT (period, fy, due_date, manager_id, manager_rating, rating, status) ON hr_performance_review TO edify_gateway_ro;
-- Compensation & Benefits: a record's person, salary band, medical cover,
-- pension scheme, next review day and status. NEVER the salary, allowances,
-- currency, other benefits or bank details, which the register does not
-- show either.
GRANT SELECT (id, staff_id, salary_band, medical_cover, pension_scheme, next_review_date, status) ON hr_compensation TO edify_gateway_ro;
-- Staff Pulse Surveys: a survey's title, countries, window and status; each
-- anonymous answer's scores, which Go only averages (no result under five
-- answers). Never who answered, their key or their comment.
GRANT SELECT (id, title, countries, opens_on, closes_on, status) ON hr_pulse_survey TO edify_gateway_ro;
GRANT SELECT (survey_id, scores) ON hr_pulse_response TO edify_gateway_ro;

-- Leave Policies (internal/leavepolicies, docs/migration/164-leave-policies.md):
-- each leave type's label and key, beside the recorded public holidays
-- already granted. Not the entitlements or approvers, which only the page's
-- forms show.
GRANT SELECT (label, leave_type) ON leave_type_policy TO edify_gateway_ro;

-- Duplicate Review (internal/iapages, docs/migration/153-ia-duplicates.md):
-- each flag's two activities, status, reason and when it was raised.
GRANT SELECT (id, activity_id, duplicate_of_id, status, reason, created_at) ON ia_duplicate_activity TO edify_gateway_ro;
-- Returned Activities: which activity a verification belongs to and the
-- reasons it gave for returning it. Not the checklist, comments or verifier.
GRANT SELECT (id, activity_id) ON ia_verification TO edify_gateway_ro;
GRANT SELECT (verification_id, reason) ON ia_returned_reason TO edify_gateway_ro;
-- Verification History: each verification's activity, verifier, time and
-- whether it counts in analytics. Not its notes.
GRANT SELECT (activity_id, verified_by, verified_at, analytics_included) ON ia_verification_history TO edify_gateway_ro;

-- CCE monthly reports (internal/ccelead, docs/migration/136-cce-reports.md):
-- each report's author, month, countries, status and when it was submitted
-- and reviewed, and by whom. Not its written sections, figures or the
-- review note.
GRANT SELECT (id, author_id, status, period, countries, submitted_at, reviewed_at, reviewed_by_id, created_at) ON cce_regional_report TO edify_gateway_ro;
-- Training Feedback: each observation's author, kind, subject, country,
-- recommendation, day, sharing and acknowledgement times, the Programme Leads
-- it is shared with, its training and its five ratings; whether a coaching
-- record passed it on. Not the notes, feedback or the lead's response.
GRANT SELECT (id, author_id, kind, subject, country, recommendation, held_on, feedback_shared_at, acknowledged_at, program_lead_ids,
  activity_id, rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation, rating_application, created_at)
  ON cce_regional_engagement TO edify_gateway_ro;
GRANT SELECT (source_engagement_id) ON cce_cceo_coaching TO edify_gateway_ro;
-- My Coaching: a coaching record's subject, kind, day, author, officer (by
-- People record and account), country, follow-up day and the times it was
-- shared, acknowledged and followed up. Not its strengths, growth areas,
-- agreed actions or the officer's response.
GRANT SELECT (id, subject, kind, held_on, author_id, cceo_staff_id, cceo_user_id, country, follow_up_due, follow_up_done_at,
  shared_at, acknowledged_at, created_at) ON cce_cceo_coaching TO edify_gateway_ro;
-- Quality Flags: a flag's raiser, assignee, what it is about, its note and
-- recommendation, priority, due day, status and resolution note.
GRANT SELECT (id, raised_by_user_id, raised_by_name, assigned_to_user_id, category, scope_name, note, recommended_action,
  priority, due_date, status, resolution_note, created_at) ON cd_flag TO edify_gateway_ro;
-- Project Capacity: an allocation's id, which its Edit capacity drawer opens.
GRANT SELECT (id) ON project_staff_capacity TO edify_gateway_ro;
-- Platform operations (Admin): a ticket's reference, title, category, status, the
-- reporter's role, page and time (never its description, reporter or browser);
-- an incident's title, severity, status, where and when it was last seen (never
-- its samples or detail); the maintenance templates' schedule and the open
-- maintenance work.
GRANT SELECT (id, reference, title, category, status, reporter_role, route, created_at) ON admin_support_ticket TO edify_gateway_ro;
GRANT SELECT (id, title, severity, status, affected_route, affected_component, last_detected_at) ON admin_system_incident TO edify_gateway_ro;
GRANT SELECT (name, category, frequency_days, estimated_minutes, next_due_date) ON admin_maintenance_template TO edify_gateway_ro;
GRANT SELECT (reference, title, category, status, scheduled_date, created_at) ON admin_ops_work_item TO edify_gateway_ro;
-- Recruitment: a vacancy's type, target start and when it was requested (never its salary band or budget source).
GRANT SELECT (replacement_or_new_role, target_start_date, created_at) ON hr_vacancy TO edify_gateway_ro;
-- Fiscal Year Planning: each year's delivery window and follow-up rule (never its notes or who opened it).
GRANT SELECT (execution_start, execution_end, follow_up_visit_requires_prior_training) ON fiscal_year_planning_policy TO edify_gateway_ro;
-- Policy Compliance: each acknowledgement's reading time, attestation, due day, role and time; a policy's
-- required reading; whether a comment waits for the reader (its status and author's country, never its text).
GRANT SELECT (document_id, version_id, role_at_acknowledgement, active_reading_seconds, offline_attestation, due_date, created_at) ON document_acknowledgement TO edify_gateway_ro;
GRANT SELECT (required_reading_minutes) ON document_asset TO edify_gateway_ro;
GRANT SELECT (status, author_country) ON document_comment TO edify_gateway_ro;
-- The To-Do page's Programme Lead builders (agent/todos-pl, docs/migration/55).
GRANT SELECT (id, fy, status, due_date, created_at) ON hr_performance_review TO edify_gateway_ro;
GRANT SELECT (id, fy, active_window) ON hr_performance_cycle TO edify_gateway_ro;
GRANT SELECT (kind, held_on, author_id) ON cce_cceo_coaching TO edify_gateway_ro;
GRANT SELECT (id) ON cce_regional_engagement TO edify_gateway_ro;
GRANT SELECT (author_id) ON cce_team_guidance TO edify_gateway_ro;
GRANT SELECT (assigned_to_user_id) ON cd_flag TO edify_gateway_ro;
GRANT SELECT (id) ON partner_invoice TO edify_gateway_ro;
GRANT SELECT (program_lead_user_id) ON planning_oversight_follow_up TO edify_gateway_ro;
GRANT SELECT (pl_user_id, status, staff_user_id) ON target_catchup_plan TO edify_gateway_ro;
GRANT SELECT (author_id) ON partner_engagement TO edify_gateway_ro;

-- Impact Assessment's To-Do queue (docs/migration/56): what IA's own
-- builders read and the guards that pass a reader on.
GRANT SELECT (updated_at, ssa_not_collected_reason) ON activity TO edify_gateway_ro;
GRANT SELECT (collector_type) ON ssa_record TO edify_gateway_ro;
GRANT SELECT (id, status, batch_id) ON ssa_import_row TO edify_gateway_ro;
GRANT SELECT (id, uploaded_by, created_at) ON ssa_import_batch TO edify_gateway_ro;
GRANT SELECT (requires_school) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (catalogue_item_id, is_primary, reviewed_at) ON activity_intervention_mapping TO edify_gateway_ro;
GRANT SELECT (status) ON impact_outcome_area TO edify_gateway_ro;
GRANT SELECT (status) ON impact_indicator_definition TO edify_gateway_ro;
GRANT SELECT (status) ON unmatched_ssa_record TO edify_gateway_ro;
GRANT SELECT (status) ON ia_duplicate_activity TO edify_gateway_ro;
GRANT SELECT (status) ON ia_verification_sample TO edify_gateway_ro;
GRANT SELECT (id) ON impact_finding TO edify_gateway_ro;
GRANT SELECT (id) ON impact_report TO edify_gateway_ro;
GRANT SELECT (assigned_to_user_id) ON cd_flag TO edify_gateway_ro;

-- The To-Do page's Admin builders (agent/todos-cd-admin, docs/migration/57): the General Budget's desks,
-- the cost catalogue, partner logins waiting, and the guards of the Accountant's and HR's desks. Months,
-- statuses, dates and counts only; no amounts, notes or document contents.
GRANT SELECT (id, month_key, country_id, status) ON monthly_work_plan_budget TO edify_gateway_ro;
GRANT SELECT (created_at) ON fund_request TO edify_gateway_ro;
GRANT SELECT (user_setup_status, created_at) ON partner TO edify_gateway_ro;
GRANT SELECT (returned_amount, return_verified_at) ON advance_request TO edify_gateway_ro;
GRANT SELECT (status, archived_at) ON document_asset TO edify_gateway_ro;
GRANT SELECT (probation_review_date) ON hr_onboarding_plan TO edify_gateway_ro;
GRANT SELECT (uploaded_by) ON ssa_import_batch TO edify_gateway_ro;

-- The To-Do page's Project Coordinator and Business Transformation builders (agent/todos-pc-bto,
-- docs/migration/58-todos-pc-bto.md): loan submission days, the states and finding words that say whether
-- a loan section has rows, and loan impact conclusions' due days, states and preparer. No notes or amounts.
GRANT SELECT (submitted_at) ON bt_mfi_loan TO edify_gateway_ro;
GRANT SELECT (id) ON bt_loan_verification_requirement TO edify_gateway_ro;
GRANT SELECT (requirement_id, finding, concern_reviewed_at) ON bt_loan_use_result TO edify_gateway_ro;
GRANT SELECT (status) ON bt_loan_purpose_proposal TO edify_gateway_ro;
GRANT SELECT (loan_id, due_date, ia_status, prepared_by, prepared_at, updated_at) ON bt_loan_impact_assessment TO edify_gateway_ro;
-- The Training Summary's Schools tab (internal/trainingsummary, doc 44):
-- training_coverage.uncovered leaves out a school marked a duplicate.
GRANT SELECT (duplicate_status) ON school TO edify_gateway_ro;
-- Planning Oversight's Team Plan (internal/planningoversight, doc 47.6):
-- an undated activity sits in its month by planned_month (_in_month).
GRANT SELECT (planned_month) ON activity TO edify_gateway_ro;
-- The four tables' Purpose of Visit falls back to the support rationale
-- (_activity_item's purpose_of_visit and operational_rationale).
GRANT SELECT (support_rationale) ON activity TO edify_gateway_ro;
-- Staff Activity Log, a person's detail (docs/migration/41-staff-activity.md
-- §41.6): each session's active time, the number of tasks a person worked on,
-- and their follow-ups' kind, state and due day.
GRANT SELECT (active_seconds) ON login_event TO edify_gateway_ro;
GRANT SELECT (working_on) ON presence_time TO edify_gateway_ro;
GRANT SELECT (id, trigger, due_date, created_at) ON staff_usage_follow_up TO edify_gateway_ro;

-- Core School Oversight's recommendations (backlog core-recommendations): the
-- recommended training each names, or why none is mapped.
GRANT SELECT (recommended_item_id, unmapped_reason) ON ssa_recommendation TO edify_gateway_ro;
-- Extra Assigned Work (internal/extrawork, docs/migration/114-extra-work.md):
-- the reader's assignments of a year as assignee, assigner, reviewer and
-- supervising Programme Lead, the words the page shows of each (title,
-- instruction, return reason, outcome and evidence note) and the points the
-- verified ones earned; whether the year's scoring policy is approved. The
-- evidence link's address is read only to know there is one; Go never shows
-- it. No category, link to a priority, reason or verifier.
GRANT SELECT (id, fy, title, instruction, assigner_id, assigner_role, assignee_id, assignee_role, supervising_pl_id,
  reviewer_id, due_date, status, return_reason, outcome, evidence_note, evidence_uri, contribution_points, submitted_at)
  ON hr_extra_assignment TO edify_gateway_ro;
GRANT SELECT (fy, status) ON hr_extra_work_scoring_policy TO edify_gateway_ro;
-- Staff Setup Queue: whether a school's uploaded owner is matched yet.
GRANT SELECT (account_owner_status) ON school TO edify_gateway_ro;
-- The partner's intake queues: an assignment's free-text purpose, shown when no coded one exists.
GRANT SELECT (purpose) ON partner_assignment TO edify_gateway_ro;
-- Partner Evidence: which evidence an activity must carry, and which kinds it holds (never the files).
GRANT SELECT (evidence_profile_snapshot) ON activity TO edify_gateway_ro;
GRANT SELECT (activity_id, kind, quarantined) ON evidence_record TO edify_gateway_ro;
-- Sample Checks: each drawn sample, its check and its outcome.
GRANT SELECT (id, subject_type, activity_id, ssa_record_id, method, original_verifier, sampled_at, status, outcome_note, checked_by, checked_at) ON ia_verification_sample TO edify_gateway_ro;

-- Verification Analytics (internal/iapages/analytics.go): each decision's
-- verification, verdict, verifier and time. Not its notes.
GRANT SELECT (id, verification_id, decision, decided_by, decided_at) ON ia_verification_decision TO edify_gateway_ro;

-- Most Significant Change review (internal/iapages/stories.go): who reviewed
-- a story and why it went back, a schoolless story's country, and the outcome
-- areas a story may be tagged with and their SSA domains. Not the narrative.
GRANT SELECT (reviewed_by, return_reason, country) ON mscs_story TO edify_gateway_ro;
GRANT SELECT (id, code, name, version) ON impact_outcome_area TO edify_gateway_ro;
GRANT SELECT (area_id, intervention) ON impact_outcome_area_domain TO edify_gateway_ro;

-- Admin My Plan and Admin Planning (internal/adminops/myplan.go, planning.go):
-- each work item's severity, route, next action, incident, due and closing
-- dates and verification note; an open incident's reference and how often it
-- fired. Not a work item's description or resolution criteria.
GRANT SELECT (id, severity, affected_route, next_action, incident_id, due_date, completed_at, verification_note) ON admin_ops_work_item TO edify_gateway_ro;
GRANT SELECT (reference, occurrence_count) ON admin_system_incident TO edify_gateway_ro;

-- The partner's Evidence page (internal/partnerassigned/evidence.go): when each
-- upload arrived. Not the file, its name or its notes.
GRANT SELECT (created_at) ON evidence_record TO edify_gateway_ro;

-- Roles & Permissions matrix (internal/rolesmatrix): each permission's key and
-- the roles that hold one. Not a permission's description.
GRANT SELECT (id, key) ON permission TO edify_gateway_ro;
GRANT SELECT (role, permission_id) ON role_permission TO edify_gateway_ro;

-- Completion Reviews (internal/plreview): when a completion was submitted for
-- review, to date its wait. Not its decision or notes.
GRANT SELECT (activity_id, updated_at) ON activity_completion_verification TO edify_gateway_ro;

-- Team Plans (internal/adminops/teamplans.go): the week a plan item is planned
-- in, for its week filter and order.
GRANT SELECT (planned_week) ON activity TO edify_gateway_ro;

-- Closure Quality (internal/closurequality): how many of a closed school's
-- activities wait on finance.
GRANT SELECT (locked_activities_for_review) ON school_closure TO edify_gateway_ro;

-- Measurement Framework (internal/iaframework): the catalogue item's programme;
-- each measurement rule's window, threshold, mode, who wrote, submitted and
-- reviewed it; a loan purpose's measurement profile; each indicator and outcome
-- area version's words, author and reviewer. Not definitions' long text.
GRANT SELECT (programme_category) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (id, review_note, follow_up_min_days, follow_up_expected_days, follow_up_max_days, priority, submitted_by, not_ssa_measured_reason, reviewed_by, mapping_mode, authored_by) ON activity_intervention_mapping TO edify_gateway_ro;
GRANT SELECT (applicable_countries, verification_method, follow_up_days, measurement_profile_complete, impact_indicators) ON bt_loan_purpose TO edify_gateway_ro;
GRANT SELECT (id, key, version, name, level, source, country, outcome_area_id, author_id, reviewed_by_id) ON impact_indicator_definition TO edify_gateway_ro;
GRANT SELECT (author_id, reviewed_by_id) ON impact_outcome_area TO edify_gateway_ro;

-- Evidence Compare (internal/iapages/compare.go): each upload's id (for its
-- download link), original name and size. Not its storage path.
GRANT SELECT (id, original_name, file_size) ON evidence_record TO edify_gateway_ro;

-- Impact Reports (internal/iapages/reports.go): each report's title, period,
-- programmes, version, author, reviewer and status; its recommendations' and
-- releases' states. Not the report's methodology, findings or evidence.
GRANT SELECT (title, created_at, programme_areas, fy, period_start, version, review_note, author_id, status, updated_at, reviewed_by_id, period_end, country) ON impact_report TO edify_gateway_ro;
GRANT SELECT (report_id, status, due_date) ON impact_report_recommendation TO edify_gateway_ro;
GRANT SELECT (audience, report_id, status) ON impact_report_release TO edify_gateway_ro;

-- Ownership Transfers (internal/ownership): each district and school transfer's
-- what, who from and to, when, the open-work decision and reason, and the
-- targets left to reconcile. Not the actor or the saved preview.
GRANT SELECT (district_id, from_staff_id, to_staff_id, open_activity_decision, reason, effective_date, school_count, activities_transferred, created_at) ON district_portfolio_transfer TO edify_gateway_ro;
GRANT SELECT (school_id, from_staff_id, to_staff_id, open_activity_decision, reason, effective_date, transferred_activity_ids, batch_id, target_reconciliation_status, target_reconciliation_note, created_at) ON school_ownership_transfer TO edify_gateway_ro;

-- Data Quality Center (internal/dataquality): each open issue's school, kind,
-- wrong value, suggested fix and whether someone holds it.
GRANT SELECT (school_id, issue_type, status, field_name, current_value, suggested_fix, assigned_to, created_at) ON data_quality_issue TO edify_gateway_ro;

-- Completed Work & Payments (internal/partnerassigned/completed.go): what was
-- paid against partner work, its reference and date, and whether it sits on a
-- live invoice. Not who paid or the invoice's file.
GRANT SELECT (activity_id, payment_type, payment_reference, payment_date, amount_paid) ON partner_payment TO edify_gateway_ro;
GRANT SELECT (activity_id, invoice_id) ON partner_invoice_item TO edify_gateway_ro;
GRANT SELECT (id, status) ON partner_invoice TO edify_gateway_ro;

-- SSA Verification (internal/ssaverify): who uploaded a record (never their
-- own to decide) and who sent it back, with the reason the queue shows.
GRANT SELECT (uploaded_by, returned_by_user_id, return_reason) ON ssa_record TO edify_gateway_ro;

-- Programme Output Reports (internal/reports): each target type's approved
-- value for a year and whether it is active. Not who set it or its scope.
GRANT SELECT (fy, target_type, target_value, is_active) ON target_setting TO edify_gateway_ro;

-- Leave Tracker (internal/leavetracker): the working days a booked leave
-- charges and its handover note, each person's remaining balance by type and
-- year, and the leave a cover handover belongs to.
GRANT SELECT (days_charged, coverage_notes) ON leave TO edify_gateway_ro;
GRANT SELECT (staff_id, year, leave_type, remaining) ON leave_balance TO edify_gateway_ro;
GRANT SELECT (leave_request_id) ON temporary_coverage_assignment TO edify_gateway_ro;

-- Leave Approvals (internal/leaveapprovals): a request's reason (shown only
-- to an authorised approver, as the existing page does), whether it carries a
-- document (the page is passed on when it does), its cover's state, length,
-- decision and when it was made; each leave type's approval floor; a
-- balance's entitlement; and the monthly-plan items a leave falls on.
GRANT SELECT (reason, attachment, coverage_status, days, reviewed_by_user_id, reviewed_at, created_at) ON leave TO edify_gateway_ro;
GRANT SELECT (id, approver_role) ON leave_type_policy TO edify_gateway_ro;
GRANT SELECT (id, entitlement) ON leave_balance TO edify_gateway_ro;
GRANT SELECT (assignee_id, scheduled_date) ON monthly_plan_activity TO edify_gateway_ro;

-- HR Today (internal/hrtoday): a development request's status, course, who
-- it is for and when it was sent; when a policy last changed; which policy a
-- version belongs to and whether it was replaced; a review's functional
-- manager; and an agreement's priority weights.
GRANT SELECT (status, course_name, staff_name, staff_id, submitted_at) ON pd_request TO edify_gateway_ro;
GRANT SELECT (updated_at) ON document_asset TO edify_gateway_ro;
GRANT SELECT (document_id, superseded_at) ON document_version TO edify_gateway_ro;
GRANT SELECT (functional_manager_id) ON hr_performance_review TO edify_gateway_ro;
GRANT SELECT (id, review_id, weight) ON hr_performance_priority TO edify_gateway_ro;

-- Business Transformation engine (internal/btportfolio, internal/btpages):
-- who registered a loan (a loan officer's own book), its IA validation state
-- and Salesforce loan id (filters and search), and the year a case opened.
GRANT SELECT (registered_by, ia_validation_status, salesforce_loan_id) ON bt_mfi_loan TO edify_gateway_ro;
GRANT SELECT (opened_fy) ON bt_case TO edify_gateway_ro;

-- BT Business Accounting & Finance and Government Requirements
-- (internal/btpages/portfolio.go): the intervention a partner assignment and
-- a case recommendation are for; when a practice assessment was recorded; a
-- compliance assessment's IA state and expiry; and each requirement's
-- authority, country and whether it is active.
GRANT SELECT (focus_intervention) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (source_intervention) ON bt_case_recommendation TO edify_gateway_ro;
GRANT SELECT (created_at) ON bt_financial_practice_assessment TO edify_gateway_ro;
GRANT SELECT (ia_status, expiry_date) ON bt_school_compliance_assessment TO edify_gateway_ro;
GRANT SELECT (responsible_authority, country_code, active) ON bt_compliance_requirement TO edify_gateway_ro;

-- BT Loans register (internal/btpages/loans.go): what the latest repayment
-- snapshot says was paid, and when a loan's repayment data and record last
-- changed (the register's Last Updated column and the partner dashboard).
GRANT SELECT (amount_paid_during_period) ON bt_repayment_snapshot TO edify_gateway_ro;
GRANT SELECT (last_repayment_data_date, updated_at) ON bt_mfi_loan TO edify_gateway_ro;

-- BT Impact & Reports (internal/btpages/impact.go) and the portfolio's reach
-- and impact figures (internal/btportfolio/metrics.go): an impact
-- assessment's id (the Prepare drawer) and classification, and a verified
-- baseline enrolment snapshot's learner count, status and order.
GRANT SELECT (id, classification) ON bt_loan_impact_assessment TO edify_gateway_ro;
GRANT SELECT (status, learner_count, created_at) ON bt_enrolment_snapshot TO edify_gateway_ro;

-- MFI partner portal (internal/btpages/portal.go): a lending partner's
-- monthly portfolio returns and their open row-level data issues.
GRANT SELECT (id, reporting_month, source_type, valid_rows, total_rows, exception_rows, status, mfi_id) ON bt_portfolio_submission TO edify_gateway_ro;
GRANT SELECT (submission_id, row_number, code, message, status) ON bt_portfolio_data_exception TO edify_gateway_ro;

-- Partner Activities (internal/partnerworkspace): each organisation card's
-- contact person and phone, the regions and interventions it works in (the
-- first of each and every one) and how many catalogue activities it is
-- recorded for; a hand-over's delivery date; and a partner activity's
-- planned cost.
GRANT SELECT (contact_person, phone, region_name, region_names, ssa_intervention, ssa_interventions, activity_codes) ON partner TO edify_gateway_ro;
GRANT SELECT (scheduled_date) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (est_cost_cents) ON activity TO edify_gateway_ro;

-- Employee Relations (internal/hrregister/employeerelations.go): which case
-- it is, its type, country, severity and status, whom it concerns, who owns
-- and investigates it, whether it is confidential (a confidential case is
-- listed only to its owner and investigator) and its dates. Never what was
-- said: the description, findings, action taken, appeal note, hearing,
-- sanction and complainant stay unreadable. Each read of the register is
-- itself audited, appended through the audit chain's own grants
-- (activities_roles.sql, edify_activities_rw).
GRANT SELECT (id, case_type, country, severity, status, subject_staff_id, case_owner_id, investigator_id,
              is_confidential, opened_at, created_at, updated_at) ON hr_relations_case TO edify_gateway_ro;

-- The target engine (internal/targets), for the pages that show a person's
-- targets and progress: the target areas; an agreed review's priorities
-- (which measured area, its annual figure, words, weight and order) and when
-- the review changed; the explicit monthly targets; the target profile's
-- annual figures the areas fall back on; the validated ledger's monthly
-- quantities; and whether a ledger is marked for rebuilding (Go then hands the
-- reader on: the existing engine rebuilds on that read).
GRANT SELECT (id, key, label, weight, sort_order, active) ON target_area TO edify_gateway_ro;
GRANT SELECT (updated_at) ON hr_performance_review TO edify_gateway_ro;
GRANT SELECT (review_id, metric_key, target_number, outcome_statement, weight, sequence, created_at) ON hr_performance_priority TO edify_gateway_ro;
GRANT SELECT (user_id, fy, month_of_fy, target, area_id) ON monthly_personal_target TO edify_gateway_ro;
GRANT SELECT (staff_id, fy, visits_target, trainings_target, group_trainings_target, cluster_meetings_target, ssa_target) ON staff_target_profile TO edify_gateway_ro;
GRANT SELECT (user_id, fy, validation_status, area_id, credited_month, quantity) ON target_achievement_ledger TO edify_gateway_ro;
GRANT SELECT (owner_id, fy) ON target_ledger_dirty TO edify_gateway_ro;

-- My Performance (internal/myperformance): the reader's own commitments
-- (each value's words, kind, the behaviour agreed, their reflection and the
-- manager's observation) and development items, their development requests'
-- year and order, whether a review holds conversation snapshots or
-- amendments (Go passes those readers on), and whether the year has an
-- approved allocation on a live, approved milestone (Go passes those on too,
-- until the allocations engine is in Go).
GRANT SELECT (review_id, kind, value_name, agreed_behaviour, employee_reflection, manager_evidence) ON hr_value_commitment TO edify_gateway_ro;
GRANT SELECT (review_id, description) ON hr_development_plan_item TO edify_gateway_ro;
GRANT SELECT (fy, created_at) ON pd_request TO edify_gateway_ro;
GRANT SELECT (review_id) ON hr_performance_snapshot TO edify_gateway_ro;
GRANT SELECT (priority_id) ON hr_priority_amendment TO edify_gateway_ro;
GRANT SELECT (active, definition_status) ON hr_priority_milestone TO edify_gateway_ro;

-- The approved priority contract (internal/allocations): an allocation's
-- parent, denominator and weight; a milestone's title, unit, weight and cap;
-- each activity rule's milestone, counting basis and the activities it
-- matches; and each progress credit's rule, activity, value and reversal.
GRANT SELECT (parent_id, denominator, weight) ON hr_milestone_allocation TO edify_gateway_ro;
GRANT SELECT (title, target_unit, weight, cap_at_100) ON hr_priority_milestone TO edify_gateway_ro;
GRANT SELECT (id, milestone_id, counting_basis, catalogue_item_id, project_id, required_executor_type, required_delivery_method,
              school_type, target_intervention, active) ON hr_milestone_activity_rule TO edify_gateway_ro;
GRANT SELECT (rule_id, activity_id, reversed_at, credited_value) ON hr_milestone_progress_credit TO edify_gateway_ro;

-- The Cost Catalogue and Cost Intelligence (internal/costsettings): whether
-- the published card is provisional; each rate's label, unit and version;
-- each governed activity's workflow and the dates it is in force; and the
-- cost review queue (its reason, amounts and status, newest first).
GRANT SELECT (is_provisional) ON cost_catalogue TO edify_gateway_ro;
GRANT SELECT (id, label, unit, version) ON cost_setting TO edify_gateway_ro;
GRANT SELECT (workflow_kind, effective_from, effective_to) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (id, activity_id, reason_code, status, current_operational_cost, proposed_operational_cost, created_at)
  ON activity_cost_review TO edify_gateway_ro;

-- Budget (internal/budgetpage): each planned cost line's catalogue key,
-- rate, quantity, kind, partner and owner, and the rates the day a line
-- shares was priced at.
GRANT SELECT (cost_setting_key, unit_cost, quantity, line_item_type, partner_id, responsible_user)
  ON activity_schedule_cost_line TO edify_gateway_ro;
GRANT SELECT (rate_snapshot) ON daily_visit_batch TO edify_gateway_ro;

-- The country's Budget (internal/budgetpage/country.go): the month's budget
-- record's year, request and operating requirement, and each advance's
-- activity, date and amounts (requested, disbursed, accounted, reimbursed).
GRANT SELECT (fy, total_amount, operational_activity_requirement) ON monthly_work_plan_budget TO edify_gateway_ro;
GRANT SELECT (activity_id, planned_date, responsible_user_id, amount, disbursed_amount, accounted_amount, reimbursed_amount)
  ON advance_request TO edify_gateway_ro;

-- Pricing a stored activity (internal/pricing): the materials it plans, and
-- the dates a rate card is in force and its material-difference threshold.
GRANT SELECT (printing_pages, photocopy_pages, photocopy_copies) ON activity TO edify_gateway_ro;
GRANT SELECT (effective_from, effective_to, material_difference_threshold_bps) ON cost_catalogue TO edify_gateway_ro;
GRANT SELECT (currency, required_school_visits_per_day) ON cost_catalogue TO edify_gateway_ro;

-- The day a visit shares, priced read-only (internal/pricing/day.go): the
-- district type it was last priced as and how many schools it held.
GRANT SELECT (district_type, school_count) ON daily_visit_batch TO edify_gateway_ro;

-- Which way a stored activity is priced (internal/pricing/path.go): whether
-- its day's week has left its owner's hands.
GRANT SELECT (week_end_date) ON weekly_fund_request TO edify_gateway_ro;

-- Stage 4a: Go's own day check reads the finance guards a day's members are
-- asked (costing_service._ask_money_guards: the monthly requests carrying
-- their lines) and whether the day's transport was paid
-- (vendor_channel.paid_transport_amounts).
GRANT SELECT (id) ON fund_request TO edify_gateway_ro;
GRANT SELECT (fund_request_id, activity_schedule_cost_line_id) ON fund_request_item TO edify_gateway_ro;
GRANT SELECT (batch_id, status, amount) ON transport_payment TO edify_gateway_ro;

-- The Special Projects page (internal/projectspage): a project's type and
-- ceiling, an activity's fiscal year (the page's year reads either), and
-- the partners linked to each project.
GRANT SELECT (category, budget_ceiling_ugx) ON project TO edify_gateway_ro;
GRANT SELECT (fiscal_year) ON activity TO edify_gateway_ro;
GRANT SELECT (project_id, partner_id) ON project_partner_assignment TO edify_gateway_ro;

-- My Professional Development (internal/mypd): the reader's courses, their
-- dates and money, the year's allocation, the proof on file and the
-- messages from HR.
GRANT SELECT (updated_at, institution, course_type, course_category, start_date, end_date, funding_type, currency,
  requested_amount_cents, accounted_amount, returned_amount, accountability_netsuite_id, marked_complete_at,
  supervisor_reviewed_at, hr_reviewed_at, enrollment_confirmed_at, bamboohr_uploaded_at, accountability_submitted_at,
  signed_off_at) ON pd_request TO edify_gateway_ro;
GRANT SELECT (staff_id, fy, annual_allocation, currency) ON pd_allocation TO edify_gateway_ro;
GRANT SELECT (id, request_id, original_name, document_type, status, created_at) ON pd_certificate TO edify_gateway_ro;
GRANT SELECT (id, recipient_id, category, status, context_id) ON message TO edify_gateway_ro;

-- Lending Evidence (internal/iapages/lending.go): the reported loan use,
-- purpose outputs and teacher completions waiting for Impact Assessment, and
-- a conclusion's return note and filing order. The teacher is an anonymised
-- reference only.
GRANT SELECT (purpose_id, status, reported_amount, intended_output, updated_at) ON bt_loan_purpose_allocation TO edify_gateway_ro;
GRANT SELECT (evidence_reference) ON bt_enrolment_snapshot TO edify_gateway_ro;
GRANT SELECT (id, allocation_id, asset_type, planned_quantity, reported_quantity, reported_operational_quantity,
  evidence_reference, status, updated_at) ON bt_purpose_asset_output TO edify_gateway_ro;
GRANT SELECT (id, loan_id, anonymized_reference, programme, institution, completed_on, evidence_reference, status)
  ON bt_teacher_degree_beneficiary TO edify_gateway_ro;
GRANT SELECT (ia_note, created_at) ON bt_loan_impact_assessment TO edify_gateway_ro;

-- Fund Disbursement Dashboard (internal/disbursements): the month's fund
-- plans and weekly advances with their amounts and accountability dates, the
-- advances' snapshot lines, the advance ledger's month, and the partner a
-- payment went to.
GRANT SELECT (fy, submitted_by_role, total_amount, activity_count, disbursed_amount, accountability_submitted_at,
  accountability_reviewed_at) ON fund_request TO edify_gateway_ro;
GRANT SELECT (fy, total_amount, disbursed_amount, accountability_submitted_at, accountability_reviewed_at)
  ON weekly_fund_request TO edify_gateway_ro;
GRANT SELECT (line_item_type, description, quantity, unit_cost, total_cost) ON weekly_fund_request_line TO edify_gateway_ro;
GRANT SELECT (fy, month) ON advance_request TO edify_gateway_ro;
GRANT SELECT (partner_name) ON partner_payment TO edify_gateway_ro;

-- Fund Approvals (internal/fundapprovals): whether a cost line is paid
-- straight to a provider and whether it carries a cost catalogue version
-- (a plan without one needs review).
GRANT SELECT (vendor_paid, catalogue_id) ON activity_schedule_cost_line TO edify_gateway_ro;

-- Upload Center (internal/uploadcenter): the school and SSA import batches,
-- who filed each document and when, whether it asks for agreement, its
-- version's preview, and who each document is aimed at.
GRANT SELECT (id, file_name, uploaded_by, status, total_rows, created_at) ON school_import_batch TO edify_gateway_ro;
GRANT SELECT (file_name, status, total_rows) ON ssa_import_batch TO edify_gateway_ro;
GRANT SELECT (created_by, created_at, agreement_required) ON document_asset TO edify_gateway_ro;
GRANT SELECT (preview_status) ON document_version TO edify_gateway_ro;
GRANT SELECT (document_id, role, country, partner_id, project_id, user_id, effective_from)
  ON document_audience_rule TO edify_gateway_ro;

-- Field Debrief Dashboard (internal/debriefs): each debrief's who, when,
-- status, risk and completion, its title (and summary, which the search
-- reads), the schools it names, who it was routed to, its linked
-- activities, challenge types, open commitments, actions owed, peer
-- solutions and the open insights. None of a debrief's narrative fields.
GRANT SELECT (id, deleted_at, fy, date, status, risk_level, completion_status, submitted_by_user_id, submitted_by_role,
  staff_id, partner_id, kind, debrief_type, title, summary, is_restricted_incident, linked_school_ids)
  ON daily_debrief TO edify_gateway_ro;
GRANT SELECT (debrief_id, recipient_user_id) ON daily_debrief_recipient TO edify_gateway_ro;
GRANT SELECT (id, debrief_id, activity_id) ON daily_debrief_activity_link TO edify_gateway_ro;
-- The Daily Debrief (internal/debriefs/submit.go): the reader's own day's
-- debrief, with what they wrote, read back into their form. Go reads these
-- only for the debrief the reader submitted.
GRANT SELECT (other_work_description, what_went_well, what_did_not_go_well, challenges_faced, recommendations)
  ON daily_debrief TO edify_gateway_ro;
-- The Weekly Debrief Report (internal/debriefs/weekly.go): the report the
-- reader's role lands on for the week, drawn from its locked snapshot.
GRANT SELECT (scope_kind, scope_id, week_start, status, version, snapshot, commentary)
  ON weekly_debrief_report TO edify_gateway_ro;
GRANT SELECT (debrief_id, challenge_type) ON daily_debrief_challenge TO edify_gateway_ro;
GRANT SELECT (debrief_id, status) ON daily_debrief_commitment TO edify_gateway_ro;
GRANT SELECT (owner_user_id, status, due_date) ON daily_debrief_action TO edify_gateway_ro;
GRANT SELECT (debrief_id, author_user_id, suggestion, endorsed_by_user_ids, created_at)
  ON daily_debrief_peer_solution TO edify_gateway_ro;
GRANT SELECT (description, status, occurrence_count) ON daily_debrief_insight TO edify_gateway_ro;

-- Professional Development Dashboard (internal/cpdlearning): each course's
-- holder, supervisor and country, its proof and accountability marks, each
-- person's allocation and country, and the roles' default allocations.
GRANT SELECT (position, supervisor_name, country, accountability_reviewed_at, certification_expected, bamboohr_uploaded)
  ON pd_request TO edify_gateway_ro;
GRANT SELECT (id, country) ON pd_allocation TO edify_gateway_ro;
GRANT SELECT (role, fy, country, currency, annual_allocation_cents) ON pd_role_allocation TO edify_gateway_ro;

-- Partner Payment Queue (internal/partnerpayments): each PL-confirmed
-- partner invoice's partner, type, period, totals, whether the partner's
-- document is on file, and when it came in.
GRANT SELECT (created_at, partner_id, invoice_type, period_start, period_end, entered_total, payable_amount, stored_name)
  ON partner_invoice TO edify_gateway_ro;

-- Special Projects Planning (internal/projectplanning): the project type an
-- enrolment was given, beside the project's own category.
GRANT SELECT (project_type) ON project_school_assignment TO edify_gateway_ro;

-- Smart Route Planner (internal/routeplan): a school's corrected point, kept
-- by the existing application (apps.routes.SchoolGeoPoint), which the planner
-- prefers over the directory's coordinates.
GRANT SELECT (school_id, latitude, longitude) ON school_geo_point TO edify_gateway_ro;

-- Weekly Advance Request (internal/weeklyrequest): a request's return
-- reason, funding source and accounted amount, and the week and school a
-- cost line is filed under (the mission status and the district filter).
GRANT SELECT (return_reason, funding_source, accounted_amount) ON weekly_fund_request TO edify_gateway_ro;
GRANT SELECT (week_start_date, school_id) ON activity_schedule_cost_line TO edify_gateway_ro;

-- User Management (internal/adminusers): a partner organisation's email,
-- expertise and training areas, as its row in the partner table shows them.
GRANT SELECT (email, expertise_areas, trains_on) ON partner TO edify_gateway_ro;

-- Personal Time Off (internal/personaltimeoff): a balance's used, pending and
-- approved days, which the page checks against their recalculation before
-- answering (it answers only when the existing page's rewrite would change
-- nothing).
GRANT SELECT (used, pending, approved) ON leave_balance TO edify_gateway_ro;

-- My Targets (internal/mytargets): whether a milestone still needs
-- defining and has its metric (a strategic priority's ready milestones), a
-- Core School's baseline SSA average, whether an agreed priority came from a
-- source rule (the manual priorities), and a Project assignment's year.
GRANT SELECT (requires_definition, metric_definition_id) ON hr_priority_milestone TO edify_gateway_ro;
GRANT SELECT (baseline_average) ON core_plan TO edify_gateway_ro;
GRANT SELECT (source_rule_id) ON hr_performance_priority TO edify_gateway_ro;
GRANT SELECT (fy) ON project_staff_assignment TO edify_gateway_ro;
-- …and, for a reader's approved milestone allocations: each period
-- target's end, verified actual and achievement, the milestone's metric
-- name (the table's data source), and the planning links from work to an
-- allocation (its linked activities).
GRANT SELECT (period_end, actual_value, achievement_percentage) ON hr_milestone_period_target TO edify_gateway_ro;
GRANT SELECT (id, canonical_label) ON hr_milestone_metric_definition TO edify_gateway_ro;
GRANT SELECT (allocation_id, activity_id) ON hr_activity_priority_link TO edify_gateway_ro;
-- …and the reader's assigned Projects (its Project priorities): each
-- assignment's responsibility, the Project's school focus.
GRANT SELECT (id, responsibility) ON project_staff_assignment TO edify_gateway_ro;
GRANT SELECT (school_focus) ON project TO edify_gateway_ro;
-- The target engine (internal/targets) works out a ledger marked stale in
-- memory, as the existing rebuild would write it: each row's source and the
-- day it credits. Go reads it; it never writes the ledger.
GRANT SELECT (source_type, source_id, activity_date) ON target_achievement_ledger TO edify_gateway_ro;
-- Uganda Target Distribution (internal/targetdistribution): the cycles' years
-- and states (the year the page opens on and its year filter), and whether a
-- year holds staged priority imports.
GRANT SELECT (financial_year, status) ON hr_strategic_priority_cycle TO edify_gateway_ro;
GRANT SELECT (id, fy, country_id) ON hr_priority_import_batch TO edify_gateway_ro;
-- …and a year's Uganda master: each milestone's allocation method, owner,
-- confirmation flag and source text, each priority's code and state, an
-- allocation's quarterly state, component split and Project, and the
-- milestones' target components (the reconciliation).
GRANT SELECT (allocation_method, responsible_role, needs_confirmation, source_text) ON hr_priority_milestone TO edify_gateway_ro;
GRANT SELECT (code, status) ON hr_strategic_priority TO edify_gateway_ro;
GRANT SELECT (quarter_status, component_split, project_id) ON hr_milestone_allocation TO edify_gateway_ro;
GRANT SELECT (id, milestone_id, code, target_value) ON hr_milestone_target_component TO edify_gateway_ro;
-- Uganda Priorities (internal/prioritiesmaster): how a milestone's target
-- reads (a monthly recurrence, a due date, the source's target text) and
-- its components' names and order.
GRANT SELECT (recurrence_per_month, due_date, target_source_text) ON hr_priority_milestone TO edify_gateway_ro;
GRANT SELECT (label, sequence) ON hr_milestone_target_component TO edify_gateway_ro;
-- Core Schools Planning (internal/coreschools): a package's follow-up
-- average (the staff and partner outcomes), and each slot's side, partner and
-- intervention.
GRANT SELECT (follow_up_average) ON core_plan TO edify_gateway_ro;
GRANT SELECT (owner, assigned_partner_name, intervention) ON core_activity_slot TO edify_gateway_ro;
-- Impact Assessment's dashboard (internal/iapages/dashboard.go): evidence
-- waiting for a decision, the unmatched SSA rows' placing, and the upload
-- batches that failed.
GRANT SELECT (status) ON evidence_record TO edify_gateway_ro;
GRANT SELECT (batch_id, suggested_school_id) ON unmatched_ssa_record TO edify_gateway_ro;
GRANT SELECT (id, uploaded_by) ON ssa_import_batch TO edify_gateway_ro;
GRANT SELECT (status, uploaded_by) ON upload_batch TO edify_gateway_ro;
-- The IA dashboard's Outcomes view (internal/iapages/outcomes.go): each
-- enrolment's previous FY SSA and current FY score, and the approved outcome
-- areas with their SSA domains.
GRANT SELECT (baseline_ssa_id, follow_up_score) ON project_school_assignment TO edify_gateway_ro;
GRANT SELECT (id, code, name, version) ON impact_outcome_area TO edify_gateway_ro;
GRANT SELECT (area_id, intervention) ON impact_outcome_area_domain TO edify_gateway_ro;
-- Programme Rollout (internal/programmerollout): whether the Regional Lead
-- observed a training in the year.
GRANT SELECT (fy) ON cce_regional_engagement TO edify_gateway_ro;
-- Programme Rollout's Spiritual Formation view: a response to a weak
-- spiritual area may name it as a secondary focus.
GRANT SELECT (secondary_focus_interventions) ON activity TO edify_gateway_ro;
-- Programme Rollout: the partner engagement a Programme Lead recorded in
-- answer to a Regional Lead's recommendation, and when.
GRANT SELECT (source_engagement_id, held_on) ON partner_engagement TO edify_gateway_ro;
-- Core Schools' Team Core Oversight lens (internal/coreschools): whether an
-- ask about a school is already open for the year.
GRANT SELECT (fy) ON team_action TO edify_gateway_ro;
-- Partner Monitoring with partner work (internal/partneroversight): whether a
-- hand-back has been decided and why it came back, and a course's name as
-- its source gave it where it has no display name.
GRANT SELECT (resolution, return_reason_category) ON partner_assignment TO edify_gateway_ro;
GRANT SELECT (source_name) ON activity_catalogue_item TO edify_gateway_ro;
-- Partner Monitoring through a region's lens: the school or hand-over a
-- withdrawal request names, to place it in the reader's regions.
GRANT SELECT (school_id, assignment_id) ON partner_assignment_withdrawal TO edify_gateway_ro;
-- Partner Monitoring's withdrawal queue: each request a CCEO raised, why,
-- whose it is, what happens next and the money it carries.
GRANT SELECT (id, requested_at, kind, reason_category, partner_facing_reason, internal_note, attribution, disposition, original_planned_cost, financial_state_at_withdrawal, partner_id) ON partner_assignment_withdrawal TO edify_gateway_ro;
-- Partner Monitoring's Core tab: the package slot a hand-over waiting on
-- its Partner holds (slot_held_by_assignment).
GRANT SELECT (assigned_partner_id) ON core_activity_slot TO edify_gateway_ro;
-- Partner Monitoring's partnership register: each engagement's row, its
-- follow-up and whether the partner has it.
GRANT SELECT (id, kind, fy, country, subject, agreed_improvements, follow_up_due, follow_up_done_at, shared_with_partner_at, partner_id, created_at) ON partner_engagement TO edify_gateway_ro;
-- The Sub-region profile: the region a sub-region sits in.
GRANT SELECT (region_id) ON sub_region TO edify_gateway_ro;
-- The profiles' records of teachers and leaders: the register's own order.
GRANT SELECT (id) ON cluster_activity_attendance TO edify_gateway_ro;

-- The Graduated Champion Schools directory: each champion's Core start year
-- (core_schools_views.champions_list_view).
GRANT SELECT (school_id, core_start_fy) ON core_school_profile TO edify_gateway_ro;
-- Public Holidays & Blackout Dates: the region a regional event applies to.
GRANT SELECT (region_id) ON calendar_block TO edify_gateway_ro;
-- Temporary Leave Coverage Assignments: the scope, the revocation and the
-- order the page lists them in.
GRANT SELECT (scope, revoked_at, created_at) ON temporary_coverage_assignment TO edify_gateway_ro;
-- Visit Requests: the owner's note on a decided request.
GRANT SELECT (owner_decision_note) ON activity TO edify_gateway_ro;
-- The Blocked Closures directory: each blocker, its reason, role and age, longest blocked first.
GRANT SELECT (id, activity_id, blocking_reason, responsible_role, created_at) ON closure_blocker TO edify_gateway_ro;
-- Analytics Publishing Status: each publish record, failures first.
GRANT SELECT (id, activity_id, status, published_at, error_message, created_at) ON analytics_publish_record TO edify_gateway_ro;
-- The Completed Activities ledger: each closed activity's IA verification
-- and its NetSuite expense id.
GRANT SELECT (activity_id, ia_verified) ON closure_checklist TO edify_gateway_ro;
GRANT SELECT (activity_id, netsuite_expense_id) ON completed_activity_snapshot TO edify_gateway_ro;
-- Regional Lead Coaching: each conversation's agreed actions and follow-up.
GRANT SELECT (agreed_actions, follow_up_due) ON cce_regional_engagement TO edify_gateway_ro;
-- The RVP's To-Dos: each General Budget and Country Annual Budget submitted
-- to them (todo_service._rvp_todos).
GRANT SELECT (activity_count) ON monthly_work_plan_budget TO edify_gateway_ro;
GRANT SELECT (total_amount, created_at) ON country_annual_budget TO edify_gateway_ro;
-- The Country Director's To-Dos from the RVP's open strategy notes
-- (todo_service._strategy_note_todos).
GRANT SELECT (id, priority_label, scope, instruction, responsible_cd_id, deadline, status, created_at)
  ON rvp_strategy_note TO edify_gateway_ro;
-- The Regional Lead's To-Dos: the RVP's note on a returned monthly report
-- (todo_service._cce_leadership_todos).
GRANT SELECT (review_note) ON cce_regional_report TO edify_gateway_ro;
-- The lending partners' To-Dos: the loans a partner administrator's
-- memberships or a loan officer's own reach (bt_services.scoped_loans), and
-- when Salesforce returned each.
GRANT SELECT (user_id, mfi_id, role, active, officer_reference) ON bt_mfi_membership TO edify_gateway_ro;
GRANT SELECT (assigned_officer_reference, salesforce_returned_at) ON bt_mfi_loan TO edify_gateway_ro;
-- The Accounts desks (internal/financedesks): accountability records, the
-- finance audit log, budget amendments, the cleared ledger's snapshots,
-- returned and confirmed advances, and variance reviews.
GRANT SELECT (id, activity_id, staff_id, amount_disbursed, actual_spend, variance, netsuite_expense_id, status, submitted_at)
  ON accountability_record TO edify_gateway_ro;
GRANT SELECT (id, activity_id, event_type, actor_id, actor_role, new_value, timestamp) ON finance_audit_log TO edify_gateway_ro;
GRANT SELECT (id, activity_id, original_date, new_date, original_fy, original_quarter, new_fy, new_quarter, original_amount,
  reason, status, review_note, created_at) ON budget_amendment TO edify_gateway_ro;
GRANT SELECT (id, final_budget_amount, disbursed_amount, actual_spend_amount) ON completed_activity_snapshot TO edify_gateway_ro;
GRANT SELECT (activity_id, amount, responsible_user_id, last_note, updated_at) ON advance_request TO edify_gateway_ro;
GRANT SELECT (id, activity_id, budgeted_amount, disbursed_amount, actual_spend, variance, reason, status, created_at)
  ON variance_review TO edify_gateway_ro;
GRANT SELECT (est_cost_cents, payment_status) ON activity TO edify_gateway_ro;
-- The Finance Blocked directory: each activity's evidence, Salesforce record
-- and ID, and when it was created.
GRANT SELECT (activity_id, quarantined) ON evidence_record TO edify_gateway_ro;
GRANT SELECT (salesforce_record_type_snapshot, salesforce_activity_id, delivery_type, created_at) ON activity TO edify_gateway_ro;
-- The Weekly Staff Fund Requests registry: each request's money.
GRANT SELECT (total_amount, disbursed_amount) ON weekly_fund_request TO edify_gateway_ro;
-- The Budget Overview's rollups and the Submitted Budgets history.
GRANT SELECT (id, activity_id, amount, month) ON activity_schedule_cost_line TO edify_gateway_ro;
GRANT SELECT (budget_line_id, status, disbursed_amount, accounted_amount) ON advance_request TO edify_gateway_ro;
GRANT SELECT (fy, quarter, planned_date) ON activity TO edify_gateway_ro;
GRANT SELECT (fy, total_amount, submitted_at, submitted_by_user_id, submission_version) ON monthly_work_plan_budget TO edify_gateway_ro;

-- The Closure Readiness Workspace (internal/closurepages/queue.go): each
-- activity's closure facts, read as ClosureEligibilityService.with_facts
-- annotates them: whether the accountant entered a NetSuite expense, and
-- which advances moved and were accounted for.
GRANT SELECT (activity_id) ON netsuite_expense_record TO edify_gateway_ro;
GRANT SELECT (activity_id, status, accountability_netsuite_id) ON advance_request TO edify_gateway_ro;

-- The Unmatched SSA queue (internal/iapages/unmatched.go): each imported row
-- no school matched, its suggested school and confidence, and the batches.
GRANT SELECT (id, school_id, school_name_raw, district_raw, date_of_ssa, reason, status, match_confidence, created_at)
  ON unmatched_ssa_record TO edify_gateway_ro;

-- School Upload History (internal/adminpanel/upload_history.go): each upload
-- batch's file, type, source, row breakdown, state and error summary.
GRANT SELECT (id, file_name, original_file_name, upload_type, source, error_summary, total_rows, created_rows,
  updated_rows, failed_rows, created_at)
  ON upload_batch TO edify_gateway_ro;

-- Geographical Location Setup (internal/adminpanel/geography.go): the
-- Secondary District Groups and the districts each holds.
GRANT SELECT (id, name, status) ON secondary_district_group TO edify_gateway_ro;
GRANT SELECT (id, group_id, district_id, created_at) ON secondary_district_group_member TO edify_gateway_ro;

-- Notification & Alert Logs (internal/adminpanel/notifications.go): the
-- Admin's log reads every recipient's newest notices with the role each was
-- sent to (the columns above, and this one).
GRANT SELECT (recipient_role) ON notification TO edify_gateway_ro;


-- Payroll Readiness and Succession Planning (internal/hrregister/programmes.go):
-- each check's person, period, exception and readiness flags (and its notes,
-- which the search reads); each nomination's position, successor, readiness
-- and when it changed. Not the nomination notes.
GRANT SELECT (staff_id, payroll_period, has_exceptions, is_payroll_ready, exception_notes) ON hr_payroll_readiness TO edify_gateway_ro;
GRANT SELECT (staff_successor_id, position_name, readiness, updated_at) ON hr_succession_candidate TO edify_gateway_ro;

-- Performance Conversation (internal/perfconversation): each priority's
-- alignment, the three channels' words and ratings and whether it is
-- inherited; each commitment's id (its save); a snapshot's window. Not a
-- snapshot's frozen figures.
GRANT SELECT (strategic_alignment, employee_reflection, employee_rating, manager_assessment, manager_rating, agreed_action,
  functional_manager_rating, is_mandatory) ON hr_performance_priority TO edify_gateway_ro;
GRANT SELECT (id) ON hr_value_commitment TO edify_gateway_ro;
GRANT SELECT ("window") ON hr_performance_snapshot TO edify_gateway_ro;

-- Consolidated Fund Allocation (internal/budgetpage/fundallocation.go): each
-- active line of the country admin plan, its item, category, quantity, unit
-- and total cost, and the month's budget it belongs to. Not its justification.
GRANT SELECT (description, cost_category, unit_cost, total_cost, quantity, status, monthly_budget_id)
  ON admin_budget_line TO edify_gateway_ro;

-- Report a Problem (internal/adminops/report.go): whose ticket it is (the
-- reader's own twenty) and the resolution its reporter is told.
GRANT SELECT (reporter_id, resolution) ON admin_support_ticket TO edify_gateway_ro;

-- The policy response page (internal/uploadcenter/restricted.go): the
-- reason a person gave for disagreeing, and the policy's description, its
-- statement and whether it gates the application.
GRANT SELECT (comment) ON document_acknowledgement TO edify_gateway_ro;
GRANT SELECT (description, agreement_statement, blocks_application_access) ON document_asset TO edify_gateway_ro;

-- Activity Catalogue settings (internal/catalogue): each item's profiles,
-- delivery eligibility and Salesforce record; its versions (number, reason,
-- when); the mapping corrections waiting on review. Not a version's
-- snapshot.
GRANT SELECT (evidence_profile, salesforce_record_type, salesforce_expected_prefix, staff_delivery_allowed, partner_delivery_allowed,
  individual_school_allowed, project_delivery_allowed) ON activity_catalogue_item TO edify_gateway_ro;
GRANT SELECT (id, catalogue_item_id, version, change_reason, created_at) ON activity_catalogue_version TO edify_gateway_ro;
GRANT SELECT (id, review_kind, source_model, source_record_id, source_value, candidate_codes, status, created_at)
  ON activity_catalogue_review_queue TO edify_gateway_ro;

-- School Evidence (internal/schoolevidence): a learning result's
-- proficiency, its state's reason and country, and when it was recorded;
-- every kind's school, year and deletion for the page's figures. Not its
-- notes or evidence reference.
GRANT SELECT (learners_proficient, return_reason, country, created_at) ON impact_learning_result TO edify_gateway_ro;
GRANT SELECT (school_id, deleted_at) ON impact_edtech_deployment TO edify_gateway_ro;
GRANT SELECT (school_id, deleted_at) ON impact_edtech_check TO edify_gateway_ro;
-- School Evidence's Discipleship tab reads each record's figures.
GRANT SELECT (id, devotions_per_week, learners_in_groups, learners_enrolled, staff_in_devotions_pct, spiritual_lead_in_post, bible_lessons_timetabled, return_reason, country, created_at) ON impact_discipleship_record TO edify_gateway_ro;
-- School Evidence's EdTech tab reads each deployment and check of use.
GRANT SELECT (id, fy, asset_type, quantity, deployed_on, funding, learners_with_access, return_reason, country, created_at) ON impact_edtech_deployment TO edify_gateway_ro;
GRANT SELECT (id, fy, deployment_id, checked_on, units_functional, teachers_using, learners_using, return_reason, country, created_at) ON impact_edtech_check TO edify_gateway_ro;
-- The Knowledge Center's reading pages (internal/helpcenter).
GRANT SELECT (id, created_at, updated_at, slug, title, summary, category_id, search_document, reviewer_name, estimated_reading_minutes, version, last_reviewed_at, review_due_at, reviewer_id, keywords, content, state, workflow, feature) ON help_center_helparticle TO edify_gateway_ro;
GRANT SELECT (id, slug, name, description, sort_order) ON help_center_helpcategory TO edify_gateway_ro;
GRANT SELECT (article_id, role) ON help_center_helparticleroleaccess TO edify_gateway_ro;
GRANT SELECT (from_helparticle_id, to_helparticle_id) ON help_center_helparticle_related_articles TO edify_gateway_ro;
GRANT SELECT (id, article_id, title, steps) ON help_center_helpwalkthrough TO edify_gateway_ro;
GRANT SELECT (slug, term, definition, used_in, article_id) ON help_center_helpglossaryterm TO edify_gateway_ro;
GRANT SELECT (id, title, version_label, summary, published_at) ON help_center_helpreleasenote TO edify_gateway_ro;
GRANT SELECT (id) ON help_center_helparticleroutecontext TO edify_gateway_ro;
GRANT SELECT (article_id, term) ON help_center_helpsearchkeyword TO edify_gateway_ro;
GRANT SELECT (is_staff) ON "user" TO edify_gateway_ro;
-- The Policy Agreement Center (uploadcenter/agreement.go).
GRANT SELECT (id, title, description, slug, status, acknowledgement_reason, agreement_statement, required_reading_minutes, download_allowed, comment_required, acknowledgement_required, current_version_id) ON document_asset TO edify_gateway_ro;
GRANT SELECT (id, version_number, effective_date) ON document_version TO edify_gateway_ro;
GRANT SELECT (id, state, user_id, document_id, version_id, due_date, active_reading_seconds, session_count, responded_at, offline_attestation, created_at) ON document_acknowledgement TO edify_gateway_ro;
-- The Today page (internal/todaypage).
GRANT SELECT (user_id, todo_id, until) ON command_center_todo_snooze TO edify_gateway_ro;
GRANT SELECT (user_id, created_at) ON command_center_today_action TO edify_gateway_ro;
-- Contextual help (/help/context, internal/helpcontext) and Uganda cutover todos builders (Batch 9).
GRANT SELECT (article_id, route_pattern, workflow_status, priority) ON help_center_helparticleroutecontext TO edify_gateway_ro;
GRANT SELECT (id, requested_action, workflow_route, priority, due_date, state, school_id, sender_id, recipient_id, created_at) ON team_action TO edify_gateway_ro;
GRANT SELECT (id, partner_id, status, created_at) ON partner_invoice TO edify_gateway_ro;
GRANT SELECT (id, invoice_id, activity_id) ON partner_invoice_item TO edify_gateway_ro;
GRANT SELECT (id, staff_id, status, type, days, start_date) ON leave TO edify_gateway_ro;
GRANT SELECT (id, raised_by_user_id, raised_by_name, assigned_to_user_id, addressed_role, subject, requested_decision, severity, category, due_date, status, created_at) ON leadership_escalation TO edify_gateway_ro;
GRANT SELECT (id, staff_id, course_name, status, updated_at) ON pd_request TO edify_gateway_ro;
GRANT SELECT (id, debrief_id, action, issue, owner_user_id, status, due_date) ON daily_debrief_action TO edify_gateway_ro;
GRANT SELECT (id, assignee_id, created_by_id, note, status, due_date) ON staff_usage_follow_up TO edify_gateway_ro;
-- Evidence metadata read (uri is restricted to SECURITY DEFINER gateway_field_ops.read_evidence_uri).
GRANT SELECT (id, activity_id, quarantined, status, kind, original_name, mime_type) ON evidence_record TO edify_gateway_ro;
-- Native Go To-Do builders closing remaining passOnIf guards (Step 2).
GRANT SELECT (id, note, month_of_fy, created_at) ON target_catchup_plan TO edify_gateway_ro;
GRANT SELECT (status) ON impact_finding TO edify_gateway_ro;
GRANT SELECT (id, proposed_label, created_at) ON bt_loan_purpose_proposal TO edify_gateway_ro;
GRANT SELECT (id, school_name, instruction, priority, due_date, status, assigned_at) ON planning_oversight_follow_up TO edify_gateway_ro;
GRANT SELECT (fy) ON cce_regional_report TO edify_gateway_ro;
GRANT SELECT (created_at) ON cce_team_guidance TO edify_gateway_ro;

-- internal/detailpages, read only, after the page checks its reader (Admin
-- until each page has its record scope), and two columns the staff profile
-- and message threads already select.
GRANT SELECT (actual_observations, actual_outcome, expected_outcome, follow_up_note) ON activity TO edify_gateway_ro;
GRANT SELECT (acknowledged_at, category, detail, first_detected_at, owner_id, reopened_count, resolved_at)
  ON admin_system_incident TO edify_gateway_ro;
GRANT SELECT (confidentiality) ON document_asset TO edify_gateway_ro;
GRANT SELECT (change_summary, original_filename) ON document_version TO edify_gateway_ro;
GRANT SELECT (amount, fy, month, staff_id, status) ON monthly_fund_request TO edify_gateway_ro;
GRANT SELECT (certification_status, contract_status, notes) ON partner TO edify_gateway_ro;
GRANT SELECT (updated_at) ON document_acknowledgement TO edify_gateway_ro;
GRANT SELECT (measurement_end_fy, measurement_start_fy) ON project TO edify_gateway_ro;
GRANT SELECT (baseline_band) ON project_school_assignment TO edify_gateway_ro;
GRANT SELECT (staff_number) ON staff_profile TO edify_gateway_ro;
GRANT SELECT (created_at) ON messaging_messageparticipant TO edify_gateway_ro;

-- An activity's detail drawer (/my-plan/<id>, internal/myplan detail_*.go):
-- the Finance tab's figure (the view's activity_cost), the snapshot the view
-- reads first, the rate card it names and the order the cost lines are
-- shown in.
GRANT SELECT (cost_status, actual_accounted_spend, amount_disbursed, approved_operating_limit, calculated_at, sequence) ON activity_cost_snapshot TO edify_gateway_ro;
GRANT SELECT (label) ON cost_catalogue TO edify_gateway_ro;
GRANT SELECT (created_at) ON activity_schedule_cost_line TO edify_gateway_ro;
-- Fund Requests' monthly plans waiting for receipt (internal/weeklyrequest,
-- receipt_pending_plans): how and under what reference each was paid.
GRANT SELECT (disburse_method, disburse_reference) ON fund_request TO edify_gateway_ro;

-- Country Planning Oversight's eligible schools on the reporting date (a reopened
-- school's reopening) and, for a past year, the type each school had then
-- (requirements.operating_on_q, historical_adjustments).
GRANT SELECT (reopened_at) ON school TO edify_gateway_ro;
GRANT SELECT (school_id, old_value, field_name, changed_at) ON school_change_log TO edify_gateway_ro;
GRANT SELECT (previous_school_type, onboarded_at) ON core_school_onboarding TO edify_gateway_ro;

-- Its Open Follow-ups panel and the table's follow-up count
-- (_followups_panel, _followup_card, open_counts).
GRANT SELECT (fy, module, issue_type, activity_label, partner_name, cceo_name, program_lead_name,
  last_reminder_at, reminder_count) ON planning_oversight_follow_up TO edify_gateway_ro;

-- The Professional Development dashboard's approval queue
-- (HRPDDashboardService.supervisor_queue): an over-allocation request and a
-- schedule conflict are said on its row.
GRANT SELECT (is_exception, conflict_status) ON pd_request TO edify_gateway_ro;

-- Country Oversight's Execution & Completion stage (country_execution.dataset):
-- the day verified work was fully closed, the schedule trail that says what
-- was due when a period began, and when that trail began (its migration).
GRANT SELECT (activity_id, closed_at) ON activity_closure TO edify_gateway_ro;
GRANT SELECT (activity_id, from_day, to_day, from_status, changed_at) ON activity_schedule_change TO edify_gateway_ro;
GRANT SELECT (id, app, name, applied) ON django_migrations TO edify_gateway_ro;
-- Its locked period figures (snapshots.for_window) and the open execution
-- follow-ups each row counts (followups.open_counts), with the follow-ups
-- sent for Recent Activity.
GRANT SELECT (id, taken_at, country, period_type, period_start, version) ON execution_period_snapshot TO edify_gateway_ro;
GRANT SELECT (program_lead_staff_id, cceo_staff_id, remaining_value) ON planning_oversight_follow_up TO edify_gateway_ro;
-- Team Targets (apps.targets.team_targets.get_page): the supervision
-- portfolio and the Lead's catch-up plans (read, and whether a render would
-- advance one).
GRANT SELECT (id, staff_id, school_id) ON staff_school_assignment TO edify_gateway_ro;
GRANT SELECT (id, created_at, pl_user_id, staff_user_id, fy, month_of_fy, status, created_activity_ids, area_id)
  ON target_catchup_plan TO edify_gateway_ro;
-- Follow Up with PL for execution: the Lead's open follow-ups show what is
-- still open as last checked (live_remaining).
GRANT SELECT (live_remaining) ON planning_oversight_follow_up TO edify_gateway_ro;
-- Team Oversight's record drawer (oversight_detail_view): each cost line's
-- rate-card version.
GRANT SELECT (cost_setting_version) ON activity_schedule_cost_line TO edify_gateway_ro;
-- Team Oversight's record drawer for a hand-over (_assignment_item): its
-- notes, the rationale when no purpose is given.
GRANT SELECT (notes) ON partner_assignment TO edify_gateway_ro;
