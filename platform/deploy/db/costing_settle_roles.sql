-- Native Go day-pool costing settlement and durable activity events (Step 1).
--
-- Keeps edify_gateway read-only by default and preserves dbguard invariants:
-- edify_gateway holds NO direct UPDATE on protectedColumns (activity.est_cost_cents,
-- daily_visit_batch.daily_pool_amount, etc.) and NO direct DELETE on undeletableTables
-- (daily_visit_costs_to_follow, activity_cost_snapshot). All settlement writes pass
-- through narrow SECURITY DEFINER functions owned by edify_costing_owner (NOLOGIN NOINHERIT).
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_costing_owner') THEN
    CREATE ROLE edify_costing_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_costing_owner;
GRANT USAGE ON SCHEMA public TO edify_costing_owner;

-- Narrow read grants needed for settlement & audit chaining.
GRANT SELECT ON daily_visit_batch TO edify_costing_owner;
GRANT SELECT ON activity TO edify_costing_owner;
GRANT SELECT ON activity_cost_snapshot TO edify_costing_owner;
GRANT SELECT ON activity_schedule_cost_line TO edify_costing_owner;
GRANT SELECT ON daily_visit_costs_to_follow TO edify_costing_owner;
GRANT SELECT ON weekly_fund_request TO edify_costing_owner;
GRANT SELECT ON weekly_fund_request_line TO edify_costing_owner;
GRANT SELECT ON advance_request TO edify_costing_owner;

-- Narrow write grants confined to costing settlement tables.
GRANT UPDATE (
  district_type, cost_catalogue_id, catalogue_version, rate_snapshot,
  daily_pool_amount, school_count, per_school_amount, required_target_snapshot,
  school_visit_allocation, planned_field_cost_per_school,
  actual_field_cost_per_school, workload_snapshot, updated_at
) ON daily_visit_batch TO edify_costing_owner;

GRANT UPDATE (
  est_cost_cents, cost_missing, week_start_date, week_end_date,
  month, fiscal_year, updated_at
) ON activity TO edify_costing_owner;

GRANT INSERT ON activity_cost_snapshot TO edify_costing_owner;
GRANT UPDATE (is_current, updated_at) ON activity_cost_snapshot TO edify_costing_owner;

GRANT INSERT, UPDATE, DELETE ON activity_schedule_cost_line TO edify_costing_owner;

GRANT INSERT (
  created_at, updated_at, owners, asked_by, asked_by_role,
  steps, provenance, attempts, held_reason
) ON daily_visit_costs_to_follow TO edify_costing_owner;
GRANT UPDATE (attempts, held_at, held_reason, updated_at) ON daily_visit_costs_to_follow TO edify_costing_owner;
GRANT DELETE ON daily_visit_costs_to_follow TO edify_costing_owner;
GRANT USAGE, SELECT ON SEQUENCE daily_visit_costs_to_follow_id_seq TO edify_costing_owner;

GRANT INSERT (
  id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
) ON domain_event_log TO edify_costing_owner;

CREATE SCHEMA IF NOT EXISTS gateway_costing AUTHORIZATION edify_costing_owner;
REVOKE ALL ON SCHEMA gateway_costing FROM PUBLIC;

SET ROLE edify_costing_owner;

-- Read specific daily_visit_costs_to_follow rows by ID.
CREATE OR REPLACE FUNCTION gateway_costing.read_costs_to_follow(row_ids bigint[])
RETURNS TABLE(
  id bigint,
  steps jsonb,
  owners jsonb,
  asked_by text,
  asked_by_role text,
  attempts integer,
  held_at timestamptz,
  held_reason text
)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT c.id, c.steps, c.owners, c.asked_by::text, c.asked_by_role::text,
         c.attempts::integer, c.held_at, c.held_reason::text
    FROM public.daily_visit_costs_to_follow c
   WHERE c.id = ANY(row_ids)
   ORDER BY c.id;
$fn$;

-- Read unsettled, non-quarantined costs-to-follow rows for cost_reprice_sweep.
CREATE OR REPLACE FUNCTION gateway_costing.read_unsettled_costs(p_limit integer)
RETURNS TABLE(
  id bigint,
  steps jsonb,
  owners jsonb,
  asked_by text,
  asked_by_role text,
  attempts integer
)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT c.id, c.steps, c.owners, c.asked_by::text, c.asked_by_role::text,
         c.attempts::integer
    FROM public.daily_visit_costs_to_follow c
   WHERE c.held_at IS NULL AND c.attempts < 5
   ORDER BY c.created_at ASC, c.id ASC
   LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 200));
$fn$;

-- Update daily_visit_batch with newly computed pool totals and workload snapshot.
CREATE OR REPLACE FUNCTION gateway_costing.update_batch(
  p_batch_id text,
  p_district_type text,
  p_catalogue_id text,
  p_catalogue_version integer,
  p_rate_snapshot jsonb,
  p_daily_pool_amount bigint,
  p_school_count integer,
  p_per_school_amount bigint,
  p_required_target integer,
  p_school_visit_alloc bigint,
  p_planned_per_school bigint,
  p_workload_snapshot jsonb,
  p_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  UPDATE public.daily_visit_batch
     SET district_type                 = p_district_type,
         cost_catalogue_id             = NULLIF(p_catalogue_id, ''),
         catalogue_version             = p_catalogue_version,
         rate_snapshot                 = COALESCE(p_rate_snapshot, '{}'::jsonb),
         daily_pool_amount             = p_daily_pool_amount,
         school_count                  = p_school_count,
         per_school_amount             = p_per_school_amount,
         required_target_snapshot      = p_required_target,
         school_visit_allocation       = p_school_visit_alloc,
         planned_field_cost_per_school = p_planned_per_school,
         workload_snapshot             = COALESCE(p_workload_snapshot, '{}'::jsonb),
         updated_at                    = p_at
   WHERE id = p_batch_id;
  RETURN FOUND;
END
$fn$;

-- Persist one activity's settled cost, snapshot revision, schedule cost lines,
-- and chained audit + domain event rows atomically inside the caller's tx.
CREATE OR REPLACE FUNCTION gateway_costing.apply_activity_cost(
  p_activity_id text,
  p_operational_cost bigint,
  p_cost_missing boolean,
  p_week_start date,
  p_week_end date,
  p_month integer,
  p_fy text,
  p_quarter text,
  p_catalogue_id text,
  p_catalogue_version integer,
  p_currency text,
  p_responsible_user text,
  p_responsible_role text,
  p_calculated_by text,
  p_snapshot_id text,
  p_calc_inputs jsonb,
  p_op_breakdown jsonb,
  p_missing_cfg jsonb,
  p_lines jsonb,
  p_audit_id text,
  p_event_id text,
  p_at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_prev_id   text;
  v_prev_seq  integer := 0;
  v_next_seq  integer;
  v_cat_item  text;
  v_cat_ver   integer;
  v_profile   text;
  v_school    text;
  v_cluster   text;
  v_project   text;
  v_partner   text;
  v_planned   date;
  v_line      jsonb;
  v_key       text;
  v_label     text;
  v_unit      bigint;
  v_qty       integer;
  v_amount    bigint;
  v_line_id   text;
  v_keys      text[] := ARRAY[]::text[];
  v_tag       text;
  v_type      text;
  v_described text;
  v_delivered boolean;
  v_fee_partner text;
  v_line_partner text;
  v_hotel_booked boolean;
  v_accommodation text[] := ARRAY['secondary_accommodation_per_night', 'management_accommodation_per_night'];
BEGIN
  SELECT a.catalogue_item_id, a.catalogue_version, a.costing_profile_snapshot,
         a.school_id, a.cluster_id, a.project_id, a.assigned_partner_id, a.planned_date,
         a.delivery_type = 'partner', a.facilitating_partner_id,
         -- costing_service tags a Core activity's budget lines.
         CASE WHEN a.activity_type = 'core_visit' AND a.delivery_type = 'partner' THEN 'Core Partner Activity'
              WHEN a.activity_type = 'core_training' AND a.delivery_type = 'partner' THEN 'Core Partner Activity'
              WHEN a.activity_type = 'core_visit' THEN 'Core Visit'
              WHEN a.activity_type = 'core_training' THEN 'Core Training' END
    INTO v_cat_item, v_cat_ver, v_profile, v_school, v_cluster, v_project, v_partner, v_planned,
         v_delivered, v_fee_partner, v_tag
    FROM public.activity a
   WHERE a.id = p_activity_id AND a.deleted_at IS NULL
     FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;

  UPDATE public.activity
     SET est_cost_cents  = p_operational_cost,
         cost_missing    = p_cost_missing,
         week_start_date = p_week_start,
         week_end_date   = p_week_end,
         month           = p_month,
         fiscal_year     = p_fy,
         updated_at      = p_at
   WHERE id = p_activity_id;

  SELECT s.id, s.sequence
    INTO v_prev_id, v_prev_seq
    FROM public.activity_cost_snapshot s
   WHERE s.activity_id = p_activity_id AND s.is_current = true
   ORDER BY s.sequence DESC
   LIMIT 1
     FOR UPDATE;

  IF v_prev_id IS NOT NULL THEN
    UPDATE public.activity_cost_snapshot
       SET is_current = false, updated_at = p_at
     WHERE activity_id = p_activity_id AND is_current = true;
  END IF;
  v_next_seq := COALESCE(v_prev_seq, 0) + 1;

  INSERT INTO public.activity_cost_snapshot (
    created_at, updated_at, id, sequence, is_current,
    activity_catalogue_item_id, activity_catalogue_version, costing_profile_version,
    reference_cost, operational_cost, approved_operating_limit,
    amount_disbursed, actual_accounted_spend, unused_balance, reimbursement_amount,
    calculation_inputs, reference_breakdown, operational_breakdown,
    warnings, missing_configuration, calculated_at, calculated_by,
    recalculation_reason, approved_by, approved_at, cost_status,
    activity_id, operational_rate_card_id, reference_rate_card_id, supersedes_id
  ) VALUES (
    p_at, p_at, p_snapshot_id, v_next_seq, true,
    v_cat_item, v_cat_ver, v_profile,
    NULL, p_operational_cost, NULL,
    0, 0, 0, 0,
    COALESCE(p_calc_inputs, '{}'::jsonb), '[]'::jsonb, COALESCE(p_op_breakdown, '[]'::jsonb),
    '[]'::jsonb, COALESCE(p_missing_cfg, '[]'::jsonb), p_at, NULLIF(p_calculated_by, ''),
    'day_pool_settlement', NULL, NULL, 'estimated',
    p_activity_id, NULLIF(p_catalogue_id, ''), NULL, v_prev_id
  );

  -- Finance's hotel booking survives a re-price: the night is one booking
  -- under either accommodation rate.
  SELECT EXISTS (SELECT 1 FROM public.activity_schedule_cost_line l
                  WHERE l.activity_id = p_activity_id AND l.vendor_paid
                    AND split_part(l.cost_setting_key, '#', 1) = ANY (v_accommodation))
    INTO v_hotel_booked;

  -- Upsert each cost line and remove stale unlocked lines not in the new set.
  FOR v_line IN SELECT value FROM jsonb_array_elements(COALESCE(p_lines, '[]'::jsonb))
  LOOP
    v_key    := COALESCE(v_line->>'key', '');
    v_label  := COALESCE(v_line->>'label', v_key);
    v_unit   := COALESCE((v_line->>'unit')::bigint, 0);
    v_qty    := GREATEST(1, COALESCE((v_line->>'qty')::integer, 1));
    v_amount := COALESCE((v_line->>'amount')::bigint, 0);
    v_type   := COALESCE(NULLIF(v_line->>'lineItemType', ''), 'other');
    v_described := CASE WHEN v_tag IS NULL THEN v_label ELSE '[' || v_tag || '] ' || v_label END;
    -- facilitation.line_partner_id: every line of partner-delivered work, and
    -- only the fee of a facilitated training.
    v_line_partner := CASE WHEN COALESCE(v_delivered, false) THEN v_partner
                           WHEN v_type = 'facilitation' THEN v_fee_partner END;
    IF v_key = '' THEN
      CONTINUE;
    END IF;
    v_keys := array_append(v_keys, v_key);

    SELECT l.id INTO v_line_id
      FROM public.activity_schedule_cost_line l
     WHERE l.activity_id = p_activity_id AND l.cost_setting_key = v_key
     LIMIT 1;

    IF v_line_id IS NOT NULL THEN
      UPDATE public.activity_schedule_cost_line
         SET label                      = left(v_label, 255),
             description                = left(v_described, 255),
             line_item_type             = v_type,
             unit_cost                  = v_unit,
             quantity                   = v_qty,
             amount                     = v_amount,
             total_cost                 = v_amount,
             cost_setting_version       = COALESCE(p_catalogue_version, 1),
             catalogue_id               = NULLIF(p_catalogue_id, ''),
             catalogue_version          = p_catalogue_version,
             currency                   = COALESCE(NULLIF(p_currency, ''), 'UGX'),
             fiscal_year                = p_fy,
             quarter                    = p_quarter,
             month                      = p_month,
             planned_date               = v_planned,
             week_start_date            = p_week_start,
             week_end_date              = p_week_end,
             responsible_user           = NULLIF(p_responsible_user, ''),
             responsible_role           = NULL,
             school_id                  = v_school,
             cluster_id                 = v_cluster,
             project_id                 = v_project,
             partner_id                 = v_line_partner,
             vendor_paid                = vendor_paid OR (v_hotel_booked AND split_part(v_key, '#', 1) = ANY (v_accommodation)),
             activity_catalogue_item_id = v_cat_item,
             activity_catalogue_version = v_cat_ver,
             costing_profile            = v_profile,
             updated_at                 = p_at
       WHERE id = v_line_id;
    ELSE
      v_line_id := 'cl_' || substr(md5(p_activity_id || ':' || v_key || ':' || clock_timestamp()::text), 1, 24);
      INSERT INTO public.activity_schedule_cost_line (
        created_at, updated_at, id, cost_setting_key, label, description,
        unit_cost, quantity, amount, total_cost, cost_setting_version,
        activity_id, catalogue_id, catalogue_version, currency, line_item_type,
        cluster_id, fiscal_year, month, partner_id, planned_date, project_id,
        quarter, responsible_role, responsible_user, school_id,
        week_start_date, week_end_date, activity_catalogue_item_id,
        activity_catalogue_version, costing_profile, vendor_paid
      ) VALUES (
        p_at, p_at, v_line_id, left(v_key, 128), left(v_label, 255), left(v_described, 255),
        v_unit, v_qty, v_amount, v_amount, COALESCE(p_catalogue_version, 1),
        p_activity_id, NULLIF(p_catalogue_id, ''), p_catalogue_version,
        COALESCE(NULLIF(p_currency, ''), 'UGX'), v_type,
        v_cluster, p_fy, p_month, v_line_partner, v_planned, v_project,
        p_quarter, NULL, NULLIF(p_responsible_user, ''), v_school,
        p_week_start, p_week_end, v_cat_item, v_cat_ver, v_profile,
        v_hotel_booked AND split_part(v_key, '#', 1) = ANY (v_accommodation)
      );
    END IF;
  END LOOP;

  -- Prune obsolete cost lines that are not pinned by an advance or weekly fund request line.
  DELETE FROM public.activity_schedule_cost_line l
   WHERE l.activity_id = p_activity_id
     AND NOT (l.cost_setting_key = ANY(v_keys))
     AND NOT EXISTS (SELECT 1 FROM public.advance_request ar WHERE ar.budget_line_id = l.id)
     AND NOT EXISTS (SELECT 1 FROM public.weekly_fund_request_line wl WHERE wl.activity_budget_line_id = l.id);

  -- Callers append the canonical SHA-256 audit_log & domain_event_log row in Go via audit.Append.
  RETURN v_next_seq;
END
$fn$;

-- Complete a settled daily_visit_costs_to_follow row.
CREATE OR REPLACE FUNCTION gateway_costing.complete_costs_to_follow(row_id bigint)
RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  DELETE FROM public.daily_visit_costs_to_follow WHERE id = row_id;
  RETURN FOUND;
END
$fn$;

-- Record a settlement failure; quarantine (held_at = p_at) once attempts reach 5.
CREATE OR REPLACE FUNCTION gateway_costing.fail_costs_to_follow(
  row_id bigint,
  p_reason text,
  p_at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_attempts integer;
BEGIN
  UPDATE public.daily_visit_costs_to_follow
     SET attempts    = attempts + 1,
         held_reason = left(COALESCE(p_reason, ''), 500),
         held_at     = CASE WHEN attempts + 1 >= 5 THEN COALESCE(held_at, p_at) ELSE held_at END,
         updated_at  = p_at
   WHERE id = row_id
   RETURNING attempts::integer INTO v_attempts;
  RETURN COALESCE(v_attempts, 0);
END
$fn$;

-- Enqueue a day batch for re-pricing (used on role change or sweep repair).
CREATE OR REPLACE FUNCTION gateway_costing.enqueue_day_reprice(
  p_batch_id text,
  p_owner_uid text,
  p_actor_id text,
  p_actor_role text,
  p_at timestamptz
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id bigint;
BEGIN
  INSERT INTO public.daily_visit_costs_to_follow (
    created_at, updated_at, owners, asked_by, asked_by_role,
    steps, provenance, attempts, held_reason
  ) VALUES (
    p_at, p_at,
    jsonb_build_array(p_owner_uid),
    COALESCE(NULLIF(p_actor_id, ''), 'system'),
    COALESCE(p_actor_role, ''),
    jsonb_build_object(
      'days', jsonb_build_array(jsonb_build_array(p_batch_id, p_owner_uid)),
      'together', false,
      'weeks', '[]'::jsonb,
      'months', '[]'::jsonb,
      'notes', '[]'::jsonb,
      'change', 'roles_changed'
    ),
    '{}'::jsonb,
    0, ''
  )
  RETURNING id INTO v_id;
  RETURN v_id;
END
$fn$;

-- Record a durable observable activity event (plan.changed, etc.) into domain_event_log.
CREATE OR REPLACE FUNCTION gateway_costing.record_activity_event(
  p_event_id text,
  p_event_type text,
  p_activity_id text,
  p_actor_id text,
  p_payload jsonb,
  p_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  INSERT INTO public.domain_event_log (
    id, event_type, aggregate_type, aggregate_id, actor_id, payload, created_at, updated_at
  ) VALUES (
    p_event_id, left(p_event_type, 128), 'Activity', p_activity_id,
    NULLIF(p_actor_id, ''), COALESCE(p_payload, '{}'::jsonb), p_at, p_at
  );
  RETURN true;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_costing.read_costs_to_follow(bigint[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.read_unsettled_costs(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.update_batch(text, text, text, integer, jsonb, bigint, integer, bigint, integer, bigint, bigint, jsonb, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.apply_activity_cost(text, bigint, boolean, date, date, integer, text, text, text, integer, text, text, text, text, text, jsonb, jsonb, jsonb, jsonb, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.complete_costs_to_follow(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.fail_costs_to_follow(bigint, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.enqueue_day_reprice(text, text, text, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_costing.record_activity_event(text, text, text, text, jsonb, timestamptz) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_costing TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.read_costs_to_follow(bigint[]) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.read_unsettled_costs(integer) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.update_batch(text, text, text, integer, jsonb, bigint, integer, bigint, integer, bigint, bigint, jsonb, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.apply_activity_cost(text, bigint, boolean, date, date, integer, text, text, text, integer, text, text, text, text, text, jsonb, jsonb, jsonb, jsonb, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.complete_costs_to_follow(bigint) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.fail_costs_to_follow(bigint, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.enqueue_day_reprice(text, text, text, text, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_costing.record_activity_event(text, text, text, text, jsonb, timestamptz) TO edify_gateway;
