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
