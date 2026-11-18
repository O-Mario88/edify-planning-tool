-- Edify Global, Phase 3 (docs/migration/80-multi-country-phase-0.md §12):
-- the roles an account holds in a country, and the scope each one has there.
--
-- Where a country's roles come from. Uganda's come from the account's
-- profile in the existing application, exactly as today, and are never
-- recorded here. Every other country's come from this registry: an account
-- works there only in the roles an Admin assigned it there. Every country
-- already registered keeps the existing behaviour when this migration runs
-- (the column is added with that value); the legacy seed then moves the
-- countries that are not Active to the registry, and any country added
-- later starts there.
ALTER TABLE country_registry.country ADD COLUMN roles_source text NOT NULL DEFAULT 'existing_profile'
  CHECK (roles_source IN ('existing_profile', 'registry'));
ALTER TABLE country_registry.country ALTER COLUMN roles_source SET DEFAULT 'registry';

-- A role assignment names its membership together with that membership's
-- country and account, so the table itself refuses a role filed against a
-- membership of another country or another account.
CREATE UNIQUE INDEX country_membership_identity ON country_registry.country_membership (id, country_id, user_id);

-- One role an account holds in a country, under one membership. Its dates
-- are the membership's: it applies while the membership is in force and the
-- country is Active. The scope is the role's kind of scope (country-wide,
-- named regions, or the account's own portfolio); a regional role names the
-- existing regions it covers. Nothing is rewritten: a revoked role keeps who
-- assigned it, who revoked it and why.
CREATE TABLE country_registry.country_role_assignment (
  id uuid PRIMARY KEY,
  membership_id uuid NOT NULL,
  country_id uuid NOT NULL,
  -- The existing account id.
  user_id varchar(30) NOT NULL,
  -- A role the existing application defines (its EdifyRole values).
  role_name varchar(64) NOT NULL CHECK (role_name <> ''),
  scope_type text NOT NULL CHECK (scope_type IN ('country', 'regions', 'portfolio')),
  -- The existing region ids a regional role covers; empty otherwise.
  region_ids text[] NOT NULL DEFAULT '{}',
  granted_by varchar(30) NOT NULL,
  grant_reason text NOT NULL CHECK (grant_reason <> ''),
  granted_at timestamptz NOT NULL DEFAULT now(),
  revoked_by varchar(30),
  revoked_at timestamptz,
  revoke_reason text,
  FOREIGN KEY (membership_id, country_id, user_id)
    REFERENCES country_registry.country_membership (id, country_id, user_id),
  CHECK ((scope_type = 'regions') = (cardinality(region_ids) > 0)),
  CHECK ((revoked_at IS NULL) = (revoked_by IS NULL)),
  CHECK ((revoked_at IS NULL) = (revoke_reason IS NULL) AND revoke_reason <> '')
);
CREATE UNIQUE INDEX country_role_assignment_once ON country_registry.country_role_assignment (membership_id, role_name)
  WHERE revoked_at IS NULL;
CREATE INDEX country_role_assignment_by_user ON country_registry.country_role_assignment (user_id);

GRANT SELECT, INSERT, UPDATE ON country_registry.country_role_assignment TO edify_country_rw;

-- Row-level security as on the other registry tables (0002): read by the
-- registry's roles, written only for a country the transaction declares.
ALTER TABLE country_registry.country_role_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_role_assignment FORCE ROW LEVEL SECURITY;
CREATE POLICY country_role_read ON country_registry.country_role_assignment
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY country_role_add ON country_registry.country_role_assignment
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY country_role_change ON country_registry.country_role_assignment
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
