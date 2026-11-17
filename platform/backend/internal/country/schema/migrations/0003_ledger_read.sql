-- The gateway checks the applied version before serving CountryService and
-- Platform Health (it never migrates): let it read the migration ledger, as
-- field_routes and school_loans do. Without this the check fails under the
-- gateway's own role and the service stands down.
GRANT SELECT ON country_registry.schema_migration TO edify_country_rw;
