-- Add to Project saved through Go, with Django absent (school_views.
-- assign_to_project_flow and apps.projects.services.assign_school). Go
-- decides the rules and their words; this function makes the writes in one
-- transaction: the allocation's place under its lock, the enrolment with its
-- matched intervention and baseline, the impact refresh the existing workers
-- run, and the project's coordinator when none is set.
--
-- Replaces gateway_school_actions.assign_school_to_project for this save
-- (left in place, unused). Applied by apply-roles.sh and the integration
-- TestMain. Idempotent. New database objects: production needs the owner's
-- approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_project_enrol_owner') THEN
    CREATE ROLE edify_project_enrol_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_project_enrol_owner;
GRANT USAGE ON SCHEMA public TO edify_project_enrol_owner;
GRANT SELECT (id, project_id, staff_id, max_schools) ON project_staff_capacity TO edify_project_enrol_owner;
GRANT UPDATE (updated_at) ON project_staff_capacity TO edify_project_enrol_owner;
GRANT SELECT (id, project_id, school_id, assigned_staff_id), INSERT ON project_school_assignment TO edify_project_enrol_owner;
GRANT SELECT (id, manager_staff_id), UPDATE (manager_staff_id, updated_at) ON project TO edify_project_enrol_owner;
GRANT SELECT (idempotency_key) ON outbox_event TO edify_project_enrol_owner;
GRANT INSERT (id, created_at, updated_at, event_type, payload, idempotency_key, status, attempts,
              max_attempts, next_attempt_at, locked_by, last_error)
  ON outbox_event TO edify_project_enrol_owner;

CREATE SCHEMA IF NOT EXISTS gateway_project_enrol AUTHORIZATION edify_project_enrol_owner;
REVOKE ALL ON SCHEMA gateway_project_enrol FROM PUBLIC;

SET ROLE edify_project_enrol_owner;

-- Answers 'already', 'no_allocation', 'full:<max>' or 'ok'.
CREATE OR REPLACE FUNCTION gateway_project_enrol.enrol(
  p_id varchar, p_project varchar, p_school varchar, p_holder varchar, p_by varchar, p_project_type varchar,
  p_participation varchar, p_start date, p_support varchar, p_notes text, p_matched varchar, p_reason text,
  p_baseline_record varchar, p_baseline_score double precision, p_baseline_band varchar, p_classification varchar,
  p_coordinator varchar, p_outbox_id varchar, p_now timestamptz) RETURNS varchar
  -- public on the path for the existing application's own trigger on
  -- project_school_assignment (project_school_capacity_guard), which names
  -- its tables unqualified; pg_catalog is searched first regardless.
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $fn$
DECLARE
  v_max integer;
  v_held integer;
BEGIN
  IF EXISTS (SELECT 1 FROM public.project_school_assignment a WHERE a.project_id = p_project AND a.school_id = p_school) THEN
    RETURN 'already';
  END IF;
  -- capacity.reserve_place: the holder's allocation, locked, then counted.
  IF COALESCE(p_holder, '') <> '' THEN
    SELECT c.max_schools INTO v_max FROM public.project_staff_capacity c
     WHERE c.project_id = p_project AND c.staff_id = p_holder FOR UPDATE;
    IF NOT FOUND THEN
      IF EXISTS (SELECT 1 FROM public.project_staff_capacity c WHERE c.project_id = p_project) THEN
        RETURN 'no_allocation';
      END IF;
    ELSE
      SELECT count(*) INTO v_held FROM public.project_school_assignment a
       WHERE a.project_id = p_project AND a.assigned_staff_id = p_holder;
      IF v_held >= v_max THEN
        RETURN 'full:' || v_max::text;
      END IF;
    END IF;
  END IF;
  INSERT INTO public.project_school_assignment (
    id, created_at, updated_at, project_id, school_id, assigned_by, assigned_staff_id, project_type, participation_type,
    start_date, support_area, notes, matched_intervention, assignment_reason, baseline_ssa_id, baseline_score,
    baseline_band, baseline_captured_at, impact_classification, exception_status, exception_reason, exception_approved_by)
  VALUES (
    p_id, p_now, p_now, p_project, p_school, NULLIF(p_by, ''), NULLIF(p_holder, ''), NULLIF(p_project_type, ''),
    NULLIF(p_participation, ''), p_start, NULLIF(p_support, ''), NULLIF(p_notes, ''), NULLIF(p_matched, ''),
    NULLIF(p_reason, ''), NULLIF(p_baseline_record, ''), p_baseline_score, COALESCE(p_baseline_band, ''),
    CASE WHEN p_baseline_score IS NULL THEN NULL ELSE p_now END, COALESCE(p_classification, ''), '', '', '');
  -- enqueue_impact_refresh: a school with a baseline and no mapping yet.
  IF p_baseline_score IS NOT NULL THEN
    INSERT INTO public.outbox_event (id, created_at, updated_at, event_type, payload, idempotency_key,
                                     status, attempts, max_attempts, next_attempt_at, locked_by, last_error)
    VALUES (p_outbox_id, p_now, p_now, 'projects.impact.refresh', jsonb_build_object('schoolId', p_school),
            'projects.impact:' || p_school || ':enrolment:' || p_id, 'pending', 0, 8, p_now, '', '')
    ON CONFLICT (idempotency_key) DO NOTHING;
  END IF;
  IF COALESCE(p_coordinator, '') <> '' THEN
    UPDATE public.project SET manager_staff_id = p_coordinator, updated_at = p_now
     WHERE id = p_project AND manager_staff_id IS NULL;
  END IF;
  RETURN 'ok';
END
$fn$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_project_enrol FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_project_enrol TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_project_enrol.enrol(varchar, varchar, varchar, varchar, varchar, varchar, varchar, date,
  varchar, text, varchar, text, varchar, double precision, varchar, varchar, varchar, varchar, timestamptz)
TO edify_activities_rw;
