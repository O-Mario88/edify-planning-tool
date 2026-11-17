-- Edify Global, Phase 1 (docs/migration/80-multi-country-phase-0.md §8):
-- row-level security on the registry, forced so that it binds the owner as
-- well as the gateway. Superusers are not bound by it; no service runs as one.
--
-- Reading stays open to the registry's roles. A reader's and a school's
-- country are resolved from these rows before any country is known, and the
-- resolution falls back to the region or the profile only where a row is
-- absent: hiding another country's rows there would turn "not yours" into
-- "no country recorded" and fail open.
--
-- Writing is keyed. A session declares, inside its transaction, the
-- countries it writes for (edify.write_countries, registry ids separated by
-- commas) and whether it may change the countries themselves
-- (edify.platform_write = 'on'). A row of any other country is refused, and
-- a session that declares nothing writes nothing.

ALTER TABLE country_registry.country ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_alias ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_alias FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_config_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_config_version FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.school_country ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.school_country FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.country_membership FORCE ROW LEVEL SECURITY;

-- The countries and their names: read by everyone the registry serves,
-- written only by a platform session.
CREATE POLICY country_read ON country_registry.country
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY country_add ON country_registry.country
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (current_setting('edify.platform_write', true) = 'on');
CREATE POLICY country_change ON country_registry.country
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (current_setting('edify.platform_write', true) = 'on')
  WITH CHECK (current_setting('edify.platform_write', true) = 'on');

CREATE POLICY country_alias_read ON country_registry.country_alias
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY country_alias_add ON country_registry.country_alias
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (current_setting('edify.platform_write', true) = 'on');
CREATE POLICY country_alias_change ON country_registry.country_alias
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (current_setting('edify.platform_write', true) = 'on')
  WITH CHECK (current_setting('edify.platform_write', true) = 'on');

-- A country's settings, schools and members: written only for a country
-- the session declares.
CREATE POLICY country_config_read ON country_registry.country_config_version
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY country_config_add ON country_registry.country_config_version
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY country_config_change ON country_registry.country_config_version
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));

CREATE POLICY school_country_read ON country_registry.school_country
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY school_country_add ON country_registry.school_country
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY school_country_change ON country_registry.school_country
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));

CREATE POLICY country_membership_read ON country_registry.country_membership
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY country_membership_add ON country_registry.country_membership
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY country_membership_change ON country_registry.country_membership
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
