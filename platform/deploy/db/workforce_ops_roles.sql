-- Least-privilege role and SECURITY DEFINER functions for Batch 13 operational
-- workflows: self-service /profile updates, leave decisions, escalations,
-- team guidance receipts, and help center article feedback.
--
-- Never grants UPDATE on dbguard.protectedColumns (roles, active_role, status,
-- is_superuser) or DELETE on any undeletable table.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_workforce_ops_owner') THEN
        CREATE ROLE edify_workforce_ops_owner NOLOGIN NOINHERIT;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO edify_workforce_ops_owner;
GRANT SELECT, UPDATE (name, phone, updated_at) ON "user" TO edify_workforce_ops_owner;
GRANT SELECT, INSERT, UPDATE ON
    leave,
    leadership_escalation,
    cce_team_guidance_receipt,
    help_center_helparticlefeedback
TO edify_workforce_ops_owner;
GRANT SELECT, UPDATE (
    state, acknowledged_at, started_at, blocked_reason, returned_reason,
    resolved_at, resolved_by_system, manual_resolution_reason,
    escalated_at, escalated_to_id, updated_at
) ON public.team_action TO edify_workforce_ops_owner;
GRANT SELECT (id, user_id) ON public.staff_profile TO edify_workforce_ops_owner;
GRANT SELECT (supervisee_id, supervisor_id, created_at) ON public.staff_supervisor_assignment TO edify_workforce_ops_owner;

CREATE SCHEMA IF NOT EXISTS gateway_workforce_ops AUTHORIZATION edify_workforce_ops_owner;
REVOKE ALL ON SCHEMA gateway_workforce_ops FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_workforce_ops TO edify_gateway;

CREATE OR REPLACE FUNCTION gateway_workforce_ops.update_own_profile(
    p_user_id text, p_name text, p_phone text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    UPDATE public."user"
    SET name = COALESCE(NULLIF(trim(p_name), ''), name),
        phone = COALESCE(trim(p_phone), phone),
        updated_at = NOW()
    WHERE id = p_user_id AND deleted_at IS NULL;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_workforce_ops.decide_leave(
    p_leave_id text, p_new_status text, p_actor_id text, p_actor_role text, p_note text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_prev text;
BEGIN
    SELECT status INTO v_prev FROM public.leave WHERE id = p_leave_id FOR UPDATE;
    IF v_prev IS NULL THEN
        RAISE EXCEPTION 'workforceops: leave % not found', p_leave_id;
    END IF;
    UPDATE public.leave SET status = p_new_status, updated_at = NOW() WHERE id = p_leave_id;
    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN p_new_status;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_workforce_ops.decide_escalation(
    p_escalation_id text, p_decision text, p_note text, p_actor_id text, p_actor_role text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    UPDATE public.leadership_escalation
    SET status = 'resolved',
        decision = p_decision,
        decision_note = COALESCE(p_note, ''),
        resolved_at = NOW(),
        updated_at = NOW()
    WHERE id = p_escalation_id;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN 'resolved';
END;
$$;

CREATE OR REPLACE FUNCTION gateway_workforce_ops.record_help_feedback(
    p_article_id text, p_user_id text, p_role text, p_helpful boolean,
    p_feedback_type text, p_comment text, p_page_context text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text := 'hfb_' || substr(md5(p_article_id || ':' || p_user_id || ':' || clock_timestamp()::text), 1, 22);
BEGIN
    INSERT INTO public.help_center_helparticlefeedback (
        id, article_id, user_id, user_role, helpful, feedback_type, comment,
        page_context, created_at, updated_at
    ) VALUES (
        v_id, p_article_id, p_user_id, p_role, p_helpful, COALESCE(NULLIF(p_feedback_type, ''), 'helpful'),
        COALESCE(p_comment, ''), COALESCE(p_page_context, ''), NOW(), NOW()
    );
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_workforce_ops.transition_team_action(
    p_action_id text, p_transition text, p_actor_id text, p_actor_role text, p_reason text, p_now timestamptz
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_row public.team_action%ROWTYPE;
    v_is_admin boolean := (p_actor_role = 'Admin');
    v_reason text := COALESCE(trim(p_reason), '');
    v_target text;
    v_next text;
    v_active boolean;
BEGIN
    SELECT * INTO v_row FROM public.team_action WHERE id = p_action_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'workforceops: forbidden: action not found';
    END IF;

    IF p_transition IN ('acknowledge', 'start', 'block', 'return') THEN
        IF p_actor_id <> v_row.recipient_id AND NOT v_is_admin THEN
            RAISE EXCEPTION 'workforceops: forbidden: this action was not assigned to you';
        END IF;
    ELSIF p_transition IN ('cancel', 'escalate', 'resolve') THEN
        IF p_transition = 'cancel' THEN
            IF p_actor_id <> v_row.sender_id AND p_actor_role NOT IN ('Admin', 'CountryDirector') THEN
                RAISE EXCEPTION 'workforceops: forbidden: only the sender can cancel this action';
            END IF;
        ELSIF p_actor_id <> v_row.sender_id AND NOT v_is_admin THEN
            RAISE EXCEPTION 'workforceops: forbidden: you did not send this action';
        END IF;
    ELSE
        RAISE EXCEPTION 'workforceops: invalid: unknown transition %', p_transition;
    END IF;

    v_active := v_row.state IN ('open', 'acknowledged', 'in_progress', 'blocked', 'overdue', 'escalated');

    IF p_transition = 'acknowledge' THEN
        IF v_row.state <> 'open' THEN
            RETURN v_row.state;
        END IF;
        v_next := 'acknowledged';
        UPDATE public.team_action
        SET state = v_next, acknowledged_at = p_now, updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'start' THEN
        IF v_row.state NOT IN ('open', 'acknowledged', 'blocked', 'overdue') THEN
            RETURN v_row.state;
        END IF;
        v_next := 'in_progress';
        UPDATE public.team_action
        SET state = v_next, started_at = COALESCE(started_at, p_now), updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'block' THEN
        IF v_reason = '' THEN
            RAISE EXCEPTION 'workforceops: invalid: say what is blocking this before marking it blocked';
        END IF;
        v_next := 'blocked';
        UPDATE public.team_action
        SET state = v_next, blocked_reason = v_reason, updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'return' THEN
        IF v_reason = '' THEN
            RAISE EXCEPTION 'workforceops: invalid: say why you are returning this before sending it back';
        END IF;
        IF NOT v_active THEN
            RAISE EXCEPTION 'workforceops: invalid: this action is already closed';
        END IF;
        v_next := 'returned';
        UPDATE public.team_action
        SET state = v_next, returned_reason = v_reason, resolved_at = p_now, updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'cancel' THEN
        IF NOT v_active THEN
            RAISE EXCEPTION 'workforceops: invalid: this action is already closed';
        END IF;
        v_next := 'cancelled';
        UPDATE public.team_action
        SET state = v_next, returned_reason = v_reason, resolved_at = p_now, updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'escalate' THEN
        IF NOT v_active THEN
            RAISE EXCEPTION 'workforceops: invalid: this action is already closed';
        END IF;
        SELECT sup.user_id INTO v_target
        FROM public.staff_profile me
        JOIN public.staff_supervisor_assignment sa ON sa.supervisee_id = me.id
        JOIN public.staff_profile sup ON sup.id = sa.supervisor_id
        WHERE me.user_id = v_row.sender_id AND sup.user_id IS NOT NULL
        ORDER BY sa.created_at ASC
        LIMIT 1;
        IF v_target IS NULL OR v_target = '' THEN
            RAISE EXCEPTION 'workforceops: invalid: no supervisor is recorded above the sender to escalate to';
        END IF;
        v_next := 'escalated';
        UPDATE public.team_action
        SET state = v_next, escalated_at = p_now, escalated_to_id = v_target, updated_at = p_now
        WHERE id = p_action_id;
    ELSIF p_transition = 'resolve' THEN
        IF v_row.issue_type IN ('no_ssa', 'low_ssa', 'no_visit', 'no_training', 'no_visit_or_training') THEN
            RAISE EXCEPTION 'workforceops: invalid: system-verifiable actions close automatically once the record shows the work is done';
        END IF;
        IF v_reason = '' THEN
            RAISE EXCEPTION 'workforceops: invalid: a manual resolution needs a reason';
        END IF;
        v_next := 'resolved';
        UPDATE public.team_action
        SET state = v_next, resolved_at = p_now, resolved_by_system = false,
            manual_resolution_reason = v_reason, updated_at = p_now
        WHERE id = p_action_id;
    END IF;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN v_next;
END;
$$;

ALTER FUNCTION gateway_workforce_ops.update_own_profile(text, text, text) OWNER TO edify_workforce_ops_owner;
ALTER FUNCTION gateway_workforce_ops.decide_leave(text, text, text, text, text) OWNER TO edify_workforce_ops_owner;
ALTER FUNCTION gateway_workforce_ops.decide_escalation(text, text, text, text, text) OWNER TO edify_workforce_ops_owner;
ALTER FUNCTION gateway_workforce_ops.record_help_feedback(text, text, text, boolean, text, text, text) OWNER TO edify_workforce_ops_owner;
ALTER FUNCTION gateway_workforce_ops.transition_team_action(text, text, text, text, text, timestamptz) OWNER TO edify_workforce_ops_owner;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_workforce_ops FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA gateway_workforce_ops TO edify_gateway;
