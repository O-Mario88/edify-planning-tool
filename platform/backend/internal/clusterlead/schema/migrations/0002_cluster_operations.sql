-- Cluster operations (brief A4-A7): a leader's meeting plans, the schools
-- invited to an activity and their answers, the leader's own attendance
-- record, meeting minutes, action items and requests to staff.
--
-- The official activity stays the existing application's (public.activity):
-- a plan is the leader's proposal until staff schedule it there, and is then
-- linked to that activity's id; no second official record is ever made.
-- Invitations and attendance are kept apart: an answer is never attendance.
-- As before, no foreign key reaches into the existing tables.

CREATE TABLE cluster_leadership.meeting_plan (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  category text NOT NULL CHECK (category IN ('only_meeting', 'cluster_leaders', 'training')),
  title text NOT NULL,
  -- public.activity_catalogue_item.id: required for a training, never for a meeting.
  training_course_id varchar(30),
  planned_on date NOT NULL,
  starts_at text NOT NULL DEFAULT '',
  venue text NOT NULL DEFAULT '',
  is_online boolean NOT NULL DEFAULT false,
  objectives text NOT NULL DEFAULT '',
  agenda text NOT NULL DEFAULT '',
  expected_participants integer NOT NULL DEFAULT 0 CHECK (expected_participants >= 0),
  facilitator text NOT NULL DEFAULT '',
  resources text NOT NULL DEFAULT '',
  notes text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN ('draft', 'submitted', 'returned', 'approved', 'scheduled', 'cancelled')),
  -- public.activity.id once staff schedule it: one plan, one official activity.
  activity_id varchar(30) UNIQUE,
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  reviewed_by varchar(30),
  reviewed_at timestamptz,
  review_note text NOT NULL DEFAULT '',
  CHECK ((category = 'training') = (training_course_id IS NOT NULL)),
  CHECK ((status = 'scheduled') = (activity_id IS NOT NULL))
);
CREATE INDEX meeting_plan_by_cluster ON cluster_leadership.meeting_plan (cluster_id, planned_on);

CREATE TABLE cluster_leadership.plan_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  plan_id uuid NOT NULL REFERENCES cluster_leadership.meeting_plan (id),
  event text NOT NULL CHECK (event IN ('drafted', 'edited', 'submitted', 'returned', 'approved', 'scheduled', 'cancelled')),
  actor_id varchar(30) NOT NULL,
  note text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX plan_event_by_plan ON cluster_leadership.plan_event (plan_id, at);

CREATE TABLE cluster_leadership.invitation (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  -- public.activity.id: an approved or scheduled activity of the cluster.
  activity_id varchar(30) NOT NULL,
  -- public.school.id: a member school of the cluster when invited.
  school_id varchar(30) NOT NULL,
  status text NOT NULL CHECK (status IN ('invited', 'acknowledged', 'confirmed', 'declined')),
  channel text NOT NULL CHECK (channel IN ('in_person', 'phone', 'sms', 'email', 'whatsapp')),
  -- No messaging integration confirms delivery yet: an invitation is
  -- "recorded" until one does, and never claimed as delivered.
  delivery_status text NOT NULL DEFAULT 'recorded' CHECK (delivery_status IN ('recorded', 'sent', 'delivered', 'failed')),
  invited_by varchar(30) NOT NULL,
  invited_at timestamptz NOT NULL DEFAULT now(),
  responded_at timestamptz,
  response_note text NOT NULL DEFAULT '',
  follow_up_count integer NOT NULL DEFAULT 0 CHECK (follow_up_count >= 0),
  last_follow_up_at timestamptz,
  UNIQUE (activity_id, school_id)
);
CREATE INDEX invitation_by_cluster ON cluster_leadership.invitation (cluster_id, activity_id);

CREATE TABLE cluster_leadership.invitation_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  invitation_id uuid NOT NULL REFERENCES cluster_leadership.invitation (id),
  event text NOT NULL CHECK (event IN ('invited', 'acknowledged', 'confirmed', 'declined', 'followed_up')),
  actor_id varchar(30) NOT NULL,
  note text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invitation_event_by_invitation ON cluster_leadership.invitation_event (invitation_id, at);

-- The leader's attendance record. The official attendance is the activity's
-- own (public.activity.attended_school_ids, set by staff at completion);
-- this is what the leader saw, until staff complete the activity.
CREATE TABLE cluster_leadership.attendance_record (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  activity_id varchar(30) NOT NULL,
  school_id varchar(30) NOT NULL,
  attended boolean NOT NULL,
  participants integer NOT NULL DEFAULT 0 CHECK (participants >= 0),
  recorded_by varchar(30) NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (activity_id, school_id)
);

CREATE TABLE cluster_leadership.meeting_minutes (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  activity_id varchar(30) NOT NULL UNIQUE,
  discussion text NOT NULL DEFAULT '',
  decisions text NOT NULL DEFAULT '',
  status text NOT NULL CHECK (status IN ('draft', 'submitted')),
  written_by varchar(30) NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  CHECK ((status = 'submitted') = (submitted_at IS NOT NULL))
);

CREATE TABLE cluster_leadership.action_item (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  -- The meeting it came from, when it came from one.
  activity_id varchar(30),
  title text NOT NULL,
  -- A member school (public.school.id) or a named person; one of the two.
  owner_school_id varchar(30),
  owner_name text NOT NULL DEFAULT '',
  due_on date,
  status text NOT NULL CHECK (status IN ('open', 'done', 'cancelled')),
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_by varchar(30),
  closed_at timestamptz,
  CHECK (owner_school_id IS NOT NULL OR owner_name <> ''),
  CHECK ((status = 'open') = (closed_at IS NULL))
);
CREATE INDEX action_item_by_cluster ON cluster_leadership.action_item (cluster_id, status, due_on);

CREATE TABLE cluster_leadership.action_item_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action_item_id uuid NOT NULL REFERENCES cluster_leadership.action_item (id),
  event text NOT NULL CHECK (event IN ('created', 'updated', 'done', 'cancelled', 'reopened')),
  actor_id varchar(30) NOT NULL,
  note text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now()
);

-- A leader's request or concern to the cluster's responsible staff.
CREATE TABLE cluster_leadership.leader_request (
  id uuid PRIMARY KEY,
  cluster_id varchar(30) NOT NULL,
  subject text NOT NULL,
  body text NOT NULL,
  status text NOT NULL CHECK (status IN ('open', 'answered', 'closed')),
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  answered_by varchar(30),
  answered_at timestamptz,
  answer text NOT NULL DEFAULT ''
);
CREATE INDEX leader_request_by_cluster ON cluster_leadership.leader_request (cluster_id, created_at);

-- Records are read, added and updated; histories only added to. Nothing is
-- ever deleted.
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.meeting_plan TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.plan_event TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.invitation TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.invitation_event TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.attendance_record TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.meeting_minutes TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.action_item TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.action_item_event TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.leader_request TO edify_cluster_rw;
