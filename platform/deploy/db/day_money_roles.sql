-- What follows a priced day when Go settles it with Django absent: the
-- transport company's obligation, each staff advance, the owner's weekly
-- request and their monthly draft. These are the existing application's
-- vendor_channel.ensure_transport_obligation, advance_service.sync_for_activities,
-- weekly_service.generate_weekly_fund_request and monthly_service.sync_monthly_periods.
--
-- The gateway holds no write on these money tables. It may only ask these
-- functions, inside the settlement's own transaction, so a day's costs and its
-- money land together or not at all. Their owner is a NOLOGIN role nobody is a
-- member of.
--
-- The status lists are the existing application's; TestTheMoneyFunctionsNameTheExistingStatuses
-- fails when they differ.
--
-- Applied after costing_settle_roles.sql (apply-roles.sh, the integration
-- TestMain). Idempotent. New database objects: production needs the owner's
-- approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_day_money_owner') THEN
    CREATE ROLE edify_day_money_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_day_money_owner;
GRANT USAGE ON SCHEMA public TO edify_day_money_owner;

GRANT SELECT (id, delivery_type, status, deleted_at, school_id, scheduled_date, cost_missing, planned_date, end_date,
              facilitating_partner_id, fy, quarter, month, responsible_staff_id, daily_visit_batch_id)
  ON activity TO edify_day_money_owner;
GRANT SELECT (id, activity_id, amount, line_item_type, vendor_paid, label, quantity, unit_cost, currency,
              responsible_user, planned_date, fiscal_year, quarter, month)
  ON activity_schedule_cost_line TO edify_day_money_owner;
GRANT SELECT (description), UPDATE (description, updated_at) ON activity_schedule_cost_line TO edify_day_money_owner;
GRANT SELECT (id, responsible_user, visit_date, school_count) ON daily_visit_batch TO edify_day_money_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  advance_request, weekly_fund_request, weekly_fund_request_line, fund_request, fund_request_item, transport_payment
TO edify_day_money_owner;

CREATE SCHEMA IF NOT EXISTS gateway_day_money AUTHORIZATION edify_day_money_owner;
REVOKE ALL ON SCHEMA gateway_day_money FROM PUBLIC;

SET ROLE edify_day_money_owner;

-- MONEY_MOVED_ADVANCE_STATUSES.
CREATE OR REPLACE FUNCTION gateway_day_money.money_moved() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['disbursed', 'accountability_pl_pending', 'accountability_pending', 'accounted',
    'reimbursement_pl_pending', 'reimbursement_submitted', 'reimbursement_disbursed', 'reimbursed']::varchar[]
$fn$;

-- NON_REQUESTABLE_ADVANCE_STATUSES.
CREATE OR REPLACE FUNCTION gateway_day_money.not_requestable() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['disbursed', 'accountability_pl_pending', 'accountability_pending', 'accounted',
    'reimbursement_pl_pending', 'reimbursement_submitted', 'reimbursement_disbursed', 'reimbursed',
    'self_funded_pending_reimbursement', 'not_requested', 'cancelled']::varchar[]
$fn$;

-- NON_FUNDABLE_ACTIVITY_STATUSES.
CREATE OR REPLACE FUNCTION gateway_day_money.not_fundable() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['cancelled', 'rejected', 'deferred', 'awaiting_owner_approval']::varchar[]
$fn$;

-- REBUILDABLE_WEEKLY_STATUSES.
CREATE OR REPLACE FUNCTION gateway_day_money.week_rebuildable() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['pending_responsible_confirmation', 'returned_by_pl', 'returned_by_cd', 'returned_by_accountant']::varchar[]
$fn$;

-- repriceable_monthly_statuses.
CREATE OR REPLACE FUNCTION gateway_day_money.month_repriceable() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['draft', 'returned', 'rejected', 'returned_by_pl', 'returned_by_cd', 'returned_by_rvp',
    'returned_by_accountant']::varchar[]
$fn$;

-- plan_changes.MONTHLY_IN_CHAIN_STATUSES: sent to a reviewer or approved by
-- one, and not yet with the accountant.
CREATE OR REPLACE FUNCTION gateway_day_money.month_in_chain() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['submitted', 'submitted_to_pl', 'approved_by_pl', 'submitted_to_cd', 'approved_by_cd',
    'submitted_to_rvp', 'approved_by_rvp']::varchar[]
$fn$;

CREATE OR REPLACE FUNCTION gateway_day_money.new_id() RETURNS varchar
  LANGUAGE sql VOLATILE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ('c' || left(replace(gen_random_uuid()::text, '-', ''), 24))::varchar
$fn$;

-- fundable.vendor_direct_filter: paid straight to a vendor, never to staff.
CREATE OR REPLACE FUNCTION gateway_day_money.is_vendor_direct(
  p_type varchar, p_vendor_paid boolean, p_school varchar, p_start date, p_end date
) RETURNS boolean
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT (p_type = 'transport' AND p_school IS NOT NULL AND (p_end IS NULL OR p_start IS NULL OR p_end <= p_start))
      OR (p_type = 'accommodation' AND COALESCE(p_vendor_paid, false))
$fn$;

-- fundable.fundable_lines for one owner's week (p_from, p_to) or month (p_fy, p_month).
CREATE OR REPLACE FUNCTION gateway_day_money.fundable_lines(
  p_owner varchar, p_from date, p_to date, p_fy varchar, p_month integer
) RETURNS TABLE(line_id varchar, activity varchar, item_type varchar, label varchar,
                qty integer, unit bigint, amount bigint, currency varchar)
  LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT l.id::varchar, l.activity_id::varchar, l.line_item_type::varchar, l.label::varchar,
         l.quantity::integer, l.unit_cost::bigint, l.amount::bigint, l.currency::varchar
    FROM public.activity_schedule_cost_line l
    JOIN public.activity a ON a.id = l.activity_id
   WHERE l.responsible_user = p_owner
     AND (p_from IS NULL OR l.planned_date BETWEEN p_from AND p_to)
     AND (p_fy IS NULL OR (l.fiscal_year = p_fy AND l.month = p_month))
     AND a.deleted_at IS NULL
     AND a.scheduled_date IS NOT NULL
     AND NOT a.cost_missing
     AND l.amount <> 0
     AND NOT (a.status = ANY (gateway_day_money.not_fundable()))
     AND a.delivery_type IS DISTINCT FROM 'partner'
     AND NOT (l.line_item_type = 'facilitation' AND a.facilitating_partner_id IS NOT NULL)
     AND NOT gateway_day_money.is_vendor_direct(l.line_item_type, l.vendor_paid, a.school_id, a.planned_date, a.end_date)
     AND NOT EXISTS (SELECT 1 FROM public.advance_request r
                      WHERE r.budget_line_id = l.id AND r.status = ANY (gateway_day_money.not_requestable()))
$fn$;

-- Replaced by day_refusal: a filed monthly request is now carried along.
DROP FUNCTION IF EXISTS gateway_day_money.day_month_filed(varchar, date[]);
DROP FUNCTION IF EXISTS gateway_day_money.money_guard(varchar[]);

-- costing_service._ask_money_guards for one activity, in its order: the
-- refusal of money that has moved or is with someone, or NULL. A planner's own
-- change (p_plan_change) passes a monthly request in its approval chain, which
-- then follows the plan (plan_changes.follows_plan_change).
-- p_taking_back: the save takes a sent-but-unpaid week back before it prices
-- (a planner's move), so such a week does not refuse it.
DROP FUNCTION IF EXISTS gateway_day_money.activity_refusal(varchar, boolean);
CREATE OR REPLACE FUNCTION gateway_day_money.activity_refusal(p_activity varchar, p_plan_change boolean, p_taking_back boolean)
  RETURNS text
  LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  IF EXISTS (SELECT 1 FROM public.advance_request r JOIN public.activity_schedule_cost_line l ON l.id = r.budget_line_id
              WHERE l.activity_id = p_activity AND r.status = ANY (gateway_day_money.money_moved())) THEN
    RETURN 'This activity already has a disbursed or accounted advance — its cost snapshot is locked. '
        || 'Use a budget amendment instead of rescheduling to change its cost.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.advance_request r JOIN public.activity_schedule_cost_line l ON l.id = r.budget_line_id
              WHERE l.activity_id = p_activity AND r.status IN ('confirmed_for_advance', 'submitted_to_accountant')) THEN
    RETURN 'This activity''s advance is already confirmed and sitting in the accountant''s queue. '
        || 'Ask the accountant to return the advance first, then reschedule.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.weekly_fund_request_line wl
               JOIN public.activity_schedule_cost_line l ON l.id = wl.activity_budget_line_id
               JOIN public.weekly_fund_request w ON w.id = wl.weekly_fund_request_id
              WHERE l.activity_id = p_activity AND NOT (w.status = ANY (gateway_day_money.week_rebuildable()))
                AND NOT (p_taking_back AND w.status = ANY (gateway_day_money.week_sent_unpaid()))) THEN
    RETURN 'This activity is already included in a submitted or approved weekly fund request. '
        || 'Return that request before changing its cost.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.fund_request_item i
               JOIN public.activity_schedule_cost_line l ON l.id = i.activity_schedule_cost_line_id
               JOIN public.fund_request f ON f.id = i.fund_request_id
              WHERE l.activity_id = p_activity
                AND NOT (f.status = ANY (gateway_day_money.month_repriceable()))
                AND NOT (p_plan_change AND f.period = 'monthly' AND f.status = ANY (gateway_day_money.month_in_chain()))) THEN
    RETURN 'This activity is already included in a submitted or approved monthly fund request. '
        || 'Return that request before changing its cost.';
  END IF;
  RETURN NULL;
END
$fn$;

-- costs_follow._assert_days_can_follow's guards, asked before the save is
-- written: the first refusal of the day's members as the pricing will find
-- them, by id. A visit leaving the day (p_leaving) is not one of them; one
-- joining it (p_joining) is. Nothing is locked.
DROP FUNCTION IF EXISTS gateway_day_money.day_refusal(varchar, date[], boolean);
DROP FUNCTION IF EXISTS gateway_day_money.day_refusal(varchar, date, boolean, varchar, varchar);
CREATE OR REPLACE FUNCTION gateway_day_money.day_refusal(
  p_owner varchar, p_day date, p_plan_change boolean, p_leaving varchar, p_joining varchar, p_taking_back boolean
) RETURNS text
  LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_activity varchar;
  v_refusal  text;
BEGIN
  FOR v_activity IN
    SELECT member.id FROM (
      SELECT a.id
        FROM public.daily_visit_batch b
        JOIN public.activity a ON a.daily_visit_batch_id = b.id
       WHERE b.responsible_user = p_owner AND b.visit_date = p_day
         AND a.deleted_at IS NULL AND NOT (a.status = ANY (gateway_day_money.not_fundable()))
         AND a.id IS DISTINCT FROM p_leaving
      UNION
      SELECT p_joining WHERE COALESCE(p_joining, '') <> ''
    ) member
     ORDER BY member.id
  LOOP
    v_refusal := gateway_day_money.activity_refusal(v_activity, p_plan_change, p_taking_back);
    IF v_refusal IS NOT NULL THEN
      RETURN v_refusal;
    END IF;
  END LOOP;
  RETURN NULL;
END
$fn$;

-- The guards as the cost writer asks them: what the day's lines carry is
-- locked first, then each activity is asked in turn. NULL when the day may be
-- priced.
CREATE OR REPLACE FUNCTION gateway_day_money.money_guard(p_activity_ids varchar[], p_plan_change boolean) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_activity varchar;
  v_refusal  text;
BEGIN
  PERFORM 1 FROM public.advance_request r
    WHERE r.budget_line_id IN (SELECT l.id FROM public.activity_schedule_cost_line l WHERE l.activity_id = ANY (p_activity_ids))
    ORDER BY r.id FOR UPDATE;
  PERFORM 1 FROM public.weekly_fund_request w
    WHERE w.id IN (SELECT wl.weekly_fund_request_id FROM public.weekly_fund_request_line wl
                     JOIN public.activity_schedule_cost_line l ON l.id = wl.activity_budget_line_id
                    WHERE l.activity_id = ANY (p_activity_ids))
    ORDER BY w.id FOR UPDATE;
  PERFORM 1 FROM public.fund_request f
    WHERE f.id IN (SELECT i.fund_request_id FROM public.fund_request_item i
                     JOIN public.activity_schedule_cost_line l ON l.id = i.activity_schedule_cost_line_id
                    WHERE l.activity_id = ANY (p_activity_ids))
    ORDER BY f.id FOR UPDATE;

  FOREACH v_activity IN ARRAY p_activity_ids LOOP
    v_refusal := gateway_day_money.activity_refusal(v_activity, p_plan_change, false);
    IF v_refusal IS NOT NULL THEN
      RETURN v_refusal;
    END IF;
  END LOOP;
  RETURN NULL;
END
$fn$;

-- plan_changes._lines_the_request_holds: the activity's lines of the request's
-- month, by the rule of whoever built it. A Programme Lead's team month holds
-- every staff line of scheduled work; any other request the staff-payable ones.
CREATE OR REPLACE FUNCTION gateway_day_money.request_lines(
  p_activity varchar, p_fy varchar, p_month integer, p_team boolean
) RETURNS TABLE(line_id varchar, amount bigint)
  LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT l.id::varchar, COALESCE(l.amount, 0)::bigint
    FROM public.activity_schedule_cost_line l
    JOIN public.activity a ON a.id = l.activity_id
   WHERE l.activity_id = p_activity AND l.fiscal_year = p_fy AND l.month = p_month
     AND a.deleted_at IS NULL AND a.scheduled_date IS NOT NULL
     AND NOT (a.status = ANY (gateway_day_money.not_fundable()))
     AND NOT (l.line_item_type = 'facilitation' AND a.facilitating_partner_id IS NOT NULL)
     AND (p_team OR (
           NOT a.cost_missing
       AND l.amount <> 0
       AND a.delivery_type IS DISTINCT FROM 'partner'
       AND NOT gateway_day_money.is_vendor_direct(l.line_item_type, l.vendor_paid, a.school_id, a.planned_date, a.end_date)
       AND NOT EXISTS (SELECT 1 FROM public.advance_request r
                        WHERE r.budget_line_id = l.id AND r.status = ANY (gateway_day_money.not_requestable()))))
$fn$;

-- plan_changes.carry_monthly_requests: the monthly requests (other than the
-- owner's own draft, which its sync rebuilds whole) that carried the
-- activity's old lines are pointed at its lines as they now stand, and their
-- totals follow. Answers each request in its approval chain with its total
-- before, when the change is a planner's own, so they can be told.
CREATE OR REPLACE FUNCTION gateway_day_money.carry_month(
  p_activity varchar, p_old_lines varchar[], p_plan_change boolean, p_at timestamptz
) RETURNS TABLE(request_id varchar, total_before bigint)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_request record;
  v_fy      varchar;
  v_month   text;
BEGIN
  FOR v_request IN
    SELECT f.id, f.status, f.scope, f.period, f.period_key, COALESCE(f.total_amount, 0)::bigint AS total
      FROM public.fund_request f
     WHERE f.period = 'monthly'
       AND NOT (f.scope = 'own' AND f.status = 'draft')
       AND EXISTS (SELECT 1 FROM public.fund_request_item i
                    WHERE i.fund_request_id = f.id AND i.activity_schedule_cost_line_id = ANY (p_old_lines))
     ORDER BY f.id
  LOOP
    IF p_plan_change AND v_request.status = ANY (gateway_day_money.month_in_chain()) THEN
      request_id := v_request.id;
      total_before := v_request.total;
      RETURN NEXT;
    END IF;
    DELETE FROM public.fund_request_item i
     WHERE i.fund_request_id = v_request.id AND i.activity_schedule_cost_line_id = ANY (p_old_lines);
    v_fy := split_part(v_request.period_key, '-M', 1);
    v_month := split_part(v_request.period_key, '-M', 2);
    IF v_month ~ '^[0-9]+$' THEN
      INSERT INTO public.fund_request_item (
        id, created_at, updated_at, activity_id, activity_schedule_cost_line_id, amount, period, period_key,
        added_after_generation, fund_request_id
      )
      SELECT gateway_day_money.new_id(), p_at, p_at, p_activity, h.line_id, h.amount, v_request.period,
             v_request.period_key, true, v_request.id
        FROM gateway_day_money.request_lines(p_activity, v_fy, v_month::integer, v_request.scope = 'team') h;
    END IF;
    UPDATE public.fund_request f
       SET total_amount = (SELECT COALESCE(sum(i.amount), 0) FROM public.fund_request_item i WHERE i.fund_request_id = f.id),
           activity_count = (SELECT count(DISTINCT i.activity_id) FROM public.fund_request_item i WHERE i.fund_request_id = f.id),
           updated_at = p_at
     WHERE f.id = v_request.id;
  END LOOP;
END
$fn$;

-- What the existing cost writer's delete of the old lines cascades to: their
-- advances and weekly lines. Answers the weekly requests that lost a line, so
-- each is rebuilt. Asked only after money_guard has passed.
CREATE OR REPLACE FUNCTION gateway_day_money.clear_day(p_activity_ids varchar[])
  RETURNS TABLE(bucket_owner varchar, bucket_week date)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  RETURN QUERY
  WITH day_lines AS (
    SELECT l.id FROM public.activity_schedule_cost_line l WHERE l.activity_id = ANY (p_activity_ids)
  ), gone AS (
    DELETE FROM public.weekly_fund_request_line wl USING day_lines d
     WHERE wl.activity_budget_line_id = d.id
    RETURNING wl.weekly_fund_request_id
  ), withdrawn AS (
    DELETE FROM public.advance_request r USING day_lines d WHERE r.budget_line_id = d.id RETURNING r.id
  )
  SELECT DISTINCT w.responsible_user::varchar, w.week_start_date
    FROM public.weekly_fund_request w JOIN gone g ON g.weekly_fund_request_id = w.id;
END
$fn$;

-- advance_service.sync_for_activities, lines_just_written: one advance for
-- each staff-payable line of these activities.
CREATE OR REPLACE FUNCTION gateway_day_money.open_advances(
  p_activity_ids varchar[], p_owner varchar, p_at timestamptz
) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_opened integer;
BEGIN
  INSERT INTO public.advance_request (
    id, created_at, updated_at, responsible_user_id, fy, quarter, month, week, planned_date,
    amount, status, advance_type, activity_id, budget_line_id
  )
  SELECT gateway_day_money.new_id(), p_at, p_at, COALESCE(NULLIF(p_owner, ''), a.responsible_staff_id),
         COALESCE(a.fy, l.fiscal_year), COALESCE(a.quarter, l.quarter), a.month,
         CASE WHEN a.planned_date IS NULL THEN NULL
              ELSE LEAST(5, (EXTRACT(DAY FROM a.planned_date)::integer - 1) / 7 + 1) END,
         a.scheduled_date, l.amount, 'pending_responsible_confirmation', 'advance', a.id, l.id
    FROM public.activity_schedule_cost_line l
    JOIN public.activity a ON a.id = l.activity_id
   WHERE l.activity_id = ANY (p_activity_ids)
     AND NOT a.cost_missing
     AND a.delivery_type IS DISTINCT FROM 'partner'
     AND l.amount <> 0
     AND NOT (l.line_item_type = 'facilitation' AND a.facilitating_partner_id IS NOT NULL)
     AND NOT gateway_day_money.is_vendor_direct(l.line_item_type, l.vendor_paid, a.school_id, a.planned_date, a.end_date)
     AND NOT EXISTS (SELECT 1 FROM public.advance_request r WHERE r.budget_line_id = l.id);
  GET DIAGNOSTICS v_opened = ROW_COUNT;
  RETURN v_opened;
END
$fn$;

-- vendor_channel.ensure_transport_obligation: one obligation per mission day,
-- refreshed while pending and immutable once paid.
CREATE OR REPLACE FUNCTION gateway_day_money.ensure_transport(p_batch varchar, p_amount bigint, p_at timestamptz)
  RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_paid bigint;
BEGIN
  SELECT t.amount INTO v_paid FROM public.transport_payment t
   WHERE t.batch_id = p_batch AND t.status = 'paid' FOR UPDATE;
  IF FOUND AND v_paid <> p_amount THEN
    RAISE EXCEPTION 'Transport for this day has already been paid. Finance must reconcile it before changing the daily allocation.';
  END IF;
  IF p_amount = 0 THEN
    DELETE FROM public.transport_payment t WHERE t.batch_id = p_batch AND t.status = 'pending';
    RETURN;
  END IF;
  INSERT INTO public.transport_payment AS t (
    id, created_at, updated_at, provider_name, amount, status, payment_method, payment_reference,
    netsuite_expense_id, notes, batch_id
  ) VALUES (
    gateway_day_money.new_id(), p_at, p_at, 'Approved transport provider', p_amount, 'pending', '', '', '', '', p_batch
  )
  ON CONFLICT (batch_id) DO UPDATE SET amount = EXCLUDED.amount, updated_at = EXCLUDED.updated_at
   WHERE t.status = 'pending' AND t.amount <> EXCLUDED.amount;
END
$fn$;

-- weekly_service.generate_weekly_fund_request. A request that has left its
-- owner's hands is a finance snapshot and is never rewritten.
CREATE OR REPLACE FUNCTION gateway_day_money.refile_week(
  p_owner varchar, p_week_start date, p_fy varchar, p_at timestamptz
) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_start  date := p_week_start - (EXTRACT(ISODOW FROM p_week_start)::integer - 1);
  v_end    date;
  v_id     varchar;
  v_status varchar;
  v_count  integer;
  v_total  bigint;
BEGIN
  v_end := v_start + 6;
  PERFORM pg_advisory_xact_lock(hashtext('day_money:week:' || p_owner || ':' || v_start::text));
  SELECT count(*), COALESCE(sum(f.amount), 0) INTO v_count, v_total
    FROM gateway_day_money.fundable_lines(p_owner, v_start, v_end, NULL, NULL) f;
  SELECT w.id, w.status INTO v_id, v_status FROM public.weekly_fund_request w
   WHERE w.responsible_user = p_owner AND w.week_start_date = v_start FOR UPDATE;

  IF v_count = 0 THEN
    IF v_id IS NOT NULL AND v_status = ANY (gateway_day_money.week_rebuildable()) THEN
      DELETE FROM public.weekly_fund_request_line wl WHERE wl.weekly_fund_request_id = v_id;
      DELETE FROM public.weekly_fund_request w WHERE w.id = v_id;
    END IF;
    RETURN;
  END IF;
  IF v_id IS NOT NULL AND NOT (v_status = ANY (gateway_day_money.week_rebuildable())) THEN
    RETURN;
  END IF;

  IF v_id IS NOT NULL THEN
    UPDATE public.weekly_fund_request w SET total_amount = v_total, updated_at = p_at WHERE w.id = v_id;
  ELSE
    v_id := gateway_day_money.new_id();
    INSERT INTO public.weekly_fund_request (
      id, created_at, updated_at, fy, week_start_date, week_end_date, responsible_user,
      total_amount, status, return_reason, funding_source
    ) VALUES (
      v_id, p_at, p_at, p_fy, v_start, v_end, p_owner, v_total, 'pending_responsible_confirmation', '', 'advance'
    );
  END IF;

  DELETE FROM public.weekly_fund_request_line wl WHERE wl.weekly_fund_request_id = v_id;
  INSERT INTO public.weekly_fund_request_line (
    id, created_at, updated_at, line_item_type, description, quantity, unit_cost, total_cost, currency,
    activity_budget_line_id, weekly_fund_request_id
  )
  SELECT gateway_day_money.new_id(), p_at, p_at, COALESCE(NULLIF(f.item_type, ''), 'other'), f.label, f.qty, f.unit,
         f.amount, f.currency, f.line_id, v_id
    FROM gateway_day_money.fundable_lines(p_owner, v_start, v_end, NULL, NULL) f;
END
$fn$;

-- monthly_service.sync_monthly_periods for one owner-month. Only the owner's
-- own draft is ever rewritten.
CREATE OR REPLACE FUNCTION gateway_day_money.refile_month(
  p_owner varchar, p_fy varchar, p_month integer, p_at timestamptz
) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_key        varchar := p_fy || '-M' || p_month;
  v_id         varchar;
  v_status     varchar;
  v_count      integer;
  v_activities integer;
  v_total      bigint;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('day_money:month:' || p_owner || ':' || v_key));
  SELECT r.id, r.status INTO v_id, v_status FROM public.fund_request r
   WHERE r.submitted_by_user_id = p_owner AND r.period = 'monthly' AND r.period_key = v_key AND r.scope = 'own'
     FOR UPDATE;
  IF v_id IS NOT NULL AND v_status = 'draft' THEN
    DELETE FROM public.fund_request_item i WHERE i.fund_request_id = v_id;
  END IF;

  SELECT count(*), count(DISTINCT f.activity), COALESCE(sum(f.amount), 0) INTO v_count, v_activities, v_total
    FROM gateway_day_money.fundable_lines(p_owner, NULL, NULL, p_fy, p_month) f;
  IF v_count = 0 THEN
    IF v_id IS NOT NULL AND v_status = 'draft' THEN
      DELETE FROM public.fund_request r WHERE r.id = v_id;
    END IF;
    RETURN;
  END IF;

  IF v_id IS NULL THEN
    v_id := gateway_day_money.new_id();
    INSERT INTO public.fund_request (
      id, created_at, updated_at, fy, period, period_key, scope, submitted_by_user_id, submitted_by_role,
      total_amount, activity_count, status
    ) VALUES (
      v_id, p_at, p_at, p_fy, 'monthly', v_key, 'own', p_owner, '', v_total, v_activities, 'draft'
    );
  ELSIF v_status <> 'draft' THEN
    RETURN;
  ELSE
    UPDATE public.fund_request r
       SET fy = p_fy, total_amount = v_total, activity_count = v_activities, updated_at = p_at
     WHERE r.id = v_id;
  END IF;

  INSERT INTO public.fund_request_item (
    id, created_at, updated_at, activity_id, activity_schedule_cost_line_id, amount, period, period_key,
    added_after_generation, fund_request_id
  )
  SELECT gateway_day_money.new_id(), p_at, p_at, f.activity, f.line_id, f.amount, 'monthly', v_key, false, v_id
    FROM gateway_day_money.fundable_lines(p_owner, NULL, NULL, p_fy, p_month) f;
END
$fn$;

-- LeaveBudgetImpactService.handle_reschedule: the trail a move leaves on the
-- activity's budget lines, once.
CREATE OR REPLACE FUNCTION gateway_day_money.note_lines(p_activity varchar, p_trail text, p_at timestamptz)
  RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_noted integer;
BEGIN
  UPDATE public.activity_schedule_cost_line l
     SET description = CASE WHEN COALESCE(l.description, '') = '' THEN left(btrim(p_trail), 255)
                            ELSE left(l.description || p_trail, 255) END,
         updated_at = p_at
   WHERE l.activity_id = p_activity
     AND position('Rescheduled due to' IN COALESCE(l.description, '')) = 0;
  GET DIAGNOSTICS v_noted = ROW_COUNT;
  RETURN v_noted;
END
$fn$;

-- plan_changes.SENT_UNPAID_STATUSES: with its approver, approved and waiting
-- for the accountant, or set aside by its owner ("No Advance This Week").
CREATE OR REPLACE FUNCTION gateway_day_money.week_sent_unpaid() RETURNS varchar[]
  LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT ARRAY['submitted_to_pl', 'submitted_to_cd', 'confirmed_for_advance', 'not_requested']::varchar[]
$fn$;

-- plan_changes.take_back_for_plan_change, inside the move's transaction: the
-- sent-but-unpaid weekly requests the change runs into (those carrying the
-- activity's lines, and its owners' requests for the weeks it leaves and joins)
-- come back to their owner, and their advances go back to pending with them.
-- An advance whose money has moved is left exactly as it is.
CREATE OR REPLACE FUNCTION gateway_day_money.take_back_weeks(
  p_activity varchar, p_owners varchar[], p_weeks date[], p_at timestamptz
) RETURNS TABLE(request_id varchar, was varchar, owner varchar, week_start date, week_end date, total bigint)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_request record;
BEGIN
  IF EXISTS (SELECT 1 FROM public.activity a WHERE a.id = p_activity AND a.delivery_type = 'partner') THEN
    RETURN;
  END IF;
  FOR v_request IN
    SELECT w.id, w.status, w.responsible_user, w.week_start_date, w.week_end_date, COALESCE(w.total_amount, 0)::bigint AS total
      FROM public.weekly_fund_request w
     WHERE w.status = ANY (gateway_day_money.week_sent_unpaid())
       AND (w.id IN (SELECT wl.weekly_fund_request_id FROM public.weekly_fund_request_line wl
                       JOIN public.activity_schedule_cost_line l ON l.id = wl.activity_budget_line_id
                      WHERE l.activity_id = p_activity)
            OR (w.responsible_user = ANY (p_owners) AND w.week_start_date = ANY (p_weeks)))
     ORDER BY w.week_start_date, w.id
       FOR UPDATE
  LOOP
    UPDATE public.weekly_fund_request w
       SET status = 'pending_responsible_confirmation', confirmed_at = NULL, updated_at = p_at
     WHERE w.id = v_request.id;
    UPDATE public.advance_request r
       SET status = 'pending_responsible_confirmation', advance_type = 'advance', confirmed_at = p_at, updated_at = p_at
     WHERE r.budget_line_id IN (SELECT wl.activity_budget_line_id FROM public.weekly_fund_request_line wl
                                 WHERE wl.weekly_fund_request_id = v_request.id)
       AND NOT (r.status = ANY (gateway_day_money.money_moved()));
    request_id := v_request.id;
    was := v_request.status;
    owner := v_request.responsible_user;
    week_start := v_request.week_start_date;
    week_end := v_request.week_end_date;
    total := v_request.total;
    RETURN NEXT;
  END LOOP;
END
$fn$;

-- services.resync_stale_batches' choice: the owner's days in the week, not
-- frozen by a request outside its owner's hands, whose live members no longer
-- match the split they were priced for.
CREATE OR REPLACE FUNCTION gateway_day_money.stale_days(p_owner varchar, p_start date, p_end date)
  RETURNS TABLE(batch_id varchar)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  SELECT b.id::varchar
    FROM public.daily_visit_batch b
   WHERE b.responsible_user = p_owner AND b.visit_date BETWEEN p_start AND p_end
     AND NOT EXISTS (SELECT 1 FROM public.weekly_fund_request w
                      WHERE w.responsible_user = b.responsible_user
                        AND w.week_start_date <= b.visit_date AND w.week_end_date >= b.visit_date
                        AND NOT (w.status = ANY (gateway_day_money.week_rebuildable())))
     AND (SELECT count(*) FROM public.activity a
           WHERE a.daily_visit_batch_id = b.id AND a.deleted_at IS NULL
             AND NOT (a.status = ANY (gateway_day_money.not_fundable()))) <> COALESCE(b.school_count, 0)
   ORDER BY b.id
$fn$;

-- The owner's own decisions on their week (weekly_service.request_advance,
-- self_funded, not_requested, confirm_receipt). Each locks the request, checks
-- it as the existing service does and answers what it found: 'gone',
-- 'not_owner', 'changed' (the role stamped on the request is not the one the
-- caller routed by), 'status:<status>', 'paid', 'not_disbursed', 'already',
-- 'no_bank', or the request's new status.

-- weekly_service._sync_advances: each line's advance whose money has not
-- moved follows the request; the row locks keep a payment committing in
-- another channel from being rewritten.
CREATE OR REPLACE FUNCTION gateway_day_money.sync_week_advances(
  p_request varchar, p_status varchar, p_type varchar, p_now timestamptz) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  PERFORM 1 FROM public.advance_request r
    WHERE r.budget_line_id IN (SELECT wl.activity_budget_line_id FROM public.weekly_fund_request_line wl
                                WHERE wl.weekly_fund_request_id = p_request)
    FOR UPDATE;
  UPDATE public.advance_request r
     SET status = p_status, advance_type = p_type, confirmed_at = p_now, updated_at = p_now
   WHERE r.budget_line_id IN (SELECT wl.activity_budget_line_id FROM public.weekly_fund_request_line wl
                               WHERE wl.weekly_fund_request_id = p_request)
     AND NOT (r.status = ANY (gateway_day_money.money_moved()));
END
$fn$;

-- request_advance: p_role and p_status are the caller's routing for the role
-- the request carried when it was read (p_stamped).
CREATE OR REPLACE FUNCTION gateway_day_money.send_week(
  p_request varchar, p_user varchar, p_stamped varchar, p_role varchar, p_status varchar,
  p_funding varchar, p_now timestamptz) RETURNS varchar
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_owner varchar;
  v_status varchar;
  v_role varchar;
BEGIN
  SELECT w.responsible_user, w.status, COALESCE(w.responsible_role, '')
    INTO v_owner, v_status, v_role
    FROM public.weekly_fund_request w WHERE w.id = p_request FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 'gone';
  END IF;
  IF v_owner IS DISTINCT FROM p_user THEN
    RETURN 'not_owner';
  END IF;
  IF NOT (v_status = ANY (ARRAY['pending_responsible_confirmation', 'not_requested', 'returned_by_pl',
                                'returned_by_cd', 'returned_by_accountant']::varchar[])) THEN
    RETURN 'status:' || v_status;
  END IF;
  IF v_role <> COALESCE(p_stamped, '') THEN
    RETURN 'changed';
  END IF;
  UPDATE public.weekly_fund_request
     SET funding_source = p_funding, status = p_status, responsible_role = p_role,
         confirmed_at = p_now, updated_at = p_now
   WHERE id = p_request;
  IF p_status = 'confirmed_for_advance' THEN
    PERFORM gateway_day_money.sync_week_advances(p_request, 'confirmed_for_advance', 'advance', p_now);
  ELSE
    PERFORM gateway_day_money.sync_week_advances(p_request, 'pending_responsible_confirmation', 'advance', p_now);
  END IF;
  RETURN p_status;
END
$fn$;

-- not_requested.
CREATE OR REPLACE FUNCTION gateway_day_money.skip_week(p_request varchar, p_user varchar, p_now timestamptz)
  RETURNS varchar
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_owner varchar;
  v_status varchar;
BEGIN
  SELECT w.responsible_user, w.status INTO v_owner, v_status
    FROM public.weekly_fund_request w WHERE w.id = p_request FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 'gone';
  END IF;
  IF v_owner IS DISTINCT FROM p_user THEN
    RETURN 'not_owner';
  END IF;
  IF v_status IN ('disbursed', 'accounted') THEN
    RETURN 'paid';
  END IF;
  UPDATE public.weekly_fund_request SET status = 'not_requested', confirmed_at = p_now, updated_at = p_now
   WHERE id = p_request;
  PERFORM gateway_day_money.sync_week_advances(p_request, 'not_requested', 'not_requested', p_now);
  RETURN 'not_requested';
END
$fn$;

-- confirm_receipt: an owner's second confirmation changes nothing.
CREATE OR REPLACE FUNCTION gateway_day_money.confirm_week_receipt(
  p_request varchar, p_user varchar, p_bank boolean, p_now timestamptz) RETURNS varchar
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_owner varchar;
  v_status varchar;
  v_received timestamptz;
BEGIN
  SELECT w.responsible_user, w.status, w.receipt_confirmed_at INTO v_owner, v_status, v_received
    FROM public.weekly_fund_request w WHERE w.id = p_request FOR UPDATE;
  IF NOT FOUND THEN
    RETURN 'gone';
  END IF;
  IF v_owner IS DISTINCT FROM p_user THEN
    RETURN 'not_owner';
  END IF;
  IF v_status <> 'disbursed' THEN
    RETURN 'not_disbursed';
  END IF;
  IF v_received IS NOT NULL THEN
    RETURN 'already';
  END IF;
  IF p_bank IS NOT TRUE THEN
    RETURN 'no_bank';
  END IF;
  UPDATE public.weekly_fund_request SET receipt_confirmed_at = p_now, updated_at = p_now WHERE id = p_request;
  RETURN 'confirmed';
END
$fn$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_day_money FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_day_money TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION
  gateway_day_money.day_refusal(varchar, date, boolean, varchar, varchar, boolean),
  gateway_day_money.money_guard(varchar[], boolean),
  gateway_day_money.carry_month(varchar, varchar[], boolean, timestamptz),
  gateway_day_money.clear_day(varchar[]),
  gateway_day_money.open_advances(varchar[], varchar, timestamptz),
  gateway_day_money.ensure_transport(varchar, bigint, timestamptz),
  gateway_day_money.refile_week(varchar, date, varchar, timestamptz),
  gateway_day_money.refile_month(varchar, varchar, integer, timestamptz),
  gateway_day_money.note_lines(varchar, text, timestamptz),
  gateway_day_money.take_back_weeks(varchar, varchar[], date[], timestamptz),
  gateway_day_money.stale_days(varchar, date, date),
  gateway_day_money.send_week(varchar, varchar, varchar, varchar, varchar, varchar, timestamptz),
  gateway_day_money.skip_week(varchar, varchar, timestamptz),
  gateway_day_money.confirm_week_receipt(varchar, varchar, boolean, timestamptz)
TO edify_activities_rw;
