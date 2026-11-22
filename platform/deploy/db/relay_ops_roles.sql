-- Native Go replacement for legacy Django security/account event relays (Step 2).
--
-- Implements the real side effects previously performed by:
--   - apps/accounts/security_event_relay.py -> SystemIncidentService.report (admin_system_incident)
--   - apps/accounts/account_event_relay.py  -> partner login release (partner.user_id = NULL) + audit_log
--                                           -> open planned days lookup for roles_changed repricing
--
-- Keeps edify_gateway read-only by default; all writes pass through narrow
-- SECURITY DEFINER functions owned by edify_relay_ops_owner (NOLOGIN NOINHERIT).
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_relay_ops_owner') THEN
    CREATE ROLE edify_relay_ops_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_relay_ops_owner;
GRANT USAGE ON SCHEMA public TO edify_relay_ops_owner;

GRANT SELECT, INSERT, UPDATE ON admin_system_incident TO edify_relay_ops_owner;
GRANT SELECT, UPDATE (user_id, user_setup_status, updated_at) ON partner TO edify_relay_ops_owner;
GRANT SELECT ON daily_visit_batch TO edify_relay_ops_owner;
GRANT SELECT ON staff_profile TO edify_relay_ops_owner;
GRANT SELECT ON weekly_fund_request TO edify_relay_ops_owner;
GRANT INSERT (
  id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
) ON domain_event_log TO edify_relay_ops_owner;

CREATE SCHEMA IF NOT EXISTS gateway_relay_ops AUTHORIZATION edify_relay_ops_owner;
REVOKE ALL ON SCHEMA gateway_relay_ops FROM PUBLIC;

SET ROLE edify_relay_ops_owner;

-- Mirrors SecurityAlertService.failed_login_threshold_reached -> SystemIncidentService.report:
-- dedupes by signature, creates INC-XXXXXX or increments occurrence_count (reopening if closed/resolved),
-- and writes domain_event_log. Callers append the canonical SHA-256 audit_log row in Go via audit.Append.
DROP FUNCTION IF EXISTS gateway_relay_ops.record_security_incident(text, text, text, text, text, text, jsonb, timestamptz);
CREATE OR REPLACE FUNCTION gateway_relay_ops.record_security_incident(
  p_signature text,
  p_title text,
  p_category text,
  p_severity text,
  p_route text,
  p_component text,
  p_detail jsonb,
  p_at timestamptz
) RETURNS TABLE(incident_id text, reference text, created boolean, reopened boolean, occurrence_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id        text;
  v_ref       text;
  v_status    text;
  v_occ       integer;
  v_created   boolean := false;
  v_reopened  boolean := false;
  v_n         integer;
  v_try       integer;
BEGIN
  SELECT i.id, i.reference, i.status, i.occurrence_count
    INTO v_id, v_ref, v_status, v_occ
    FROM public.admin_system_incident i
   WHERE i.signature = p_signature
     FOR UPDATE;

  IF NOT FOUND THEN
    SELECT COUNT(*) + 1 INTO v_n FROM public.admin_system_incident;
    FOR v_try IN 0..50 LOOP
      v_ref := 'INC-' || lpad((v_n + v_try)::text, 6, '0');
      EXIT WHEN NOT EXISTS (SELECT 1 FROM public.admin_system_incident ai WHERE ai.reference = v_ref);
    END LOOP;
    v_id := 'inc_' || substr(md5(p_signature || ':' || clock_timestamp()::text), 1, 22);
    v_occ := 1;
    v_created := true;

    INSERT INTO public.admin_system_incident (
      created_at, updated_at, id, reference, signature, title,
      category, severity, status, affected_route, affected_component,
      affected_roles, detail, samples, occurrence_count,
      first_detected_at, last_detected_at, reopened_count
    ) VALUES (
      p_at, p_at, v_id, v_ref, left(p_signature, 64), left(p_title, 255),
      COALESCE(NULLIF(p_category, ''), 'security'),
      COALESCE(NULLIF(p_severity, ''), 'high'),
      'open', left(COALESCE(p_route, '/login'), 255),
      left(COALESCE(p_component, 'authentication'), 128),
      '[]'::jsonb, COALESCE(p_detail, '{}'::jsonb), '[]'::jsonb, 1,
      p_at, p_at, 0
    );
  ELSE
    v_occ := v_occ + 1;
    IF v_status IN ('resolved', 'closed') THEN
      v_reopened := true;
      UPDATE public.admin_system_incident
         SET occurrence_count = v_occ,
             last_detected_at = p_at,
             detail           = COALESCE(p_detail, detail),
             status           = 'open',
             reopened_count   = reopened_count + 1,
             resolved_at      = NULL,
             updated_at       = p_at
       WHERE id = v_id;
    ELSE
      UPDATE public.admin_system_incident
         SET occurrence_count = v_occ,
             last_detected_at = p_at,
             detail           = COALESCE(p_detail, detail),
             updated_at       = p_at
       WHERE id = v_id;
    END IF;
  END IF;

  INSERT INTO public.domain_event_log (
    id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
  ) VALUES (
    'evt_' || substr(md5(v_id || ':' || v_occ::text || ':' || clock_timestamp()::text), 1, 22),
    CASE WHEN v_created THEN 'incident.detected' ELSE 'incident.recurred' END,
    'SystemIncident', v_id, NULL,
    jsonb_build_object('reference', v_ref, 'severity', p_severity, 'occurrences', v_occ),
    p_at, p_at
  );

  RETURN QUERY SELECT v_id::text, v_ref::text, v_created, v_reopened, v_occ;
END
$fn$;

-- Mirrors apps/accounts/account_event_relay.py _release_partner_login:
-- releases partner.user_id when an account is deleted and returns each released partner
-- so Go appends the canonical SHA-256 audit_log entry in the same transaction.
DROP FUNCTION IF EXISTS gateway_relay_ops.release_partner_login(text, text, text, timestamptz);
CREATE OR REPLACE FUNCTION gateway_relay_ops.release_partner_login(
  p_user_id text,
  p_actor_id text,
  p_actor_role text,
  p_at timestamptz
) RETURNS TABLE(partner_id text, partner_name text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_partner record;
BEGIN
  FOR v_partner IN
    SELECT p.id, p.name
      FROM public.partner p
     WHERE p.user_id = p_user_id AND p.deleted_at IS NULL
       FOR UPDATE
  LOOP
    UPDATE public.partner
       SET user_id           = NULL,
           user_setup_status = 'pending',
           updated_at        = p_at
     WHERE id = v_partner.id;

    RETURN QUERY SELECT v_partner.id::text, v_partner.name::text;
  END LOOP;
END
$fn$;

-- Lists future/today unlocked daily_visit_batch rows for a user whose roles changed.
CREATE OR REPLACE FUNCTION gateway_relay_ops.open_planned_batches_for_user(
  p_user_id text,
  p_today date
) RETURNS TABLE(batch_id text, owner_uid text)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  WITH owner_ids AS (
    SELECT p_user_id AS oid
    UNION
    SELECT sp.id FROM public.staff_profile sp WHERE sp.user_id = p_user_id AND sp.deleted_at IS NULL
  )
  SELECT b.id::text, b.responsible_user::text
    FROM public.daily_visit_batch b
   WHERE b.responsible_user IN (SELECT oid FROM owner_ids)
     AND b.visit_date >= p_today
     AND b.school_count > 0
     AND NOT EXISTS (
       SELECT 1 FROM public.weekly_fund_request w
        WHERE w.responsible_user = b.responsible_user
          AND w.week_start_date <= b.visit_date
          AND w.week_end_date >= b.visit_date
          AND w.status NOT IN (
            'draft', 'pending_responsible_confirmation',
            'returned_by_pl', 'returned_by_cd', 'returned_by_accountant'
          )
     )
   ORDER BY b.visit_date ASC, b.id ASC;
$fn$;

REVOKE ALL ON FUNCTION gateway_relay_ops.record_security_incident(text, text, text, text, text, text, jsonb, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_relay_ops.release_partner_login(text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_relay_ops.open_planned_batches_for_user(text, date) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_relay_ops TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_relay_ops.record_security_incident(text, text, text, text, text, text, jsonb, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_relay_ops.release_partner_login(text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_relay_ops.open_planned_batches_for_user(text, date) TO edify_gateway;
