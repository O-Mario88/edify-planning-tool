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
--                        ledger's mark and the costs to follow. No DELETE
--                        anywhere, no UPDATE of an audit row, no UPDATE of
--                        an activity once inserted.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): the save opens a read-write transaction on purpose (08 §8.2).
--
-- Not granted, on purpose (27.7): the school row lock. The existing save
-- holds SELECT … FOR UPDATE on the school while it asks the one-visit rule,
-- and Postgres needs an UPDATE right on some school column for that lock.
-- The staging guard (dbguard.VerifyIdentity) refuses any gateway role that
-- can write a school column, so that grant waits for the owner's decision.

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

-- A Training Follow Up answers the school's open recommendation for its
-- intervention (apps.ssa.plan_alignment.link_recommendations): planned, by
-- this activity. Its other columns stay the SSA's.
GRANT UPDATE (state, planned_activity_id, decided_at, updated_at) ON ssa_recommendation TO edify_activities_rw;
