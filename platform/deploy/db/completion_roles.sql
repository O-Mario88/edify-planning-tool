-- The tenth Go save, completing a staff school visit (docs/migration/183),
-- hands the visit in for its Programme Lead's review, as the existing
-- completion does (apps.frontend.views.my_plan_views.complete_activity_action
-- → apps.activities.services.complete → salesforce.reserve_salesforce_id).
-- Those writes touch columns the gateway may never change itself
-- (internal/dbguard protectedColumns: the delivery day, the Salesforce ID,
-- the evidence status) and two tables it holds nothing on. As for the
-- cancel's advances (30 §30.4, 03 §3.7), the gateway gets one narrow
-- function and no grant: it may ask this function, which makes exactly one
-- visit's hand-in and nothing else, and only for 183.1's case — a staff
-- school visit (a School Visit, or a donor, story-gathering, invitation or
-- social visit) outside a cluster, already started (completion_started),
-- with no Salesforce reference and no completion verification yet.
--
-- The function answers '' when it handed the visit in, and otherwise writes
-- nothing and says why: 'changed' (the visit is not 183.1's case under its
-- lock), 'own_reference' or 'verification' (it already holds one),
-- 'called_off' (the ID is held by cancelled, deferred or removed work, which
-- the existing reservation releases: handed on), or 'held:<activity id>'
-- (the ID is live work's: refused, in the existing words, by the caller).
-- A race the pre-check missed meets the unique constraint (23505).
--
-- The function's owner is a NOLOGIN role nobody is a member of, holding only
-- the columns the hand-in reads and writes. Applied after
-- activities_roles.sql (apply-roles.sh, the integration TestMain).
-- Idempotent. A new database object: production needs the owner's approval
-- at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_completion_owner') THEN
    CREATE ROLE edify_completion_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_completion_owner;
GRANT USAGE ON SCHEMA public TO edify_completion_owner;
GRANT SELECT (id, status, delivery_type, activity_type, cluster_id, deleted_at, evidence_status,
              actual_outcome, actual_observations, follow_up_note)
  ON activity TO edify_completion_owner;
GRANT UPDATE (salesforce_activity_id, salesforce_activity_type, teachers_attended, leaders_attended,
              other_participants, attended_school_ids, actual_delivery_date, actual_outcome,
              actual_observations, follow_up_note, status, evidence_status, updated_at)
  ON activity TO edify_completion_owner;
-- Start activity (services.start_completion): the first start's moment.
GRANT SELECT (execution_started_at), UPDATE (execution_started_at) ON activity TO edify_completion_owner;
GRANT SELECT (activity_id, normalized_value) ON activity_salesforce_reference TO edify_completion_owner;
GRANT INSERT (id, created_at, updated_at, raw_value, normalized_value, activity_type, expected_prefix,
              entry_source, entered_by, entered_at, activity_id)
  ON activity_salesforce_reference TO edify_completion_owner;
GRANT SELECT (activity_id) ON activity_completion_verification TO edify_completion_owner;
GRANT INSERT (id, created_at, updated_at, salesforce_id, entered_by, entered_at, status, activity_id)
  ON activity_completion_verification TO edify_completion_owner;
-- Submit for review (services.submit_for_review): the ID it is handed in
-- with, a returned visit's reviews set pending again
-- (_clear_returned_verification), and the completion verification's
-- update_or_create.
GRANT SELECT (salesforce_activity_id, ia_verification_status), UPDATE (ia_verification_status)
  ON activity TO edify_completion_owner;
GRANT SELECT (activity_id, status), UPDATE (status) ON ia_verification TO edify_completion_owner;
GRANT SELECT (salesforce_id, entered_by, status), UPDATE (salesforce_id, entered_by, status, updated_at)
  ON activity_completion_verification TO edify_completion_owner;

-- A cluster meeting's completion (services.complete with the view's start,
-- _cluster_member_school_ids and _sync_cluster_attendance): the per-school
-- head counts a new register row borrows, the cluster's member schools, and
-- the register itself, whose absent invitations completion removes.
GRANT SELECT (teachers_per_school, leaders_per_school, other_per_school, attended_school_ids)
  ON activity TO edify_completion_owner;
GRANT SELECT (id, cluster_id, deleted_at) ON school TO edify_completion_owner;
GRANT SELECT, INSERT, DELETE, UPDATE (attended, recorded_by, updated_at)
  ON cluster_activity_attendance TO edify_completion_owner;
GRANT USAGE ON SEQUENCE cluster_activity_attendance_id_seq TO edify_completion_owner;

CREATE SCHEMA IF NOT EXISTS gateway_completion AUTHORIZATION edify_completion_owner;
REVOKE ALL ON SCHEMA gateway_completion FROM PUBLIC;

SET ROLE edify_completion_owner;
CREATE OR REPLACE FUNCTION gateway_completion.hand_in_school_visit(
  target varchar, delivered date, raw_value varchar, normalized varchar,
  teachers integer, leaders integer, other integer,
  outcome text, observations text, follow_up text,
  entered_by varchar, at timestamptz, reference_id varchar, verification_id varchar
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  visit record;
  holder record;
BEGIN
  SELECT a.status, a.delivery_type, a.activity_type, a.cluster_id, a.deleted_at
    INTO visit FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR visit.status IS DISTINCT FROM 'completion_started'
     OR visit.delivery_type IS DISTINCT FROM 'staff'
     OR NOT (visit.activity_type = ANY (ARRAY['school_visit', 'donor_visit', 'story_gathering_visit',
                                              'school_invitation', 'social_visit']::varchar[]))
     OR visit.cluster_id IS NOT NULL OR visit.deleted_at IS NOT NULL THEN
    RETURN 'changed';
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_salesforce_reference r WHERE r.activity_id = target) THEN
    RETURN 'own_reference';
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_completion_verification v WHERE v.activity_id = target) THEN
    RETURN 'verification';
  END IF;
  SELECT h.id, h.status, h.deleted_at INTO holder
    FROM public.activity_salesforce_reference r JOIN public.activity h ON h.id = r.activity_id
   WHERE r.normalized_value = normalized;
  IF FOUND THEN
    IF holder.deleted_at IS NOT NULL OR holder.status IN ('cancelled', 'deferred') THEN
      RETURN 'called_off';
    END IF;
    RETURN 'held:' || holder.id;
  END IF;
  INSERT INTO public.activity_salesforce_reference (id, created_at, updated_at, raw_value, normalized_value,
    activity_type, expected_prefix, entry_source, entered_by, entered_at, activity_id)
  VALUES (reference_id, at, at, raw_value, normalized, visit.activity_type, 'SVE-', 'staff_self_entry',
    entered_by, at, target);
  UPDATE public.activity a SET
    salesforce_activity_id = normalized, salesforce_activity_type = 'visit',
    teachers_attended = teachers, leaders_attended = leaders, other_participants = other,
    attended_school_ids = '{}', actual_delivery_date = delivered,
    actual_outcome = COALESCE(outcome, a.actual_outcome),
    actual_observations = COALESCE(observations, a.actual_observations),
    follow_up_note = COALESCE(follow_up, a.follow_up_note),
    status = 'submitted_to_pl',
    evidence_status = CASE WHEN a.evidence_status = 'none' THEN 'accepted' ELSE a.evidence_status END,
    updated_at = at
  WHERE a.id = target;
  INSERT INTO public.activity_completion_verification (id, created_at, updated_at, salesforce_id, entered_by,
    entered_at, status, activity_id)
  VALUES (verification_id, at, at, normalized, entered_by, at, 'pending', target);
  RETURN '';
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.hand_in_school_visit(varchar, date, varchar, varchar, integer,
  integer, integer, text, text, text, varchar, timestamptz, varchar, varchar) FROM PUBLIC;

-- services.start_completion for a staff school visit: started, and the first
-- start's moment kept. False when the visit is not one it may start.
CREATE OR REPLACE FUNCTION gateway_completion.start_visit(target varchar, at timestamptz) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  UPDATE public.activity a
     SET status = 'completion_started', execution_started_at = COALESCE(a.execution_started_at, at), updated_at = at
   WHERE a.id = target AND a.deleted_at IS NULL AND a.delivery_type = 'staff' AND a.cluster_id IS NULL
     AND a.activity_type = ANY (ARRAY['school_visit', 'donor_visit', 'story_gathering_visit',
                                      'school_invitation', 'social_visit']::varchar[])
     AND a.status = ANY (ARRAY['scheduled', 'in_progress', 'partner_scheduled', 'assigned_to_partner',
                               'rescheduled']::varchar[]);
  RETURN FOUND;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.start_visit(varchar, timestamptz) FROM PUBLIC;

-- The Salesforce ID drawer's hand-in (services.hand_in_with_id): the same
-- checks and reservation, but the visit's attendance, evidence and notes are
-- left as they stand, as the existing drawer leaves them.
CREATE OR REPLACE FUNCTION gateway_completion.hand_in_with_id(
  target varchar, delivered date, raw_value varchar, normalized varchar,
  entered_by varchar, at timestamptz, reference_id varchar, verification_id varchar
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  visit record;
  holder record;
BEGIN
  SELECT a.status, a.delivery_type, a.activity_type, a.cluster_id, a.deleted_at
    INTO visit FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR visit.status IS DISTINCT FROM 'completion_started'
     OR visit.delivery_type IS DISTINCT FROM 'staff'
     OR NOT (visit.activity_type = ANY (ARRAY['school_visit', 'donor_visit', 'story_gathering_visit',
                                              'school_invitation', 'social_visit']::varchar[]))
     OR visit.cluster_id IS NOT NULL OR visit.deleted_at IS NOT NULL THEN
    RETURN 'changed';
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_salesforce_reference r WHERE r.activity_id = target) THEN
    RETURN 'own_reference';
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_completion_verification v WHERE v.activity_id = target) THEN
    RETURN 'verification';
  END IF;
  SELECT h.id, h.status, h.deleted_at INTO holder
    FROM public.activity_salesforce_reference r JOIN public.activity h ON h.id = r.activity_id
   WHERE r.normalized_value = normalized;
  IF FOUND THEN
    IF holder.deleted_at IS NOT NULL OR holder.status IN ('cancelled', 'deferred') THEN
      RETURN 'called_off';
    END IF;
    RETURN 'held:' || holder.id;
  END IF;
  INSERT INTO public.activity_salesforce_reference (id, created_at, updated_at, raw_value, normalized_value,
    activity_type, expected_prefix, entry_source, entered_by, entered_at, activity_id)
  VALUES (reference_id, at, at, raw_value, normalized, visit.activity_type, 'SVE-', 'staff_self_entry',
    entered_by, at, target);
  UPDATE public.activity a SET
    salesforce_activity_id = normalized, salesforce_activity_type = 'visit',
    actual_delivery_date = delivered, status = 'submitted_to_pl', updated_at = at
  WHERE a.id = target;
  INSERT INTO public.activity_completion_verification (id, created_at, updated_at, salesforce_id, entered_by,
    entered_at, status, activity_id)
  VALUES (verification_id, at, at, normalized, entered_by, at, 'pending', target);
  RETURN '';
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.hand_in_with_id(varchar, date, varchar, varchar, varchar, timestamptz,
  varchar, varchar) FROM PUBLIC;

-- Submit for review for an officer's staff school visit outside a cluster:
-- '' when it was handed in to the Programme Lead, 'not_ready' or 'no_id' for
-- the service's own refusals, 'changed' when it is no longer that case.
CREATE OR REPLACE FUNCTION gateway_completion.submit_for_review(
  target varchar, entered_by varchar, at timestamptz, verification_id varchar
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  visit record;
  was_returned boolean;
BEGIN
  SELECT a.status, a.delivery_type, a.activity_type, a.cluster_id, a.deleted_at, a.salesforce_activity_id
    INTO visit FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR visit.delivery_type IS DISTINCT FROM 'staff'
     OR NOT (visit.activity_type = ANY (ARRAY['school_visit', 'donor_visit', 'story_gathering_visit',
                                              'school_invitation', 'social_visit']::varchar[]))
     OR visit.cluster_id IS NOT NULL OR visit.deleted_at IS NOT NULL THEN
    RETURN 'changed';
  END IF;
  IF NOT (visit.status = ANY (ARRAY['completion_started', 'in_progress', 'evidence_uploaded', 'evidence_accepted',
                                    'salesforce_id_required', 'returned', 'returned_by_pl', 'returned_by_ia',
                                    'completed']::varchar[])) THEN
    RETURN 'not_ready';
  END IF;
  IF COALESCE(visit.salesforce_activity_id, '') = '' THEN
    RETURN 'no_id';
  END IF;
  was_returned := visit.status IN ('returned', 'returned_by_pl', 'returned_by_ia');
  UPDATE public.activity a SET status = 'submitted_to_pl',
    ia_verification_status = CASE WHEN was_returned THEN 'pending' ELSE a.ia_verification_status END,
    updated_at = at
  WHERE a.id = target;
  IF was_returned THEN
    UPDATE public.ia_verification v SET status = 'pending' WHERE v.activity_id = target AND v.status = 'returned';
  END IF;
  UPDATE public.activity_completion_verification v SET salesforce_id = visit.salesforce_activity_id,
    entered_by = submit_for_review.entered_by, status = 'pending', updated_at = at
  WHERE v.activity_id = target;
  IF NOT FOUND THEN
    INSERT INTO public.activity_completion_verification (id, created_at, updated_at, salesforce_id, entered_by,
      entered_at, status, activity_id)
    VALUES (verification_id, at, at, visit.salesforce_activity_id, submit_for_review.entered_by, at, 'pending', target);
  END IF;
  RETURN '';
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.submit_for_review(varchar, varchar, timestamptz, varchar) FROM PUBLIC;

-- Attendance (services.record_attendance) on staff work at one school outside
-- a cluster: the head count, other participants and the register set as the
-- view posts them (none), and work not yet started started. '' when kept,
-- 'closed' under the lock, 'changed' when it is no longer that case.
CREATE OR REPLACE FUNCTION gateway_completion.record_attendance(
  target varchar, teachers integer, leaders integer, at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  work record;
BEGIN
  SELECT a.status, a.delivery_type, a.activity_type, a.cluster_id, a.deleted_at
    INTO work FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR work.delivery_type IS DISTINCT FROM 'staff' OR work.cluster_id IS NOT NULL
     OR work.deleted_at IS NOT NULL
     OR NOT (work.activity_type = ANY (ARRAY['school_visit', 'donor_visit', 'story_gathering_visit',
                                             'school_invitation', 'social_visit', 'in_school_training',
                                             'training', 'school_improvement_training']::varchar[])) THEN
    RETURN 'changed';
  END IF;
  IF work.status IN ('closed', 'cancelled', 'rejected', 'deferred') THEN
    RETURN 'closed';
  END IF;
  UPDATE public.activity a SET teachers_attended = teachers, leaders_attended = leaders, other_participants = 0,
    attended_school_ids = '{}',
    status = CASE WHEN work.status IN ('scheduled', 'in_progress', 'partner_scheduled', 'assigned_to_partner',
                                       'rescheduled') THEN 'completion_started' ELSE work.status END,
    updated_at = at
  WHERE a.id = target;
  RETURN '';
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.record_attendance(varchar, integer, integer, timestamptz) FROM PUBLIC;
-- A staff cluster meeting's completion (my_plan_views.complete_activity_action
-- → services.start_completion and services.complete) with no visiting school
-- on its register: started if it was not, its Training ID reserved, the
-- register mirrored (_sync_cluster_attendance with release_absent: a ticked
-- member attends, an unticked one no longer does, an invited one left
-- unticked loses its invitation), and handed in to the Programme Lead.
-- attended is the posted register, stripped and de-duplicated; only the
-- cluster's member schools are kept (_cluster_member_school_ids). answer is
-- '' when handed in, otherwise what hand_in_school_visit answers, or
-- 'guests' when the register holds a visiting school; released is the
-- schools whose invitations were removed, sorted.
CREATE OR REPLACE FUNCTION gateway_completion.hand_in_cluster_meeting(
  target varchar, delivered date, raw_value varchar, normalized varchar,
  teachers integer, leaders integer, attended varchar[],
  outcome text, observations text, follow_up text,
  entered_by varchar, at timestamptz, reference_id varchar, verification_id varchar,
  OUT answer text, OUT released varchar[]
)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  work record;
  holder record;
  members varchar[];
  member varchar;
BEGIN
  released := '{}';
  SELECT a.status, a.delivery_type, a.activity_type, a.cluster_id, a.deleted_at,
         a.teachers_per_school, a.leaders_per_school, a.other_per_school
    INTO work FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR work.delivery_type IS DISTINCT FROM 'staff' OR work.activity_type IS DISTINCT FROM 'cluster_meeting'
     OR work.cluster_id IS NULL OR work.deleted_at IS NOT NULL
     OR NOT (work.status = ANY (ARRAY['completion_started', 'scheduled', 'in_progress', 'partner_scheduled',
                                      'assigned_to_partner', 'rescheduled']::varchar[])) THEN
    answer := 'changed';
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_salesforce_reference r WHERE r.activity_id = target) THEN
    answer := 'own_reference';
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM public.activity_completion_verification v WHERE v.activity_id = target) THEN
    answer := 'verification';
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM public.cluster_activity_attendance x WHERE x.activity_id = target AND x.is_guest) THEN
    answer := 'guests';
    RETURN;
  END IF;
  SELECT h.id, h.status, h.deleted_at INTO holder
    FROM public.activity_salesforce_reference r JOIN public.activity h ON h.id = r.activity_id
   WHERE r.normalized_value = normalized;
  IF FOUND THEN
    IF holder.deleted_at IS NOT NULL OR holder.status IN ('cancelled', 'deferred') THEN
      answer := 'called_off';
      RETURN;
    END IF;
    answer := 'held:' || holder.id;
    RETURN;
  END IF;
  INSERT INTO public.activity_salesforce_reference (id, created_at, updated_at, raw_value, normalized_value,
    activity_type, expected_prefix, entry_source, entered_by, entered_at, activity_id)
  VALUES (reference_id, at, at, raw_value, normalized, work.activity_type, 'TS-', 'staff_self_entry',
    entered_by, at, target);
  SELECT COALESCE(array_agg(t.id ORDER BY t.n), '{}') INTO members
    FROM unnest(attended) WITH ORDINALITY AS t(id, n)
   WHERE EXISTS (SELECT 1 FROM public.school s WHERE s.id = t.id AND s.cluster_id = work.cluster_id
                 AND s.deleted_at IS NULL);
  FOREACH member IN ARRAY members LOOP
    UPDATE public.cluster_activity_attendance x SET attended = true, recorded_by = entered_by, updated_at = at
     WHERE x.activity_id = target AND x.school_id = member AND NOT x.attended;
    IF NOT EXISTS (SELECT 1 FROM public.cluster_activity_attendance x WHERE x.activity_id = target
                   AND x.school_id = member) THEN
      INSERT INTO public.cluster_activity_attendance (created_at, updated_at, invited, attended, is_guest, teachers,
        leaders, other, recorded_by, activity_id, school_id)
      VALUES (at, at, false, true, false, work.teachers_per_school, work.leaders_per_school, work.other_per_school,
        entered_by, target, member);
    END IF;
  END LOOP;
  UPDATE public.cluster_activity_attendance x SET attended = false
   WHERE x.activity_id = target AND x.attended AND NOT (x.school_id = ANY (members));
  SELECT COALESCE(array_agg(x.school_id ORDER BY x.school_id COLLATE "C"), '{}') INTO released
    FROM public.cluster_activity_attendance x
   WHERE x.activity_id = target AND x.invited AND NOT x.is_guest AND NOT (x.school_id = ANY (members));
  DELETE FROM public.cluster_activity_attendance x
   WHERE x.activity_id = target AND x.invited AND NOT x.is_guest AND NOT (x.school_id = ANY (members));
  UPDATE public.activity a SET
    execution_started_at = CASE WHEN work.status = 'completion_started' THEN a.execution_started_at
                                ELSE COALESCE(a.execution_started_at, at) END,
    salesforce_activity_id = normalized, salesforce_activity_type = 'training',
    teachers_attended = teachers, leaders_attended = leaders, other_participants = 0,
    attended_school_ids = members, actual_delivery_date = delivered,
    actual_outcome = COALESCE(outcome, a.actual_outcome),
    actual_observations = COALESCE(observations, a.actual_observations),
    follow_up_note = COALESCE(follow_up, a.follow_up_note),
    status = 'submitted_to_pl',
    evidence_status = CASE WHEN a.evidence_status = 'none' THEN 'accepted' ELSE a.evidence_status END,
    updated_at = at
  WHERE a.id = target;
  INSERT INTO public.activity_completion_verification (id, created_at, updated_at, salesforce_id, entered_by,
    entered_at, status, activity_id)
  VALUES (verification_id, at, at, normalized, entered_by, at, 'pending', target);
  answer := '';
END
$fn$;
REVOKE ALL ON FUNCTION gateway_completion.hand_in_cluster_meeting(varchar, date, varchar, varchar, integer,
  integer, varchar[], text, text, text, varchar, timestamptz, varchar, varchar) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_completion TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.hand_in_school_visit(varchar, date, varchar, varchar, integer,
  integer, integer, text, text, text, varchar, timestamptz, varchar, varchar) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.hand_in_with_id(varchar, date, varchar, varchar, varchar, timestamptz,
  varchar, varchar) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.start_visit(varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.submit_for_review(varchar, varchar, timestamptz, varchar)
  TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.record_attendance(varchar, integer, integer, timestamptz)
  TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_completion.hand_in_cluster_meeting(varchar, date, varchar, varchar, integer,
  integer, varchar[], text, text, text, varchar, timestamptz, varchar, varchar) TO edify_activities_rw;
