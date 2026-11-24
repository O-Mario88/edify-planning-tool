-- A cluster created through Go with Django absent (create_cluster_view and
-- apps.clusters.services.create_cluster). Go decides who may create where and
-- checks the district, the sub-counties and the name; this function makes the
-- writes in one transaction: the cluster (its first sub-county the primary
-- one), a coverage row per sub-county, and the PRIMARY catchment row the
-- cluster's save signal adds (apps.clusters.signals.keep_primary_catchment,
-- catchment.ensure_primary_catchment). A new cluster has no catchment row to
-- end, so that half of the helper never runs here.
--
-- The owner is a NOLOGIN role nobody is a member of. Applied by
-- apply-roles.sh and the integration TestMain. Idempotent. A new database
-- object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_create_owner') THEN
    CREATE ROLE edify_cluster_create_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_cluster_create_owner;
GRANT USAGE ON SCHEMA public TO edify_cluster_create_owner;
GRANT INSERT (created_at, updated_at, deleted_at, id, name, sub_county_name, cluster_type, status, override_reason,
              responsible_staff_id, cluster_leader_name, cluster_leader_phone, district_id, region_id, sub_county_id,
              environment, source, facilitating_partner_id, facilitator_assigned_at, facilitator_assigned_by)
  ON cluster TO edify_cluster_create_owner;
GRANT SELECT (id, name) ON sub_county TO edify_cluster_create_owner;
GRANT INSERT (id, created_at, updated_at, cluster_id, sub_county_id) ON cluster_sub_county TO edify_cluster_create_owner;
GRANT INSERT (id, created_at, updated_at, relationship_type, reason, effective_from, effective_to, active, created_by,
              approved_by, approved_at, ended_by, ended_reason, cluster_id, district_id)
  ON cluster_service_district TO edify_cluster_create_owner;

CREATE SCHEMA IF NOT EXISTS gateway_cluster_create AUTHORIZATION edify_cluster_create_owner;
REVOKE ALL ON SCHEMA gateway_cluster_create FROM PUBLIC;

SET ROLE edify_cluster_create_owner;

-- p_subs are the sub-county ids in the order chosen (the first is primary),
-- p_sub_rows the coverage rows' ids beside them; Go makes every id (cuid).
CREATE OR REPLACE FUNCTION gateway_cluster_create.create(
  p_id varchar, p_name varchar, p_region varchar, p_district varchar, p_subs varchar[], p_sub_rows varchar[],
  p_type varchar, p_owner varchar, p_leader_name varchar, p_leader_phone varchar, p_at timestamptz, p_today date,
  p_catchment varchar
) RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  primary_name varchar := NULL;
BEGIN
  IF COALESCE(array_length(p_subs, 1), 0) <> COALESCE(array_length(p_sub_rows, 1), 0) THEN
    RAISE EXCEPTION 'clustercreate: a coverage row id per sub-county';
  END IF;
  IF COALESCE(array_length(p_subs, 1), 0) > 0 THEN
    SELECT s.name INTO primary_name FROM public.sub_county s WHERE s.id = p_subs[1];
  END IF;
  INSERT INTO public.cluster (created_at, updated_at, deleted_at, id, name, sub_county_name, cluster_type, status,
    override_reason, responsible_staff_id, cluster_leader_name, cluster_leader_phone, district_id, region_id,
    sub_county_id, environment, source, facilitating_partner_id, facilitator_assigned_at, facilitator_assigned_by)
  VALUES (p_at, p_at, NULL, p_id, p_name, primary_name, p_type, 'active', NULL, p_owner, p_leader_name,
    p_leader_phone, p_district, p_region, p_subs[1], 'production', 'manual_upload', NULL, NULL, NULL);
  INSERT INTO public.cluster_sub_county (id, created_at, updated_at, cluster_id, sub_county_id)
  SELECT r.row_id, p_at, p_at, p_id, r.sub_id
    FROM unnest(p_subs, p_sub_rows) AS r(sub_id, row_id);
  INSERT INTO public.cluster_service_district (id, created_at, updated_at, relationship_type, reason, effective_from,
    effective_to, active, created_by, approved_by, approved_at, ended_by, ended_reason, cluster_id, district_id)
  VALUES (p_catchment, p_at, p_at, 'primary', 'The cluster''s own district.', p_today, NULL, TRUE, 'system', 'system',
    p_at, '', '', p_id, p_district);
END
$fn$;
REVOKE ALL ON FUNCTION gateway_cluster_create.create(varchar, varchar, varchar, varchar, varchar[], varchar[], varchar,
  varchar, varchar, varchar, timestamptz, date, varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_cluster_create TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_cluster_create.create(varchar, varchar, varchar, varchar, varchar[], varchar[],
  varchar, varchar, varchar, varchar, timestamptz, date, varchar) TO edify_activities_rw;
