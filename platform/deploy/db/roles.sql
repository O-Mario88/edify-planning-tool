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
