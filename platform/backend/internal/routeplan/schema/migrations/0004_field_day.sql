-- Save Plan and Start Field Day (owner, 2026-11-16: "Build Save Plan and
-- Start Field Day properly"): a person's own record of a field day. The
-- order they saved, so the planner opens on it on any device; when they
-- started and ended the day; when they reached and left each stop. It
-- schedules, moves and completes nothing: the existing application's
-- activities are never written.

CREATE TABLE field_routes.field_day (
  -- The person (the existing application's user id) and their local day.
  user_id varchar(30) NOT NULL,
  day date NOT NULL,
  -- The schools in the order they keep.
  school_ids varchar(30)[] NOT NULL DEFAULT '{}',
  saved_at timestamptz,
  started_at timestamptz,
  ended_at timestamptz,
  PRIMARY KEY (user_id, day),
  CHECK (ended_at IS NULL OR started_at IS NOT NULL),
  CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE field_routes.field_day_stop (
  user_id varchar(30) NOT NULL,
  day date NOT NULL,
  school_id varchar(30) NOT NULL,
  arrived_at timestamptz NOT NULL,
  left_at timestamptz,
  PRIMARY KEY (user_id, day, school_id),
  FOREIGN KEY (user_id, day) REFERENCES field_routes.field_day (user_id, day),
  CHECK (left_at IS NULL OR left_at >= arrived_at)
);

GRANT SELECT, INSERT, UPDATE ON field_routes.field_day TO edify_routes_rw;
GRANT SELECT, INSERT, UPDATE ON field_routes.field_day_stop TO edify_routes_rw;
