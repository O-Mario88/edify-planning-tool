-- Edify Global, Phase 3 (docs/migration/80-multi-country-phase-0.md §17):
-- which countries each partner organisation works in. The existing partner
-- table has no country; a partner's country is a row here, never a new
-- column on it, as a school's is (school_country).
--
-- A partner may work in more than one country, each with its own dates.
-- The legacy seed records every existing partner in Uganda; a partner the
-- existing application creates afterwards has no row and is read as
-- Uganda's (country.PartnerIn), since that application serves Uganda alone.
CREATE TABLE country_registry.partner_country (
  -- The existing partner.id.
  partner_id varchar(30) NOT NULL,
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  effective_from date NOT NULL,
  effective_until date,
  source text NOT NULL CHECK (source IN ('legacy_uganda', 'import', 'assignment')),
  recorded_by varchar(30) NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (partner_id, country_id, effective_from),
  CHECK (effective_until IS NULL OR effective_until > effective_from)
);

CREATE INDEX partner_country_by_country ON country_registry.partner_country (country_id, partner_id);

GRANT SELECT, INSERT, UPDATE ON country_registry.partner_country TO edify_country_rw;

-- Row-level security as on the other registry tables (0002): read by the
-- registry's roles, written only for a country the transaction declares.
ALTER TABLE country_registry.partner_country ENABLE ROW LEVEL SECURITY;
ALTER TABLE country_registry.partner_country FORCE ROW LEVEL SECURITY;
CREATE POLICY partner_country_read ON country_registry.partner_country
  FOR SELECT TO edify_country_rw, edify_country_owner USING (true);
CREATE POLICY partner_country_add ON country_registry.partner_country
  FOR INSERT TO edify_country_rw, edify_country_owner
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
CREATE POLICY partner_country_change ON country_registry.partner_country
  FOR UPDATE TO edify_country_rw, edify_country_owner
  USING (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')))
  WITH CHECK (country_id::text = ANY(string_to_array(current_setting('edify.write_countries', true), ',')));
