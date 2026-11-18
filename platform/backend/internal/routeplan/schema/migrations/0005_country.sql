-- Edify Global (docs/migration/80-multi-country-phase-0.md §24): every
-- field route record carries a country, and the database keeps each request
-- to its own country's records, behind the Go checks (owner, 2026-11-18:
-- "enforce country isolation in both Go and the database").
--
-- Every record already kept is Uganda's (owner decision 2), so the column is
-- added with UG for them. Go records a school's location report, capture
-- and location under the school's country (country.SchoolCountryCode), a
-- change under its capture's, and a field day under the country its person
-- works in, with its stops under the day's.
--
-- Each connection carries the country its request is made in
-- (internal/countryctx, edify.read_countries): "*" for every country (the
-- Admin, a regional role, the platform's own work), a country's code, or ""
-- for none. A row of another country is neither read nor written.

ALTER TABLE field_routes.location_report ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX location_report_country ON field_routes.location_report (country_code);
ALTER TABLE field_routes.location_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.location_report FORCE ROW LEVEL SECURITY;
CREATE POLICY location_report_country_read ON field_routes.location_report
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY location_report_country_add ON field_routes.location_report
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY location_report_country_change ON field_routes.location_report
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.verified_location ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX verified_location_country ON field_routes.verified_location (country_code);
ALTER TABLE field_routes.verified_location ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.verified_location FORCE ROW LEVEL SECURITY;
CREATE POLICY verified_location_country_read ON field_routes.verified_location
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY verified_location_country_add ON field_routes.verified_location
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY verified_location_country_change ON field_routes.verified_location
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.location_capture ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX location_capture_country ON field_routes.location_capture (country_code);
ALTER TABLE field_routes.location_capture ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.location_capture FORCE ROW LEVEL SECURITY;
CREATE POLICY location_capture_country_read ON field_routes.location_capture
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY location_capture_country_add ON field_routes.location_capture
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY location_capture_country_change ON field_routes.location_capture
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.school_location ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX school_location_country ON field_routes.school_location (country_code);
ALTER TABLE field_routes.school_location ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.school_location FORCE ROW LEVEL SECURITY;
CREATE POLICY school_location_country_read ON field_routes.school_location
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY school_location_country_add ON field_routes.school_location
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY school_location_country_change ON field_routes.school_location
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.location_change ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX location_change_country ON field_routes.location_change (country_code);
ALTER TABLE field_routes.location_change ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.location_change FORCE ROW LEVEL SECURITY;
CREATE POLICY location_change_country_read ON field_routes.location_change
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY location_change_country_add ON field_routes.location_change
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.field_day ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX field_day_country ON field_routes.field_day (country_code);
ALTER TABLE field_routes.field_day ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.field_day FORCE ROW LEVEL SECURITY;
CREATE POLICY field_day_country_read ON field_routes.field_day
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY field_day_country_add ON field_routes.field_day
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY field_day_country_change ON field_routes.field_day
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.field_day_stop ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX field_day_stop_country ON field_routes.field_day_stop (country_code);
ALTER TABLE field_routes.field_day_stop ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.field_day_stop FORCE ROW LEVEL SECURITY;
CREATE POLICY field_day_stop_country_read ON field_routes.field_day_stop
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY field_day_stop_country_add ON field_routes.field_day_stop
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY field_day_stop_country_change ON field_routes.field_day_stop
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
