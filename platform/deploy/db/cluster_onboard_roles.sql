-- Least-privilege role and SECURITY DEFINER function for native Go Cluster
-- Leader account onboarding (Batch 10 & Step 2 — full parity with
-- apps/clusters/leader_onboarding.py).
--
-- Keeps edify_gateway read-only by default (no direct INSERT/UPDATE on "user")
-- and never touches protected columns or deletes rows.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_onboard_owner') THEN
        CREATE ROLE edify_cluster_onboard_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
    END IF;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_cluster_onboard_owner;
GRANT USAGE ON SCHEMA public TO edify_cluster_onboard_owner;
GRANT SELECT, INSERT ON "user" TO edify_cluster_onboard_owner;
GRANT SELECT, INSERT ON user_invitation TO edify_cluster_onboard_owner;

CREATE SCHEMA IF NOT EXISTS gateway_cluster_onboard AUTHORIZATION edify_cluster_onboard_owner;
REVOKE ALL ON SCHEMA gateway_cluster_onboard FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_cluster_onboard TO edify_gateway;

SET ROLE edify_cluster_onboard_owner;

-- Mirrors apps/clusters/leader_onboarding.py:
--   * If email belongs to a non-ClusterLeader account -> returns conflict=true.
--   * If email already belongs to a ClusterLeader account -> returns existing=true.
--   * Otherwise creates the user (status='pending_invited', is_active=false,
--     roles=['ClusterLeader']), inserts a user_invitation row with token_hash,
--     and appends audit_log ('cluster_leader.onboarded').
CREATE OR REPLACE FUNCTION gateway_cluster_onboard.ensure_leader_account(
    p_name         text,
    p_email        text,
    p_phone        text,
    p_token_hash   text,
    p_cluster_id   text,
    p_actor_id     text,
    p_actor_role   text
) RETURNS TABLE(user_id text, existing boolean, conflict boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_email      text := lower(trim(p_email));
    v_id         text;
    v_roles      varchar[];
    v_inv_id     text;
    v_inviter    text;
    v_now        timestamptz := NOW();
BEGIN
    SELECT u.id, u.roles INTO v_id, v_roles
    FROM public."user" u
    WHERE lower(u.email) = v_email AND u.deleted_at IS NULL
    LIMIT 1;

    IF v_id IS NOT NULL THEN
        IF v_roles IS DISTINCT FROM ARRAY['ClusterLeader']::varchar[] THEN
            RETURN QUERY SELECT ''::text, false, true;
            RETURN;
        END IF;
        RETURN QUERY SELECT v_id::text, true, false;
        RETURN;
    END IF;

    v_id := 'clu_' || substr(md5(v_email || ':' || clock_timestamp()::text || ':' || p_token_hash), 1, 22);
    INSERT INTO public."user" (
        id, email, name, phone, password,
        active_role, roles, status, is_active, is_staff, is_superuser,
        must_change_password, failed_login_count, mfa_enabled, mfa_channel,
        lockout_cycle_count, lockout_escalated, sms_money_alerts,
        last_seen_path, last_seen_action, environment, source,
        created_at, updated_at
    ) VALUES (
        v_id, v_email, trim(p_name), NULLIF(trim(COALESCE(p_phone, '')), ''), NULL,
        'ClusterLeader', ARRAY['ClusterLeader']::varchar[], 'pending_invited', false, false, false,
        true, 0, false, 'none',
        0, false, false,
        '', '', 'production', 'go_gateway',
        v_now, v_now
    );

    -- Resolve inviter user_id (required NOT NULL FK on user_invitation).
    v_inviter := NULLIF(trim(COALESCE(p_actor_id, '')), '');
    IF v_inviter IS NULL THEN
        SELECT u.id INTO v_inviter FROM public."user" u WHERE u.deleted_at IS NULL AND u.is_active LIMIT 1;
    END IF;
    IF v_inviter IS NOT NULL AND COALESCE(p_token_hash, '') <> '' THEN
        v_inv_id := 'inv_' || substr(md5(v_id || ':' || p_token_hash || ':' || clock_timestamp()::text), 1, 22);
        INSERT INTO public.user_invitation (
            created_at, updated_at, id, token_hash, expires_at,
            accepted_at, revoked_at, invited_by_id, user_id
        ) VALUES (
            v_now, v_now, v_inv_id, p_token_hash, v_now + interval '7 days',
            NULL, NULL, v_inviter, v_id
        );
    END IF;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN QUERY SELECT v_id::text, false, false;
END;
$$;

REVOKE ALL ON FUNCTION gateway_cluster_onboard.ensure_leader_account(text, text, text, text, text, text, text) FROM PUBLIC;
RESET ROLE;

GRANT EXECUTE ON FUNCTION gateway_cluster_onboard.ensure_leader_account(text, text, text, text, text, text, text) TO edify_gateway;
