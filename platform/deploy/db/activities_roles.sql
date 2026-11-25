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
