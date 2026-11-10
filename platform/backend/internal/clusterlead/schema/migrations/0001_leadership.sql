-- Cluster leadership assignments and their history (brief A1).
--
-- A leader is an existing Edify account (public."user", created only by the
-- people who may manage users) given one or more clusters for a span of
-- dates. Ending or replacing a leader never deletes the assignment: the row
-- keeps who held the cluster and when, and every change is written to
-- assignment_event, which nobody may update or delete.
--
-- No foreign key reaches into the existing application's tables (a foreign
-- key would put a trigger on them); Go checks the cluster and the account.

CREATE TABLE cluster_leadership.leader_assignment (
  id uuid PRIMARY KEY,
  -- public.cluster.id and public."user".id, checked by Go on assignment.
  cluster_id varchar(30) NOT NULL,
  user_id varchar(30) NOT NULL,
  starts_on date NOT NULL,
  ends_on date,
  status text NOT NULL CHECK (status IN ('active', 'suspended', 'ended')),
  assigned_by varchar(30) NOT NULL,
  assigned_reason text NOT NULL DEFAULT '',
  ended_by varchar(30),
  ended_reason text,
  ended_at timestamptz,
  -- The assignment this one took over, when a leader was replaced.
  replaces_assignment_id uuid REFERENCES cluster_leadership.leader_assignment (id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_on IS NULL OR ends_on >= starts_on),
  CHECK ((status = 'ended') = (ended_at IS NOT NULL))
);

-- One live assignment per leader and cluster; history is kept as ended rows.
CREATE UNIQUE INDEX leader_assignment_one_live
  ON cluster_leadership.leader_assignment (cluster_id, user_id)
  WHERE status <> 'ended';
CREATE INDEX leader_assignment_by_leader
  ON cluster_leadership.leader_assignment (user_id)
  WHERE status = 'active';
CREATE INDEX leader_assignment_by_cluster
  ON cluster_leadership.leader_assignment (cluster_id, created_at);

CREATE TABLE cluster_leadership.assignment_event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  assignment_id uuid NOT NULL REFERENCES cluster_leadership.leader_assignment (id),
  event text NOT NULL CHECK (event IN ('assigned', 'suspended', 'reinstated', 'ended', 'replaced')),
  actor_id varchar(30) NOT NULL,
  reason text NOT NULL DEFAULT '',
  at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assignment_event_by_assignment
  ON cluster_leadership.assignment_event (assignment_id, at);

-- The gateway reads both tables, writes assignments and appends events. It
-- may never rewrite or remove an event, nor delete an assignment.
GRANT SELECT ON cluster_leadership.schema_migration TO edify_cluster_rw;
GRANT SELECT, INSERT, UPDATE ON cluster_leadership.leader_assignment TO edify_cluster_rw;
GRANT SELECT, INSERT ON cluster_leadership.assignment_event TO edify_cluster_rw;
