-- Edify Global, Phase 1 (docs/migration/80-multi-country-phase-0.md, §3):
-- the countries the platform serves and each one's settings. One codebase,
-- one set of programmes and roles; a country differs only by what is
-- recorded here and by the data that belongs to it.

-- A country: a stable two-letter code (UG, KE, RW, ET) with an immutable
-- internal id behind it. Registering a country does not make it
-- operational: only an Active country is worked in.
CREATE TABLE country_registry.country (
  id uuid PRIMARY KEY,
  code varchar(2) NOT NULL UNIQUE CHECK (code ~ '^[A-Z]{2}$'),
  name text NOT NULL CHECK (name <> ''),
  state text NOT NULL DEFAULT 'draft'
    CHECK (state IN ('draft', 'validated', 'ready_for_pilot', 'active', 'suspended', 'archived')),
  activated_on date,
  -- Where the country's data-residency assessment is recorded, once made.
  residency_policy text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by varchar(30) NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by varchar(30) NOT NULL,
  CHECK (state <> 'active' OR activated_on IS NOT NULL)
);

-- A country's settings, versioned and effective-dated, so a report for a
-- period reads the settings that applied in it and a change never rewrites
-- history. Money is stored in whole units of minor_units decimals.
CREATE TABLE country_registry.country_config_version (
  id uuid PRIMARY KEY,
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  version integer NOT NULL CHECK (version > 0),
  default_language text NOT NULL,
  languages text[] NOT NULL,
  currency_code varchar(3) NOT NULL CHECK (currency_code ~ '^[A-Z]{3}$'),
  currency_minor_units smallint NOT NULL CHECK (currency_minor_units BETWEEN 0 AND 3),
  time_zone text NOT NULL,
  date_format text NOT NULL,
  calendars text[] NOT NULL DEFAULT '{gregorian}',
  fy_start_month smallint NOT NULL CHECK (fy_start_month BETWEEN 1 AND 12),
  effective_from date NOT NULL,
  effective_until date,
  changed_by varchar(30) NOT NULL,
  change_reason text NOT NULL CHECK (change_reason <> ''),
  approved_by varchar(30),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (country_id, version),
  CHECK (effective_until IS NULL OR effective_until > effective_from),
  CHECK (default_language = ANY (languages))
);

-- The names the existing tables already give a country (the free-text
-- 'Uganda' of region, staff_profile and others; the country_id strings of
-- the planning and HR tables), each read through the registry without
-- rewriting a row.
CREATE TABLE country_registry.country_alias (
  alias text PRIMARY KEY CHECK (alias <> ''),
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by varchar(30) NOT NULL
);

-- Which country a school belongs to, set explicitly (a legacy mapping, an
-- import or an assignment), never inferred from its address. Effective-dated:
-- a school's history is kept when it moves.
CREATE TABLE country_registry.school_country (
  -- The existing school.id.
  school_id varchar(30) NOT NULL,
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  effective_from date NOT NULL,
  effective_until date,
  source text NOT NULL CHECK (source IN ('legacy_uganda', 'import', 'assignment')),
  recorded_by varchar(30) NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (school_id, effective_from),
  CHECK (effective_until IS NULL OR effective_until > effective_from)
);

CREATE INDEX school_country_by_country ON country_registry.school_country (country_id, school_id);

-- Which countries an account may work in. A membership is explicit and
-- effective-dated; it is not access to every record of the country: the
-- account's role, scope and portfolio still decide that.
CREATE TABLE country_registry.country_membership (
  id uuid PRIMARY KEY,
  -- The existing account id.
  user_id varchar(30) NOT NULL,
  country_id uuid NOT NULL REFERENCES country_registry.country (id),
  is_default boolean NOT NULL DEFAULT false,
  effective_from date NOT NULL,
  effective_until date,
  granted_by varchar(30) NOT NULL,
  grant_reason text NOT NULL CHECK (grant_reason <> ''),
  granted_at timestamptz NOT NULL DEFAULT now(),
  revoked_by varchar(30),
  revoked_at timestamptz,
  CHECK (effective_until IS NULL OR effective_until > effective_from),
  CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
);

CREATE UNIQUE INDEX country_membership_once ON country_registry.country_membership (user_id, country_id, effective_from);
CREATE INDEX country_membership_by_user ON country_registry.country_membership (user_id);

GRANT SELECT, INSERT, UPDATE ON country_registry.country, country_registry.country_config_version,
  country_registry.country_alias, country_registry.school_country, country_registry.country_membership
  TO edify_country_rw;
