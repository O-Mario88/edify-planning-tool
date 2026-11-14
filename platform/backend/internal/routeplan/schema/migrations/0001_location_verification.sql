-- Verify Location (Smart Route brief, parts 2 and 11): anyone who may open a
-- school's profile can report that its stored location is wrong or missing,
-- with a proposed point and a note; someone else reviews the report. An
-- approved point becomes the school's verified location, which the planner
-- reads before the School Directory's own coordinates. The existing
-- application's coordinates are never changed. Additive only: every report
-- and decision stays as history.

CREATE TABLE field_routes.location_report (
  id uuid PRIMARY KEY,
  -- public.school.id and its School ID as they were when reported.
  school_id varchar(30) NOT NULL,
  school_code varchar(64) NOT NULL DEFAULT '',
  kind text NOT NULL CHECK (kind IN ('wrong', 'missing')),
  -- The proposed point, when the reporter gave one; where it came from and,
  -- for a device reading, its reported accuracy in metres.
  proposed_lat double precision,
  proposed_lng double precision,
  point_source text NOT NULL DEFAULT 'none' CHECK (point_source IN ('none', 'typed', 'device')),
  accuracy_m double precision,
  access_note text NOT NULL DEFAULT '',
  note text NOT NULL,
  -- The location shown when reported, so a review sees what was questioned.
  previous_lat double precision,
  previous_lng double precision,
  previous_status text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  reported_by varchar(30) NOT NULL,
  reported_role text NOT NULL,
  reported_at timestamptz NOT NULL DEFAULT now(),
  reviewed_by varchar(30),
  reviewed_role text,
  reviewed_at timestamptz,
  review_note text NOT NULL DEFAULT '',
  -- A client's key for a report, so a retry never files a second one.
  idempotency_key text UNIQUE,
  CHECK ((proposed_lat IS NULL) = (proposed_lng IS NULL)),
  CHECK (status = 'pending' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)),
  -- The reporter never reviews their own report.
  CHECK (reviewed_by IS NULL OR reviewed_by <> reported_by)
);

-- One open report per school at a time.
CREATE UNIQUE INDEX location_report_one_pending ON field_routes.location_report (school_id) WHERE status = 'pending';
CREATE INDEX location_report_school ON field_routes.location_report (school_id, reported_at);

-- The school's verified location: the latest approved report. Replaced when
-- a later report is approved (the reports keep the history).
CREATE TABLE field_routes.verified_location (
  school_id varchar(30) PRIMARY KEY,
  lat double precision NOT NULL,
  lng double precision NOT NULL,
  access_note text NOT NULL DEFAULT '',
  report_id uuid NOT NULL REFERENCES field_routes.location_report (id),
  verified_by varchar(30) NOT NULL,
  verified_at timestamptz NOT NULL
);

GRANT SELECT, INSERT, UPDATE ON field_routes.location_report TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.verified_location TO edify_routes_rw;
