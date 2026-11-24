-- SSA scores keyed on a visit, saved through Go with Django absent
-- (my_plan_views.ssa_evidence_upload_action → apps.ssa.services.upload) for
-- an officer's own staff school visit. Go reads the scores, their range, the
-- visit's day, the year and the previous year's rule, and the record's
-- confirmer; this function makes the writes in one transaction under the
-- school's lock: the visit's own record re-keyed or a new one, its eight
-- scores, the school's SSA status, readiness and data quality
-- (_recompute_readiness, School.recompute_quality_and_readiness), and the
-- school's save signal (gateway_pl_review.reconcile_school_issues).
--
-- Answers 'created:<id>' or 'rekeyed:<id>', and otherwise writes nothing and
-- says why: 'other_school' (the visit's record is another school's),
-- 'confirmed' (its record is confirmed), 'year' (another record holds the
-- school's year). A race the lock did not see meets uniq_live_ssa_school_fy.
--
-- The owner is a NOLOGIN role nobody is a member of. Applied after
-- pl_review_roles.sql (apply-roles.sh, the integration TestMain). Idempotent.
-- A new database object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_ssa_entry_owner') THEN
    CREATE ROLE edify_ssa_entry_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_ssa_entry_owner;
GRANT USAGE ON SCHEMA public TO edify_ssa_entry_owner;
GRANT SELECT (id, school_id, fy, source_activity_id, deleted_at, verification_status, date_of_ssa)
  ON ssa_record TO edify_ssa_entry_owner;
GRANT INSERT (id, created_at, updated_at, deleted_at, date_of_ssa, fy, quarter, new_enrollment, average_score,
              salesforce_id, verification_status, collector_type, verification_source, collected_by_user_id,
              collected_by_partner_id, verified_by_user_id, verified_at, qa_reviewed_by_user_id, qa_reviewed_at,
              uploaded_by, school_id, environment, source, return_reason, returned_at, returned_by_user_id,
              source_activity_id)
  ON ssa_record TO edify_ssa_entry_owner;
GRANT UPDATE (date_of_ssa, fy, quarter, average_score, uploaded_by, collector_type, collected_by_user_id,
              collected_by_partner_id, verification_status, verification_source, verified_by_user_id, verified_at,
              return_reason, returned_by_user_id, returned_at, updated_at)
  ON ssa_record TO edify_ssa_entry_owner;
GRANT SELECT (ssa_record_id), INSERT (id, created_at, updated_at, ssa_record_id, intervention, score), DELETE
  ON ssa_score TO edify_ssa_entry_owner;
GRANT SELECT (id, current_fy_ssa_status, school_phone, primary_contact_name, enrollment, account_owner_id,
              account_owner_status, cluster_id, duplicate_status)
  ON school TO edify_ssa_entry_owner;
GRANT UPDATE (current_fy_ssa_status, planning_readiness, data_quality_score, data_quality_status, updated_at)
  ON school TO edify_ssa_entry_owner;
GRANT USAGE ON SCHEMA gateway_pl_review TO edify_ssa_entry_owner;
GRANT EXECUTE ON FUNCTION gateway_pl_review.reconcile_school_issues(varchar, timestamptz) TO edify_ssa_entry_owner;

CREATE SCHEMA IF NOT EXISTS gateway_ssa_entry AUTHORIZATION edify_ssa_entry_owner;
REVOKE ALL ON SCHEMA gateway_ssa_entry FROM PUBLIC;

SET ROLE edify_ssa_entry_owner;

-- p_scores is [{"id": ..., "intervention": ..., "score": ...}, ...] in the
-- drawer's order.
CREATE OR REPLACE FUNCTION gateway_ssa_entry.key_visit_ssa(
  p_school varchar, p_activity varchar, p_record varchar, p_date timestamptz, p_fy varchar, p_quarter varchar,
  p_average double precision, p_user varchar, p_scores jsonb, p_at timestamptz, p_operational_fy varchar
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  existing record;
  place record;
  record_id varchar;
  answer varchar;
  ssa_state varchar;
  points integer;
  quality varchar;
  readiness varchar;
BEGIN
  PERFORM 1 FROM public.school sc WHERE sc.id = p_school FOR UPDATE;
  -- The visit's own record (Meta.ordering, -date_of_ssa).
  SELECT r.id, r.school_id, r.verification_status INTO existing FROM public.ssa_record r
   WHERE r.source_activity_id = p_activity AND r.deleted_at IS NULL ORDER BY r.date_of_ssa DESC LIMIT 1;
  IF FOUND AND existing.school_id <> p_school THEN
    RETURN 'other_school';
  END IF;
  IF FOUND AND existing.verification_status = 'confirmed' THEN
    RETURN 'confirmed';
  END IF;
  IF EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = p_school AND o.fy = p_fy AND o.deleted_at IS NULL
              AND o.verification_status = ANY (ARRAY['pending', 'confirmed']::varchar[])
              AND o.id IS DISTINCT FROM existing.id) THEN
    RETURN 'year';
  END IF;
  IF existing.id IS NOT NULL THEN
    UPDATE public.ssa_record r SET date_of_ssa = p_date, fy = p_fy, quarter = p_quarter, average_score = p_average,
      uploaded_by = p_user, collector_type = 'staff', collected_by_user_id = p_user, collected_by_partner_id = NULL,
      verification_status = 'pending', verification_source = 'staff_keyed', verified_by_user_id = NULL,
      verified_at = NULL, return_reason = '', returned_by_user_id = NULL, returned_at = NULL, updated_at = p_at
     WHERE r.id = existing.id;
    DELETE FROM public.ssa_score s WHERE s.ssa_record_id = existing.id;
    record_id := existing.id;
    answer := 'rekeyed:';
  ELSE
    INSERT INTO public.ssa_record (id, created_at, updated_at, deleted_at, date_of_ssa, fy, quarter, new_enrollment,
      average_score, salesforce_id, verification_status, collector_type, verification_source, collected_by_user_id,
      collected_by_partner_id, verified_by_user_id, verified_at, qa_reviewed_by_user_id, qa_reviewed_at, uploaded_by,
      school_id, environment, source, return_reason, returned_at, returned_by_user_id, source_activity_id)
    VALUES (p_record, p_at, p_at, NULL, p_date, p_fy, p_quarter, NULL, p_average, NULL, 'pending', 'staff',
      'staff_keyed', p_user, NULL, NULL, NULL, NULL, NULL, p_user, p_school, 'production', 'manual_upload', '', NULL,
      NULL, p_activity);
    record_id := p_record;
    answer := 'created:';
  END IF;
  INSERT INTO public.ssa_score (id, created_at, updated_at, ssa_record_id, intervention, score)
  SELECT e->>'id', p_at, p_at, record_id, e->>'intervention', (e->>'score')::double precision
    FROM jsonb_array_elements(p_scores) e;

  -- _recompute_readiness and School.recompute_quality_and_readiness.
  SELECT sc.id, sc.current_fy_ssa_status, sc.school_phone, sc.primary_contact_name, sc.enrollment,
         sc.account_owner_id, sc.account_owner_status, sc.cluster_id, sc.duplicate_status
    INTO place FROM public.school sc WHERE sc.id = p_school;
  IF EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = place.id AND o.deleted_at IS NULL
              AND o.verification_status = 'confirmed' AND o.fy = p_operational_fy) THEN
    ssa_state := 'done';
  ELSIF EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = place.id AND o.deleted_at IS NULL
                 AND o.verification_status = 'pending' AND o.fy = p_operational_fy) THEN
    ssa_state := 'partner_assigned';
  ELSIF place.current_fy_ssa_status = ANY (ARRAY['done', 'partner_assigned']::varchar[]) THEN
    ssa_state := 'not_done';
  ELSE
    ssa_state := place.current_fy_ssa_status;
  END IF;
  points := 100;
  IF COALESCE(place.school_phone, '') = '' THEN points := points - 15; END IF;
  IF COALESCE(place.primary_contact_name, '') = '' THEN points := points - 15; END IF;
  IF place.enrollment IS NULL OR place.enrollment <= 0 THEN points := points - 20; END IF;
  IF COALESCE(place.account_owner_id, '') = '' OR place.account_owner_status <> 'matched' THEN points := points - 20; END IF;
  IF COALESCE(place.cluster_id, '') = '' THEN points := points - 20; END IF;
  IF place.duplicate_status = 'potential' THEN
    quality := 'Duplicate Risk';
  ELSIF COALESCE(place.cluster_id, '') = '' OR points < 40 THEN
    quality := 'Missing Critical Data';
  ELSIF points >= 90 THEN
    quality := 'Clean';
  ELSIF points >= 70 THEN
    quality := 'Needs Review';
  ELSE
    quality := 'Needs Cleanup';
  END IF;
  IF COALESCE(place.cluster_id, '') = '' THEN
    readiness := 'requires_cluster';
  ELSIF ssa_state <> 'done' THEN
    readiness := 'ready_for_baseline_ssa';
  ELSE
    readiness := 'ready_for_support_planning';
  END IF;
  UPDATE public.school
     SET current_fy_ssa_status = ssa_state, planning_readiness = readiness,
         data_quality_score = GREATEST(points, 0), data_quality_status = quality, updated_at = p_at
   WHERE id = place.id;
  PERFORM gateway_pl_review.reconcile_school_issues(place.id, p_at);
  RETURN answer || record_id;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_ssa_entry.key_visit_ssa(varchar, varchar, varchar, timestamptz, varchar, varchar,
  double precision, varchar, jsonb, timestamptz, varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_ssa_entry TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_ssa_entry.key_visit_ssa(varchar, varchar, varchar, timestamptz, varchar, varchar,
  double precision, varchar, jsonb, timestamptz, varchar) TO edify_activities_rw;
