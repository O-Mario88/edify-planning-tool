\set ON_ERROR_STOP on

-- Run with psql against the APPLICATION database, never defaultdb:
--   psql "$ADMIN_DATABASE_URL" \
--     --set=expected_database=edify \
--     --set=runtime_role=edify_runtime \
--     --set=owner_role=doadmin \
--     --file=scripts/configure_runtime_database_role.sql
-- The managed provider creates the login and password; this script grants only
-- the least privileges needed by the web and scheduler processes.

SELECT current_database() = :'expected_database' AS database_is_expected \gset
\if :database_is_expected
\else
  \echo 'REFUSED: connected database does not match expected_database'
  -- ON_ERROR_STOP turns this deliberate assertion failure into a non-zero
  -- psql exit on versions where \quit does not accept an exit-code argument.
  SELECT 1 / 0 AS connected_to_the_wrong_database;
\endif

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'expected_database', :'runtime_role') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'runtime_role') \gexec
SELECT format(
  'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
  :'runtime_role'
) \gexec
SELECT format(
  'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I',
  :'runtime_role'
) \gexec

-- Future Django migrations are owned by the administrative migration role.
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'owner_role', :'runtime_role'
) \gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
  'GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
  :'owner_role', :'runtime_role'
) \gexec

-- Managed PgBouncer rejects libpq's generic startup-options parameter. These
-- role defaults preserve the same fail-safe ceilings on every pooled session.
SELECT format('ALTER ROLE %I SET statement_timeout = %L', :'runtime_role', '30s') \gexec
SELECT format('ALTER ROLE %I SET lock_timeout = %L', :'runtime_role', '10s') \gexec
SELECT format(
  'ALTER ROLE %I SET idle_in_transaction_session_timeout = %L',
  :'runtime_role', '60s'
) \gexec

SELECT current_user AS configured_by,
       current_database() AS configured_database,
       :'runtime_role' AS configured_role;
