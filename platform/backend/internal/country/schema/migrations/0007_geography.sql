-- Edify Global, Phase 2 (docs/migration/80-multi-country-phase-0.md §3,
-- §25): the geographic registry. Each country names its own levels of
-- administrative units (Uganda: region, sub-region, district, county,
-- sub-county, parish, village; another country its own), and its units
-- form one tree per country.
--
-- Uganda's existing units are mapped in by id (existing_table, existing_id),
-- never copied over them or rewritten: the existing tables stay what the
-- existing application reads and writes, and the registry points at them.
-- A unit and its parent, a unit and its type, and both ends of a
-- relationship always belong to the same country (the composite keys).
-- Go refuses a parent chain or relationship that would loop.
--
-- Every row is readable, as the registry's other reference data is (0002):
-- the clauses that place a school or a record read it. A country's rows
-- are written only by a write declared for that country
-- (edify.write_countries, country.WriteFor).

CREATE TABLE country_registry.admin_unit_type (
  id uuid PRIMARY KEY,
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  -- What the level is, the same word in every country (district,
  -- province, ward), and what the country calls it.
  canonical_type text NOT NULL CHECK (canonical_type ~ '^[a-z][a-z_]*$'),
  local_label text NOT NULL CHECK (btrim(local_label) <> ''),
  -- 1 is the top level; each lower level has a higher number.
  level smallint NOT NULL CHECK (level BETWEEN 1 AND 12),
  is_required boolean NOT NULL DEFAULT false,
  effective_from date NOT NULL,
  effective_to date,
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, country_id),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);
-- One live type per word and per level in a country.
CREATE UNIQUE INDEX admin_unit_type_one_live
  ON country_registry.admin_unit_type (country_id, canonical_type) WHERE effective_to IS NULL;
CREATE UNIQUE INDEX admin_unit_type_level_live
  ON country_registry.admin_unit_type (country_id, level) WHERE effective_to IS NULL;

CREATE TABLE country_registry.admin_unit (
  id uuid PRIMARY KEY,
  country_id uuid NOT NULL,
  type_id uuid NOT NULL,
  official_name text NOT NULL CHECK (btrim(official_name) <> ''),
  -- Language code to name, for the languages the country supports.
  localized_names jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(localized_names) = 'object'),
  official_code text CHECK (official_code IS NULL OR btrim(official_code) <> ''),
  parent_id uuid,
  valid_from date NOT NULL,
  valid_to date,
  source text NOT NULL CHECK (source IN ('existing_table', 'import', 'manual')),
  verification_status text NOT NULL CHECK (verification_status IN ('verified', 'unverified', 'rejected')),
  -- The existing application's row this unit is, for Uganda's units.
  existing_table text CHECK (existing_table IN ('region', 'sub_region', 'district', 'county', 'sub_county', 'parish', 'village')),
  existing_id varchar(30),
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, country_id),
  FOREIGN KEY (type_id, country_id) REFERENCES country_registry.admin_unit_type (id, country_id),
  FOREIGN KEY (parent_id, country_id) REFERENCES country_registry.admin_unit (id, country_id),
  CHECK ((existing_table IS NULL) = (existing_id IS NULL)),
  CHECK ((source = 'existing_table') = (existing_table IS NOT NULL)),
  CHECK (parent_id IS NULL OR parent_id <> id),
  CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX admin_unit_existing
  ON country_registry.admin_unit (existing_table, existing_id) WHERE existing_table IS NOT NULL;
CREATE UNIQUE INDEX admin_unit_code
  ON country_registry.admin_unit (country_id, type_id, official_code) WHERE official_code IS NOT NULL;
CREATE INDEX admin_unit_parent ON country_registry.admin_unit (parent_id);
CREATE INDEX admin_unit_by_type ON country_registry.admin_unit (country_id, type_id, official_name);

-- Ties between units that are not the tree: a cluster's units, a former
-- district split in two, an education zone over several districts.
CREATE TABLE country_registry.admin_unit_relationship (
  id uuid PRIMARY KEY,
  country_id uuid NOT NULL,
  from_unit_id uuid NOT NULL,
  to_unit_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind ~ '^[a-z][a-z_]*$'),
  effective_from date NOT NULL,
  effective_to date,
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (from_unit_id, country_id) REFERENCES country_registry.admin_unit (id, country_id),
  FOREIGN KEY (to_unit_id, country_id) REFERENCES country_registry.admin_unit (id, country_id),
  CHECK (from_unit_id <> to_unit_id),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);
CREATE UNIQUE INDEX admin_unit_relationship_one_live
  ON country_registry.admin_unit_relationship (from_unit_id, to_unit_id, kind) WHERE effective_to IS NULL;
CREATE INDEX admin_unit_relationship_to ON country_registry.admin_unit_relationship (to_unit_id);

GRANT SELECT, INSERT, UPDATE ON country_registry.admin_unit_type TO edify_country_rw;
GRANT SELECT, INSERT, UPDATE ON country_registry.admin_unit TO edify_country_rw;
GRANT SELECT, INSERT, UPDATE ON country_registry.admin_unit_relationship TO edify_country_rw;

ALTER TABLE country_registry.admin_unit_type ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.admin_unit_type FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.admin_unit ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.admin_unit FORCE ROW LEVEL SECURITY;
ALTER TABLE country_registry.admin_unit_relationship ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.admin_unit_relationship FORCE ROW LEVEL SECURITY;

CREATE POLICY admin_unit_type_read ON country_registry.admin_unit_type
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY admin_unit_type_add ON country_registry.admin_unit_type
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY admin_unit_type_change ON country_registry.admin_unit_type
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));

CREATE POLICY admin_unit_read ON country_registry.admin_unit
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY admin_unit_add ON country_registry.admin_unit
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY admin_unit_change ON country_registry.admin_unit
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));

CREATE POLICY admin_unit_relationship_read ON country_registry.admin_unit_relationship
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY admin_unit_relationship_add ON country_registry.admin_unit_relationship
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY admin_unit_relationship_change ON country_registry.admin_unit_relationship
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
