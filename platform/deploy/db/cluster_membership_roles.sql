-- A school joining a cluster, saved through Go with Django absent
-- (apps.clusters.services.set_school_cluster_membership, the one membership
-- service every Add Schools and Add to Cluster save goes through). Go decides
-- who may add which school to which cluster; this function makes the writes
-- under the school's lock, then the cluster's, in the service's order:
--
--   * the cluster must be active, and in the school's country;
--   * an unowned cluster is claimed by the school's portfolio owner, and a
--     cluster owned by someone else refuses (the claim is undone with it);
--   * the school's cluster and status, and the quality and readiness its save
--     derives (School.recompute_quality_and_readiness), then its save signal
--     (gateway_pl_review.reconcile_school_issues);
--   * the compatibility projection (SchoolClusterAssignment), replaced;
--   * the school's sub-county declared on the cluster when it is in the
--     cluster's district (eligibility.declare_sub_county_coverage);
--   * the membership history (membership_history.sync_membership_history):
--     the open row closed and one opened for the new cluster.
--
-- It answers 'inactive', 'country' or 'other_owner' (nothing written), 'same'
-- when the school is already in that cluster, or 'joined', with the previous
-- cluster, how the cluster serves the school's district, and both districts,
-- for the audit row Go writes.
--
-- The owner is a NOLOGIN role nobody is a member of. Applied by
-- apply-roles.sh and the integration TestMain. Idempotent. A new database
-- object: production needs the owner's approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_membership_owner') THEN
    CREATE ROLE edify_cluster_membership_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_cluster_membership_owner;
GRANT USAGE ON SCHEMA public TO edify_cluster_membership_owner;
GRANT SELECT (id, deleted_at, district_id, sub_county_id, cluster_id, account_owner_id, account_owner_status,
              school_phone, primary_contact_name, enrollment, duplicate_status, current_fy_ssa_status),
      UPDATE (cluster_id, cluster_status, planning_readiness, data_quality_score, data_quality_status, updated_at)
  ON school TO edify_cluster_membership_owner;
GRANT SELECT (id, deleted_at, status, district_id, sub_county_id, responsible_staff_id),
      UPDATE (responsible_staff_id, updated_at)
  ON cluster TO edify_cluster_membership_owner;
GRANT SELECT (id, region_id) ON district TO edify_cluster_membership_owner;
GRANT SELECT (id, country) ON region TO edify_cluster_membership_owner;
GRANT SELECT (id, district_id) ON sub_county TO edify_cluster_membership_owner;
GRANT SELECT (id, cluster_id, district_id, relationship_type, active, effective_from, effective_to)
  ON cluster_service_district TO edify_cluster_membership_owner;
GRANT SELECT (id, user_id, deleted_at) ON staff_profile TO edify_cluster_membership_owner;
GRANT SELECT (school_id, staff_id) ON staff_school_assignment TO edify_cluster_membership_owner;
GRANT SELECT (school_id), DELETE, INSERT (id, created_at, updated_at, assigned_by, cluster_id, school_id)
  ON school_cluster_assignment TO edify_cluster_membership_owner;
GRANT SELECT (cluster_id, sub_county_id), INSERT (id, created_at, updated_at, cluster_id, sub_county_id)
  ON cluster_sub_county TO edify_cluster_membership_owner;
GRANT SELECT (id, school_id, cluster_id, ended_at),
      UPDATE (ended_at, ended_by, end_reason, updated_at),
      INSERT (id, created_at, updated_at, started_at, ended_at, started_by, started_by_role, ended_by, start_reason,
              end_reason, relationship_type, correlation_id, catchment_id, cluster_id, cluster_district_id, school_id,
              school_district_id)
  ON school_cluster_membership TO edify_cluster_membership_owner;
GRANT USAGE ON SCHEMA gateway_pl_review TO edify_cluster_membership_owner;
GRANT EXECUTE ON FUNCTION gateway_pl_review.reconcile_school_issues(varchar, timestamptz) TO edify_cluster_membership_owner;

CREATE SCHEMA IF NOT EXISTS gateway_cluster_membership AUTHORIZATION edify_cluster_membership_owner;
REVOKE ALL ON SCHEMA gateway_cluster_membership FROM PUBLIC;

SET ROLE edify_cluster_membership_owner;

-- The ids are Go's (cuid), so a retry names the same rows: p_assignment the
-- projection row, p_coverage the sub-county row, p_membership the history row.
CREATE OR REPLACE FUNCTION gateway_cluster_membership.join(
  p_school varchar, p_cluster varchar, p_actor varchar, p_role varchar, p_reason varchar, p_at timestamptz,
  p_today date, p_assignment varchar, p_coverage varchar, p_membership varchar, p_correlation varchar
) RETURNS TABLE (answer text, old_cluster varchar, relationship varchar, school_district varchar,
                 cluster_district varchar)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  place record;
  target record;
  served record;
  rel varchar := NULL;
  catchment varchar := NULL;
  owners varchar[] := ARRAY[]::varchar[];
  assigned varchar[];
  portfolio_owner varchar := NULL;
  variants varchar[] := ARRAY[]::varchar[];
  cluster_owner varchar;
  points integer;
  quality varchar;
  readiness varchar;
  open_row record;
  sub_district varchar;
  reason_text varchar;
BEGIN
  SELECT sc.id, sc.district_id, sc.sub_county_id, sc.cluster_id, sc.account_owner_id, sc.account_owner_status,
         sc.school_phone, sc.primary_contact_name, sc.enrollment, sc.duplicate_status, sc.current_fy_ssa_status
    INTO place FROM public.school sc WHERE sc.id = p_school AND sc.deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'clustermembership: no such school';
  END IF;
  SELECT c.id, c.status, c.deleted_at, c.district_id, c.sub_county_id, c.responsible_staff_id
    INTO target FROM public.cluster c WHERE c.id = p_cluster FOR UPDATE;
  IF NOT FOUND OR target.deleted_at IS NOT NULL OR target.status IS DISTINCT FROM 'active' THEN
    RETURN QUERY SELECT 'inactive'::text, NULL::varchar, NULL::varchar, NULL::varchar, NULL::varchar;
    RETURN;
  END IF;
  -- country_of_district: the district's region's country, Uganda by default.
  IF target.district_id IS NOT NULL AND place.district_id IS NOT NULL
     AND EXISTS (SELECT 1 FROM public.district d WHERE d.id = target.district_id)
     AND EXISTS (SELECT 1 FROM public.district d WHERE d.id = place.district_id)
     AND (SELECT btrim(COALESCE(NULLIF(r.country, ''), 'Uganda')) FROM public.district d
            LEFT JOIN public.region r ON r.id = d.region_id WHERE d.id = target.district_id)
         IS DISTINCT FROM
         (SELECT btrim(COALESCE(NULLIF(r.country, ''), 'Uganda')) FROM public.district d
            LEFT JOIN public.region r ON r.id = d.region_id WHERE d.id = place.district_id) THEN
    RETURN QUERY SELECT 'country'::text, NULL::varchar, NULL::varchar, NULL::varchar, NULL::varchar;
    RETURN;
  END IF;
  -- serving_match: the catchment row in force today, else the cluster's own district.
  IF place.district_id IS NOT NULL THEN
    SELECT s.id, s.relationship_type INTO served FROM public.cluster_service_district s
     WHERE s.cluster_id = target.id AND s.district_id = place.district_id AND s.active
       AND s.effective_from <= p_today AND (s.effective_to IS NULL OR s.effective_to >= p_today)
     ORDER BY s.relationship_type LIMIT 1;
    IF FOUND THEN
      rel := served.relationship_type;
      catchment := served.id;
    ELSIF target.district_id = place.district_id THEN
      rel := 'primary';
    END IF;
  END IF;

  -- school_owner_ids: the account owner in both id spaces, else the one
  -- staff assignment there is (two are a decision, and none is an answer).
  IF btrim(COALESCE(place.account_owner_id, '')) <> '' THEN
    owners := ARRAY[btrim(place.account_owner_id)];
  ELSE
    SELECT array_agg(a.staff_id) INTO assigned FROM (SELECT ssa.staff_id FROM public.staff_school_assignment ssa
      WHERE ssa.school_id = place.id LIMIT 2) a;
    IF COALESCE(array_length(assigned, 1), 0) = 1 AND btrim(COALESCE(assigned[1], '')) <> '' THEN
      owners := ARRAY[btrim(assigned[1])];
    END IF;
  END IF;
  IF array_length(owners, 1) = 1 THEN
    owners := owners || ARRAY(SELECT x FROM public.staff_profile sp, LATERAL unnest(ARRAY[sp.id, sp.user_id]) x
                               WHERE sp.deleted_at IS NULL AND (sp.id = owners[1] OR sp.user_id = owners[1])
                                 AND COALESCE(x, '') <> '');
    -- portfolio_owner_profile_id: the first live profile, by id.
    SELECT sp.id INTO portfolio_owner FROM public.staff_profile sp
     WHERE sp.deleted_at IS NULL AND (sp.id = ANY (owners) OR sp.user_id = ANY (owners)) ORDER BY sp.id LIMIT 1;
  END IF;
  IF portfolio_owner IS NOT NULL THEN
    variants := ARRAY[portfolio_owner] || ARRAY(SELECT x FROM public.staff_profile sp,
                                                  LATERAL unnest(ARRAY[sp.id, sp.user_id]) x
                                                 WHERE sp.deleted_at IS NULL
                                                   AND (sp.id = portfolio_owner OR sp.user_id = portfolio_owner)
                                                   AND COALESCE(x, '') <> '');
  END IF;
  cluster_owner := btrim(COALESCE(target.responsible_staff_id, ''));
  IF portfolio_owner IS NOT NULL AND cluster_owner = '' THEN
    UPDATE public.cluster c SET responsible_staff_id = portfolio_owner, updated_at = p_at WHERE c.id = target.id;
    cluster_owner := portfolio_owner;
  END IF;
  IF cluster_owner <> '' AND NOT (cluster_owner = ANY (variants)) THEN
    -- The claim above is the service's own write, undone with its refusal.
    RAISE EXCEPTION USING ERRCODE = 'P0001', MESSAGE = 'clustermembership: other_owner';
  END IF;

  -- The school's save: its cluster, then School.recompute_quality_and_readiness.
  points := 100;
  IF COALESCE(place.school_phone, '') = '' THEN points := points - 15; END IF;
  IF COALESCE(place.primary_contact_name, '') = '' THEN points := points - 15; END IF;
  IF place.enrollment IS NULL OR place.enrollment <= 0 THEN points := points - 20; END IF;
  IF COALESCE(place.account_owner_id, '') = '' OR place.account_owner_status IS DISTINCT FROM 'matched' THEN
    points := points - 20;
  END IF;
  IF place.duplicate_status = 'potential' THEN
    quality := 'Duplicate Risk';
  ELSIF points < 40 THEN
    quality := 'Missing Critical Data';
  ELSIF points >= 90 THEN
    quality := 'Clean';
  ELSIF points >= 70 THEN
    quality := 'Needs Review';
  ELSE
    quality := 'Needs Cleanup';
  END IF;
  IF place.current_fy_ssa_status IS DISTINCT FROM 'done' THEN
    readiness := 'ready_for_baseline_ssa';
  ELSE
    readiness := 'ready_for_support_planning';
  END IF;
  UPDATE public.school sc
     SET cluster_id = target.id, cluster_status = 'clustered', planning_readiness = readiness,
         data_quality_score = GREATEST(points, 0), data_quality_status = quality, updated_at = p_at
   WHERE sc.id = place.id;
  PERFORM gateway_pl_review.reconcile_school_issues(place.id, p_at);

  DELETE FROM public.school_cluster_assignment a WHERE a.school_id = place.id;
  INSERT INTO public.school_cluster_assignment (id, created_at, updated_at, assigned_by, cluster_id, school_id)
  VALUES (p_assignment, p_at, p_at, COALESCE(p_actor, ''), target.id, place.id);

  -- declare_sub_county_coverage.
  IF place.sub_county_id IS NOT NULL AND place.sub_county_id IS DISTINCT FROM target.sub_county_id
     AND NOT EXISTS (SELECT 1 FROM public.cluster_sub_county cs
                      WHERE cs.cluster_id = target.id AND cs.sub_county_id = place.sub_county_id) THEN
    SELECT s.district_id INTO sub_district FROM public.sub_county s WHERE s.id = place.sub_county_id;
    IF sub_district IS NOT NULL AND sub_district = target.district_id THEN
      INSERT INTO public.cluster_sub_county (id, created_at, updated_at, cluster_id, sub_county_id)
      VALUES (p_coverage, p_at, p_at, target.id, place.sub_county_id);
    END IF;
  END IF;

  IF place.cluster_id IS NOT DISTINCT FROM target.id THEN
    RETURN QUERY SELECT 'same'::text, place.cluster_id, rel, place.district_id, target.district_id;
    RETURN;
  END IF;
  reason_text := COALESCE(NULLIF(p_reason, ''),
                          CASE WHEN place.cluster_id IS NULL THEN 'Cluster membership added.'
                               ELSE 'Cluster membership changed.' END);
  -- sync_membership_history.
  SELECT m.id, m.cluster_id INTO open_row FROM public.school_cluster_membership m
   WHERE m.school_id = place.id AND m.ended_at IS NULL LIMIT 1 FOR UPDATE;
  IF NOT FOUND OR open_row.cluster_id IS DISTINCT FROM target.id THEN
    IF FOUND THEN
      UPDATE public.school_cluster_membership m
         SET ended_at = p_at, ended_by = COALESCE(p_actor, ''), end_reason = reason_text, updated_at = p_at
       WHERE m.id = open_row.id;
    END IF;
    INSERT INTO public.school_cluster_membership (id, created_at, updated_at, started_at, ended_at, started_by,
      started_by_role, ended_by, start_reason, end_reason, relationship_type, correlation_id, catchment_id,
      cluster_id, cluster_district_id, school_id, school_district_id)
    VALUES (p_membership, p_at, p_at, p_at, NULL, COALESCE(p_actor, ''), COALESCE(p_role, ''), '', reason_text, '',
      COALESCE(rel, ''), COALESCE(p_correlation, ''), catchment, target.id, target.district_id, place.id,
      place.district_id);
  END IF;
  RETURN QUERY SELECT 'joined'::text, place.cluster_id, rel, place.district_id, target.district_id;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_cluster_membership.join(varchar, varchar, varchar, varchar, varchar, timestamptz, date,
  varchar, varchar, varchar, varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_cluster_membership TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_cluster_membership.join(varchar, varchar, varchar, varchar, varchar, timestamptz,
  date, varchar, varchar, varchar, varchar) TO edify_activities_rw;
