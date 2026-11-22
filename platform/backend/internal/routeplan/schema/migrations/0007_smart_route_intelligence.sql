-- Smart Route Planner enterprise intelligence tables (Section 13):
-- Route Plans, versioned Route Stops (linked to authoritative planned_activity_id),
-- Route Calculations (provider/version/fallback audit), and Staff Road
-- Condition Reports (verified/unverified/expired road hazards).
-- Append/update only (zero DELETE); all tables live inside field_routes with
-- country RLS; public tables are never referenced by foreign keys or mutated.

CREATE TABLE field_routes.route_plan (
  route_id uuid PRIMARY KEY,
  user_id varchar(30) NOT NULL,
  day date NOT NULL,
  country_code text NOT NULL DEFAULT 'UG' CHECK (country_code ~ '^[A-Z]{2}$'),
  financial_year varchar(16) NOT NULL DEFAULT '',
  start_lat double precision,
  start_lng double precision,
  start_label text NOT NULL DEFAULT '',
  end_lat double precision,
  end_lng double precision,
  end_label text NOT NULL DEFAULT '',
  transport_mode varchar(24) NOT NULL DEFAULT 'DRIVE'
    CHECK (transport_mode IN ('DRIVE', 'TWO_WHEELER', 'WALK')),
  optimization_mode varchar(32) NOT NULL DEFAULT 'balanced'
    CHECK (optimization_mode IN ('fastest', 'shortest', 'max_schools', 'priority_schools', 'balanced', 'as_given')),
  route_status varchar(24) NOT NULL DEFAULT 'saved'
    CHECK (route_status IN ('draft', 'saved', 'in_progress', 'completed', 'stale')),
  estimated_meters bigint NOT NULL DEFAULT 0,
  estimated_seconds bigint NOT NULL DEFAULT 0,
  visit_minutes integer NOT NULL DEFAULT 0,
  field_minutes integer NOT NULL DEFAULT 0,
  provider varchar(32) NOT NULL DEFAULT 'none',
  routing_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  route_version integer NOT NULL DEFAULT 1,
  calculated_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, day)
);

CREATE INDEX route_plan_country_day_idx ON field_routes.route_plan (country_code, day);

CREATE TABLE field_routes.route_stop (
  route_id uuid NOT NULL REFERENCES field_routes.route_plan (route_id),
  route_version integer NOT NULL DEFAULT 1 CHECK (route_version >= 1),
  stop_sequence integer NOT NULL CHECK (stop_sequence >= 1),
  planned_activity_id varchar(64) NOT NULL DEFAULT '',
  school_id varchar(64) NOT NULL,
  arrival_estimate varchar(10) NOT NULL DEFAULT '',
  departure_estimate varchar(10) NOT NULL DEFAULT '',
  visit_minutes integer NOT NULL DEFAULT 60,
  leg_meters bigint NOT NULL DEFAULT 0,
  leg_seconds bigint NOT NULL DEFAULT 0,
  road_available boolean NOT NULL DEFAULT false,
  completion_status varchar(32) NOT NULL DEFAULT 'planned',
  ssa_priority_band varchar(24) NOT NULL DEFAULT '',
  ssa_priority_score double precision NOT NULL DEFAULT 0,
  country_code text NOT NULL DEFAULT 'UG' CHECK (country_code ~ '^[A-Z]{2}$'),
  PRIMARY KEY (route_id, route_version, stop_sequence)
);

CREATE INDEX route_stop_school_idx ON field_routes.route_stop (country_code, school_id);

CREATE TABLE field_routes.route_calculation (
  calculation_id uuid PRIMARY KEY,
  route_id uuid REFERENCES field_routes.route_plan (route_id),
  user_id varchar(30) NOT NULL,
  day date NOT NULL,
  route_version integer NOT NULL DEFAULT 1,
  provider varchar(32) NOT NULL DEFAULT 'none',
  input_hash varchar(64) NOT NULL DEFAULT '',
  alternatives_count integer NOT NULL DEFAULT 0,
  constraints jsonb NOT NULL DEFAULT '{}'::jsonb,
  result_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  fallback_status varchar(48) NOT NULL DEFAULT 'none',
  calculated_at timestamptz NOT NULL DEFAULT now(),
  country_code text NOT NULL DEFAULT 'UG' CHECK (country_code ~ '^[A-Z]{2}$')
);

CREATE INDEX route_calculation_user_day_idx ON field_routes.route_calculation (country_code, user_id, day, calculated_at DESC);

CREATE TABLE field_routes.road_condition_report (
  id uuid PRIMARY KEY,
  road_name text NOT NULL,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  radius_m integer NOT NULL DEFAULT 1500 CHECK (radius_m BETWEEN 100 AND 25000),
  category varchar(32) NOT NULL
    CHECK (category IN (
      'road_closed', 'road_flooded', 'bridge_damaged',
      'under_construction', 'poor_condition', 'severe_congestion', 'road_reopened'
    )),
  source varchar(32) NOT NULL DEFAULT 'staff_report'
    CHECK (source IN ('staff_report', 'official_notice', 'provider_feed')),
  verification_status varchar(24) NOT NULL DEFAULT 'unverified'
    CHECK (verification_status IN ('unverified', 'verified', 'expired', 'resolved')),
  impact_level varchar(24) NOT NULL DEFAULT 'delay'
    CHECK (impact_level IN ('advisory', 'delay', 'impassable')),
  notes text NOT NULL DEFAULT '',
  reported_by varchar(30) NOT NULL,
  reported_by_name text NOT NULL DEFAULT '',
  reported_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  reviewed_by varchar(30) NOT NULL DEFAULT '',
  reviewed_at timestamptz,
  country_code text NOT NULL DEFAULT 'UG' CHECK (country_code ~ '^[A-Z]{2}$')
);

CREATE INDEX road_condition_country_status_idx
  ON field_routes.road_condition_report (country_code, verification_status, expires_at DESC);

CREATE INDEX road_condition_gist_point_idx
  ON field_routes.road_condition_report USING gist (point(lng, lat));

-- Row-level country isolation matching 0005_country.sql.
ALTER TABLE field_routes.route_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.route_plan FORCE ROW LEVEL SECURITY;
CREATE POLICY route_plan_country_read ON field_routes.route_plan
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_plan_country_add ON field_routes.route_plan
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_plan_country_change ON field_routes.route_plan
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.route_stop ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.route_stop FORCE ROW LEVEL SECURITY;
CREATE POLICY route_stop_country_read ON field_routes.route_stop
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_stop_country_add ON field_routes.route_stop
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_stop_country_change ON field_routes.route_stop
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.route_calculation ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.route_calculation FORCE ROW LEVEL SECURITY;
CREATE POLICY route_calculation_country_read ON field_routes.route_calculation
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_calculation_country_add ON field_routes.route_calculation
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY route_calculation_country_change ON field_routes.route_calculation
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE field_routes.road_condition_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_routes.road_condition_report FORCE ROW LEVEL SECURITY;
CREATE POLICY road_condition_country_read ON field_routes.road_condition_report
  FOR SELECT TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY road_condition_country_add ON field_routes.road_condition_report
  FOR INSERT TO edify_routes_rw, edify_routes_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY road_condition_country_change ON field_routes.road_condition_report
  FOR UPDATE TO edify_routes_rw, edify_routes_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

GRANT SELECT, INSERT, UPDATE ON field_routes.route_plan TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.route_stop TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.route_calculation TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.road_condition_report TO edify_routes_rw;
