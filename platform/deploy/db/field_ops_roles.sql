-- Least-privilege role and SECURITY DEFINER functions for Field Execution,
-- Evidence, IA Verification, SSA, and Partner workflows (Batch 11: M7–M10).
--
-- Keeps edify_gateway read-only by default; never touches dbguard protected
-- columns or deletes rows.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_field_ops_owner') THEN
        CREATE ROLE edify_field_ops_owner NOLOGIN NOINHERIT;
    END IF;
END $$;

GRANT USAGE ON SCHEMA public TO edify_field_ops_owner;
GRANT SELECT, INSERT, UPDATE ON
    evidence_record,
    ssa_record,
    ssa_score,
    partner_assignment,
    activity,
    activity_completion_verification
TO edify_field_ops_owner;
GRANT SELECT ON school, staff_profile TO edify_field_ops_owner;

CREATE SCHEMA IF NOT EXISTS gateway_field_ops AUTHORIZATION edify_field_ops_owner;
REVOKE ALL ON SCHEMA gateway_field_ops FROM PUBLIC;
GRANT USAGE ON SCHEMA gateway_field_ops TO edify_gateway;

-- M8: Record uploaded evidence idempotently (rejects broken/empty uploads).
CREATE OR REPLACE FUNCTION gateway_field_ops.record_evidence(
    p_activity_id   text,
    p_kind          text,
    p_uri           text,
    p_original_name text,
    p_mime_type     text,
    p_ext           text,
    p_file_size     int,
    p_provider      text,
    p_uploaded_by   text,
    p_uploader_role text,
    p_notes         text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text;
BEGIN
    IF trim(COALESCE(p_uri, '')) = '' OR COALESCE(p_file_size, 0) <= 0 THEN
        RAISE EXCEPTION 'fieldops: incomplete or empty evidence upload rejected';
    END IF;
    SELECT id INTO v_id FROM public.evidence_record
    WHERE activity_id = p_activity_id AND uri = p_uri
    LIMIT 1;
    IF v_id IS NOT NULL THEN
        RETURN v_id;
    END IF;
    v_id := 'evd_' || substr(md5(p_activity_id || ':' || p_uri), 1, 22);
    INSERT INTO public.evidence_record (
        id, activity_id, kind, uri, original_name, mime_type, file_extension,
        file_size, storage_provider, notes, uploaded_by, uploader_role,
        status, scan_status, quarantined, preview_status, view_count,
        created_at, updated_at
    ) VALUES (
        v_id, p_activity_id, p_kind, p_uri, p_original_name, p_mime_type, p_ext,
        p_file_size, COALESCE(NULLIF(p_provider, ''), 'object_storage'), p_notes,
        p_uploaded_by, p_uploader_role, 'pending', 'clean', false, 'ready', 0,
        NOW(), NOW()
    );
    RETURN v_id;
END;
$$;

-- M9: Impact Assessment verification or return of a completion or partner evidence.
CREATE OR REPLACE FUNCTION gateway_field_ops.ia_decide_activity(
    p_activity_id text,
    p_decision    text, -- 'verified' | 'returned'
    p_actor_id    text,
    p_actor_role  text,
    p_note        text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_status text;
    v_new_st text;
    v_ia_st  text;
BEGIN
    SELECT status INTO v_status FROM public.activity
    WHERE id = p_activity_id AND deleted_at IS NULL FOR UPDATE;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'fieldops: activity % not found', p_activity_id;
    END IF;

    IF p_decision = 'verified' THEN
        v_new_st := 'closed';
        v_ia_st  := 'confirmed';
    ELSIF p_decision = 'returned' THEN
        v_new_st := 'returned_for_correction';
        v_ia_st  := 'returned';
    ELSE
        RAISE EXCEPTION 'fieldops: invalid IA decision %', p_decision;
    END IF;

    UPDATE public.activity
    SET status = v_new_st,
        ia_verification_status = v_ia_st,
        updated_at = NOW()
    WHERE id = p_activity_id;

    -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
    RETURN v_new_st;
END;
$$;

-- M7: Enter or update an SSA record with its intervention scores atomically.
CREATE OR REPLACE FUNCTION gateway_field_ops.enter_ssa(
    p_school_id   text,
    p_fy          text,
    p_quarter     text,
    p_date        timestamptz,
    p_enrollment  int,
    p_avg_score   double precision,
    p_scores_json jsonb,
    p_collector   text,
    p_actor_id    text,
    p_activity_id text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id   text;
    v_item jsonb;
    v_sid  text;
BEGIN
    SELECT id INTO v_id FROM public.ssa_record
    WHERE school_id = p_school_id AND fy = p_fy AND deleted_at IS NULL
      AND verification_status IN ('pending', 'confirmed')
    LIMIT 1;

    IF v_id IS NULL THEN
        v_id := 'ssa_' || substr(md5(p_school_id || ':' || p_fy || ':' || clock_timestamp()::text), 1, 22);
        INSERT INTO public.ssa_record (
            id, school_id, fy, quarter, date_of_ssa, new_enrollment, average_score,
            verification_status, collector_type, collected_by_user_id, uploaded_by,
            source_activity_id, environment, source, return_reason, created_at, updated_at
        ) VALUES (
            v_id, p_school_id, p_fy, p_quarter, p_date, p_enrollment, p_avg_score,
            'pending', COALESCE(NULLIF(p_collector, ''), 'staff'), p_actor_id, p_actor_id,
            NULLIF(p_activity_id, ''), 'development', 'gateway', '', NOW(), NOW()
        );
    ELSE
        UPDATE public.ssa_record
        SET date_of_ssa = p_date,
            quarter = p_quarter,
            new_enrollment = COALESCE(p_enrollment, new_enrollment),
            average_score = p_avg_score,
            updated_at = NOW()
        WHERE id = v_id;
    END IF;

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_scores_json) LOOP
        v_sid := 'ssc_' || substr(md5(v_id || ':' || (v_item->>'intervention')), 1, 22);
        INSERT INTO public.ssa_score (
            id, ssa_record_id, intervention, score, created_at, updated_at
        ) VALUES (
            v_sid, v_id, v_item->>'intervention', (v_item->>'score')::double precision, NOW(), NOW()
        )
        ON CONFLICT (ssa_record_id, intervention) DO UPDATE
        SET score = EXCLUDED.score, updated_at = NOW();
    END LOOP;
    RETURN v_id;
END;
$$;

-- M7: Confirm or return an SSA record (PL / IA).
CREATE OR REPLACE FUNCTION gateway_field_ops.decide_ssa(
    p_ssa_id   text,
    p_decision text, -- 'confirmed' | 'returned'
    p_actor_id text,
    p_reason   text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF p_decision NOT IN ('confirmed', 'returned') THEN
        RAISE EXCEPTION 'fieldops: invalid SSA decision %', p_decision;
    END IF;
    UPDATE public.ssa_record
    SET verification_status = p_decision,
        verified_by_user_id = CASE WHEN p_decision = 'confirmed' THEN p_actor_id ELSE verified_by_user_id END,
        verified_at = CASE WHEN p_decision = 'confirmed' THEN NOW() ELSE verified_at END,
        return_reason = CASE WHEN p_decision = 'returned' THEN COALESCE(p_reason, '') ELSE '' END,
        updated_at = NOW()
    WHERE id = p_ssa_id AND deleted_at IS NULL;
    RETURN p_decision;
END;
$$;

-- M10: Partner handover creation, partner dating, and partner return.
CREATE OR REPLACE FUNCTION gateway_field_ops.create_partner_assignment(
    p_partner_id text, p_school_id text, p_staff_id text,
    p_purpose text, p_intervention text, p_activity_type text, p_notes text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id text := 'pas_' || substr(md5(p_partner_id || ':' || COALESCE(p_school_id, '') || ':' || clock_timestamp()::text), 1, 22);
BEGIN
    INSERT INTO public.partner_assignment (
        id, partner_id, school_id, assigning_staff_id, monitoring_staff_id,
        purpose, focus_intervention, expected_activity_type, status, notes,
        assignment_mode, catalogue_snapshot, override_reason, recommendation_reason,
        reassignment_sequence, resolution, created_at, updated_at
    ) VALUES (
        v_id, p_partner_id, NULLIF(p_school_id, ''), p_staff_id, p_staff_id,
        p_purpose, NULLIF(p_intervention, ''), COALESCE(NULLIF(p_activity_type, ''), 'school_visit'),
        'assigned', COALESCE(p_notes, ''), 'manual', '{}'::jsonb, '', '', 0, 'open',
        NOW(), NOW()
    );
    RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION gateway_field_ops.update_partner_assignment(
    p_assignment_id text, p_action text, p_date date, p_actor_id text, p_reason text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_new_st text;
BEGIN
    IF p_action = 'date' THEN
        v_new_st := 'scheduled';
        UPDATE public.partner_assignment
        SET scheduled_date = p_date, status = v_new_st, updated_at = NOW()
        WHERE id = p_assignment_id;
    ELSIF p_action = 'return' THEN
        v_new_st := 'returned';
        UPDATE public.partner_assignment
        SET status = v_new_st, return_reason = COALESCE(p_reason, ''),
            returned_at = NOW(), returned_by = p_actor_id, updated_at = NOW()
        WHERE id = p_assignment_id;
    ELSE
        RAISE EXCEPTION 'fieldops: unknown partner action %', p_action;
    END IF;
    RETURN v_new_st;
END;
$$;

-- M8: Authorized evidence storage URI lookup (keeps evidence_record.uri off edify_gateway_ro).
CREATE OR REPLACE FUNCTION gateway_field_ops.read_evidence_uri(p_evidence_id text)
RETURNS TABLE(uri text, quarantined boolean, responsible_staff_id text, monitored_by_staff_id text)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT e.uri, e.quarantined, COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, '')
      FROM public.evidence_record e
      JOIN public.activity a ON a.id = e.activity_id
     WHERE e.id = p_evidence_id
       AND a.deleted_at IS NULL;
$$;

ALTER FUNCTION gateway_field_ops.record_evidence(text, text, text, text, text, text, int, text, text, text, text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.read_evidence_uri(text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.ia_decide_activity(text, text, text, text, text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.enter_ssa(text, text, text, timestamptz, int, double precision, jsonb, text, text, text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.decide_ssa(text, text, text, text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.create_partner_assignment(text, text, text, text, text, text, text) OWNER TO edify_field_ops_owner;
ALTER FUNCTION gateway_field_ops.update_partner_assignment(text, text, date, text, text) OWNER TO edify_field_ops_owner;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_field_ops FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA gateway_field_ops TO edify_gateway;
