-- Scheduling a school visit, the first save Go makes (docs/migration/27).
-- Applied by apply-roles.sh to a development, test or staging database;
-- never to production without the owner's approval at cutover.
--
-- Roles and grants only. Nothing here creates, alters or drops a table,
-- column, index or constraint, and no row is read or written.
--
--   edify_activities_rw  NOLOGIN, granted to edify_gateway. Exactly what one
--                        visit save writes (27.1, measured with the shadow
--                        harness, 26): the activity row, its day's batch,
--                        the audit row and its domain event, the target
--                        ledger's mark and the costs to follow; and what
--                        one move of a visit writes (docs/migration/29): the
--                        activity's day, batch and status, the day it
--                        joins, its timeline row; and what an edit of a
--                        visit's words writes (docs/migration/31): its goal
--                        and expected outcome. No DELETE anywhere, no
--                        UPDATE of an audit row or a timeline row, and no
--                        UPDATE of an activity beyond the move's columns
--                        and those two.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): the save opens a read-write transaction on purpose (08 §8.2).
--
-- The school row lock (27.8 §2): the existing save holds SELECT … FOR UPDATE
-- on the school while it asks the one-visit rule, and Postgres takes a row
-- lock only for a role with an UPDATE right on a column of the table. The
-- gateway holds none on school (dbguard.VerifyIdentity refuses one), so the
-- lock is taken by gateway_lock.lock_school(id): a SECURITY DEFINER function
-- owned by edify_school_lock_owner, a NOLOGIN role no one is a member of
-- that holds UPDATE (updated_at) on school and nothing else of it. The
-- function writes nothing; it takes the same row lock Django's saves take, in
-- the caller's transaction, so a Go save and a Django save at the same school
-- wait for each other. The gateway gets EXECUTE on it and nothing else.
-- A new database object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_activities_rw') THEN
    CREATE ROLE edify_activities_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

-- Start from nothing, so re-running after the save changes never leaves a
-- grant behind that the code no longer needs.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_activities_rw;
GRANT USAGE ON SCHEMA public TO edify_activities_rw;
GRANT edify_activities_rw TO edify_gateway;

-- The activity: one INSERT of the row as `_create`, the catalogue snapshot,
-- the SSA verdict and the day's join leave it (27.6), every NOT NULL column
-- at its model default. The price (est_cost_cents, cost_missing), evidence,
-- verification and payment columns are inserted at their defaults only:
-- setting them is the pricing's and the later saves' work.
GRANT INSERT (
  id, created_at, updated_at, activity_type, fy, quarter, delivery_type, executor_type, status,
  evidence_status, ia_verification_status, payment_status, reschedule_count, est_cost_cents, cost_missing,
  environment, source, school_id, responsible_staff_id, scheduled_date, planned_date, planned_month,
  planned_week, purpose_type, purpose_intervention, focus_intervention, secondary_focus_interventions,
  activity_purpose_text, expected_outcome, ssa_collection_expected, attended_school_ids,
  salesforce_activity_type, catalogue_item_id, catalogue_version, activity_name_snapshot,
  activity_type_snapshot, delivery_method_snapshot, evidence_profile_snapshot, costing_profile_snapshot,
  salesforce_record_type_snapshot, recommendation_reason, recommendation_source, override_reason,
  source_ssa_id, source_ssa_verification_state, source_score, source_classification, ssa_recommendation_id,
  ssa_alignment, ssa_deviation_reason, planning_source, activity_context_type, support_rationale, venue,
  primary_driver_type, primary_driver_id, driver_reason, delivery_contact_name, approval_owner_id,
  owner_decision_note, visit_justification, partner_date_set_by, meeting_kind, daily_visit_batch_id
) ON activity TO edify_activities_rw;
-- A Training Follow Up names the session it follows, and that session's SSA
-- decides whether Go may take the save.
GRANT INSERT (follow_up_of_activity_id) ON activity TO edify_activities_rw;
GRANT SELECT (source_ssa_id) ON activity TO edify_activities_rw;

-- The day the visit joins: made with its defaults when the owner has none
-- that day (the pricing that follows fills its figures, in Django). The
-- existing join locks the day's row (SELECT … FOR UPDATE), which needs an
-- UPDATE right on some column; the timestamp is the harmless one.
GRANT INSERT (
  id, created_at, updated_at, responsible_user, visit_date, district_type, rate_snapshot,
  daily_pool_amount, school_count, per_school_amount, secondary_district_group_id, workload_snapshot
) ON daily_visit_batch TO edify_activities_rw;
GRANT UPDATE (updated_at) ON daily_visit_batch TO edify_activities_rw;

-- The audit chain: the tail is read and rows are added; nothing is updated.
GRANT SELECT (seq, hash) ON audit_log TO edify_activities_rw;
GRANT INSERT (id, seq, action, subject_kind, subject_id, actor_id, actor_role, payload, ip_address,
              user_agent, correlation_id, success, reason, prev_hash, hash, created_at)
  ON audit_log TO edify_activities_rw;
GRANT INSERT (id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at)
  ON domain_event_log TO edify_activities_rw;

-- The target ledger's mark: upserted once the save commits
-- (apps.targets.ledger_sync._write_marks: marked_at on conflict).
-- An upsert reads the columns its conflict names and its SET reads.
GRANT SELECT (owner_id, fy, marked_at) ON target_ledger_dirty TO edify_activities_rw;
GRANT INSERT (owner_id, fy, marked_at) ON target_ledger_dirty TO edify_activities_rw;
GRANT UPDATE (marked_at) ON target_ledger_dirty TO edify_activities_rw;

-- The costs to follow: what the save kept for the pricing, which Django
-- settles after the save commits (27.2). Written, never read back here.
GRANT INSERT (created_at, updated_at, owners, asked_by, asked_by_role, steps, provenance, attempts,
              held_reason)
  ON daily_visit_costs_to_follow TO edify_activities_rw;
-- Its id, read back (RETURNING) to ask for that row's settling.
GRANT SELECT (id) ON daily_visit_costs_to_follow TO edify_activities_rw;

-- A Training Follow Up answers the school's open recommendation for its
-- intervention (apps.ssa.plan_alignment.link_recommendations): planned, by
-- this activity. Its other columns stay the SSA's.
GRANT UPDATE (state, planned_activity_id, decided_at, updated_at) ON ssa_recommendation TO edify_activities_rw;

-- The lock's owner and function.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_school_lock_owner') THEN
    CREATE ROLE edify_school_lock_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_school_lock_owner;
GRANT SELECT (id) ON school TO edify_school_lock_owner;
GRANT UPDATE (updated_at) ON school TO edify_school_lock_owner;

CREATE SCHEMA IF NOT EXISTS gateway_lock AUTHORIZATION edify_school_lock_owner;
REVOKE ALL ON SCHEMA gateway_lock FROM PUBLIC;

SET ROLE edify_school_lock_owner;
CREATE OR REPLACE FUNCTION gateway_lock.lock_school(target_id varchar) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  PERFORM 1 FROM public.school s WHERE s.id = target_id FOR UPDATE;
  RETURN FOUND;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_lock.lock_school(varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_lock TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_lock.lock_school(varchar) TO edify_activities_rw;

-- What the save reads to decide (27.6), and nothing else of these tables.
GRANT SELECT (id, school_id, name, school_type, operational_status, district_id, cluster_id, deleted_at, created_at)
  ON school TO edify_activities_rw;
GRANT SELECT (id, name, district_type) ON district TO edify_activities_rw;
GRANT SELECT (school_id, staff_id, created_at) ON staff_school_assignment TO edify_activities_rw;
GRANT SELECT (id, user_id, deleted_at, primary_district_id, created_at) ON staff_profile TO edify_activities_rw;
GRANT SELECT (id, name, roles, active_role) ON "user" TO edify_activities_rw;
GRANT SELECT (id, stable_code, workflow_kind, display_name, activity_type, delivery_method, evidence_profile,
              salesforce_record_type, costing_profile, status, standard_support, counts_toward_client_visit,
              requires_school, requires_cluster, is_training_course, participant_mode, effective_from, effective_to)
  ON activity_catalogue_item TO edify_activities_rw;
GRANT SELECT (id, catalogue_item_id, mapping_mode, is_primary, priority, active) ON activity_intervention_mapping TO edify_activities_rw;
GRANT SELECT (catalogue_item_id, version) ON activity_catalogue_version TO edify_activities_rw;
-- An item scheduled for the first time gets its version 1 (_latest_version),
-- a snapshot of the item as it stood. Versions are only ever added.
GRANT SELECT (target_audience, support_objective) ON activity_catalogue_item TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, catalogue_item_id, version, snapshot, change_reason, created_by)
  ON activity_catalogue_version TO edify_activities_rw;
-- A Core school's visit takes one of its package's slots, and the package's
-- completed counts are kept from them.
GRANT SELECT (id, school_id, fy, status, visits_completed, trainings_completed) ON core_plan TO edify_activities_rw;
GRANT UPDATE (visits_completed, trainings_completed, updated_at) ON core_plan TO edify_activities_rw;
GRANT SELECT (id, core_plan_id, activity_type, sequence_number, status, activity_id) ON core_activity_slot TO edify_activities_rw;
GRANT UPDATE (status, activity_id, scheduled_for, scheduled_month, scheduled_week, assigned_staff_id, owner, updated_at)
  ON core_activity_slot TO edify_activities_rw;
-- The Core Schools form hands a package slot to a partner: its assignment row,
-- the slot's partner, and what decides whether the partner may take it.
GRANT UPDATE (assigned_partner_id, assigned_partner_name) ON core_activity_slot TO edify_activities_rw;
GRANT SELECT (activity_type, weight_hundredths, version, active) ON activity_workload_weight TO edify_activities_rw;
-- A school owner decides on a visit request: the decision's own columns, and
-- a declined Core visit's slot handed back whole.
GRANT UPDATE (owner_decided_at, owner_decided_by, owner_decision_note) ON activity TO edify_activities_rw;
-- Starting work is gateway_completion.start_visit's alone: the start's moment
-- is a protected column (dbguard), never the gateway's to write.
REVOKE UPDATE (execution_started_at) ON activity FROM edify_activities_rw;
GRANT UPDATE (assigned_staff_name) ON core_activity_slot TO edify_activities_rw;
-- A monthly request carried along with a planner's change is told to its people.
GRANT SELECT (id, total_amount, status, period_key, submitted_by_user_id, reviewed_by_user_id)
  ON fund_request TO edify_activities_rw;
-- An owner's weekly request is routed by the role stamped on it
-- (weekly_service._owner_role); gateway_day_money.send_week writes it.
GRANT SELECT (responsible_role) ON weekly_fund_request TO edify_activities_rw;
-- An officer's accountability and reimbursement drawers read their advances.
GRANT SELECT (activity_id, amount, disbursed_amount, responsible_user_id, reimbursed_amount, reimburse_reference,
              reimbursed_at) ON advance_request TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, assigning_staff_id, focus_intervention, expected_activity_type, status, notes,
              partner_id, school_id, support_type, training_number, visit_number, purpose_of_visit, assignment_mode,
              catalogue_item_id, catalogue_snapshot, override_reason, recommendation_reason, source_ssa_id,
              source_activity_id, reassignment_sequence, training_course_id, resolution, resolution_note, outside_ssa,
              monitoring_staff_id, purpose)
  ON partner_assignment TO edify_activities_rw;
-- assigning_staff_id, expected_activity_type, created_at: the Planning
-- hand-over's double-submit guard (assign_partner_action_view's
-- _recent_duplicate).
GRANT SELECT (id, school_id, partner_id, status, outside_ssa, purpose_of_visit, support_type, visit_number, training_number,
              assigning_staff_id, expected_activity_type, created_at)
  ON partner_assignment TO edify_activities_rw;
GRANT SELECT (id, name, user_id, activity_codes, deleted_at, active_status, partner_role) ON partner TO edify_activities_rw;
GRANT SELECT (partner_id, lifted_at) ON partner_hold TO edify_activities_rw;
GRANT SELECT (catalogue_item_id, milestone_id, active) ON hr_milestone_activity_rule TO edify_activities_rw;
GRANT SELECT (id, title) ON hr_priority_milestone TO edify_activities_rw;
GRANT SELECT (school_id, field_name, status) ON data_quality_issue TO edify_activities_rw;
GRANT SELECT (partner_delivery_allowed) ON activity_catalogue_item TO edify_activities_rw;
GRANT SELECT (id, school_id, fy, date_of_ssa, created_at, average_score, verification_status, deleted_at)
  ON ssa_record TO edify_activities_rw;
GRANT SELECT (id, ssa_record_id, intervention, score) ON ssa_score TO edify_activities_rw;
GRANT SELECT (id, school_id, intervention, state, created_at) ON ssa_recommendation TO edify_activities_rw;
GRANT SELECT (country, fy, follow_up_visit_requires_prior_training, created_at) ON fiscal_year_planning_policy TO edify_activities_rw;
GRANT SELECT (id, activity_type, planned_date, deleted_at, responsible_staff_id, assigned_partner_id, status,
              school_id, catalogue_item_id, purpose_type)
  ON activity TO edify_activities_rw;
GRANT SELECT (id, responsible_user, visit_date, created_at) ON daily_visit_batch TO edify_activities_rw;
GRANT SELECT (covering_staff_id, original_staff_id, start_datetime, end_datetime, status, leave_request_id, created_at)
  ON temporary_coverage_assignment TO edify_activities_rw;

-- ── The second save: moving a scheduled school visit (docs/migration/29) ──
-- The activity's row is locked (SELECT … FOR UPDATE, which the UPDATE right
-- below allows) and its day moved: exactly the columns services.reschedule,
-- the day's leaving and the day's join write for 29.1's case. Its price,
-- evidence, verification, payment, owner, school and kind stay unwritable
-- (dbguard.protectedColumns).
GRANT SELECT (last_reason, updated_at) ON activity TO edify_activities_rw;
GRANT UPDATE (scheduled_date, fy, quarter, planned_date, planned_month, planned_week, reschedule_count,
              last_reason, status, daily_visit_batch_id, updated_at)
  ON activity TO edify_activities_rw;
-- A confirmed SSA's recommendations (the outbox handler
-- ssa.recommendations.generate): recorded, refreshed, or retired.
GRANT INSERT (id, created_at, updated_at, condition_key, intervention, fy, score, score_band, rank, reason,
              unmapped_reason, state, decision_reason, expires_on, engine_version, recommended_item_id, school_id,
              ssa_record_id, supersedes_id)
  ON ssa_recommendation TO edify_activities_rw;
GRANT UPDATE (score, score_band, rank, reason, decision_reason) ON ssa_recommendation TO edify_activities_rw;
GRANT SELECT (condition_key, ssa_record_id, fy) ON ssa_recommendation TO edify_activities_rw;
-- The Work Plan's Add (create for a non-school programme activity): the
-- columns only such work sets.
GRANT INSERT (programme_activity_type, programme_delivery_mode, planned_school_count, event_district_id,
              support_rationale, venue, primary_driver_type, primary_driver_id, driver_reason, end_date,
              expected_participants)
  ON activity TO edify_activities_rw;
-- Work completed on another day than planned moves to that day and keeps the
-- day it was planned for (apps.activities.completed_day._move).
GRANT UPDATE (planned_date_before_completion) ON activity TO edify_activities_rw;
-- The day joined takes the move's reason when it differs (reschedule_within_batch).
GRANT SELECT (reason) ON daily_visit_batch TO edify_activities_rw;
GRANT UPDATE (reason) ON daily_visit_batch TO edify_activities_rw;
-- The timeline row a moved day writes (apps.activities.schedule_trail).
GRANT INSERT (id, kind, from_day, to_day, from_status, to_status, reason, changed_at, activity_id)
  ON activity_schedule_change TO edify_activities_rw;
-- The owner-weeks and owner-months the moved visit's lines sit in, kept for
-- the pricing (sync_weekly/monthly_*_for_activity).
GRANT SELECT (activity_id, responsible_user, fiscal_year, month, week_start_date)
  ON activity_schedule_cost_line TO edify_activities_rw;
-- Whether the existing save would write notices after the move (an open
-- overdue reminder on the activity, an open day-off notice for its owner):
-- such a move is handed on. Nothing of a notice's words is read.
GRANT SELECT (id, recipient_id, source_event_type, context_type, context_id, resolved_at)
  ON notification TO edify_activities_rw;

-- ── The fourth save: editing a scheduled school visit's words (docs/migration/31) ──
-- patch_activity's save for 31.1's case: the goal and the expected outcome
-- (updated_at and the row's lock are already granted for the move). Free
-- text only: no price, day, owner, school, purpose or focus.
GRANT UPDATE (activity_purpose_text, expected_outcome) ON activity TO edify_activities_rw;

-- The fifth save, an In-school Training and its school visit
-- (docs/migration/32): the course the picker offers (its staff delivery,
-- universality, category and indicator), its intervention mapping's
-- intervention, whether the officer has a ceiling for it, and the two
-- columns that join the pair on insert. No UPDATE: the training is
-- inserted naming the visit already inserted.
GRANT SELECT (staff_delivery_allowed, universal_training, training_category, ssa_indicator_label)
  ON activity_catalogue_item TO edify_activities_rw;
GRANT SELECT (intervention) ON activity_intervention_mapping TO edify_activities_rw;
GRANT SELECT (staff_id, training_id, fy) ON training_ceiling TO edify_activities_rw;
GRANT INSERT (training_course_id, paired_school_visit_id) ON activity TO edify_activities_rw;

-- ── The seventh save: a cluster Group Training (docs/migration/38) ──
-- Granted by the coordinator's decision (38.5 §1), production at cutover
-- with the owner's approval like every role change. Exactly what the save
-- inserts and reads: the session's cluster, participant and materials
-- columns on insert; one invitation per ticked school (its serial id from
-- the table's own sequence); the cluster, its members' clustering, the
-- catalogue's cluster delivery and the cluster's sessions that the
-- recommendation engine and the duplicate guard read. No UPDATE of anything
-- new, and nothing of the money, lifecycle, evidence, verification or
-- ownership columns (dbguard.protectedColumns keeps refusing them).
GRANT INSERT (cluster_id, expected_participants, participants_per_school, cluster_school_count_snapshot,
              schools_invited, teachers_per_school, leaders_per_school, other_per_school, printing_pages,
              photocopy_pages, photocopy_copies)
  ON activity TO edify_activities_rw;
GRANT INSERT (created_at, updated_at, invited, attended, is_guest, teachers, leaders, other, recorded_by,
              activity_id, school_id)
  ON cluster_activity_attendance TO edify_activities_rw;
GRANT USAGE ON SEQUENCE cluster_activity_attendance_id_seq TO edify_activities_rw;
GRANT SELECT (id, deleted_at, responsible_staff_id, district_id) ON cluster TO edify_activities_rw;
GRANT SELECT (cluster_status) ON school TO edify_activities_rw;
GRANT SELECT (cluster_delivery_allowed) ON activity_catalogue_item TO edify_activities_rw;
GRANT SELECT (cluster_id, fy, focus_intervention, created_at) ON activity TO edify_activities_rw;

-- The cluster row lock (38.5 §2): `_create` holds SELECT … FOR UPDATE on the
-- cluster (3232) so two saves cannot both pass the duplicate guard. As for
-- the school, the lock is taken by gateway_lock.lock_cluster(id), a
-- SECURITY DEFINER function owned by edify_cluster_lock_owner, a NOLOGIN
-- role no one is a member of that holds UPDATE (updated_at) on cluster and
-- nothing else of it. The function writes nothing. The gateway gets EXECUTE
-- on it and nothing else. A new database object: production needs the
-- owner's approval at cutover.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_lock_owner') THEN
    CREATE ROLE edify_cluster_lock_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_cluster_lock_owner;
GRANT SELECT (id) ON cluster TO edify_cluster_lock_owner;
GRANT UPDATE (updated_at) ON cluster TO edify_cluster_lock_owner;
GRANT USAGE, CREATE ON SCHEMA gateway_lock TO edify_cluster_lock_owner;

SET ROLE edify_cluster_lock_owner;
CREATE OR REPLACE FUNCTION gateway_lock.lock_cluster(target_id varchar) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  PERFORM 1 FROM public.cluster c WHERE c.id = target_id FOR UPDATE;
  RETURN FOUND;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_lock.lock_cluster(varchar) FROM PUBLIC;
RESET ROLE;
-- The function made, its owner keeps no right to add others.
REVOKE CREATE ON SCHEMA gateway_lock FROM edify_cluster_lock_owner;

GRANT EXECUTE ON FUNCTION gateway_lock.lock_cluster(varchar) TO edify_activities_rw;

-- ── The eighth save: a Group Training delivered online (docs/migration/48) ──
-- Production at cutover with the owner's approval like every role change.
-- An online session is free and joins no day, so the existing save writes
-- its cost revision inside the save (_price_activity's online branch): the
-- delivery mode and the period columns on the row (its price, UGX 0 and not
-- missing, is already insertable above), and one current cost snapshot
-- with its figures from the existing pricing (read through the day check).
-- Insert only: no snapshot is changed, superseded or removed by Go, and no
-- cost line, advance or fund request is written (dbguard keeps refusing).
GRANT INSERT (programme_delivery_mode, week_start_date, week_end_date, month, fiscal_year)
  ON activity TO edify_activities_rw;
GRANT INSERT (created_at, updated_at, id, sequence, is_current, activity_catalogue_item_id,
              activity_catalogue_version, costing_profile_version, reference_cost, operational_cost,
              approved_operating_limit, amount_disbursed, actual_accounted_spend, unused_balance,
              reimbursement_amount, calculation_inputs, reference_breakdown, operational_breakdown, warnings,
              missing_configuration, calculated_at, calculated_by, recalculation_reason, approved_by, approved_at,
              cost_status, activity_id, operational_rate_card_id, reference_rate_card_id, supersedes_id)
  ON activity_cost_snapshot TO edify_activities_rw;

-- ── The outbox's bt.ssa.confirmed (docs/migration/189 §4) ──
-- Production at cutover with the owner's approval like every role change.
-- ensure_case_from_verified_ssa: a verified SSA's Financial Health or
-- Government Requirements weakness opens the school's one Business
-- Transformation case, its trigger and recommendations, and records the
-- year's Uganda policy the first time a year is used. Insert only: no case,
-- trigger, recommendation or policy is changed or removed by Go.
GRANT SELECT (verified_by_user_id, uploaded_by, verified_at) ON ssa_record TO edify_activities_rw;
GRANT SELECT (id, country_code, fy, active, financial_health_max_score, government_requirements_max_score)
  ON bt_policy TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, country_code, fy, financial_health_max_score,
              government_requirements_max_score, loan_use_verification_days, active, created_by)
  ON bt_policy TO edify_activities_rw;
GRANT SELECT (id, school_id, status, deleted_at, created_at) ON bt_case TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, source, environment, status, opened_fy, triage_decision, triage_reason,
              closure_reason, school_id)
  ON bt_case TO edify_activities_rw;
GRANT SELECT (id, trigger_type, source_id) ON bt_case_trigger TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, trigger_type, source_id, source_snapshot, triggered_by, case_id)
  ON bt_case_trigger TO edify_activities_rw;
GRANT SELECT (id, trigger_id, kind) ON bt_case_recommendation TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, kind, status, reason, source_intervention, source_score, case_id, trigger_id)
  ON bt_case_recommendation TO edify_activities_rw;

-- ── The outbox's bt.activity.state_changed (docs/migration/189 §4) ──
-- project_activity_state: a loan-use verification's requirement and result
-- follow the visit's IA state. The requirement row is locked (SELECT … FOR
-- UPDATE, which the status right below allows) as the existing handler locks
-- it; the evidence notices are resolved through
-- gateway_notifications.resolve_condition.
GRANT SELECT (ia_confirmed_at) ON activity TO edify_activities_rw;
GRANT SELECT (id, activity_id, due_date) ON bt_loan_verification_requirement TO edify_activities_rw;
GRANT UPDATE (status, verified_at, updated_at) ON bt_loan_verification_requirement TO edify_activities_rw;
GRANT SELECT (id, requirement_id) ON bt_loan_use_result TO edify_activities_rw;
GRANT UPDATE (verification_status, ia_verified_at, updated_at) ON bt_loan_use_result TO edify_activities_rw;

-- ── The outbox's projects.baselines.capture and projects.impact.refresh ──
-- (docs/migration/189 §4.) capture_missing_baselines fills an enrolment's
-- empty baseline once (locked as the existing capture locks it, which the
-- update right below allows); refresh_follow_up writes the verdict, the day
-- the follow-up is due and the assessment that judges it, and
-- stamp_measurement_rule the rule an unstamped enrolment is measured under.
-- No enrolment is inserted or removed by Go.
GRANT SELECT (id, project_id, school_id, matched_intervention, impact_classification, mapping_id, baseline_ssa_id,
              baseline_score, start_date, created_at)
  ON project_school_assignment TO edify_activities_rw;
GRANT UPDATE (baseline_ssa_id, baseline_score, baseline_band, baseline_captured_at, impact_classification, updated_at,
              follow_up_due_on, follow_up_ssa_id, follow_up_score, mapping_id, mapping_version)
  ON project_school_assignment TO edify_activities_rw;
GRANT SELECT (id, intervention, deleted_at) ON project TO edify_activities_rw;
GRANT SELECT (id, country) ON region TO edify_activities_rw;
GRANT SELECT (actual_delivery_date, scheduled_date, catalogue_item_id, project_id) ON activity TO edify_activities_rw;
GRANT SELECT (date_of_ssa) ON ssa_record TO edify_activities_rw;
GRANT SELECT (id, version, follow_up_min_days, follow_up_expected_days, follow_up_max_days, expected_direction,
              measurement_role, min_meaningful_change, intervention, country, status, active, catalogue_item_id,
              not_ssa_measured_reason, effective_from, updated_at)
  ON activity_intervention_mapping TO edify_activities_rw;

-- ── The outbox's Salesforce and NetSuite handlers (docs/migration/189 §4) ──
-- apps.integrations.services: the transport is not built, so a handler only
-- records a reference staff pasted as reconciled (one ledger row per record);
-- it reads the record's reference and never changes the record.
GRANT SELECT (id, system, context_type, context_id, status, external_id, last_error, synced_at, updated_at)
  ON integration_sync TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, system, context_type, context_id, external_id, status, last_error, synced_at)
  ON integration_sync TO edify_activities_rw;
GRANT UPDATE (status, external_id, last_error, synced_at, updated_at) ON integration_sync TO edify_activities_rw;
GRANT SELECT (salesforce_activity_id) ON activity TO edify_activities_rw;
GRANT SELECT (id, salesforce_status, salesforce_loan_id, deleted_at) ON bt_mfi_loan TO edify_activities_rw;
GRANT SELECT (id) ON bt_funding_facility_tranche TO edify_activities_rw;
GRANT SELECT (tranche_id) ON bt_funding_facility_tranche_reversal TO edify_activities_rw;
GRANT SELECT (id, accountability_netsuite_id) ON advance_request TO edify_activities_rw;

-- ── The outbox's notification.email (docs/migration/189 §4) ──
-- email_delivery.handle_email: one queued email copy's status as it is sent,
-- or why it was not. It reads the notification, its sender's name and the
-- recipient's address; no copy is inserted or removed by Go.
GRANT SELECT (id, notification_id, recipient_id, channel, status, attempts, last_error, provider_message_id, sent_at,
              failed_at) ON notification_delivery TO edify_activities_rw;
GRANT UPDATE (status, updated_at, attempts, last_error, provider_message_id, sent_at, failed_at)
  ON notification_delivery TO edify_activities_rw;
-- The notification's words and state are the gateway's already (roles.sql);
-- the copy's "Sent" time also reads when it was last reminded.
GRANT SELECT (last_reminded_at) ON notification TO edify_activities_rw;
GRANT SELECT (id, name, email, is_active, deleted_at) ON "user" TO edify_activities_rw;

-- ── The scheduler's target_ledger_sync (docs/migration/189 §4) ──
-- TargetAchievementService.rebuild for every active CCEO and Program Lead:
-- a new source's ledger row, a changed source's row rewritten, a row whose
-- source left the year's workflow reversed. No ledger row is removed.
GRANT SELECT (id, user_id, area_id, source_type, source_id, fy, activity_date, credited_month, credited_quarter, quantity,
              validation_status, validated_at)
  ON target_achievement_ledger TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, user_id, area_id, source_type, source_id, fy, activity_date, credited_month,
              credited_quarter, quantity, validation_status, validated_at)
  ON target_achievement_ledger TO edify_activities_rw;
GRANT UPDATE (fy, activity_date, credited_month, credited_quarter, validation_status, validated_at, updated_at)
  ON target_achievement_ledger TO edify_activities_rw;
GRANT SELECT (id, key, active) ON target_area TO edify_activities_rw;
GRANT SELECT (id, status, roles, deleted_at, created_at) ON "user" TO edify_activities_rw;
GRANT SELECT (id, user_id) ON staff_profile TO edify_activities_rw;

-- ── The scheduler's data_quality_scan (docs/migration/189 §4) ──
-- scan_all: duplicate pairs proposed by name similarity within a district,
-- then every operating school's quality issues reconciled (resolved when
-- cleared, refreshed, reopened, or added; never removed). The pair's schools
-- are flagged potential only from none, through
-- gateway_dataquality.flag_potential_duplicates: the gateway holds no right
-- to change a school (dbguard), so the one column is changed by a function
-- owned by edify_dataquality_owner, a NOLOGIN role no one is a member of,
-- holding UPDATE (duplicate_status) on school and nothing else of it.
-- A new database object: production needs the owner's approval at cutover.
GRANT SELECT (id, name, district_id, duplicate_status, created_at, deleted_at, operational_status, latitude, longitude,
              school_phone, primary_contact_name, school_type, sub_county_id, enrollment, account_owner_id,
              account_owner_status, account_owner_name_raw, cluster_id, current_fy_ssa_status)
  ON school TO edify_activities_rw;
GRANT SELECT (school_id) ON school_geo_point TO edify_activities_rw;
GRANT SELECT (id, school_id, candidate_id) ON school_duplicate_candidate TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, school_id, candidate_id, score, reasons, resolved)
  ON school_duplicate_candidate TO edify_activities_rw;
GRANT SELECT (id, school_id, condition_key, issue_type, severity, current_value, suggested_fix, status, resolved_at,
              created_at)
  ON data_quality_issue TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, issue_type, severity, field_name, current_value, suggested_fix, status,
              school_id, condition_key)
  ON data_quality_issue TO edify_activities_rw;
GRANT UPDATE (status, resolved_at, severity, current_value, suggested_fix) ON data_quality_issue TO edify_activities_rw;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_dataquality_owner') THEN
    CREATE ROLE edify_dataquality_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_dataquality_owner;
GRANT SELECT (id, duplicate_status) ON school TO edify_dataquality_owner;
GRANT UPDATE (duplicate_status) ON school TO edify_dataquality_owner;

CREATE SCHEMA IF NOT EXISTS gateway_dataquality AUTHORIZATION edify_dataquality_owner;
REVOKE ALL ON SCHEMA gateway_dataquality FROM PUBLIC;
-- Re-runnable: the owner may (re)define its function, then loses the right.
GRANT USAGE, CREATE ON SCHEMA gateway_dataquality TO edify_dataquality_owner;

SET ROLE edify_dataquality_owner;
CREATE OR REPLACE FUNCTION gateway_dataquality.flag_potential_duplicates(target_ids varchar[]) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.school SET duplicate_status = 'potential'
   WHERE id = ANY(target_ids) AND duplicate_status = 'none';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_dataquality.flag_potential_duplicates(varchar[]) FROM PUBLIC;
RESET ROLE;
-- The function made, its owner keeps no right to add others.
REVOKE CREATE ON SCHEMA gateway_dataquality FROM edify_dataquality_owner;

GRANT USAGE ON SCHEMA gateway_dataquality TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_dataquality.flag_potential_duplicates(varchar[]) TO edify_activities_rw;

-- ── The scheduler's interaction_rollup (docs/migration/189 §4) ──
-- rollup_interaction_days: yesterday's request events folded into one row a
-- person a day, then raw events past their 14-day retention pruned, as the
-- existing job prunes them. Go code removes nothing itself (dbguard): the
-- prune is gateway_telemetry.prune_interaction_events, owned by
-- edify_telemetry_owner, a NOLOGIN role no one is a member of, holding only
-- what that one statement needs.
-- A new database object: production needs the owner's approval at cutover.
GRANT SELECT (id, user_id, role, occurred_at, method, route) ON interaction_event TO edify_activities_rw;
GRANT SELECT (id, user_id, day, role, active_seconds, planning_seconds, execution_seconds, request_count, write_count)
  ON interaction_day TO edify_activities_rw;
GRANT INSERT (id, user_id, day, role, active_seconds, planning_seconds, execution_seconds, request_count, write_count)
  ON interaction_day TO edify_activities_rw;
GRANT UPDATE (role, active_seconds, planning_seconds, execution_seconds, request_count, write_count)
  ON interaction_day TO edify_activities_rw;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_telemetry_owner') THEN
    CREATE ROLE edify_telemetry_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_telemetry_owner;
GRANT SELECT (occurred_at) ON interaction_event TO edify_telemetry_owner;
GRANT DELETE ON interaction_event TO edify_telemetry_owner;

CREATE SCHEMA IF NOT EXISTS gateway_telemetry AUTHORIZATION edify_telemetry_owner;
REVOKE ALL ON SCHEMA gateway_telemetry FROM PUBLIC;
-- Re-runnable: the owner may (re)define its function, then loses the right.
GRANT USAGE, CREATE ON SCHEMA gateway_telemetry TO edify_telemetry_owner;

SET ROLE edify_telemetry_owner;
CREATE OR REPLACE FUNCTION gateway_telemetry.prune_interaction_events(before timestamptz) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  removed integer;
BEGIN
  DELETE FROM public.interaction_event WHERE occurred_at < before;
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_telemetry.prune_interaction_events(timestamptz) FROM PUBLIC;
RESET ROLE;
REVOKE CREATE ON SCHEMA gateway_telemetry FROM edify_telemetry_owner;

GRANT USAGE ON SCHEMA gateway_telemetry TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_telemetry.prune_interaction_events(timestamptz) TO edify_activities_rw;

-- ── The scheduler's field_debrief_recurring_issues (docs/migration/189 §4) ──
-- RecurringIssueDetectionService.scan: a challenge recurring in a scope's
-- debriefs opens or refreshes its insight, escalations are raised to the
-- Country Director and the Regional Vice President, and the people told are
-- remembered on the insight. No insight is removed by Go.
GRANT SELECT (id, debrief_id, challenge_type, created_at) ON daily_debrief_challenge TO edify_activities_rw;
GRANT SELECT (id, date, staff_id, partner_id, linked_school_ids, deleted_at, is_restricted_incident)
  ON daily_debrief TO edify_activities_rw;
GRANT SELECT (id, supervisee_id, supervisor_id) ON staff_supervisor_assignment TO edify_activities_rw;
GRANT SELECT (country) ON staff_profile TO edify_activities_rw;
GRANT SELECT (id, scope, scope_id, challenge_type, title, description, escalation_level, status, notified_user_ids)
  ON daily_debrief_insight TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, scope, scope_id, challenge_type, title, description, occurrence_count,
              window_start, window_end, debrief_ids, escalation_level, status, notified_user_ids)
  ON daily_debrief_insight TO edify_activities_rw;
GRANT UPDATE (occurrence_count, debrief_ids, window_start, window_end, description, escalation_level, notified_user_ids)
  ON daily_debrief_insight TO edify_activities_rw;

-- ── The scheduler's fiscal_year_rollover check (docs/migration/189 §4) ──
-- Whether the operational year's roll-over is recorded complete.
GRANT SELECT (fy, completed_at) ON hr_fiscal_year_rollover TO edify_activities_rw;
-- Whether an analytics report schedule is due (analytics_report_delivery).
GRANT SELECT (id, is_active, next_run_at) ON analytics_report_schedule TO edify_activities_rw;

-- ── The scheduler's loan_tracking_notifications (docs/migration/189 §4) ──
-- run_loan_tracking_notifications: application follow-ups, repayment
-- follow-ups and the Regional Vice President's monthly report, each claimed
-- once in the permanent delivery log. It reads the loans and their schedule
-- and repayments; it changes none of them.
GRANT SELECT (id, delivery_kind, subject_id, period_key, recipient_id) ON bt_loan_tracking_delivery_log TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, delivery_kind, subject_id, period_key, recipient_id)
  ON bt_loan_tracking_delivery_log TO edify_activities_rw;
GRANT SELECT (id, status, next_follow_up_on, school_id, deleted_at, created_at, submitted_at)
  ON bt_loan_application TO edify_activities_rw;
GRANT SELECT (id, school_id, mfi_id, status, repayment_frequency, disbursement_date, maturity_date, term_months,
              disbursed_amount, created_at)
  ON bt_mfi_loan TO edify_activities_rw;
GRANT SELECT (id, name) ON bt_mfi_organization TO edify_activities_rw;
GRANT SELECT (loan_id, as_of_date, next_payment_date, created_at) ON bt_repayment_snapshot TO edify_activities_rw;
GRANT SELECT (id, loan_id, schedule_version, due_date, principal_due, interest_due, fee_due)
  ON bt_loan_repayment_installment TO edify_activities_rw;
GRANT SELECT (installment_id, transaction_id, component, amount) ON bt_repayment_allocation TO edify_activities_rw;
GRANT SELECT (id, loan_id, kind, amount, value_date) ON bt_repayment_transaction TO edify_activities_rw;
GRANT SELECT (account_owner_id, region_id) ON school TO edify_activities_rw;
GRANT SELECT (id, country) ON region TO edify_activities_rw;
GRANT SELECT (active_role, is_active) ON "user" TO edify_activities_rw;

-- ── The scheduler's notification jobs (daily_digest, …; docs/migration/189 §4) ──
-- They write through the existing trigger (gateway_notifications.notify_workflow)
-- and read whether today's notice was already sent.
GRANT SELECT (source_event_id) ON notification TO edify_activities_rw;

-- ── The scheduler's weekly_debrief_reports (docs/migration/189 §4) ──
-- generate_pl_report: each lead's week as a draft report (regenerated in
-- place) or a new version over a finalized one. No report is removed.
GRANT SELECT (id, submitted_by_user_id, kind, date, linked_school_ids, linked_activity_ids, challenges_faced,
              what_did_not_go_well, what_went_well, recommendations, status)
  ON daily_debrief TO edify_activities_rw;
GRANT SELECT (id, scope_kind, scope_id, week_start, status, version, snapshot) ON weekly_debrief_report TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, fy, scope_kind, scope_id, week_start, week_end, status, version, snapshot,
              generated_by_user_id)
  ON weekly_debrief_report TO edify_activities_rw;
GRANT UPDATE (snapshot, generated_by_user_id, status, updated_at) ON weekly_debrief_report TO edify_activities_rw;
GRANT SELECT (id, district_id) ON school TO edify_activities_rw;
GRANT SELECT (id, name) ON district TO edify_activities_rw;

-- ── The scheduler's admin_maintenance_generation (docs/migration/189 §4) ──
-- MaintenanceService.generate_due: a due template's scheduled work item (the
-- next OPS reference) and the template's next due day. Nothing is removed.
GRANT SELECT (id, name, category, description, frequency_days, next_due_date, active) ON admin_maintenance_template
  TO edify_activities_rw;
GRANT UPDATE (next_due_date, updated_at) ON admin_maintenance_template TO edify_activities_rw;
GRANT SELECT (id, reference) ON admin_ops_work_item TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, reference, title, category, description, severity, status, owner_id, due_date,
              scheduled_date, next_action, resolution_criteria, verification_note, affected_module, affected_route)
  ON admin_ops_work_item TO edify_activities_rw;

-- ── The scheduler's closure_checklist_refresh (docs/migration/189 §4) ──
-- ClosureEligibilityService.refresh_open: every open activity's checklist
-- and blockers from its facts, written where they changed. A blocker that no
-- longer applies is removed, as the existing refresh removes it, through
-- gateway_closure.remove_blockers (Go code removes nothing itself; the
-- function is owned by edify_closure_owner, a NOLOGIN role no one is a member
-- of, holding only that right).
-- A new database object: production needs the owner's approval at cutover.
GRANT SELECT (id, activity_id, activity_executed, evidence_uploaded, salesforce_id_entered, ia_verified, finance_required,
              accounts_cleared, netsuite_id_entered, analytics_published, audit_trail_saved)
  ON closure_checklist TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, activity_id, activity_executed, evidence_uploaded, salesforce_id_entered,
              ia_verified, finance_required, accounts_cleared, netsuite_id_entered, analytics_published, audit_trail_saved,
              last_evaluated_at)
  ON closure_checklist TO edify_activities_rw;
GRANT UPDATE (activity_executed, evidence_uploaded, salesforce_id_entered, ia_verified, finance_required, accounts_cleared,
              netsuite_id_entered, analytics_published, audit_trail_saved, last_evaluated_at, updated_at)
  ON closure_checklist TO edify_activities_rw;
GRANT SELECT (id, activity_id, blocking_reason, responsible_role, created_at) ON closure_blocker TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, activity_id, blocking_reason, responsible_role)
  ON closure_blocker TO edify_activities_rw;
GRANT SELECT (activity_id) ON activity_timeline_event TO edify_activities_rw;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_closure_owner') THEN
    CREATE ROLE edify_closure_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_closure_owner;
GRANT SELECT (id) ON closure_blocker TO edify_closure_owner;
GRANT DELETE ON closure_blocker TO edify_closure_owner;

CREATE SCHEMA IF NOT EXISTS gateway_closure AUTHORIZATION edify_closure_owner;
REVOKE ALL ON SCHEMA gateway_closure FROM PUBLIC;
-- Re-runnable: the owner may (re)define its function, then loses the right.
GRANT USAGE, CREATE ON SCHEMA gateway_closure TO edify_closure_owner;

SET ROLE edify_closure_owner;
CREATE OR REPLACE FUNCTION gateway_closure.remove_blockers(target_ids varchar[]) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  removed integer;
BEGIN
  DELETE FROM public.closure_blocker WHERE id = ANY(target_ids);
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_closure.remove_blockers(varchar[]) FROM PUBLIC;
RESET ROLE;
REVOKE CREATE ON SCHEMA gateway_closure FROM edify_closure_owner;

GRANT USAGE ON SCHEMA gateway_closure TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_closure.remove_blockers(varchar[]) TO edify_activities_rw;

-- ── The scheduler's ssa_recommendation_sync (docs/migration/189 §4) ──
-- sync_recommendations and judge_unjudged_plans: recommendations generated
-- for schools with none (the confirmation handler's grants), live plans
-- linked to what they answer, and an unjudged plan's SSA verdict recorded.
-- Linking a plan to what it answers is a direct write; recording a verdict
-- is not (a visit's SSA verdict is never rewritten by the gateway): it goes
-- through gateway_ssa_judge.judge_unjudged_plan, owned by
-- edify_ssa_judge_owner, a NOLOGIN role no one is a member of, which only
-- judges a plan that has no verdict yet.
-- A new database object: production needs the owner's approval at cutover.
GRANT UPDATE (ssa_recommendation_id, updated_at) ON activity TO edify_activities_rw;
-- An earlier draft granted these directly; the function holds them instead.
REVOKE UPDATE (recommendation_source, ssa_alignment, source_ssa_id, source_ssa_verification_state, source_score,
               source_classification, recommendation_reason)
  ON activity FROM edify_activities_rw;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_ssa_judge_owner') THEN
    CREATE ROLE edify_ssa_judge_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_ssa_judge_owner;
GRANT SELECT (id, ssa_alignment, deleted_at, source_ssa_id, source_ssa_verification_state, source_score,
              source_classification, recommendation_reason),
      UPDATE (recommendation_source, ssa_alignment, source_ssa_id, source_ssa_verification_state, source_score,
              source_classification, recommendation_reason, updated_at)
  ON activity TO edify_ssa_judge_owner;
CREATE SCHEMA IF NOT EXISTS gateway_ssa_judge AUTHORIZATION edify_ssa_judge_owner;
REVOKE ALL ON SCHEMA gateway_ssa_judge FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA gateway_ssa_judge TO edify_ssa_judge_owner;
SET ROLE edify_ssa_judge_owner;
-- judge_unjudged_plans' stamp(link=False): the verdict and its source on a
-- plan with none; the SSA it was judged on, its score and the reason only
-- where the caller says the plan holds none.
CREATE OR REPLACE FUNCTION gateway_ssa_judge.judge_unjudged_plan(
  p_target varchar, p_source jsonb, p_alignment varchar,
  p_set_ssa boolean, p_ssa_id varchar, p_set_score boolean, p_score double precision, p_band varchar,
  p_set_reason boolean, p_reason text, p_at timestamptz
) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  UPDATE public.activity a SET recommendation_source = p_source, ssa_alignment = p_alignment, updated_at = p_at,
    source_ssa_id = CASE WHEN p_set_ssa THEN p_ssa_id ELSE a.source_ssa_id END,
    source_ssa_verification_state = CASE WHEN p_set_ssa THEN 'confirmed' ELSE a.source_ssa_verification_state END,
    source_score = CASE WHEN p_set_score THEN p_score ELSE a.source_score END,
    source_classification = CASE WHEN p_set_score THEN p_band ELSE a.source_classification END,
    recommendation_reason = CASE WHEN p_set_reason THEN p_reason ELSE a.recommendation_reason END
  WHERE a.id = p_target AND a.ssa_alignment = '' AND a.deleted_at IS NULL;
  RETURN FOUND;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_ssa_judge.judge_unjudged_plan(varchar, jsonb, varchar, boolean, varchar, boolean,
  double precision, varchar, boolean, text, timestamptz) FROM PUBLIC;
RESET ROLE;
REVOKE CREATE ON SCHEMA gateway_ssa_judge FROM edify_ssa_judge_owner;
GRANT USAGE ON SCHEMA gateway_ssa_judge TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_ssa_judge.judge_unjudged_plan(varchar, jsonb, varchar, boolean, varchar, boolean,
  double precision, varchar, boolean, text, timestamptz) TO edify_activities_rw;
GRANT SELECT (planned_activity_id) ON ssa_recommendation TO edify_activities_rw;
GRANT SELECT (ssa_recommendation_id, recommendation_source, ssa_alignment, source_ssa_id, source_score,
              recommendation_reason, ssa_deviation_reason, ssa_collection_expected, focus_intervention, project_id)
  ON activity TO edify_activities_rw;
GRANT SELECT (school_id, invited, activity_id) ON cluster_activity_attendance TO edify_activities_rw;

-- ── The scheduler's autopilot_weekly_proposals (docs/migration/189 §4) ──
-- generate_week_proposal: next week's draft per CCEO and its proposed visits;
-- a live draft is dismissed when drafted again. Nothing is removed.
GRANT SELECT (id, staff_id, week_start, status, created_at) ON autopilot_proposed_plan TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, staff_id, week_start, status, rationale, accepted_by, accepted_at)
  ON autopilot_proposed_plan TO edify_activities_rw;
GRANT UPDATE (status, updated_at) ON autopilot_proposed_plan TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, plan_id, school_id, school_name, area, proposed_date, activity_type,
              catalogue_stable_code, reason, created_activity_id)
  ON autopilot_proposed_activity TO edify_activities_rw;
GRANT SELECT (staff_id, school_id) ON staff_school_assignment TO edify_activities_rw;
GRANT SELECT (block_type, applies_to_roles, applies_to_all_roles, country, region_id, district_id, is_active, start_date,
              end_date)
  ON calendar_block TO edify_activities_rw;
GRANT SELECT (staff_id, region_id, district_id) ON staff_geography_assignment TO edify_activities_rw;
GRANT SELECT (staff_id, status, start_date, end_date) ON leave TO edify_activities_rw;
GRANT SELECT (id, name) ON sub_county TO edify_activities_rw;
GRANT SELECT (sub_county_id, school_type, current_fy_ssa_status) ON school TO edify_activities_rw;
GRANT SELECT (average_score) ON ssa_record TO edify_activities_rw;

-- ── The scheduler's scheduler_watchdog (docs/migration/189 §4) ──
-- SchedulerHealthService.job_health reads the recorded runs; the notices go
-- through gateway_notifications (notify_workflow, resolve_condition).
GRANT SELECT (job_name, status, error_message, started_at) ON scheduled_job_execution TO edify_activities_rw;

-- ── Activity.save's Core package mirror (activities.MirrorSlots) ──
-- The slot takes the work's status, day, Salesforce ID and newest evidence
-- file; the package's done counters follow (resync_plan_completion). The
-- gateway never reads an evidence file's storage address, so the slot write
-- is gateway_core_slots.mirror_slots, owned by edify_core_slots_owner, a
-- NOLOGIN role no one is a member of, holding only what that write reads.
-- A new database object: production needs the owner's approval at cutover.
GRANT SELECT (status, salesforce_activity_id, scheduled_date, cluster_id, school_id) ON activity TO edify_activities_rw;
GRANT SELECT (school_type) ON school TO edify_activities_rw;
-- An earlier draft granted these directly; the function holds them instead.
REVOKE SELECT (uri) ON evidence_record FROM edify_activities_rw;
REVOKE UPDATE (salesforce_id, evidence_uri) ON core_activity_slot FROM edify_activities_rw;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_core_slots_owner') THEN
    CREATE ROLE edify_core_slots_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_core_slots_owner;
GRANT SELECT (id, activity_id, core_plan_id, evidence_uri, scheduled_for, salesforce_id, assigned_partner_id),
      UPDATE (status, scheduled_for, salesforce_id, evidence_uri, updated_at, activity_id, owner, assigned_staff_id,
              assigned_partner_id, scheduled_month, scheduled_week)
  ON core_activity_slot TO edify_core_slots_owner;
GRANT SELECT (uri, activity_id, quarantined, created_at) ON evidence_record TO edify_core_slots_owner;
CREATE SCHEMA IF NOT EXISTS gateway_core_slots AUTHORIZATION edify_core_slots_owner;
REVOKE ALL ON SCHEMA gateway_core_slots FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA gateway_core_slots TO edify_core_slots_owner;
SET ROLE edify_core_slots_owner;
-- The slots this work fills take what Activity.save copies onto them; the
-- plans they belong to come back for the counters.
CREATE OR REPLACE FUNCTION gateway_core_slots.mirror_slots(
  target varchar, slot_status varchar, day varchar, sfid varchar, at timestamptz
) RETURNS SETOF varchar
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  UPDATE public.core_activity_slot c SET status = slot_status,
    scheduled_for = COALESCE(day, c.scheduled_for),
    salesforce_id = CASE WHEN COALESCE(sfid, '') <> '' THEN sfid ELSE c.salesforce_id END,
    evidence_uri = CASE WHEN COALESCE(c.evidence_uri, '') = '' THEN (SELECT e.uri FROM public.evidence_record e
        WHERE e.activity_id = target AND NOT e.quarantined ORDER BY e.created_at DESC LIMIT 1) ELSE c.evidence_uri END,
    updated_at = at
  WHERE c.activity_id = target
  RETURNING c.core_plan_id
$fn$;
REVOKE ALL ON FUNCTION gateway_core_slots.mirror_slots(varchar, varchar, varchar, varchar, timestamptz) FROM PUBLIC;
-- credit_school_activity's slot.save(): the work written onto the slot it
-- takes, with its newest evidence file where the slot has none.
CREATE OR REPLACE FUNCTION gateway_core_slots.link_slot(
  p_slot varchar, p_activity varchar, p_status varchar, p_owner varchar, p_staff varchar, p_partner varchar,
  p_day varchar, p_month varchar, p_week integer, p_sfid varchar, p_at timestamptz
) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  UPDATE public.core_activity_slot c SET activity_id = p_activity, status = p_status, owner = p_owner,
    assigned_staff_id = p_staff,
    assigned_partner_id = CASE WHEN COALESCE(p_partner, '') <> '' THEN p_partner ELSE c.assigned_partner_id END,
    scheduled_for = p_day, scheduled_month = p_month, scheduled_week = p_week,
    salesforce_id = CASE WHEN COALESCE(p_sfid, '') <> '' THEN p_sfid ELSE c.salesforce_id END,
    evidence_uri = CASE WHEN COALESCE(c.evidence_uri, '') = '' THEN (SELECT e.uri FROM public.evidence_record e
        WHERE e.activity_id = p_activity AND NOT e.quarantined ORDER BY e.created_at DESC LIMIT 1) ELSE c.evidence_uri END,
    updated_at = p_at
  WHERE c.id = p_slot
$fn$;
REVOKE ALL ON FUNCTION gateway_core_slots.link_slot(varchar, varchar, varchar, varchar, varchar, varchar, varchar, varchar,
  integer, varchar, timestamptz) FROM PUBLIC;
RESET ROLE;
REVOKE CREATE ON SCHEMA gateway_core_slots FROM edify_core_slots_owner;
GRANT USAGE ON SCHEMA gateway_core_slots TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_core_slots.mirror_slots(varchar, varchar, varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_core_slots.link_slot(varchar, varchar, varchar, varchar, varchar, varchar, varchar, varchar,
  integer, varchar, timestamptz) TO edify_activities_rw;
-- The package credit (activities.CreditSchoolActivity): what it reads of the
-- work, its package and the universal trainings, and the slot it adds past
-- the last when every one is taken.
GRANT SELECT (id, deleted_at, school_id, status, activity_type, purpose_type, delivery_type, cluster_id, project_id,
              training_course_id, catalogue_item_id, fy, responsible_staff_id, assigned_partner_id, salesforce_activity_id,
              scheduled_date, planned_date, planned_month, planned_week, paired_school_visit_id)
  ON activity TO edify_activities_rw;
GRANT SELECT (id, school_id, school_type) ON school TO edify_activities_rw;
GRANT SELECT (id, school_id, fy, status, interventions) ON core_plan TO edify_activities_rw;
GRANT SELECT (assigned_partner_id) ON core_activity_slot TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, core_plan_id, school_id, intervention, activity_type, sequence_number, status, owner)
  ON core_activity_slot TO edify_activities_rw;
GRANT SELECT (id, is_training_course, universal_training) ON activity_catalogue_item TO edify_activities_rw;

-- ── The scheduler's pd_reminders (docs/migration/189 §4) ──
-- send_due_reminders: the course clock (sync_dates), the reminder log, and
-- the supervisor the chart names (PDApprovalRoutingService.supervisor_for).
GRANT SELECT (id, status, course_name, institution, staff_id, staff_name, start_date, end_date, created_at),
      UPDATE (status, updated_at)
  ON pd_request TO edify_activities_rw;
GRANT SELECT (request_id, reminder_key, sent_on),
      INSERT (id, created_at, updated_at, reminder_key, sent_on, request_id)
  ON pd_reminder_log TO edify_activities_rw;
GRANT SELECT (id, supervisee_id, supervisor_id) ON staff_supervisor_assignment TO edify_activities_rw;
GRANT SELECT (id, user_id, country, onboarding_state) ON staff_profile TO edify_activities_rw;

-- ── The scheduler's escalation_sla_sweep (docs/migration/189 §4) ──
-- sweep_overdue reads the open escalations and who they are addressed to;
-- the notices go through gateway_notifications.
GRANT SELECT (id, status, severity, addressed_role, assigned_to_user_id, country_id, subject, detail, raised_by_user_id,
              raised_by_name, created_at)
  ON leadership_escalation TO edify_activities_rw;

-- ── The Partner's "who delivers this work" (apps.partners.delivery_team) ──
-- The team member named on one of the organisation's activities, from its
-- active roster.
GRANT UPDATE (delivery_contact_name, updated_at) ON activity TO edify_activities_rw;
GRANT SELECT (partner_id, name, role, active) ON partner_member TO edify_activities_rw;

-- ── Partner Oversight's hand-over send (partner_oversight_actions) ──
-- send_action's TeamAction (one INSERT; the sweep closes it), the system
-- message a workflow writes about a school or a hand-over
-- (messaging.services.workflow_message: the thread found or started, its
-- participants, the message), and raise_escalation's escalation. Nothing
-- removed; a closed action or escalation stays as history.
GRANT SELECT (id, condition_key, state, recipient_id, created_at),
      INSERT (created_at, updated_at, id, condition_key, issue_type, severity, school_id, fy, month_of_fy, related_ssa_id,
              related_activity_id, sender_id, sender_role, recipient_id, recipient_role, requested_action, workflow_route, message,
              priority, due_date, state, detected_at, blocked_reason, resolved_by_system, manual_resolution_reason, returned_reason,
              reminder_count, supersedes_id)
  ON team_action TO edify_activities_rw;
GRANT SELECT (id, context_type, context_id, is_system_generated),
      INSERT (created_at, updated_at, id, subject, context_type, context_id, context_label, category, priority, created_by,
              last_reply_at, is_system_generated, linked_items, participant_a_id, participant_b_id),
      UPDATE (last_reply_at, updated_at)
  ON messaging_messagethread TO edify_activities_rw;
GRANT SELECT (thread_id, user_id),
      INSERT (created_at, updated_at, id, user_id, recipient_type, last_read_at, archived_at, starred, thread_id)
  ON messaging_messageparticipant TO edify_activities_rw;
GRANT INSERT (created_at, updated_at, id, thread_id, sender_id, recipient_id, body, category, context_type, context_id, target_route,
              priority, action_required, is_system_generated, status)
  ON message TO edify_activities_rw;
GRANT SELECT (scope_type, scope_id),
      INSERT (created_at, updated_at, id, raised_by_user_id, raised_by_name, addressed_role, assigned_to_user_id, country_id, category,
              subject, detail, requested_decision, severity, scope_type, scope_id, scope_name, due_date, status)
  ON leadership_escalation TO edify_activities_rw;
GRANT SELECT (id, name, user_id) ON partner TO edify_activities_rw;
GRANT SELECT (id, name, active_role, roles, status, deleted_at, created_at) ON "user" TO edify_activities_rw;
GRANT SELECT (deleted_at) ON staff_profile TO edify_activities_rw;
GRANT SELECT (id, name, school_id) ON school TO edify_activities_rw;

-- ── The scheduler's verification_sampling (docs/migration/189 §4) ──
-- draw_samples: the week's verifications and confirmed SSA records, where
-- each was, and the samples drawn (one row per subject; nothing removed).
GRANT SELECT (id, activity_id, verified_by, verified_at) ON ia_verification_history TO edify_activities_rw;
GRANT SELECT (id, activity_id, ssa_record_id, subject_type, sampled_at),
      INSERT (created_at, updated_at, id, original_verifier, sampled_at, sampled_by, status, outcome_note, activity_id,
              ssa_record_id, method, subject_type)
  ON ia_verification_sample TO edify_activities_rw;
GRANT SELECT (id, country) ON region TO edify_activities_rw;
GRANT SELECT (id, region_id) ON school TO edify_activities_rw;
GRANT SELECT (id, region_id) ON cluster TO edify_activities_rw;
GRANT SELECT (id, school_id, verification_status, deleted_at, verified_at, verified_by_user_id) ON ssa_record TO edify_activities_rw;

-- ── The scheduler's document_lifecycle (docs/migration/189 §4) ──
-- apps.documents.jobs: a document's status on its version's dates, the
-- acknowledgement reminders, and idle viewer sessions closed.
GRANT SELECT (id, status, current_version_id, title, acknowledgement_reason), UPDATE (status, updated_at)
  ON document_asset TO edify_activities_rw;
GRANT SELECT (id, effective_date, expiry_date, preview_status) ON document_version TO edify_activities_rw;
GRANT SELECT (id, user_id, document_id, state, due_date, last_reminded_at, reminder_count, created_at),
      UPDATE (reminder_count, last_reminded_at, updated_at)
  ON document_acknowledgement TO edify_activities_rw;
GRANT SELECT (finalised, last_heartbeat_at), UPDATE (finalised, updated_at) ON document_engagement_session TO edify_activities_rw;

-- ── The outbox's notification.push (docs/migration/189 §4) ──
-- push.handle_push: one queued phone or browser copy's status as it is sent,
-- or why it was not; the device's keys to encrypt to, and its health (a
-- device gone is marked revoked, never removed); the recipient's push
-- setting. No copy or device is inserted or removed by Go.
GRANT SELECT (round, target) ON notification_delivery TO edify_activities_rw;
GRANT SELECT (id, user_id, kind, endpoint, p256dh, auth, revoked_at, failure_count),
      UPDATE (revoked_at, revoked_reason, last_error, failure_count, last_success_at)
  ON notification_push_subscription TO edify_activities_rw;
GRANT SELECT (user_id, push_enabled) ON notification_preference TO edify_activities_rw;
-- The copy's round, when its event names none, is the notice's re-fire count.
GRANT SELECT (reminder_count) ON notification TO edify_activities_rw;

-- ── Team Coaching's saves (apps.cce_leadership.coaching) ──
-- A lead's coaching records, recorded, corrected, shared and their follow-up
-- closed; nothing removed. They read the officers' recent work and debriefs.
GRANT SELECT (id, author_id, cceo_staff_id, cceo_user_id, kind, subject, strengths, growth_areas, agreed_actions, cceo_response,
              follow_up_note, country, activity_id, debrief_id, held_on, follow_up_due, shared_at, acknowledged_at,
              follow_up_done_at, rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation,
              rating_application),
      INSERT (created_at, updated_at, id, author_id, cceo_staff_id, cceo_user_id, kind, held_on, fy, country, subject, strengths,
              growth_areas, agreed_actions, follow_up_due, rating_biblical_integration, rating_need_alignment,
              rating_facilitation, rating_participation, rating_application, cceo_response, follow_up_note, activity_id,
              debrief_id),
      UPDATE (kind, held_on, fy, country, subject, strengths, growth_areas, agreed_actions, follow_up_due, activity_id,
              debrief_id, rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation,
              rating_application, shared_at, follow_up_done_at, follow_up_note, acknowledged_at, cceo_response, updated_at)
  ON cce_cceo_coaching TO edify_activities_rw;
GRANT SELECT (id, submitted_by_user_id, deleted_at, date, title) ON daily_debrief TO edify_activities_rw;
GRANT SELECT (id, responsible_staff_id, monitored_by_staff_id, deleted_at, planned_date, status, activity_name_snapshot,
              activity_type, school_id, cluster_id)
  ON activity TO edify_activities_rw;
GRANT SELECT (id, user_id, country, deleted_at) ON staff_profile TO edify_activities_rw;

-- ── Staff Activity follow-ups (apps.staff_activity.follow_ups) ──
-- A follow-up raised from the log and moved through its steps; its history
-- grows and nothing is removed.
GRANT SELECT (id, created_at, subject_id, assignee_id, created_by_id, route, period_key, trigger, snapshot, note, priority,
              due_date, status, resolution, history),
      INSERT (id, created_at, updated_at, subject_id, assignee_id, created_by_id, route, period_key, period_start, period_end,
              trigger, snapshot, note, priority, due_date, status, resolution, resolved_at, resolved_by_id, history),
      UPDATE (status, history, updated_at, resolved_at, resolved_by_id, resolution)
  ON staff_usage_follow_up TO edify_activities_rw;
GRANT SELECT (id, name, email, is_active, roles, deleted_at) ON "user" TO edify_activities_rw;

-- ── Follow Up with PL for execution (apps.planning.country_execution.followups.send_follow_up) ──
-- The Country Director's follow-up, created or reminded on the open record of
-- the same condition; its instruction history and history grow, nothing is
-- removed. Who it goes to is read off the Lead's account.
GRANT SELECT (id, condition_key, status, instruction_history, history, reminder_count, assigned_by_name, activity_label,
              partner_name, cceo_name, period_label, returned_reason),
      INSERT (created_at, updated_at, id, fy, period_type, period_start, period_end, period_label, country, region_id,
              region_name, program_lead_staff_id, program_lead_user_id, program_lead_name, cceo_staff_id, cceo_name,
              school_id, school_name, condition_key, issue_type, metric_key, required_value, planned_value, remaining_value,
              affected_school_ids, affected_count, snapshot, resolution_rule, live_remaining, live_checked_at, priority,
              instruction, instruction_history, assigned_by_id, assigned_by_role, assigned_by_name, assigned_at, due_date,
              status, acknowledged_at, action_linked_at, linked_team_action_ids, linked_note, resolved_at,
              resolved_by_system, resolution_note, closed_by_id, returned_reason, returned_at, reminder_count,
              last_reminder_at, history, activity_id, activity_label, blocker_owner, days_overdue, module, partner_id,
              partner_name, stage),
      UPDATE (instruction, instruction_history, reminder_count, last_reminder_at, priority, due_date, remaining_value,
              live_remaining, live_checked_at, days_overdue, status, returned_reason, history, updated_at,
              required_value, planned_value, affected_school_ids, affected_count)
  ON planning_oversight_follow_up TO edify_activities_rw;
GRANT SELECT (active_role) ON "user" TO edify_activities_rw;

-- ── The Regional Lead's engagements and monthly reports (apps.cce_leadership.services) ──
-- Engagements recorded, corrected until shared, shared and acknowledged; an
-- acknowledged observation passed to the officer as coaching; monthly
-- reports started, written, submitted and reviewed. Nothing removed.
GRANT SELECT (id, created_at, author_id, kind, held_on, fy, country, program_lead_ids, subject, notes, agreed_actions, follow_up_due,
              rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation, rating_application,
              recommendation, feedback, feedback_shared_at, acknowledged_at, acknowledged_by_id, lead_response, activity_id),
      INSERT (id, created_at, updated_at, author_id, kind, held_on, fy, country, program_lead_ids, subject, notes, agreed_actions,
              follow_up_due, rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation,
              rating_application, recommendation, feedback, lead_response, activity_id),
      UPDATE (updated_at, kind, held_on, fy, country, program_lead_ids, subject, notes, agreed_actions, follow_up_due,
              rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation, rating_application,
              recommendation, feedback, activity_id, feedback_shared_at, acknowledged_at, acknowledged_by_id, lead_response)
  ON cce_regional_engagement TO edify_activities_rw;
GRANT SELECT (id, author_id, period, fy, countries, status, executive_summary, training_programmes, cce_impact,
              curriculum_development, programme_initiatives, partnerships, support_needed, metrics, submitted_at, reviewed_by_id,
              reviewed_at, review_note),
      INSERT (id, created_at, updated_at, author_id, period, fy, countries, status, executive_summary, training_programmes,
              cce_impact, curriculum_development, programme_initiatives, partnerships, support_needed, metrics, submitted_at,
              reviewed_by_id, reviewed_at, review_note),
      UPDATE (updated_at, countries, status, executive_summary, training_programmes, cce_impact, curriculum_development,
              programme_initiatives, partnerships, support_needed, metrics, submitted_at, reviewed_by_id, reviewed_at, review_note)
  ON cce_regional_report TO edify_activities_rw;
GRANT SELECT (source_engagement_id), INSERT (source_engagement_id, shared_at) ON cce_cceo_coaching TO edify_activities_rw;
GRANT SELECT (id, activity_type, planned_date, status, deleted_at, school_id, cluster_id, activity_name_snapshot, responsible_staff_id,
              monitored_by_staff_id, delivery_type, assigned_partner_id, teachers_attended, leaders_attended, fy, ssa_alignment)
  ON activity TO edify_activities_rw;
GRANT SELECT (id, name, region_id) ON school TO edify_activities_rw;
GRANT SELECT (id, country) ON region TO edify_activities_rw;
GRANT SELECT (id, name, district_id, region_id) ON cluster TO edify_activities_rw;
GRANT SELECT (id, region_id) ON district TO edify_activities_rw;
GRANT SELECT (id, name) ON partner TO edify_activities_rw;
GRANT SELECT (id, school_id, deleted_at, verification_status, date_of_ssa) ON ssa_record TO edify_activities_rw;
GRANT SELECT (supervisor_id, supervisee_id) ON staff_supervisor_assignment TO edify_activities_rw;
GRANT SELECT (id, staff_id, region_id) ON staff_geography_assignment TO edify_activities_rw;
GRANT SELECT (id, status, roles, deleted_at) ON "user" TO edify_activities_rw;

-- ── Impact Assessment's Measurement Framework (apps.impact.framework) ──
-- Outcome areas and indicators drafted, edited while drafts, versioned once
-- approved, submitted and reviewed (the version before superseded); an
-- approved loan purpose measurement written onto its purpose. Editing a draft
-- area replaces its SSA domains: the only removal, made by
-- gateway_ia_framework.clear_area_domains, owned by edify_ia_framework_owner,
-- a NOLOGIN role no one is a member of, which clears one area's domains.
-- A new database object: production needs the owner's approval at cutover.
GRANT SELECT (id, created_at, author_id, author_role, submitted_at, reviewed_by_id, reviewed_at, review_basis, review_note, code,
              name, definition, status, version, change_reason),
      INSERT (id, created_at, updated_at, author_id, author_role, submitted_at, reviewed_by_id, reviewed_at, review_basis,
              review_note, code, name, definition, status, version, change_reason),
      UPDATE (updated_at, name, definition, change_reason, status, submitted_at, reviewed_by_id, reviewed_at, review_basis,
              review_note)
  ON impact_outcome_area TO edify_activities_rw;
GRANT SELECT (id, created_at, area_id, intervention),
      INSERT (id, created_at, updated_at, intervention, note, area_id)
  ON impact_outcome_area_domain TO edify_activities_rw;
GRANT SELECT (id, author_id, author_role, submitted_at, reviewed_by_id, reviewed_at, review_basis, review_note, key, version, name,
              level, unit, source, calculation, population, denominator, baseline_rule, frequency, disaggregation, limitations,
              data_owner_role, country, status, effective_from, change_reason, outcome_area_id),
      INSERT (id, created_at, updated_at, author_id, author_role, submitted_at, reviewed_by_id, reviewed_at, review_basis,
              review_note, key, version, name, level, unit, source, calculation, population, denominator, baseline_rule, frequency,
              disaggregation, limitations, data_owner_role, country, status, effective_from, change_reason, outcome_area_id),
      UPDATE (updated_at, outcome_area_id, effective_from, change_reason, name, level, unit, source, calculation, population,
              denominator, baseline_rule, frequency, disaggregation, limitations, data_owner_role, status, submitted_at,
              reviewed_by_id, reviewed_at, review_basis, review_note)
  ON impact_indicator_definition TO edify_activities_rw;
GRANT SELECT (id, code, label, unit_of_measure, verification_method, follow_up_days, version, applicable_countries,
              impact_indicators, required_evidence, active),
      UPDATE (impact_indicators, required_evidence, verification_method, follow_up_days, measurement_profile_complete, version,
              updated_at)
  ON bt_loan_purpose TO edify_activities_rw;
GRANT SELECT (id, name, email, active_role, roles, is_active, deleted_at) ON "user" TO edify_activities_rw;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_ia_framework_owner') THEN
    CREATE ROLE edify_ia_framework_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO edify_ia_framework_owner;
GRANT SELECT (area_id), DELETE ON impact_outcome_area_domain TO edify_ia_framework_owner;
GRANT SELECT (id, status) ON impact_outcome_area TO edify_ia_framework_owner;
CREATE SCHEMA IF NOT EXISTS gateway_ia_framework AUTHORIZATION edify_ia_framework_owner;
REVOKE ALL ON SCHEMA gateway_ia_framework FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA gateway_ia_framework TO edify_ia_framework_owner;
SET ROLE edify_ia_framework_owner;
-- save_outcome_area's record.domains.all().delete(): one draft area's
-- domains, before the edited ones are written.
CREATE OR REPLACE FUNCTION gateway_ia_framework.clear_area_domains(p_area varchar) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  removed integer;
BEGIN
  DELETE FROM public.impact_outcome_area_domain d
   WHERE d.area_id = p_area
     AND EXISTS (SELECT 1 FROM public.impact_outcome_area a WHERE a.id = p_area AND a.status IN ('draft', 'returned'));
  GET DIAGNOSTICS removed = ROW_COUNT;
  RETURN removed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_ia_framework.clear_area_domains(varchar) FROM PUBLIC;
RESET ROLE;
REVOKE CREATE ON SCHEMA gateway_ia_framework FROM edify_ia_framework_owner;
GRANT USAGE ON SCHEMA gateway_ia_framework TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_ia_framework.clear_area_domains(varchar) TO edify_activities_rw;

-- ── School Evidence (apps.impact.evidence_services) ──
-- Learning results, discipleship records, EdTech deployments and their
-- checks recorded by Impact Assessment, corrected or withdrawn (a tombstone,
-- never a removal) by their recorder, and confirmed or returned by a second
-- person.
GRANT SELECT, INSERT (id, created_at, updated_at, source, environment, deleted_at, country, fy, evidence_reference, notes,
                      recorded_by_user_id, verification_status, verified_by_user_id, verified_at, return_reason, school_id,
                      source_activity_id, assessment_type, assessed_on, grade_level, subject, learners_tested, mean_score,
                      max_score, learners_proficient),
      UPDATE (updated_at, deleted_at, fy, evidence_reference, notes, verification_status, verified_by_user_id, verified_at,
              return_reason, assessment_type, assessed_on, grade_level, subject, learners_tested, mean_score, max_score,
              learners_proficient)
  ON impact_learning_result TO edify_activities_rw;
GRANT SELECT, INSERT (id, created_at, updated_at, source, environment, deleted_at, country, fy, evidence_reference, notes,
                      recorded_by_user_id, verification_status, verified_by_user_id, verified_at, return_reason, school_id,
                      source_activity_id, observed_on, devotions_per_week, discipleship_groups_active, learners_in_groups,
                      learners_enrolled, staff_in_devotions_pct, spiritual_lead_in_post, bible_lessons_timetabled),
      UPDATE (updated_at, deleted_at, fy, evidence_reference, notes, verification_status, verified_by_user_id, verified_at,
              return_reason, observed_on, devotions_per_week, discipleship_groups_active, learners_in_groups, learners_enrolled,
              staff_in_devotions_pct, spiritual_lead_in_post, bible_lessons_timetabled)
  ON impact_discipleship_record TO edify_activities_rw;
GRANT SELECT, INSERT (id, created_at, updated_at, source, environment, deleted_at, country, fy, evidence_reference, notes,
                      recorded_by_user_id, verification_status, verified_by_user_id, verified_at, return_reason, school_id,
                      source_activity_id, asset_type, quantity, deployed_on, funding, project_id, teachers_trained,
                      learners_with_access),
      UPDATE (updated_at, deleted_at, fy, evidence_reference, notes, verification_status, verified_by_user_id, verified_at,
              return_reason, asset_type, quantity, deployed_on, funding, project_id, teachers_trained, learners_with_access)
  ON impact_edtech_deployment TO edify_activities_rw;
GRANT SELECT, INSERT (id, created_at, updated_at, source, environment, deleted_at, country, fy, evidence_reference, notes,
                      recorded_by_user_id, verification_status, verified_by_user_id, verified_at, return_reason, school_id,
                      source_activity_id, deployment_id, checked_on, units_functional, teachers_using, learners_using,
                      weekly_use_hours, issues),
      UPDATE (updated_at, deleted_at, fy, evidence_reference, notes, verification_status, verified_by_user_id, verified_at,
              return_reason, checked_on, units_functional, teachers_using, learners_using, weekly_use_hours, issues)
  ON impact_edtech_check TO edify_activities_rw;
GRANT SELECT (id, name, deleted_at) ON project TO edify_activities_rw;
GRANT SELECT (id, name, school_id, region_id, deleted_at, created_at) ON school TO edify_activities_rw;

-- ── The HR programmes' forms (apps.frontend.views.hr_programme_views) ──
-- Recognitions recorded (rewards_wellbeing_service.recognise); nothing removed.
GRANT INSERT (id, created_at, updated_at, staff_id, country, category, citation, awarded_by_id, awarded_on)
  ON hr_staff_recognition TO edify_activities_rw;
-- Compliance requirements added and employees' evidence recorded
-- (compliance_service.add_requirement, record_evidence); nothing removed.
GRANT INSERT (id, created_at, updated_at, country, name, description, is_mandatory) ON hr_compliance_requirement TO edify_activities_rw;
GRANT SELECT (id, staff_id, requirement_id, document_url, verified_by_id, verified_at),
      INSERT (id, created_at, updated_at, staff_id, requirement_id, status, document_url, expiry_date, verified_by_id, verified_at),
      UPDATE (updated_at, status, document_url, expiry_date, verified_by_id, verified_at)
  ON hr_employee_compliance_record TO edify_activities_rw;
-- Pulse surveys opened (rewards_wellbeing_service.open_pulse_survey); their
-- notices go through gateway_notifications.notify_workflow.
GRANT INSERT (id, created_at, updated_at, title, countries, opens_on, closes_on, status, created_by_id) ON hr_pulse_survey TO edify_activities_rw;
-- Safety incidents reported (report_incident), offboardings started or moved
-- (offboarding_service.open_offboarding) and employee-relations cases opened
-- (employee_relations_service.open_case); nothing removed.
GRANT INSERT (id, created_at, updated_at, country, incident_date, location, category, severity, description, immediate_action, corrective_action, days_lost, status, closed_at, affected_staff_id, reported_by_id) ON hr_safety_incident TO edify_activities_rw;
GRANT SELECT (id, status, staff_id), INSERT (id, created_at, updated_at, status, last_working_day, clearance_completed, handover_owner_id, staff_id, exit_note, exit_reason), UPDATE (updated_at, last_working_day, exit_reason, exit_note, handover_owner_id) ON hr_offboarding TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, case_type, severity, status, description, findings, is_confidential, case_owner_id, action_taken, appeal_note, closed_at, country, investigator_id, opened_at, raised_by_id, retention_until, subject_staff_id, complainant_staff_id, hearing_date, sanction) ON hr_relations_case TO edify_activities_rw;
-- Formal plans recommended (performance_engine.recommend_pip), vacancies
-- requested and candidates recorded (recruitment_service.request_vacancy,
-- record_application); nothing removed.
GRANT INSERT (id, created_at, updated_at, status, cause, action_plan, start_date, end_date, staff_id, cause_evidence, plan_type, recommended_by_id) ON hr_pip_plan TO edify_activities_rw;
GRANT SELECT (id, country, status, role), INSERT (id, created_at, updated_at, country, department, role, employment_type, reason_for_vacancy, replacement_or_new_role, required_skills, target_start_date, approved_salary_band, budget_source, status, approved_by_id, reporting_manager_id, approved_at, closed_at, decision_reason, requested_by_id) ON hr_vacancy TO edify_activities_rw;
GRANT SELECT (id, name, email), INSERT (id, created_at, updated_at, name, email, phone, skills, talent_pool_notes, consent_given_at, retention_until) ON hr_candidate TO edify_activities_rw;
GRANT SELECT (vacancy_id, candidate_id), INSERT (id, created_at, updated_at, stage, status_notes, candidate_id, vacancy_id) ON hr_application TO edify_activities_rw;
-- Compensation records made or moved (rewards_wellbeing_service.save_compensation);
-- bank details are never written here; nothing removed.
GRANT SELECT (id, staff_id, salary_band, currency, base_salary, allowances, medical_cover, pension_scheme, other_benefits, effective_date, next_review_date, status), INSERT (id, created_at, updated_at, salary_band, base_salary, allowances, benefits_tier, bank_name, account_number, status, staff_id, currency, effective_date, medical_cover, next_review_date, other_benefits, pension_scheme), UPDATE (updated_at, salary_band, currency, base_salary, allowances, medical_cover, pension_scheme, other_benefits, effective_date, next_review_date, status) ON hr_compensation TO edify_activities_rw;
-- A new Professional Development request saved as a draft (pd_request_view's
-- POST without an id); submitting and editing stay the existing application's.
GRANT INSERT (id, created_at, updated_at, fy, staff_id, staff_name, position, country, department, supervisor_staff_id, supervisor_name, course_name, course_category, course_type, institution, start_date, end_date, certification_expected, relevance_to_role, course_fee_cents, other_costs_cents, total_cost_cents, employee_contribution_cents, requested_amount_cents, funding_type, currency, is_exception, status, hr_is_independent_reviewer, enrollment_confirmed, bamboohr_uploaded, created_by, duration, purpose, requested_local_amount_cents, requested_local_currency) ON pd_request TO edify_activities_rw;
-- A partner organisation's login setup (partners.services.configure_partner_user):
-- the account it signs in with and the setup status; nothing removed.
GRANT SELECT (id, name, email, contact_person, user_id, user_setup_status, deleted_at), UPDATE (user_id, user_setup_status, user_setup_updated_by, user_setup_updated_at, updated_at) ON partner TO edify_activities_rw;
-- An Impact Assessment officer's draft impact report (reports.create_report,
-- update_report, submit_report, withdraw_report, review_report) and its recommendations
-- (add_recommendation); nothing removed.
GRANT SELECT (id, title, country, status, author_id, reviewed_by_id, version, snapshot_hash, fy, project_id, methodology, findings, limitations, period_start, period_end, programme_areas, supersedes_id, evidence_snapshot), UPDATE (title, fy, period_start, period_end, programme_areas, project_id, methodology, findings, limitations, updated_at, status, evidence_snapshot, snapshot_hash, submitted_at, reviewed_by_id, reviewed_at, review_basis, review_note), INSERT (id, created_at, updated_at, author_id, author_role, review_basis, review_note, country, fy, period_start, period_end, programme_areas, title, status, methodology, findings, limitations, evidence_snapshot, snapshot_hash, version, project_id, supersedes_id) ON impact_report TO edify_activities_rw;
GRANT SELECT (id, report_id, created_at, text, owner_role, due_date, status, response), INSERT (id, created_at, updated_at, text, owner_role, due_date, status, response, report_id), UPDATE (status, response, responded_by_id, responded_at, updated_at) ON impact_report_recommendation TO edify_activities_rw;
-- A reviewed impact report released to country leadership
-- (reports.release_to_leadership): the release, written once per audience.
GRANT SELECT (id, report_id, audience, school_id, status, redaction_profile, rendered_payload, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, created_at, updated_at), INSERT (id, created_at, updated_at, audience, redaction_profile, rendered_payload, status, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, report_id, school_id), UPDATE (redaction_profile, rendered_payload, status, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, updated_at) ON impact_report_release TO edify_activities_rw;
-- A school brief recorded as shared closes its account owner's to-do
-- (reports.record_brief_shared → action_service.resolve_manually).
GRANT SELECT (id, condition_key, state, recipient_id, due_date, manual_resolution_reason, created_at), UPDATE (state, resolved_at, manual_resolution_reason, resolved_by_system, updated_at) ON team_action TO edify_activities_rw;
-- A coordinator's hand-over of project schools to a partner
-- (planning_views.special_projects_bulk_partner_view): the hand-over names
-- its project, and the school's multiple-Partner review is read by its key
-- before the save, which Go makes only while that review would not change.
GRANT INSERT (project_id) ON partner_assignment TO edify_activities_rw;
GRANT SELECT (condition_key) ON data_quality_issue TO edify_activities_rw;
-- The partner's period invoice (partner_invoices.submit_invoice): one invoice
-- for each Programme Lead and its lines, written from the plan; nothing
-- changed or removed.
GRANT INSERT (id, created_at, updated_at, partner_id, invoice_type, period_kind, period_start, period_end, system_total,
              entered_total, payable_amount, stored_name, original_name, mime_type, file_size, status, submitted_by,
              pl_confirmed_by, pl_confirmed_at, pl_note, program_lead_staff_id)
  ON partner_invoice TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, instalment, planned_amount, payable_amount, category, activity_id, invoice_id,
              payment_id)
  ON partner_invoice_item TO edify_activities_rw;
-- A partner cancelling its own dated work (services._cancel_or_defer →
-- partners.services.undo_assignment_scheduling): the hand-over waits for the
-- partner again, or is closed with the booking; locked for that change.
GRANT UPDATE (status, scheduled_date, scheduled_activity_id, training_course_id, returned_at, return_reason, resolution,
              resolution_note, resolved_at, resolved_by, updated_at)
  ON partner_assignment TO edify_activities_rw;
