-- Who facilitates a planned training or meeting, changed through Go with
-- Django absent (apps.activities.services.set_facilitator). Go decides who
-- may change it, which partner and whether its day is re-priced; this
-- function makes the one write under the activity's lock. It answers 'same'
-- when the activity already has that facilitator (nothing written, as the
-- service returns early) and otherwise 'changed:<previous partner id or
-- empty>'.
--
-- The owner is a NOLOGIN role nobody is a member of. Applied by
-- apply-roles.sh and the integration TestMain. Idempotent. A new database
-- object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_activity_facilitator_owner') THEN
    CREATE ROLE edify_activity_facilitator_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_activity_facilitator_owner;
GRANT USAGE ON SCHEMA public TO edify_activity_facilitator_owner;
GRANT SELECT (id, facilitating_partner_id, deleted_at),
      UPDATE (facilitating_partner_id, updated_at)
  ON activity TO edify_activity_facilitator_owner;

CREATE SCHEMA IF NOT EXISTS gateway_activity_facilitator AUTHORIZATION edify_activity_facilitator_owner;
REVOKE ALL ON SCHEMA gateway_activity_facilitator FROM PUBLIC;

SET ROLE edify_activity_facilitator_owner;
CREATE OR REPLACE FUNCTION gateway_activity_facilitator.set(
  p_activity varchar, p_partner varchar, p_at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  previous varchar;
  wanted varchar := NULLIF(p_partner, '');
BEGIN
  SELECT a.facilitating_partner_id INTO previous FROM public.activity a
   WHERE a.id = p_activity AND a.deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'activityfacilitator: no such activity';
  END IF;
  previous := NULLIF(previous, '');
  IF previous IS NOT DISTINCT FROM wanted THEN
    RETURN 'same';
  END IF;
  UPDATE public.activity a SET facilitating_partner_id = wanted, updated_at = p_at
   WHERE a.id = p_activity;
  RETURN 'changed:' || COALESCE(previous, '');
END
$fn$;
REVOKE ALL ON FUNCTION gateway_activity_facilitator.set(varchar, varchar, timestamptz) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_activity_facilitator TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_activity_facilitator.set(varchar, varchar, timestamptz) TO edify_activities_rw;
