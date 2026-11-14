-- The gateway checks the applied version before serving Verify Location and
-- offline capture (it never migrates): let it read the migration ledger.
-- Without this the check failed under the gateway's own role and both
-- features stood down (found by Platform Health, 2026-11-14).
GRANT SELECT ON field_routes.schema_migration TO edify_routes_rw;
