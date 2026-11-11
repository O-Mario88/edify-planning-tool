-- The Cluster Action Register (owner brief, 2026-11-11, "Cluster Action &
-- Follow-up Management System"): a school need raised by a cluster's leader,
-- routed school by school to the CCEO who holds each school, and followed
-- until verified support is delivered and reviewed. It is a coordination
-- layer: an action never becomes an activity. Staff plan the official
-- activity in Edify and link its id here; the activity's own status (read,
-- never copied) then shows the school's progress. Additive only; nothing is
-- ever deleted.

CREATE TABLE cluster_leadership.cluster_action (
  id uuid PRIMARY KEY,
  -- Short, human reference ("CA-7K3P9Q"), unique, used in notices.
  ref text NOT NULL UNIQUE,
  cluster_id varchar(30) NOT NULL,
  -- Where the need was raised. A meeting action names the meeting; an
  -- action outside a meeting names none and no meeting is made up for it.
  source text NOT NULL CHECK (source IN ('meeting', 'school_follow_up', 'observation', 'other')),
  source_activity_id varchar(30),
  source_plan_id uuid REFERENCES cluster_leadership.meeting_plan (id),
  -- The kind of support (clusterlead.supportKinds); a training names one
  -- of the governed courses (public.activity_catalogue_item.id).
  support_kind text NOT NULL,
  training_course_id varchar(30),
  title text NOT NULL,
  description text NOT NULL,
  expected_outcome text NOT NULL DEFAULT '',
  priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high', 'urgent')),
  target_on date NOT NULL,
  -- The member schools (public.school.id) chosen while a draft; each gets
  -- its own routed row in cluster_action_school when the action is sent.
  school_ids varchar(30)[] NOT NULL DEFAULT '{}',
  -- Financial year it was raised in (October-September); never moved.
  fiscal_year integer NOT NULL,
  status text NOT NULL CHECK (status IN ('draft', 'submitted', 'closed', 'cancelled')),
  close_summary text NOT NULL DEFAULT '',
  -- A client's key for a submission, so a retry never makes a second action.
  idempotency_key text UNIQUE,
  version integer NOT NULL DEFAULT 1,
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  closed_at timestamptz,
  CHECK ((source = 'meeting') = (source_activity_id IS NOT NULL OR source_plan_id IS NOT NULL)),
  CHECK ((status IN ('closed', 'cancelled')) = (closed_at IS NOT NULL))
);
CREATE INDEX cluster_action_by_cluster ON cluster_leadership.cluster_action (cluster_id, status, target_on);

-- One row per school of a sent action: each school is routed to the CCEO
-- holding it when the action is sent, and progresses on its own, so
-- support delivered to one school never marks another supported.
CREATE TABLE cluster_leadership.cluster_action_school (
  id uuid PRIMARY KEY,
  action_id uuid NOT NULL REFERENCES cluster_leadership.cluster_action (id),
  -- public.school.id: a member school of the cluster when added.
  school_id varchar(30) NOT NULL,
  -- public.staff_profile.id of the CCEO holding the school when routed;
  -- empty when nobody held it, in which case routed_to is 'supervisor'.
  responsible_staff_id varchar(30),
  -- The supervising Program Lead's staff_profile.id, when known.
  supervisor_staff_id varchar(30),
  routed_to text CHECK (routed_to IN ('owner', 'supervisor', 'unassigned')),
  -- The coordination state; once accepted and linked, progress is the
  -- linked activity's own status.
  status text NOT NULL CHECK (status IN ('awaiting_review', 'under_review', 'clarification_requested',
                                          'accepted', 'returned', 'declined', 'cancelled')),
  -- public.activity.id: the official activity that delivers the support.
  activity_id varchar(30),
  linked_by varchar(30),
  linked_at timestamptz,
  status_note text NOT NULL DEFAULT '',
  reminded_at timestamptz,
  escalated_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (action_id, school_id)
);
CREATE INDEX cluster_action_school_by_owner ON cluster_leadership.cluster_action_school (responsible_staff_id, status);
CREATE INDEX cluster_action_school_by_supervisor ON cluster_leadership.cluster_action_school (supervisor_staff_id, status);
CREATE INDEX cluster_action_school_by_school ON cluster_leadership.cluster_action_school (school_id);
CREATE INDEX cluster_action_school_by_activity ON cluster_leadership.cluster_action_school (activity_id);

-- Every change, in order: who, in which role, from what to what, and why.
CREATE TABLE cluster_leadership.cluster_action_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action_id uuid NOT NULL REFERENCES cluster_leadership.cluster_action (id),
  school_id varchar(30),
  event text NOT NULL,
  actor_id varchar(30) NOT NULL,
  actor_role text NOT NULL DEFAULT '',
  from_status text NOT NULL DEFAULT '',
  to_status text NOT NULL DEFAULT '',
  note text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cluster_action_event_by_action ON cluster_leadership.cluster_action_event (action_id, at);

-- A meeting's review of an earlier action (brief part 9): the action is
-- discussed again without being copied; each review is its own entry.
CREATE TABLE cluster_leadership.cluster_action_review (
  id uuid PRIMARY KEY,
  action_id uuid NOT NULL REFERENCES cluster_leadership.cluster_action (id),
  -- The meeting it was reviewed at, when there was one.
  activity_id varchar(30),
  plan_id uuid REFERENCES cluster_leadership.meeting_plan (id),
  progress text NOT NULL DEFAULT '',
  challenges text NOT NULL DEFAULT '',
  next_step text NOT NULL DEFAULT '',
  outcome text NOT NULL CHECK (outcome IN ('continue', 'escalate', 'propose_closure')),
  created_by varchar(30) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cluster_action_review_by_action ON cluster_leadership.cluster_action_review (action_id, created_at);

-- Escalations up the reporting line: who raised it, from whom, to whom.
-- An escalation never changes the school's or staff member's reporting line.
CREATE TABLE cluster_leadership.cluster_action_escalation (
  id uuid PRIMARY KEY,
  action_id uuid NOT NULL REFERENCES cluster_leadership.cluster_action (id),
  school_id varchar(30),
  reason text NOT NULL,
  -- 'leader' when a person raised it, 'policy' when the follow-up rules did.
  raised_by_kind text NOT NULL CHECK (raised_by_kind IN ('leader', 'staff', 'policy')),
  raised_by varchar(30) NOT NULL,
  from_staff_id varchar(30),
  to_staff_id varchar(30),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz,
  resolved_by varchar(30),
  resolution text NOT NULL DEFAULT ''
);
CREATE INDEX cluster_action_escalation_open ON cluster_leadership.cluster_action_escalation (to_staff_id, status);

-- Notices to people (staff or the leader), each written once per event and
-- recipient and delivered to Edify's own notifications by a worker that
-- retries; delivery never decides the business event.
CREATE TABLE cluster_leadership.cluster_action_notice (
  id uuid PRIMARY KEY,
  action_id uuid NOT NULL REFERENCES cluster_leadership.cluster_action (id),
  recipient_user_id varchar(30) NOT NULL,
  event text NOT NULL,
  title text NOT NULL,
  body text NOT NULL,
  target_route text NOT NULL DEFAULT '',
  sender_user_id varchar(30),
  -- One notice per business event and recipient, however often it is retried.
  dedup_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
  attempts integer NOT NULL DEFAULT 0,
  last_error text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  sent_at timestamptz
);
CREATE INDEX cluster_action_notice_pending ON cluster_leadership.cluster_action_notice (status, created_at);

GRANT SELECT, INSERT, UPDATE ON cluster_leadership.cluster_action TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.cluster_action_school TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.cluster_action_event TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.cluster_action_review TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.cluster_action_escalation TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.cluster_action_notice TO edify_cluster_rw;
