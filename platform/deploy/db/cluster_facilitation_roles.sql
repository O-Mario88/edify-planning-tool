-- The partner a cluster is assigned to facilitate, saved through Go with
-- Django absent (apps.clusters.facilitation.assign_facilitator). Go decides
-- who may assign and which partner; this function makes the one write under
-- the cluster's lock: the partner, who assigned it and when (both cleared for
-- Staff). It answers 'same' when the cluster already has that facilitator
-- (nothing written, as the service returns early) and otherwise
-- 'changed:<previous partner id or empty>'.
--
-- The owner is a NOLOGIN role nobody is a member of. Applied by
-- apply-roles.sh and the integration TestMain. Idempotent. A new database
-- object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_facilitation_owner') THEN
    CREATE ROLE edify_cluster_facilitation_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_cluster_facilitation_owner;
GRANT USAGE ON SCHEMA public TO edify_cluster_facilitation_owner;
GRANT SELECT (id, facilitating_partner_id, deleted_at),
      UPDATE (facilitating_partner_id, facilitator_assigned_by, facilitator_assigned_at, updated_at)
  ON cluster TO edify_cluster_facilitation_owner;

CREATE SCHEMA IF NOT EXISTS gateway_cluster_facilitation AUTHORIZATION edify_cluster_facilitation_owner;
REVOKE ALL ON SCHEMA gateway_cluster_facilitation FROM PUBLIC;

SET ROLE edify_cluster_facilitation_owner;
CREATE OR REPLACE FUNCTION gateway_cluster_facilitation.assign(
  p_cluster varchar, p_partner varchar, p_by varchar, p_at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  previous varchar;
  wanted varchar := NULLIF(p_partner, '');
BEGIN
  SELECT c.facilitating_partner_id INTO previous FROM public.cluster c
   WHERE c.id = p_cluster AND c.deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'clusterfacilitation: no such cluster';
  END IF;
  previous := NULLIF(previous, '');
  IF previous IS NOT DISTINCT FROM wanted THEN
    RETURN 'same';
  END IF;
  UPDATE public.cluster c SET facilitating_partner_id = wanted,
    facilitator_assigned_by = CASE WHEN wanted IS NULL THEN NULL ELSE NULLIF(p_by, '') END,
    facilitator_assigned_at = CASE WHEN wanted IS NULL THEN NULL ELSE p_at END,
    updated_at = p_at
  WHERE c.id = p_cluster;
  RETURN 'changed:' || COALESCE(previous, '');
END
$fn$;
REVOKE ALL ON FUNCTION gateway_cluster_facilitation.assign(varchar, varchar, varchar, timestamptz) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_cluster_facilitation TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_cluster_facilitation.assign(varchar, varchar, varchar, timestamptz) TO edify_activities_rw;
