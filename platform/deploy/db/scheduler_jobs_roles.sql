-- Native Go standalone scheduler operational SQL functions (Step 4 + Batch 20).
--
-- Keeps edify_gateway read-only by default; every recurring background job
-- mutation runs through narrow SECURITY DEFINER functions owned by
-- edify_scheduler_owner (NOLOGIN NOINHERIT), recording ground-truth execution
-- history into public.scheduled_job_execution.
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_scheduler_owner') THEN
    CREATE ROLE edify_scheduler_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_scheduler_owner;
GRANT USAGE ON SCHEMA public TO edify_scheduler_owner;

GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_job_execution TO edify_scheduler_owner;
GRANT SELECT, DELETE ON mfa_challenge TO edify_scheduler_owner;
GRANT SELECT, UPDATE (reminded_at, activated_at, expired_at, updated_at) ON acting_assignment TO edify_scheduler_owner;
GRANT SELECT, UPDATE (priority, reminder_count, updated_at) ON notification TO edify_scheduler_owner;
GRANT SELECT, UPDATE (state, updated_at) ON team_action TO edify_scheduler_owner;
GRANT SELECT, UPDATE (processed_at, updated_at) ON domain_event_log TO edify_scheduler_owner;
GRANT SELECT, UPDATE (status, updated_at) ON activity TO edify_scheduler_owner;
GRANT SELECT, UPDATE (next_due_date, updated_at) ON admin_maintenance_template TO edify_scheduler_owner;
GRANT SELECT, INSERT ON admin_ops_work_item TO edify_scheduler_owner;
GRANT SELECT ON activity_schedule_cost_line TO edify_scheduler_owner;
GRANT SELECT, INSERT, UPDATE (total_amount, updated_at) ON weekly_fund_request TO edify_scheduler_owner;
GRANT SELECT, INSERT, UPDATE (program_total, total_amount, activity_count, updated_at) ON monthly_work_plan_budget TO edify_scheduler_owner;
GRANT SELECT ON document_version TO edify_scheduler_owner;
GRANT SELECT, UPDATE (status, updated_at) ON document_asset TO edify_scheduler_owner;
GRANT SELECT, UPDATE (days_overdue, updated_at) ON planning_oversight_follow_up TO edify_scheduler_owner;
GRANT SELECT, UPDATE (state, updated_at) ON ssa_recommendation TO edify_scheduler_owner;
GRANT SELECT, INSERT ON ia_verification_sample TO edify_scheduler_owner;
GRANT SELECT, UPDATE (activity_executed, salesforce_id_entered, ia_verified, last_evaluated_at, updated_at) ON closure_checklist TO edify_scheduler_owner;
GRANT SELECT (seq, hash, prev_hash) ON audit_log TO edify_scheduler_owner;

CREATE SCHEMA IF NOT EXISTS gateway_scheduler AUTHORIZATION edify_scheduler_owner;
REVOKE ALL ON SCHEMA gateway_scheduler FROM PUBLIC;

SET ROLE edify_scheduler_owner;

-- Records one scheduled job execution into public.scheduled_job_execution
-- (the ground truth table read by System Health and scheduler_watchdog).
CREATE OR REPLACE FUNCTION gateway_scheduler.record_execution(
  p_job_name         text,
  p_started_at       timestamptz,
  p_completed_at     timestamptz,
  p_status           text,
  p_records          integer,
  p_error_message    text,
  p_runner           text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id  text := 'sje_' || substr(md5(p_job_name || ':' || p_started_at::text || ':' || clock_timestamp()::text), 1, 22);
  v_dur double precision := EXTRACT(EPOCH FROM (p_completed_at - p_started_at));
BEGIN
  INSERT INTO public.scheduled_job_execution (
    created_at, updated_at, id, job_name, started_at, completed_at,
    status, duration_seconds, records_processed, error_message, retry_count, runner
  ) VALUES (
    p_started_at, p_completed_at, v_id, left(p_job_name, 64), p_started_at, p_completed_at,
    left(p_status, 16), GREATEST(0, COALESCE(v_dur, 0)), COALESCE(p_records, 0),
    NULLIF(left(COALESCE(p_error_message, ''), 4000), ''), 0,
    left(COALESCE(NULLIF(p_runner, ''), 'go-scheduler'), 128)
  );
  RETURN v_id;
END
$fn$;

-- Purges consumed or expired MFA challenges past the cutoff timestamp.
CREATE OR REPLACE FUNCTION gateway_scheduler.purge_mfa_challenges(p_cutoff timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_deleted integer;
BEGIN
  DELETE FROM public.mfa_challenge
   WHERE expires_at < p_cutoff
      OR (consumed_at IS NOT NULL AND consumed_at < p_cutoff);
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END
$fn$;

-- Stamps reminded_at (3d before start), activated_at (on/after start), and
-- expired_at (after end_date) on non-cancelled acting_assignment rows and
-- returns transitioned rows so Go appends canonical SHA-256 audit_log entries.
DROP FUNCTION IF EXISTS gateway_scheduler.run_acting_lifecycle(date, timestamptz);
CREATE OR REPLACE FUNCTION gateway_scheduler.run_acting_lifecycle(
  p_today date,
  p_now   timestamptz
) RETURNS TABLE(reminded integer, activated integer, expired integer, activated_rows jsonb, expired_rows jsonb)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_rem      integer := 0;
  v_act      integer := 0;
  v_exp      integer := 0;
  v_act_rows jsonb   := '[]'::jsonb;
  v_exp_rows jsonb   := '[]'::jsonb;
  v_row      record;
BEGIN
  FOR v_row IN
    SELECT id, appointee_id, acting_role
      FROM public.acting_assignment
     WHERE cancelled_at IS NULL
       AND reminded_at IS NULL
       AND start_date > p_today
       AND start_date <= (p_today + interval '3 days')::date
       FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE public.acting_assignment SET reminded_at = p_now, updated_at = p_now WHERE id = v_row.id;
    v_rem := v_rem + 1;
  END LOOP;

  FOR v_row IN
    SELECT id, appointee_id, acting_role
      FROM public.acting_assignment
     WHERE cancelled_at IS NULL
       AND activated_at IS NULL
       AND start_date <= p_today
       AND end_date >= p_today
       FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE public.acting_assignment SET activated_at = p_now, updated_at = p_now WHERE id = v_row.id;
    v_act_rows := v_act_rows || jsonb_build_array(jsonb_build_object(
      'id', v_row.id, 'appointeeId', COALESCE(v_row.appointee_id, ''), 'role', COALESCE(v_row.acting_role, '')
    ));
    v_act := v_act + 1;
  END LOOP;

  FOR v_row IN
    SELECT id, appointee_id, acting_role
      FROM public.acting_assignment
     WHERE cancelled_at IS NULL
       AND expired_at IS NULL
       AND end_date < p_today
       FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE public.acting_assignment SET expired_at = p_now, updated_at = p_now WHERE id = v_row.id;
    v_exp_rows := v_exp_rows || jsonb_build_array(jsonb_build_object(
      'id', v_row.id, 'appointeeId', COALESCE(v_row.appointee_id, ''), 'role', COALESCE(v_row.acting_role, '')
    ));
    v_exp := v_exp + 1;
  END LOOP;

  RETURN QUERY SELECT v_rem, v_act, v_exp, v_act_rows, v_exp_rows;
END
$fn$;

-- Escalates unread action-required notifications older than p_cutoff (48h SLA).
CREATE OR REPLACE FUNCTION gateway_scheduler.escalate_stale_notifications(
  p_cutoff timestamptz,
  p_now    timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.notification
     SET priority       = 'urgent',
         reminder_count = reminder_count + 1,
         updated_at     = p_now
   WHERE status = 'unread'
     AND action_required = true
     AND resolved_at IS NULL
     AND priority <> 'urgent'
     AND created_at <= p_cutoff;
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

-- Marks past-due delegated team_action rows as overdue.
CREATE OR REPLACE FUNCTION gateway_scheduler.sweep_school_actions(
  p_today date,
  p_now   timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.team_action
     SET state      = 'overdue',
         updated_at = p_now
   WHERE state IN ('open', 'acknowledged', 'in_progress')
     AND due_date IS NOT NULL
     AND due_date < p_today;
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

-- Claims and marks unprocessed domain_event_log rows using SKIP LOCKED.
CREATE OR REPLACE FUNCTION gateway_scheduler.drain_domain_events(
  p_now   timestamptz,
  p_limit integer
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_drained integer;
BEGIN
  WITH claimed AS (
    SELECT id
      FROM public.domain_event_log
     WHERE processed_at IS NULL
     ORDER BY created_at ASC
     LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 100), 500))
       FOR UPDATE SKIP LOCKED
  )
  UPDATE public.domain_event_log d
     SET processed_at = p_now,
         updated_at   = p_now
    FROM claimed
   WHERE d.id = claimed.id;
  GET DIAGNOSTICS v_drained = ROW_COUNT;
  RETURN v_drained;
END
$fn$;

-- Prunes scheduled_job_execution past retention (90d success, 365d failure),
-- NEVER deleting any job's latest successful run.
CREATE OR REPLACE FUNCTION gateway_scheduler.prune_scheduler_history(p_now timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_deleted integer;
BEGIN
  WITH latest_ok AS (
    SELECT DISTINCT ON (job_name) id
      FROM public.scheduled_job_execution
     WHERE status = 'success'
     ORDER BY job_name, started_at DESC
  )
  DELETE FROM public.scheduled_job_execution e
   WHERE e.id NOT IN (SELECT id FROM latest_ok)
     AND (
       (e.status = 'success' AND e.started_at < p_now - interval '90 days')
       OR (e.status <> 'success' AND e.started_at < p_now - interval '365 days')
     );
  GET DIAGNOSTICS v_deleted = ROW_COUNT;
  RETURN v_deleted;
END
$fn$;

-- Verifies audit_log chain continuity (returns count of empty hashes).
CREATE OR REPLACE FUNCTION gateway_scheduler.verify_audit_chain()
RETURNS integer
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT COUNT(*)::integer
    FROM public.audit_log
   WHERE hash IS NULL OR hash = '';
$fn$;

-- Batch 20: Hands in completed/in_progress activities that already carry a
-- Salesforce Activity ID so staff work reaches the PL Review Queue automatically.
CREATE OR REPLACE FUNCTION gateway_scheduler.hand_in_entered_work(p_now timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.activity
     SET status     = 'submitted_to_pl',
         updated_at = p_now
   WHERE deleted_at IS NULL
     AND status IN ('in_progress', 'completed')
     AND COALESCE(btrim(salesforce_activity_id), '') <> '';
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

-- Batch 20: Materializes due admin_maintenance_template rows into
-- admin_ops_work_item and advances next_due_date idempotently.
CREATE OR REPLACE FUNCTION gateway_scheduler.generate_due_maintenance(
  p_today date,
  p_now   timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_row     record;
  v_created integer := 0;
  v_id      text;
  v_ref     text;
BEGIN
  FOR v_row IN
    SELECT id, name, category, description, frequency_days, next_due_date, owner_id
      FROM public.admin_maintenance_template
     WHERE active = true
       AND next_due_date <= p_today
       FOR UPDATE SKIP LOCKED
  LOOP
    v_id  := 'mwi_' || substr(md5(v_row.id || ':' || v_row.next_due_date::text), 1, 20);
    v_ref := 'MAINT-' || upper(substr(md5(v_row.id || ':' || v_row.next_due_date::text), 1, 8));
    INSERT INTO public.admin_ops_work_item (
      created_at, updated_at, id, reference, title, category, description,
      severity, status, owner_id, due_date, scheduled_date,
      next_action, resolution_criteria, verification_note,
      affected_module, affected_route
    ) VALUES (
      p_now, p_now, v_id, v_ref, left(v_row.name, 200), v_row.category, v_row.description,
      'medium', 'open', v_row.owner_id, v_row.next_due_date, v_row.next_due_date,
      'Execute scheduled maintenance checklist', 'All checklist steps verified', '',
      'admin_ops', '/admin/ops'
    )
    ON CONFLICT (id) DO NOTHING;

    UPDATE public.admin_maintenance_template
       SET next_due_date = v_row.next_due_date + GREATEST(1, v_row.frequency_days),
           updated_at    = p_now
     WHERE id = v_row.id;

    v_created := v_created + 1;
  END LOOP;
  RETURN v_created;
END
$fn$;

-- Batch 20: Rebuilds upcoming weekly_fund_request drafts from
-- activity_schedule_cost_line without touching submitted/approved/disbursed weeks.
CREATE OR REPLACE FUNCTION gateway_scheduler.upsert_weekly_drafts(
  p_week_start date,
  p_week_end   date,
  p_fy         text,
  p_now        timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_row     record;
  v_touched integer := 0;
  v_id      text;
BEGIN
  FOR v_row IN
    SELECT responsible_user,
           COALESCE(NULLIF(MAX(responsible_role), ''), 'CCEO') AS role_name,
           SUM(COALESCE(total_cost, amount, 0))::bigint AS total_amt
      FROM public.activity_schedule_cost_line
     WHERE week_start_date = p_week_start
       AND COALESCE(btrim(responsible_user), '') <> ''
     GROUP BY responsible_user
    HAVING SUM(COALESCE(total_cost, amount, 0)) > 0
  LOOP
    v_id := 'wfr_' || substr(md5(v_row.responsible_user || ':' || p_week_start::text), 1, 20);
    INSERT INTO public.weekly_fund_request (
      created_at, updated_at, id, fy, week_start_date, week_end_date,
      responsible_user, responsible_role, total_amount, status,
      return_reason, funding_source
    ) VALUES (
      p_now, p_now, v_id, p_fy, p_week_start, p_week_end,
      v_row.responsible_user, v_row.role_name, v_row.total_amt,
      'pending_responsible_confirmation', '', 'core_budget'
    )
    ON CONFLICT (responsible_user, week_start_date) DO UPDATE
      SET total_amount = EXCLUDED.total_amount,
          updated_at   = p_now
    WHERE weekly_fund_request.status IN (
      'draft', 'pending_responsible_confirmation',
      'returned_by_pl', 'returned_by_cd', 'returned_by_accountant'
    );
    IF FOUND THEN
      v_touched := v_touched + 1;
    END IF;
  END LOOP;
  RETURN v_touched;
END
$fn$;

-- Batch 20: Upserts draft monthly_work_plan_budget for a country+month without
-- overwriting submitted/approved budgets.
CREATE OR REPLACE FUNCTION gateway_scheduler.upsert_monthly_budget_draft(
  p_fy         text,
  p_month_key  text,
  p_country_id text,
  p_now        timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_prog  bigint := 0;
  v_count integer := 0;
  v_id    text := 'mwb_' || substr(md5(COALESCE(p_country_id, 'UG') || ':' || p_month_key), 1, 20);
BEGIN
  SELECT COALESCE(SUM(COALESCE(total_cost, amount, 0)), 0)::bigint,
         COUNT(DISTINCT activity_id)::integer
    INTO v_prog, v_count
    FROM public.activity_schedule_cost_line
   WHERE fiscal_year = p_fy
     AND planned_date IS NOT NULL
     AND to_char(planned_date, 'YYYY-MM') = p_month_key;

  INSERT INTO public.monthly_work_plan_budget (
    created_at, updated_at, id, fy, month_key, country_id,
    generated_at, generated_by, status,
    program_total, admin_total, total_amount, activity_count,
    submission_version, country_funding_shortfall, deferred_amount,
    operational_activity_requirement, reference_configuration_missing_count,
    regional_standard_ceiling, strategic_reserve_requested
  ) VALUES (
    p_now, p_now, v_id, p_fy, p_month_key, p_country_id,
    p_now, 'go-scheduler', 'draft',
    v_prog, 0, v_prog, v_count,
    1, 0, 0, v_prog, 0, 0, 0
  )
  ON CONFLICT (country_id, month_key) DO UPDATE
    SET program_total  = EXCLUDED.program_total,
        total_amount   = EXCLUDED.program_total + monthly_work_plan_budget.admin_total,
        activity_count = EXCLUDED.activity_count,
        updated_at     = p_now
  WHERE monthly_work_plan_budget.status = 'draft';

  IF FOUND THEN
    RETURN 1;
  END IF;
  RETURN 0;
END
$fn$;

-- Batch 20: Activates scheduled documents on effective_date and expires
-- published documents past expiry_date idempotently.
CREATE OR REPLACE FUNCTION gateway_scheduler.reconcile_document_lifecycle(
  p_today date,
  p_now   timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_pub integer := 0;
  v_exp integer := 0;
BEGIN
  UPDATE public.document_asset d
     SET status     = 'published',
         updated_at = p_now
    FROM public.document_version v
   WHERE d.current_version_id = v.id
     AND d.archived_at IS NULL
     AND d.status = 'scheduled'
     AND v.effective_date IS NOT NULL
     AND v.effective_date <= p_today;
  GET DIAGNOSTICS v_pub = ROW_COUNT;

  UPDATE public.document_asset d
     SET status     = 'expired',
         updated_at = p_now
    FROM public.document_version v
   WHERE d.current_version_id = v.id
     AND d.archived_at IS NULL
     AND d.status = 'published'
     AND v.expiry_date IS NOT NULL
     AND v.expiry_date < p_today;
  GET DIAGNOSTICS v_exp = ROW_COUNT;

  RETURN v_pub + v_exp;
END
$fn$;

-- Batch 25: Computes overdue days on open planning_oversight_follow_up rows.
CREATE OR REPLACE FUNCTION gateway_scheduler.sweep_planning_followups(
  p_today date,
  p_now   timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.planning_oversight_follow_up
     SET days_overdue = GREATEST(0, (p_today - due_date)::integer),
         updated_at   = p_now
   WHERE status NOT IN ('resolved', 'closed')
     AND due_date < p_today
     AND COALESCE(days_overdue, -1) <> GREATEST(0, (p_today - due_date)::integer);
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

-- Batch 25: Expires stale ssa_recommendation rows past expires_on.
CREATE OR REPLACE FUNCTION gateway_scheduler.expire_ssa_recommendations(
  p_today date,
  p_now   timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.ssa_recommendation
     SET state      = 'expired',
         updated_at = p_now
   WHERE state = 'open'
     AND expires_on IS NOT NULL
     AND expires_on < p_today;
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

-- Batch 25: Samples IA-verified activities into ia_verification_sample idempotently.
CREATE OR REPLACE FUNCTION gateway_scheduler.sample_ia_verifications(
  p_now   timestamptz,
  p_limit integer
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_row     record;
  v_created integer := 0;
  v_id      text;
BEGIN
  FOR v_row IN
    SELECT a.id, COALESCE(NULLIF(a.ia_confirmed_by, ''), 'system') AS verifier
      FROM public.activity a
     WHERE a.deleted_at IS NULL
       AND a.ia_verification_status = 'verified'
       AND NOT EXISTS (
         SELECT 1 FROM public.ia_verification_sample s WHERE s.activity_id = a.id
       )
     ORDER BY a.updated_at DESC
     LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 10), 50))
  LOOP
    v_id := 'ivs_' || substr(md5(v_row.id || ':sample'), 1, 20);
    INSERT INTO public.ia_verification_sample (
      created_at, updated_at, id, original_verifier, sampled_at, sampled_by,
      status, outcome_note, activity_id, method, subject_type
    ) VALUES (
      p_now, p_now, v_id, v_row.verifier, p_now, 'go-scheduler',
      'pending', '', v_row.id, 'periodic_random', 'activity'
    )
    ON CONFLICT (id) DO NOTHING;
    IF FOUND THEN
      v_created := v_created + 1;
    END IF;
  END LOOP;
  RETURN v_created;
END
$fn$;

-- Batch 25: Reconciles closure_checklist readiness flags from public.activity.
CREATE OR REPLACE FUNCTION gateway_scheduler.refresh_closure_checklists(p_now timestamptz)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_changed integer;
BEGIN
  UPDATE public.closure_checklist c
     SET activity_executed     = (a.status IN ('completed', 'submitted_to_pl', 'pl_approved', 'ia_verified', 'closed')),
         salesforce_id_entered = (COALESCE(btrim(a.salesforce_activity_id), '') <> ''),
         ia_verified           = (a.ia_verification_status = 'verified'),
         last_evaluated_at     = p_now,
         updated_at            = p_now
    FROM public.activity a
   WHERE c.activity_id = a.id
     AND a.deleted_at IS NULL
     AND (
       c.activity_executed <> (a.status IN ('completed', 'submitted_to_pl', 'pl_approved', 'ia_verified', 'closed'))
       OR c.salesforce_id_entered <> (COALESCE(btrim(a.salesforce_activity_id), '') <> '')
       OR c.ia_verified <> (a.ia_verification_status = 'verified')
     );
  GET DIAGNOSTICS v_changed = ROW_COUNT;
  RETURN v_changed;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_scheduler.record_execution(text, timestamptz, timestamptz, text, integer, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.purge_mfa_challenges(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.run_acting_lifecycle(date, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.escalate_stale_notifications(timestamptz, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.sweep_school_actions(date, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.drain_domain_events(timestamptz, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.prune_scheduler_history(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.verify_audit_chain() FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.hand_in_entered_work(timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.generate_due_maintenance(date, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.upsert_weekly_drafts(date, date, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.upsert_monthly_budget_draft(text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_scheduler.reconcile_document_lifecycle(date, timestamptz) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_scheduler TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.record_execution(text, timestamptz, timestamptz, text, integer, text, text) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.purge_mfa_challenges(timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.run_acting_lifecycle(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.escalate_stale_notifications(timestamptz, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.sweep_school_actions(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.drain_domain_events(timestamptz, integer) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.prune_scheduler_history(timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.verify_audit_chain() TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.hand_in_entered_work(timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.generate_due_maintenance(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.upsert_weekly_drafts(date, date, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.upsert_monthly_budget_draft(text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.reconcile_document_lifecycle(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.sweep_planning_followups(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.expire_ssa_recommendations(date, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.sample_ia_verifications(timestamptz, integer) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_scheduler.refresh_closure_checklists(timestamptz) TO edify_gateway;
