-- The Smart Route Planner's own schema and the roles around it. Applied by
-- apply-roles.sh to a development, test or staging database; never to
-- production.
--
-- Location reports, their reviews and the verified locations live in the
-- schema field_routes, which Go owns. Nothing here touches a table, column,
-- index or constraint of the existing application's schema, and no row is
-- read or written: the existing school coordinates are never changed.
--
--   edify_routes_owner  NOLOGIN. Owns field_routes. Migrations run as this
--                       role (schemactl migrate does SET ROLE); it holds no
--                       privilege on any existing table.
--   edify_routes_rw     NOLOGIN. The gateway's reads and writes on the
--                       planner's tables, granted table by table by the
--                       migrations themselves.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_routes_owner') THEN
    CREATE ROLE edify_routes_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_routes_rw') THEN
    CREATE ROLE edify_routes_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS field_routes AUTHORIZATION edify_routes_owner;

REVOKE ALL ON SCHEMA public FROM edify_routes_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_routes_owner;

GRANT edify_routes_owner TO CURRENT_USER;

GRANT USAGE ON SCHEMA field_routes TO edify_routes_rw;
GRANT edify_routes_rw TO edify_gateway;
