-- A leader invites member schools to a meeting or training as soon as it is
-- planned (owner's mockup, 2026-11-11: "Save & Invite Schools", "Send
-- Invitations"). The plan still goes to staff for review. When staff link the
-- plan to its official activity, each invitation here carries over to an
-- invitation of that activity, which names it. Additive only.

CREATE TABLE cluster_leadership.plan_invitation (
  id uuid PRIMARY KEY,
  plan_id uuid NOT NULL REFERENCES cluster_leadership.meeting_plan (id),
  cluster_id varchar(30) NOT NULL,
  -- public.school.id: a member school of the cluster when invited.
  school_id varchar(30) NOT NULL,
  channel text NOT NULL CHECK (channel IN ('in_person', 'phone', 'sms', 'email', 'whatsapp')),
  invited_by varchar(30) NOT NULL,
  invited_at timestamptz NOT NULL DEFAULT now(),
  -- The activity's invitation it became when the plan was linked.
  carried_to uuid REFERENCES cluster_leadership.invitation (id),
  UNIQUE (plan_id, school_id)
);
CREATE INDEX plan_invitation_by_plan ON cluster_leadership.plan_invitation (plan_id);

GRANT SELECT, INSERT, UPDATE ON cluster_leadership.plan_invitation TO edify_cluster_rw;
