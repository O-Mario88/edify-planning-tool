-- Least-privilege role and SECURITY DEFINER functions for Finance & Money
-- workflows (Batch 12: M12 — weekly fund requests, advances, disbursements,
-- receipts, accountability, variance reconciliation, monthly work-plan budgets).
--
-- Keeps edify_gateway read-only by default; enforces exact integer UGX amounts,
-- row locking (FOR UPDATE), idempotency keys, and sealed audit_log records.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_finance_owner') THEN
        CREATE ROLE edify_finance_owner NOLOGIN NOINHERIT;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO edify_finance_owner;
GRANT SELECT, INSERT, UPDATE ON
    weekly_fund_request,
    advance_request,
    monthly_work_plan_budget
TO edify_finance_owner;

CREATE SCHEMA IF NOT EXISTS gateway_finance AUTHORIZATION edify_finance_owner;
REVOKE ALL ON SCHEMA gateway_finance FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_finance TO edify_gateway;

-- Submit or idempotently update a weekly staff fund request.
CREATE OR REPLACE FUNCTION gateway_finance.submit_weekly_request(
    p_fy             text,
    p_week_start     date,
    p_week_end       date,
    p_owner_id       text,
    p_total_amount   bigint,
    p_funding_source text,
    p_actor_role     text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id     text;
    v_status text;
BEGIN
    IF p_total_amount < 0 THEN
        RAISE EXCEPTION 'finance: total_amount must be non-negative';
    END IF;
    SELECT id, status INTO v_id, v_status
    FROM public.weekly_fund_request
    WHERE responsible_user = p_owner_id AND week_start_date = p_week_start
    FOR UPDATE;

    IF v_id IS NOT NULL THEN
        IF v_status IN ('disbursed', 'receipt_confirmed', 'accounted', 'closed') THEN
            RETURN v_id; -- Idempotent: already disbursed/settled, never double-mutate.
        END IF;
        UPDATE public.weekly_fund_request
        SET total_amount = p_total_amount,
            status = 'submitted_to_pl',
            return_reason = '',
            updated_at = NOW()
        WHERE id = v_id;
    ELSE
        v_id := 'wfr_' || substr(md5(p_owner_id || ':' || p_week_start::text), 1, 22);
        INSERT INTO public.weekly_fund_request (
            id, fy, week_start_date, week_end_date, responsible_user,
            total_amount, status, return_reason, funding_source,
            created_at, updated_at
        ) VALUES (
            v_id, p_fy, p_week_start, p_week_end, p_owner_id,
            p_total_amount, 'submitted_to_pl', '', COALESCE(NULLIF(p_funding_source, ''), 'edify_core'),
            NOW(), NOW()
        );
    END IF;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN v_id;
END;
$$;

-- Approve, return, disburse, confirm receipt, or account for a weekly fund request.
-- Idempotent on disbursement reference so duplicated callbacks apply ONCE.
CREATE OR REPLACE FUNCTION gateway_finance.transition_weekly_request(
    p_request_id      text,
    p_action          text, -- approve_pl | approve_cd | return | disburse | confirm_receipt | submit_accountability
    p_actor_id        text,
    p_actor_role      text,
    p_amount          bigint,
    p_returned_amount bigint,
    p_method          text,
    p_reference       text,
    p_reason          text
) RETURNS TABLE(new_status text, applied boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_row public.weekly_fund_request%ROWTYPE;
    v_st  text;
BEGIN
    SELECT * INTO v_row FROM public.weekly_fund_request WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'finance: weekly fund request % not found', p_request_id;
    END IF;

    CASE p_action
        WHEN 'approve_pl' THEN
            IF v_row.status = 'approved_by_pl' THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'approved_by_pl';
            UPDATE public.weekly_fund_request SET status = v_st, updated_at = NOW() WHERE id = p_request_id;
        WHEN 'approve_cd' THEN
            IF v_row.status = 'approved_by_cd' THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'approved_by_cd';
            UPDATE public.weekly_fund_request SET status = v_st, updated_at = NOW() WHERE id = p_request_id;
        WHEN 'return' THEN
            v_st := 'returned';
            UPDATE public.weekly_fund_request
            SET status = v_st, return_reason = COALESCE(p_reason, ''),
                returned_at = NOW(), returned_by_user_id = p_actor_id, updated_at = NOW()
            WHERE id = p_request_id;
        WHEN 'disburse' THEN
            IF v_row.status IN ('disbursed', 'receipt_confirmed', 'accounted', 'closed')
               AND COALESCE(v_row.disburse_reference, '') = COALESCE(p_reference, '') THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            IF v_row.disbursed_at IS NOT NULL THEN
                RAISE EXCEPTION 'finance: weekly fund request % already disbursed (ref=%)', p_request_id, v_row.disburse_reference;
            END IF;
            IF p_amount < 0 THEN
                RAISE EXCEPTION 'finance: disbursed_amount must be non-negative';
            END IF;
            v_st := 'disbursed';
            UPDATE public.weekly_fund_request
            SET status = v_st, disbursed_amount = p_amount, disbursed_at = NOW(),
                disbursed_by_user_id = p_actor_id, disburse_method = p_method,
                disburse_reference = p_reference, updated_at = NOW()
            WHERE id = p_request_id;
        WHEN 'confirm_receipt' THEN
            IF v_row.receipt_confirmed_at IS NOT NULL THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'receipt_confirmed';
            UPDATE public.weekly_fund_request
            SET status = v_st, receipt_confirmed_at = NOW(), confirmed_at = NOW(), updated_at = NOW()
            WHERE id = p_request_id;
        WHEN 'submit_accountability' THEN
            IF p_amount < 0 OR p_returned_amount < 0 THEN
                RAISE EXCEPTION 'finance: accountability amounts must be non-negative';
            END IF;
            IF v_row.accountability_submitted_at IS NOT NULL
               AND COALESCE(v_row.accountability_netsuite_id, '') = COALESCE(p_reference, '') THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'accounted';
            UPDATE public.weekly_fund_request
            SET status = v_st, accounted_amount = p_amount, returned_amount = p_returned_amount,
                accountability_netsuite_id = NULLIF(p_reference, ''),
                accountability_submitted_at = NOW(), updated_at = NOW()
            WHERE id = p_request_id;
        ELSE
            RAISE EXCEPTION 'finance: unknown weekly request action %', p_action;
    END CASE;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN QUERY SELECT v_st, true;
END;
$$;

-- Monthly work-plan budget status transition with row locking (audited in Go).
CREATE OR REPLACE FUNCTION gateway_finance.decide_monthly_budget(
    p_budget_id  text,
    p_new_status text,
    p_actor_id   text,
    p_actor_role text,
    p_note       text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_prev text;
BEGIN
    SELECT status INTO v_prev FROM public.monthly_work_plan_budget WHERE id = p_budget_id FOR UPDATE;
    IF v_prev IS NULL THEN
        RAISE EXCEPTION 'finance: monthly work plan budget % not found', p_budget_id;
    END IF;
    UPDATE public.monthly_work_plan_budget
    SET status = p_new_status, updated_at = NOW()
    WHERE id = p_budget_id;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN p_new_status;
END;
$$;

-- Advance disbursement & accountability transition (idempotent on reference).
CREATE OR REPLACE FUNCTION gateway_finance.transition_advance(
    p_advance_id      text,
    p_action          text, -- disburse | confirm_receipt | account | verify_return
    p_actor_id        text,
    p_actor_role      text,
    p_amount          bigint,
    p_returned_amount bigint,
    p_method          text,
    p_reference       text
) RETURNS TABLE(new_status text, applied boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_row public.advance_request%ROWTYPE;
    v_st  text;
BEGIN
    SELECT * INTO v_row FROM public.advance_request WHERE id = p_advance_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'finance: advance_request % not found', p_advance_id;
    END IF;

    CASE p_action
        WHEN 'disburse' THEN
            IF v_row.disbursed_at IS NOT NULL AND COALESCE(v_row.disburse_reference, '') = COALESCE(p_reference, '') THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            IF v_row.disbursed_at IS NOT NULL THEN
                RAISE EXCEPTION 'finance: advance % already disbursed', p_advance_id;
            END IF;
            v_st := 'disbursed';
            UPDATE public.advance_request
            SET status = v_st, disbursed_amount = p_amount, disbursed_at = NOW(),
                disbursed_by_user_id = p_actor_id, disburse_method = p_method,
                disburse_reference = p_reference, updated_at = NOW()
            WHERE id = p_advance_id;
        WHEN 'confirm_receipt' THEN
            IF v_row.confirmed_at IS NOT NULL THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'receipt_confirmed';
            UPDATE public.advance_request SET status = v_st, confirmed_at = NOW(), updated_at = NOW() WHERE id = p_advance_id;
        WHEN 'account' THEN
            IF v_row.accountability_submitted_at IS NOT NULL AND COALESCE(v_row.accountability_netsuite_id, '') = COALESCE(p_reference, '') THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'accountability_submitted';
            UPDATE public.advance_request
            SET status = v_st, accounted_amount = p_amount, returned_amount = p_returned_amount,
                accountability_netsuite_id = NULLIF(p_reference, ''),
                accountability_submitted_at = NOW(), updated_at = NOW()
            WHERE id = p_advance_id;
        WHEN 'verify_return' THEN
            IF v_row.return_verified_at IS NOT NULL THEN
                RETURN QUERY SELECT v_row.status::text, false; RETURN;
            END IF;
            v_st := 'closed';
            UPDATE public.advance_request
            SET status = v_st, return_verified_at = NOW(), return_verified_by_user_id = p_actor_id,
                return_reference = COALESCE(p_reference, return_reference), updated_at = NOW()
            WHERE id = p_advance_id;
        ELSE
            RAISE EXCEPTION 'finance: unknown advance action %', p_action;
    END CASE;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN QUERY SELECT v_st, true;
END;
$$;

ALTER FUNCTION gateway_finance.submit_weekly_request(text, date, date, text, bigint, text, text) OWNER TO edify_finance_owner;
ALTER FUNCTION gateway_finance.transition_weekly_request(text, text, text, text, bigint, bigint, text, text, text) OWNER TO edify_finance_owner;
ALTER FUNCTION gateway_finance.decide_monthly_budget(text, text, text, text, text) OWNER TO edify_finance_owner;
ALTER FUNCTION gateway_finance.transition_advance(text, text, text, text, bigint, bigint, text, text) OWNER TO edify_finance_owner;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_finance FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA gateway_finance TO edify_gateway;
