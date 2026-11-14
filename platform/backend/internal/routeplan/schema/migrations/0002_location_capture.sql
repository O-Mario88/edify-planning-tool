-- Offline school GPS capture (owner brief 2026-11-14): every capture, report
-- or "the location is correct" answer from the field, keyed by the id the
-- device gave it so a retried sync never files twice; the school's current
-- location (and its entrance) with a version; and one row per accepted
-- change, which is both the audit history and the durable "school location
-- updated" event. The existing application's coordinates are never written.
--
-- location_report and verified_location (0001) stay as they are: history of
-- the first reports and, for the planner, a version-1 location until a
-- capture replaces it.

CREATE TABLE field_routes.location_capture (
  -- The device's capture id (its idempotency key).
  id uuid PRIMARY KEY,
  school_id varchar(30) NOT NULL,
  school_code varchar(64) NOT NULL DEFAULT '',
  -- The school itself or its entrance / road access point.
  target text NOT NULL CHECK (target IN ('school', 'entrance')),
  -- new: the school had no usable point; correction: replaces one;
  -- confirm: the visitor said the point on record is right.
  kind text NOT NULL CHECK (kind IN ('new', 'correction', 'confirm')),
  point_source text NOT NULL CHECK (point_source IN ('none', 'typed', 'device')),
  lat double precision,
  lng double precision,
  -- What the device reported: its accuracy radius, when the fix was taken,
  -- how many readings were taken and how far apart they were.
  accuracy_m double precision,
  captured_at timestamptz,
  sample_count integer NOT NULL DEFAULT 0,
  spread_m double precision,
  received_at timestamptz NOT NULL,
  -- The location version the device knew, and the point it showed.
  base_version integer NOT NULL DEFAULT 0,
  previous_lat double precision,
  previous_lng double precision,
  previous_status text NOT NULL DEFAULT '',
  displacement_m double precision,
  reason text NOT NULL DEFAULT '',
  access_note text NOT NULL DEFAULT '',
  -- Why it waits for review (large_move, accuracy_fair, version_conflict ...).
  flags text[] NOT NULL DEFAULT '{}',
  -- accepted: by the policy at once; pending: waits for review; approved /
  -- rejected: reviewed; noted: a confirmation, which moves nothing.
  status text NOT NULL CHECK (status IN ('accepted', 'pending', 'approved', 'rejected', 'noted')),
  captured_by varchar(30) NOT NULL,
  captured_role text NOT NULL,
  reviewed_by varchar(30),
  reviewed_role text,
  reviewed_at timestamptz,
  review_note text NOT NULL DEFAULT '',
  -- The location version this capture made, once accepted or approved.
  result_version integer,
  CHECK ((lat IS NULL) = (lng IS NULL)),
  CHECK (kind = 'confirm' OR lat IS NOT NULL OR status IN ('pending', 'rejected')),
  CHECK (reviewed_by IS NULL OR reviewed_by <> captured_by)
);

CREATE INDEX location_capture_school ON field_routes.location_capture (school_id, target, received_at);
CREATE INDEX location_capture_pending ON field_routes.location_capture (received_at) WHERE status = 'pending';

-- The current location of a school (target school) and of its entrance.
CREATE TABLE field_routes.school_location (
  school_id varchar(30) NOT NULL,
  target text NOT NULL CHECK (target IN ('school', 'entrance')),
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  accuracy_m double precision,
  access_note text NOT NULL DEFAULT '',
  version integer NOT NULL CHECK (version > 0),
  capture_id uuid NOT NULL REFERENCES field_routes.location_capture (id),
  verified_by varchar(30) NOT NULL,
  verified_at timestamptz NOT NULL,
  PRIMARY KEY (school_id, target)
);

-- One row per accepted change: the history, and the event clients and the
-- planner read to refresh (one per school, target and version).
CREATE TABLE field_routes.location_change (
  id uuid PRIMARY KEY,
  school_id varchar(30) NOT NULL,
  target text NOT NULL CHECK (target IN ('school', 'entrance')),
  version integer NOT NULL,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  previous_lat double precision,
  previous_lng double precision,
  previous_version integer NOT NULL,
  capture_id uuid NOT NULL REFERENCES field_routes.location_capture (id),
  changed_by varchar(30) NOT NULL,
  changed_at timestamptz NOT NULL,
  UNIQUE (school_id, target, version)
);

CREATE INDEX location_change_at ON field_routes.location_change (changed_at);

GRANT SELECT, INSERT, UPDATE ON field_routes.location_capture TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.school_location TO edify_routes_rw;
GRANT SELECT, INSERT ON field_routes.location_change TO edify_routes_rw;
