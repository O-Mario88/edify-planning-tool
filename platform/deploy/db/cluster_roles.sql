-- The Cluster Leader Portal's own schema and the roles around it. Applied by
-- apply-roles.sh to a development, test or staging database; never to
-- production.
--
-- The portal's records (leadership assignments and their history; later its
-- invitations, attendance, minutes and action items) live in the schema
-- cluster_leadership, which Go owns. Nothing here touches a table, column,
-- index or constraint of the existing application's schema, and no row is
-- read or written.
--
--   edify_cluster_owner  NOLOGIN. Owns cluster_leadership and everything in
--                        it. Migrations run as this role (clusterctl migrate
--                        does SET ROLE), and it holds no privilege on any
--                        existing table, so a migration cannot change one.
--   edify_cluster_rw     NOLOGIN. The gateway's reads and writes on the
--                        portal's tables, granted table by table by the
--                        migrations themselves.
--
-- The gateway role stays read-only by default (default_transaction_read_only,
-- roles.sql): a write opens a read-write transaction on purpose, and can only
-- reach the tables edify_cluster_rw was granted.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_owner') THEN
    CREATE ROLE edify_cluster_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_cluster_rw') THEN
    CREATE ROLE edify_cluster_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS cluster_leadership AUTHORIZATION edify_cluster_owner;

-- The owner may build in its own schema only.
REVOKE ALL ON SCHEMA public FROM edify_cluster_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_cluster_owner;

-- The migrating session takes the owner's identity (SET ROLE).
GRANT edify_cluster_owner TO CURRENT_USER;

GRANT USAGE ON SCHEMA cluster_leadership TO edify_cluster_rw;
GRANT edify_cluster_rw TO edify_gateway;

-- internal/clusterlead: which clusters a leader holds, and the schools and
-- meetings of those clusters (the existing records, read only).
GRANT SELECT (
  id, name, status, cluster_type, district_id, region_id, sub_county_id,
  sub_county_name, responsible_staff_id, deleted_at
) ON cluster TO edify_gateway_ro;
GRANT SELECT (
  id, activity_type, meeting_kind, status, scheduled_date, planned_date,
  venue, cluster_id, schools_invited, attended_school_ids, deleted_at,
  activity_name_snapshot, responsible_staff_id, training_course_id
) ON activity TO edify_gateway_ro;
-- A cluster training names one of the governed courses that may be
-- delivered to a cluster (brief A4: an authoritative training selection).
GRANT SELECT (
  id, display_name, is_training_course, status, cluster_delivery_allowed,
  training_category, ssa_indicator_label
) ON activity_catalogue_item TO edify_gateway_ro;
