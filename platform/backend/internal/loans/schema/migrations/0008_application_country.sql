-- Edify Global (docs/migration/80-multi-country-phase-0.md §23): each school
-- loan application records the country it belongs to, and the database keeps
-- every request to its own country's applications, behind the Go checks of
-- §20 (owner, 2026-11-18: "enforce country isolation in both Go and the
-- database").
--
-- Every application already recorded is Uganda's (owner decision 2), so the
-- column is added with UG for them. A new application records its school's
-- country, or Uganda's while it is matched to no school (country.SchoolHeldIn).
ALTER TABLE school_loans.application ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX application_country ON school_loans.application (country_code);

-- Each connection carries the country its request is made in
-- (internal/countryctx, edify.read_countries): "*" for every country (the
-- Admin, a regional role, the platform's own work), a country's code, or
-- "" for none. A row of another country is neither read nor written.
ALTER TABLE school_loans.application ENABLE ROW LEVEL SECURITY;
ALTER TABLE school_loans.application FORCE ROW LEVEL SECURITY;
CREATE POLICY application_country_read ON school_loans.application
  FOR SELECT TO edify_loans_rw, edify_loans_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY application_country_add ON school_loans.application
  FOR INSERT TO edify_loans_rw, edify_loans_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY application_country_change ON school_loans.application
  FOR UPDATE TO edify_loans_rw, edify_loans_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
