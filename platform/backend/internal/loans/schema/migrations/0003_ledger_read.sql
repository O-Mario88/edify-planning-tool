-- The gateway checks the applied version before serving the portal (it
-- never migrates): let it read the migration ledger.
GRANT SELECT ON school_loans.schema_migration TO edify_loans_rw;
