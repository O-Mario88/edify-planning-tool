-- Edify Global's country registry and the roles around it. Applied by
-- apply-roles.sh to a development, test or staging database; never to
-- production.
--
-- The countries, their settings, the names the existing tables give a
-- country, each school's country and each account's countries live in the
-- schema country_registry, which Go owns. Nothing here touches a table,
-- column, index or constraint of the existing application's schema: a
-- school's or an account's country is a row in country_registry, never a
-- column added to the existing table.
--
--   edify_country_owner  NOLOGIN. Owns country_registry. Migrations run as
--                        this role (schemactl migrate does SET ROLE); it holds
--                        no privilege on any existing table.
--   edify_country_rw     NOLOGIN. The gateway's reads and writes on the
--                        registry's tables, granted table by table by the
--                        migrations themselves.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_country_owner') THEN
    CREATE ROLE edify_country_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_country_rw') THEN
    CREATE ROLE edify_country_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS country_registry AUTHORIZATION edify_country_owner;

REVOKE ALL ON SCHEMA public FROM edify_country_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_country_owner;

GRANT edify_country_owner TO CURRENT_USER;

GRANT USAGE ON SCHEMA country_registry TO edify_country_rw;
GRANT edify_country_rw TO edify_gateway;
