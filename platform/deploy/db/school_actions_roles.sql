-- Native Go School Actions & School Profile Drawer writers (Batches 22–23).
--
-- Keeps edify_gateway read-only by default (TestGatewayRoleCanNeitherWriteNorReadSecrets);
-- school cluster assignment, project enrollment, bulk school assignments, and
-- school profile edits execute through narrow SECURITY DEFINER functions owned
-- by edify_school_actions_owner.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_school_actions_owner') THEN
    CREATE ROLE edify_school_actions_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_school_actions_owner;
GRANT USAGE ON SCHEMA public TO edify_school_actions_owner;

GRANT SELECT ON school, cluster, project, staff_profile TO edify_school_actions_owner;
GRANT UPDATE (cluster_id, cluster_status, name, school_phone, primary_contact_name, primary_contact_phone, enrollment, shipping_address, headteacher_name, director_name, updated_at)
  ON school TO edify_school_actions_owner;
GRANT INSERT ON cluster TO edify_school_actions_owner;
-- Taking a school nobody holds (data_gaps.take).
GRANT UPDATE (account_owner_id, account_owner_name_raw, account_owner_status) ON school TO edify_school_actions_owner;
GRANT SELECT, INSERT ON staff_school_assignment TO edify_school_actions_owner;
GRANT SELECT, INSERT, UPDATE ON school_cluster_membership TO edify_school_actions_owner;
GRANT SELECT, INSERT, UPDATE ON school_cluster_assignment TO edify_school_actions_owner;
GRANT SELECT, INSERT, UPDATE ON project_school_assignment TO edify_school_actions_owner;

CREATE SCHEMA IF NOT EXISTS gateway_school_actions AUTHORIZATION edify_school_actions_owner;
REVOKE ALL ON SCHEMA gateway_school_actions FROM PUBLIC;

SET ROLE edify_school_actions_owner;

CREATE OR REPLACE FUNCTION gateway_school_actions.assign_school_to_cluster(
  p_school_id        text,
  p_cluster_id       text,
  p_new_cluster_name text,
  p_actor_id         text,
  p_actor_role       text,
  p_reason           text,
  p_at               timestamptz
) RETURNS TABLE(cluster_id text, cluster_name text, message text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_school     record;
  v_cluster    record;
  v_cid        text := btrim(coalesce(p_cluster_id, ''));
  v_cname      text := btrim(coalesce(p_new_cluster_name, ''));
  v_mem_id     text;
  v_asg_id     text;
BEGIN
  SELECT id, school_id, name, district_id, region_id, sub_county_id, cluster_id
    INTO v_school
    FROM public.school
   WHERE (id = p_school_id OR school_id = p_school_id)
     AND deleted_at IS NULL
   LIMIT 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'school_actions: school not found';
  END IF;

  IF v_cid = '' THEN
    IF v_cname = '' THEN
      RAISE EXCEPTION 'school_actions: cluster_id or new_cluster_name is required';
    END IF;
    IF v_school.district_id IS NULL OR v_school.region_id IS NULL THEN
      RAISE EXCEPTION 'school_actions: school is missing district or region for a new cluster';
    END IF;
    v_cid := 'clu_' || substr(md5(v_cname || ':' || v_school.district_id || ':' || p_at::text), 1, 20);
    INSERT INTO public.cluster (
      created_at, updated_at, id, name, cluster_type, status,
      district_id, region_id, sub_county_id, environment, source
    ) VALUES (
      p_at, p_at, v_cid, left(v_cname, 150), 'standard', 'active',
      v_school.district_id, v_school.region_id, v_school.sub_county_id, 'production', 'go_gateway'
    )
    ON CONFLICT (id) DO NOTHING;
  END IF;

  SELECT id, name, district_id INTO v_cluster
    FROM public.cluster
   WHERE id = v_cid AND deleted_at IS NULL
   LIMIT 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'school_actions: cluster not found';
  END IF;

  UPDATE public.school_cluster_membership
     SET ended_at   = p_at,
         ended_by   = p_actor_id,
         end_reason = COALESCE(NULLIF(btrim(p_reason), ''), 'Cluster assignment updated'),
         updated_at = p_at
   WHERE school_id = v_school.id
     AND ended_at IS NULL;

  v_mem_id := 'scm_' || substr(md5(v_school.id || ':' || v_cluster.id || ':' || clock_timestamp()::text), 1, 20);
  INSERT INTO public.school_cluster_membership (
    created_at, updated_at, id, started_at, started_by, started_by_role,
    ended_by, start_reason, end_reason, relationship_type, correlation_id,
    cluster_id, cluster_district_id, school_id, school_district_id
  ) VALUES (
    p_at, p_at, v_mem_id, p_at, p_actor_id, COALESCE(p_actor_role, ''),
    '', COALESCE(btrim(p_reason), ''), '', 'primary', v_mem_id,
    v_cluster.id, v_cluster.district_id, v_school.id, v_school.district_id
  );

  v_asg_id := 'sca_' || substr(md5(v_school.id || ':' || v_cluster.id || ':' || clock_timestamp()::text), 1, 20);
  INSERT INTO public.school_cluster_assignment (
    created_at, updated_at, id, assigned_by, cluster_id, school_id
  ) VALUES (
    p_at, p_at, v_asg_id, p_actor_id, v_cluster.id, v_school.id
  )
  ON CONFLICT DO NOTHING;

  UPDATE public.school
     SET cluster_id     = v_cluster.id,
         cluster_status = 'clustered',
         updated_at     = p_at
   WHERE id = v_school.id;

  -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
  RETURN QUERY SELECT v_cluster.id, v_cluster.name, v_school.name || ' added to ' || v_cluster.name || '.';
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_school_actions.assign_school_to_project(
  p_school_id          text,
  p_project_id         text,
  p_project_type       text,
  p_participation_type text,
  p_start_date         date,
  p_support_area       text,
  p_coordinator_id     text,
  p_notes              text,
  p_actor_id           text,
  p_actor_role         text,
  p_at                 timestamptz
) RETURNS TABLE(assignment_id text, already_enrolled boolean, message text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_school   record;
  v_project  record;
  v_existing text;
  v_id       text;
BEGIN
  SELECT id, name INTO v_school
    FROM public.school
   WHERE (id = p_school_id OR school_id = p_school_id)
     AND deleted_at IS NULL
   LIMIT 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'school_actions: school not found';
  END IF;

  SELECT id, name INTO v_project
    FROM public.project
   WHERE id = p_project_id AND deleted_at IS NULL
   LIMIT 1;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'school_actions: project not found';
  END IF;

  SELECT id INTO v_existing
    FROM public.project_school_assignment
   WHERE school_id = v_school.id AND project_id = v_project.id
   LIMIT 1;
  IF FOUND THEN
    RETURN QUERY SELECT v_existing, true, v_school.name || ' is already enrolled in ' || v_project.name || '.';
    RETURN;
  END IF;

  v_id := 'psa_' || substr(md5(v_school.id || ':' || v_project.id || ':' || clock_timestamp()::text), 1, 20);
  INSERT INTO public.project_school_assignment (
    created_at, updated_at, id, project_id, school_id, assigned_by, notes,
    participation_type, project_type, start_date, support_area,
    baseline_band, exception_approved_by, exception_reason, exception_status,
    impact_classification, assigned_staff_id
  ) VALUES (
    p_at, p_at, v_id, v_project.id, v_school.id, p_actor_id, NULLIF(btrim(p_notes), ''),
    NULLIF(btrim(p_participation_type), ''), NULLIF(btrim(p_project_type), ''),
    COALESCE(p_start_date, p_at::date), NULLIF(btrim(p_support_area), ''),
    '', '', '', 'none', 'pending', NULLIF(btrim(p_coordinator_id), '')
  );

  -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
  RETURN QUERY SELECT v_id, false, v_school.name || ' added to ' || v_project.name || '.';
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_school_actions.update_school_details(
  p_school_id        text,
  p_name             text,
  p_phone            text,
  p_contact_name     text,
  p_contact_phone    text,
  p_enrollment       integer,
  p_shipping_address text,
  p_headteacher      text,
  p_director         text,
  p_actor_id         text,
  p_actor_role       text,
  p_at               timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id text;
BEGIN
  UPDATE public.school
     SET name                  = COALESCE(NULLIF(btrim(p_name), ''), name),
         school_phone          = COALESCE(NULLIF(btrim(p_phone), ''), school_phone),
         primary_contact_name  = COALESCE(NULLIF(btrim(p_contact_name), ''), primary_contact_name),
         primary_contact_phone = COALESCE(NULLIF(btrim(p_contact_phone), ''), primary_contact_phone),
         enrollment            = COALESCE(p_enrollment, enrollment),
         shipping_address      = COALESCE(NULLIF(btrim(p_shipping_address), ''), shipping_address),
         headteacher_name      = COALESCE(NULLIF(btrim(p_headteacher), ''), headteacher_name),
         director_name         = COALESCE(NULLIF(btrim(p_director), ''), director_name),
         updated_at            = p_at
   WHERE (id = p_school_id OR school_id = p_school_id)
     AND deleted_at IS NULL
  RETURNING id INTO v_id;

  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- Callers append the canonical SHA-256 audit_log entry in Go via audit.Append.
  RETURN true;
END
$fn$;

-- data_gaps.take: a field officer or Programme Lead becomes the responsible
-- staff member of an operating school nobody holds. Answers '' when taken,
-- 'held' when someone already holds it, 'gone' when it is no school to take.
CREATE OR REPLACE FUNCTION gateway_school_actions.take_school(
  p_school varchar, p_staff varchar, p_name varchar, p_at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_school record;
BEGIN
  SELECT s.id, s.account_owner_id, s.operational_status, s.deleted_at INTO v_school
    FROM public.school s WHERE s.id = p_school FOR UPDATE;
  IF NOT FOUND OR v_school.deleted_at IS NOT NULL THEN
    RETURN 'gone';
  END IF;
  IF COALESCE(v_school.account_owner_id, '') <> ''
     OR NOT (v_school.operational_status = ANY (ARRAY['active', 'reopened']::varchar[]))
     OR EXISTS (SELECT 1 FROM public.staff_school_assignment a WHERE a.school_id = p_school) THEN
    RETURN 'held';
  END IF;
  UPDATE public.school s
     SET account_owner_id = p_staff,
         account_owner_name_raw = COALESCE(NULLIF(p_name, ''), s.account_owner_name_raw),
         account_owner_status = 'matched', updated_at = p_at
   WHERE s.id = p_school;
  INSERT INTO public.staff_school_assignment (id, created_at, updated_at, school_id, staff_id)
  SELECT 'c' || left(replace(gen_random_uuid()::text, '-', ''), 24), p_at, p_at, p_school, p_staff
   WHERE NOT EXISTS (SELECT 1 FROM public.staff_school_assignment a WHERE a.school_id = p_school AND a.staff_id = p_staff);
  RETURN '';
END
$fn$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA gateway_school_actions FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_school_actions TO edify_gateway;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA gateway_school_actions TO edify_gateway;
