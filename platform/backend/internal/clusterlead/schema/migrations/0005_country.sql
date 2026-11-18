-- Edify Global (docs/migration/80-multi-country-phase-0.md §24): every
-- cluster leadership record carries the country of the cluster it belongs
-- to, and the database keeps each request to its own country's records,
-- behind the Go checks of §16 (owner, 2026-11-18: "enforce country isolation
-- in both Go and the database").
--
-- Every record already kept is Uganda's (owner decision 2), so the column is
-- added with UG for them. Go records a new one under its cluster's country
-- (country.ClusterCountryCode), and a history, review, escalation, routed
-- school or notice under the country of the record it hangs on.
--
-- Each connection carries the country its request is made in
-- (internal/countryctx, edify.read_countries): "*" for every country (the
-- Admin, a regional role, the platform's own work), a country's code, or ""
-- for none. A row of another country is neither read nor written.

ALTER TABLE cluster_leadership.leader_assignment ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX leader_assignment_country ON cluster_leadership.leader_assignment (country_code);
ALTER TABLE cluster_leadership.leader_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.leader_assignment FORCE ROW LEVEL SECURITY;
CREATE POLICY leader_assignment_country_read ON cluster_leadership.leader_assignment
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY leader_assignment_country_add ON cluster_leadership.leader_assignment
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY leader_assignment_country_change ON cluster_leadership.leader_assignment
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.assignment_event ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX assignment_event_country ON cluster_leadership.assignment_event (country_code);
ALTER TABLE cluster_leadership.assignment_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.assignment_event FORCE ROW LEVEL SECURITY;
CREATE POLICY assignment_event_country_read ON cluster_leadership.assignment_event
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY assignment_event_country_add ON cluster_leadership.assignment_event
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.meeting_plan ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX meeting_plan_country ON cluster_leadership.meeting_plan (country_code);
ALTER TABLE cluster_leadership.meeting_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.meeting_plan FORCE ROW LEVEL SECURITY;
CREATE POLICY meeting_plan_country_read ON cluster_leadership.meeting_plan
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY meeting_plan_country_add ON cluster_leadership.meeting_plan
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY meeting_plan_country_change ON cluster_leadership.meeting_plan
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.plan_event ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX plan_event_country ON cluster_leadership.plan_event (country_code);
ALTER TABLE cluster_leadership.plan_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.plan_event FORCE ROW LEVEL SECURITY;
CREATE POLICY plan_event_country_read ON cluster_leadership.plan_event
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY plan_event_country_add ON cluster_leadership.plan_event
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.invitation ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX invitation_country ON cluster_leadership.invitation (country_code);
ALTER TABLE cluster_leadership.invitation ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.invitation FORCE ROW LEVEL SECURITY;
CREATE POLICY invitation_country_read ON cluster_leadership.invitation
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY invitation_country_add ON cluster_leadership.invitation
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY invitation_country_change ON cluster_leadership.invitation
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.invitation_event ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX invitation_event_country ON cluster_leadership.invitation_event (country_code);
ALTER TABLE cluster_leadership.invitation_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.invitation_event FORCE ROW LEVEL SECURITY;
CREATE POLICY invitation_event_country_read ON cluster_leadership.invitation_event
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY invitation_event_country_add ON cluster_leadership.invitation_event
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.attendance_record ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX attendance_record_country ON cluster_leadership.attendance_record (country_code);
ALTER TABLE cluster_leadership.attendance_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.attendance_record FORCE ROW LEVEL SECURITY;
CREATE POLICY attendance_record_country_read ON cluster_leadership.attendance_record
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY attendance_record_country_add ON cluster_leadership.attendance_record
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY attendance_record_country_change ON cluster_leadership.attendance_record
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.meeting_minutes ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX meeting_minutes_country ON cluster_leadership.meeting_minutes (country_code);
ALTER TABLE cluster_leadership.meeting_minutes ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.meeting_minutes FORCE ROW LEVEL SECURITY;
CREATE POLICY meeting_minutes_country_read ON cluster_leadership.meeting_minutes
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY meeting_minutes_country_add ON cluster_leadership.meeting_minutes
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY meeting_minutes_country_change ON cluster_leadership.meeting_minutes
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.action_item ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX action_item_country ON cluster_leadership.action_item (country_code);
ALTER TABLE cluster_leadership.action_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.action_item FORCE ROW LEVEL SECURITY;
CREATE POLICY action_item_country_read ON cluster_leadership.action_item
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY action_item_country_add ON cluster_leadership.action_item
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY action_item_country_change ON cluster_leadership.action_item
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.action_item_event ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX action_item_event_country ON cluster_leadership.action_item_event (country_code);
ALTER TABLE cluster_leadership.action_item_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.action_item_event FORCE ROW LEVEL SECURITY;
CREATE POLICY action_item_event_country_read ON cluster_leadership.action_item_event
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY action_item_event_country_add ON cluster_leadership.action_item_event
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.leader_request ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX leader_request_country ON cluster_leadership.leader_request (country_code);
ALTER TABLE cluster_leadership.leader_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.leader_request FORCE ROW LEVEL SECURITY;
CREATE POLICY leader_request_country_read ON cluster_leadership.leader_request
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY leader_request_country_add ON cluster_leadership.leader_request
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY leader_request_country_change ON cluster_leadership.leader_request
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.plan_invitation ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX plan_invitation_country ON cluster_leadership.plan_invitation (country_code);
ALTER TABLE cluster_leadership.plan_invitation ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.plan_invitation FORCE ROW LEVEL SECURITY;
CREATE POLICY plan_invitation_country_read ON cluster_leadership.plan_invitation
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY plan_invitation_country_add ON cluster_leadership.plan_invitation
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY plan_invitation_country_change ON cluster_leadership.plan_invitation
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_country ON cluster_leadership.cluster_action (country_code);
ALTER TABLE cluster_leadership.cluster_action ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_country_read ON cluster_leadership.cluster_action
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_country_add ON cluster_leadership.cluster_action
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_country_change ON cluster_leadership.cluster_action
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action_school ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_school_country ON cluster_leadership.cluster_action_school (country_code);
ALTER TABLE cluster_leadership.cluster_action_school ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action_school FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_school_country_read ON cluster_leadership.cluster_action_school
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_school_country_add ON cluster_leadership.cluster_action_school
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_school_country_change ON cluster_leadership.cluster_action_school
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action_event ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_event_country ON cluster_leadership.cluster_action_event (country_code);
ALTER TABLE cluster_leadership.cluster_action_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action_event FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_event_country_read ON cluster_leadership.cluster_action_event
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_event_country_add ON cluster_leadership.cluster_action_event
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action_review ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_review_country ON cluster_leadership.cluster_action_review (country_code);
ALTER TABLE cluster_leadership.cluster_action_review ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action_review FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_review_country_read ON cluster_leadership.cluster_action_review
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_review_country_add ON cluster_leadership.cluster_action_review
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action_escalation ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_escalation_country ON cluster_leadership.cluster_action_escalation (country_code);
ALTER TABLE cluster_leadership.cluster_action_escalation ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action_escalation FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_escalation_country_read ON cluster_leadership.cluster_action_escalation
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_escalation_country_add ON cluster_leadership.cluster_action_escalation
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_escalation_country_change ON cluster_leadership.cluster_action_escalation
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));

ALTER TABLE cluster_leadership.cluster_action_notice ADD COLUMN country_code text NOT NULL DEFAULT 'UG'
  CHECK (country_code ~ '^[A-Z]{2}$');
CREATE INDEX cluster_action_notice_country ON cluster_leadership.cluster_action_notice (country_code);
ALTER TABLE cluster_leadership.cluster_action_notice ENABLE ROW LEVEL SECURITY;
ALTER TABLE cluster_leadership.cluster_action_notice FORCE ROW LEVEL SECURITY;
CREATE POLICY cluster_action_notice_country_read ON cluster_leadership.cluster_action_notice
  FOR SELECT TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_notice_country_add ON cluster_leadership.cluster_action_notice
  FOR INSERT TO edify_cluster_rw, edify_cluster_owner
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
CREATE POLICY cluster_action_notice_country_change ON cluster_leadership.cluster_action_notice
  FOR UPDATE TO edify_cluster_rw, edify_cluster_owner
  USING (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')))
  WITH CHECK (current_setting('edify.read_countries', true) = '*'
    OR country_code = ANY(string_to_array(current_setting('edify.read_countries', true), ',')));
