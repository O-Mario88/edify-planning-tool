-- M9 Programme Lead verification (approve & return) through two narrow
-- SECURITY DEFINER functions (docs/migration/03 §3.7, 185 Batch 2).
--
-- Mirrors apps.pl_review.services.confirm (_approve) and return_activity:
-- the gateway role never receives direct UPDATE grants on activity's
-- protected verification/review columns (dbguard protectedColumns). Instead,
-- edify_pl_review_owner (NOLOGIN, NOINHERIT, nobody a member) holds only the
-- exact columns written by PL approval and return, with no DELETE.
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_pl_review_owner') THEN
    CREATE ROLE edify_pl_review_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_pl_review_owner;
GRANT USAGE ON SCHEMA public TO edify_pl_review_owner;
GRANT SELECT (id, status, deleted_at, salesforce_activity_id, salesforce_record_type_snapshot)
  ON activity TO edify_pl_review_owner;
GRANT UPDATE (status, ia_verification_status, pl_reviewed_at, pl_reviewed_by,
              ia_confirmed_at, ia_confirmed_by, evidence_status, pl_review_note, updated_at)
  ON activity TO edify_pl_review_owner;
GRANT SELECT (activity_id, quarantined) ON evidence_record TO edify_pl_review_owner;
GRANT UPDATE (status, reviewed_by, reviewed_at) ON evidence_record TO edify_pl_review_owner;
GRANT SELECT (activity_id) ON ia_verification TO edify_pl_review_owner;
GRANT UPDATE (status, verified_by, verified_at) ON ia_verification TO edify_pl_review_owner;
-- The events a decision raises, for the existing application's workers.
GRANT SELECT (idempotency_key) ON outbox_event TO edify_pl_review_owner;
GRANT INSERT (id, created_at, updated_at, event_type, payload, idempotency_key, status, attempts,
              max_attempts, next_attempt_at, locked_by, last_error)
  ON outbox_event TO edify_pl_review_owner;
-- One milestone credit per rule and activity; a reversed one comes back.
GRANT SELECT (id, rule_id, activity_id) ON hr_milestone_progress_credit TO edify_pl_review_owner;
GRANT INSERT (id, created_at, updated_at, rule_id, activity_id, credited_value, source_snapshot,
              credited_at, reversed_reason)
  ON hr_milestone_progress_credit TO edify_pl_review_owner;
GRANT UPDATE (reversed_at, reversed_reason) ON hr_milestone_progress_credit TO edify_pl_review_owner;
-- A milestone's period figures, recomputed from its credits.
GRANT SELECT (id) ON hr_milestone_period_target TO edify_pl_review_owner;
GRANT UPDATE (actual_value, achievement_percentage, actual_source, snapshot_at, status, updated_at)
  ON hr_milestone_period_target TO edify_pl_review_owner;
-- The visit's staff SSA, its school's readiness and its Core package.
GRANT SELECT (id, school_id, fy, source_activity_id, deleted_at, verification_status, collector_type,
              collected_by_user_id, date_of_ssa)
  ON ssa_record TO edify_pl_review_owner;
GRANT UPDATE (verification_status, verified_by_user_id, verified_at, updated_at)
  ON ssa_record TO edify_pl_review_owner;
GRANT SELECT (id, school_id, name, current_fy_ssa_status, school_phone, primary_contact_name, enrollment,
              account_owner_id, account_owner_status, account_owner_name_raw, cluster_id, duplicate_status,
              latitude, longitude, school_type, sub_county_id)
  ON school TO edify_pl_review_owner;
-- School.save reconciles the school's open data quality issues.
GRANT SELECT (school_id) ON school_geo_point TO edify_pl_review_owner;
GRANT SELECT (id, school_id, issue_type, severity, current_value, suggested_fix, status, resolved_at,
              condition_key, created_at),
      INSERT (id, created_at, updated_at, school_id, issue_type, severity, field_name, current_value,
              suggested_fix, status, condition_key),
      UPDATE (status, resolved_at, severity, current_value, suggested_fix)
  ON data_quality_issue TO edify_pl_review_owner;
GRANT UPDATE (current_fy_ssa_status, planning_readiness, data_quality_score, data_quality_status, updated_at)
  ON school TO edify_pl_review_owner;
GRANT SELECT (school_id, fy, assessment_completed), UPDATE (assessment_completed)
  ON core_plan TO edify_pl_review_owner;
-- The recommendations the plan was answering.
GRANT SELECT (school_id, cluster_id, attended_school_ids, catalogue_item_id) ON activity TO edify_pl_review_owner;
GRANT SELECT (activity_id, school_id, attended) ON cluster_activity_attendance TO edify_pl_review_owner;
GRANT SELECT (id, school_id, planned_activity_id, state) ON ssa_recommendation TO edify_pl_review_owner;
GRANT UPDATE (state, planned_activity_id, decided_at, updated_at, decision_reason)
  ON ssa_recommendation TO edify_pl_review_owner;
-- A loan-use visit, linked to the oldest loan need it answers.
GRANT SELECT (id, stable_code) ON activity_catalogue_item TO edify_pl_review_owner;
GRANT SELECT (id, school_id, case_id) ON bt_mfi_loan TO edify_pl_review_owner;
GRANT SELECT (id, loan_id, activity_id, status, due_date, created_at),
      UPDATE (activity_id, status, updated_at)
  ON bt_loan_verification_requirement TO edify_pl_review_owner;
GRANT SELECT (activity_id), INSERT (id, created_at, updated_at, activity_id, case_id, loan_id, purpose)
  ON bt_activity_link TO edify_pl_review_owner;
-- The owner's year, marked for the targets ledger to rebuild.
GRANT SELECT (owner_id, fy, marked_at) ON target_ledger_dirty TO edify_pl_review_owner;
-- hand_in_entered (the scheduler's hand_in_entered_work).
GRANT SELECT (evidence_status, responsible_staff_id) ON activity TO edify_pl_review_owner;
GRANT SELECT (activity_id), INSERT (id, created_at, updated_at, salesforce_id, entered_by, entered_at, status, activity_id),
      UPDATE (salesforce_id, entered_by, status, updated_at)
  ON activity_completion_verification TO edify_pl_review_owner;
GRANT INSERT (owner_id, fy, marked_at), UPDATE (marked_at) ON target_ledger_dirty TO edify_pl_review_owner;

CREATE SCHEMA IF NOT EXISTS gateway_pl_review AUTHORIZATION edify_pl_review_owner;
REVOKE ALL ON SCHEMA gateway_pl_review FROM PUBLIC;

SET ROLE edify_pl_review_owner;

CREATE OR REPLACE FUNCTION gateway_pl_review.approve_completion(
  target varchar, reviewer_id varchar, at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  visit record;
BEGIN
  SELECT a.status, a.deleted_at, COALESCE(btrim(a.salesforce_activity_id), '') AS sfid,
         upper(COALESCE(a.salesforce_record_type_snapshot, '')) AS record_type
    INTO visit FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR visit.deleted_at IS NOT NULL
     OR NOT (visit.status = ANY (ARRAY['submitted_to_pl', 'awaiting_ia_verification']::varchar[])) THEN
    RETURN 'changed';
  END IF;
  -- Work Salesforce does not record (NO_SALESFORCE_RECORD_TYPES) carries no ID.
  IF visit.sfid = '' AND visit.record_type <> 'NONE' THEN
    RETURN 'no_sfid';
  END IF;
  UPDATE public.activity SET
    status = 'ia_verified',
    ia_verification_status = 'confirmed',
    pl_reviewed_at = at,
    pl_reviewed_by = reviewer_id,
    ia_confirmed_at = at,
    ia_confirmed_by = reviewer_id,
    evidence_status = 'accepted',
    updated_at = at
  WHERE id = target;
  UPDATE public.evidence_record SET
    status = 'accepted',
    reviewed_by = reviewer_id,
    reviewed_at = at
  WHERE activity_id = target AND quarantined = false;
  UPDATE public.ia_verification SET
    status = 'confirmed',
    verified_by = reviewer_id,
    verified_at = at
  WHERE activity_id = target;
  RETURN '';
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_pl_review.return_completion(
  target varchar, reviewer_id varchar, note text, at timestamptz
) RETURNS text
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  visit record;
BEGIN
  IF COALESCE(btrim(note), '') = '' THEN
    RETURN 'no_reason';
  END IF;
  SELECT a.status, a.deleted_at
    INTO visit FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR visit.deleted_at IS NOT NULL
     OR NOT (visit.status = ANY (ARRAY['submitted_to_pl', 'awaiting_ia_verification']::varchar[])) THEN
    RETURN 'changed';
  END IF;
  UPDATE public.activity SET
    status = 'returned_by_pl',
    pl_review_note = btrim(note),
    pl_reviewed_at = at,
    pl_reviewed_by = reviewer_id,
    updated_at = at
  WHERE id = target;
  RETURN '';
END
$fn$;

-- apps.outbox.services.enqueue for the three events a decision raises: a
-- repeat of a key converges on the row already there.
CREATE OR REPLACE FUNCTION gateway_pl_review.enqueue_event(
  event_id varchar, kind varchar, body jsonb, idem_key varchar, at timestamptz
) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  IF NOT (kind = ANY (ARRAY['bt.activity.state_changed', 'projects.impact.refresh',
                            'integrations.salesforce.activity', 'bt.ssa.confirmed',
                            'ssa.recommendations.generate', 'projects.baselines.capture']::varchar[])) THEN
    RAISE EXCEPTION 'plreview: % is not an event a review raises', kind;
  END IF;
  INSERT INTO public.outbox_event (id, created_at, updated_at, event_type, payload, idempotency_key,
                                   status, attempts, max_attempts, next_attempt_at, locked_by, last_error)
  VALUES (event_id, at, at, kind, body, idem_key, 'pending', 0, 8, at, '', '')
  ON CONFLICT (idempotency_key) DO NOTHING;
  RETURN FOUND;
END
$fn$;

-- record_activity_progress's get_or_create for one rule and activity.
CREATE OR REPLACE FUNCTION gateway_pl_review.record_credit(
  credit_id varchar, rule varchar, target varchar, amount numeric, snapshot jsonb, at timestamptz
) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  INSERT INTO public.hr_milestone_progress_credit (id, created_at, updated_at, rule_id, activity_id,
                                                   credited_value, source_snapshot, credited_at, reversed_reason)
  VALUES (credit_id, at, at, rule, target, amount, snapshot, at, '')
  ON CONFLICT (rule_id, activity_id) DO NOTHING;
  RETURN FOUND;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_pl_review.record_credit(varchar, varchar, varchar, numeric, jsonb, timestamptz) FROM PUBLIC;

-- reverse_activity_progress undone: the same row counts again.
CREATE OR REPLACE FUNCTION gateway_pl_review.revive_credits(credit_ids varchar[])
RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.hr_milestone_progress_credit
     SET reversed_at = NULL, reversed_reason = ''
   WHERE id = ANY (credit_ids);
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

-- refresh_period_targets' save of one period's figures.
CREATE OR REPLACE FUNCTION gateway_pl_review.update_period_target(
  target_id varchar, actual numeric, achievement numeric, new_status varchar, at timestamptz
) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  UPDATE public.hr_milestone_period_target
     SET actual_value = actual, achievement_percentage = achievement,
         actual_source = 'MilestoneProgressCredit', snapshot_at = at, status = new_status, updated_at = at
   WHERE id = target_id;
$fn$;

-- apps.schools.data_quality.reconcile_issues for one school, as School.save
-- runs it: a condition that cleared is resolved, one that persists keeps its
-- row and its assignee, one a person resolved reopens, a new one is added.
-- Multiple-partner issues are another module's to close.
CREATE OR REPLACE FUNCTION gateway_pl_review.reconcile_school_issues(school_pk varchar, at timestamptz)
RETURNS void
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  place record;
  want record;
  located boolean;
  wanted jsonb;
  fresh varchar[];
  issue_key varchar;
  held varchar;
BEGIN
  SELECT sc.id, sc.latitude, sc.longitude, sc.school_phone, sc.primary_contact_name, sc.enrollment, sc.school_type,
         sc.sub_county_id, sc.duplicate_status, sc.account_owner_id, sc.account_owner_status, sc.account_owner_name_raw,
         sc.cluster_id, sc.current_fy_ssa_status
    INTO place FROM public.school sc WHERE sc.id = school_pk;
  located := (place.latitude IS NOT NULL AND place.longitude IS NOT NULL)
             OR EXISTS (SELECT 1 FROM public.school_geo_point g WHERE g.school_id = place.id);
  SELECT COALESCE(jsonb_agg(jsonb_build_object('issue_type', v.issue_type, 'severity', v.severity, 'field_name', v.field_name,
                                                'current_value', v.current_value, 'suggested_fix', v.suggested_fix)), '[]'::jsonb)
    INTO wanted
    FROM (VALUES
      ('no_coordinates', 'warning', 'latitude', NULL::text,
       'Capture GPS coordinates on the next visit, or set a geo point in Route Intelligence', NOT located),
      ('missing_phone', 'warning', 'school_phone', NULL, 'Add school phone number', COALESCE(place.school_phone, '') = ''),
      ('missing_contact', 'warning', 'primary_contact_name', NULL, 'Add primary contact name',
       COALESCE(place.primary_contact_name, '') = ''),
      ('missing_enrollment', 'warning', 'enrollment', place.enrollment::text, 'Update school pupil enrollment counts',
       place.enrollment IS NULL OR place.enrollment <= 0),
      ('missing_school_type', 'warning', 'school_type', NULL, 'Specify whether school is Core, Client, or Partner',
       COALESCE(place.school_type, '') = ''),
      ('missing_sub_county', 'warning', 'sub_county', NULL, 'Assign sub-county location', COALESCE(place.sub_county_id, '') = ''),
      ('duplicate_risk', 'warning', 'duplicate_status', NULL, 'Review and resolve potential duplicate school conflict',
       place.duplicate_status = 'potential'),
      ('unmatched_staff', 'warning', 'account_owner_id', place.account_owner_name_raw::text,
       'Match raw owner name to a registered staff user',
       COALESCE(place.account_owner_id, '') = '' OR place.account_owner_status <> 'matched'),
      ('no_cluster', 'critical', 'cluster_id', NULL, 'Add school to an active cluster', COALESCE(place.cluster_id, '') = ''),
      ('no_ssa', 'info', 'current_fy_ssa_status', NULL, 'Collect and upload School Self-Assessment (SSA)',
       place.current_fy_ssa_status <> 'done')
    ) AS v(issue_type, severity, field_name, current_value, suggested_fix, applies)
   WHERE v.applies;
  SELECT COALESCE(array_agg('school:' || place.id || '|dq:' || (w ->> 'issue_type')), ARRAY[]::varchar[])
    INTO fresh FROM jsonb_array_elements(wanted) AS w;

  UPDATE public.data_quality_issue d SET status = 'resolved', resolved_at = at
   WHERE d.id IN (
     SELECT DISTINCT ON (o.condition_key) o.id FROM public.data_quality_issue o
      WHERE o.school_id = place.id AND o.status = 'open' AND o.issue_type <> 'multiple_partner_support'
        AND (o.condition_key IS NULL OR NOT o.condition_key = ANY (fresh))
      ORDER BY o.condition_key, o.created_at);

  FOR want IN SELECT * FROM jsonb_to_recordset(wanted)
                AS x(issue_type varchar, severity varchar, field_name varchar, current_value text, suggested_fix text) LOOP
    issue_key := 'school:' || place.id || '|dq:' || want.issue_type;
    SELECT o.id INTO held FROM public.data_quality_issue o
     WHERE o.school_id = place.id AND o.status = 'open' AND o.condition_key = issue_key;
    IF FOUND THEN
      UPDATE public.data_quality_issue d
         SET severity = want.severity, current_value = want.current_value, suggested_fix = want.suggested_fix
       WHERE d.id = held AND (d.severity IS DISTINCT FROM want.severity OR d.current_value IS DISTINCT FROM want.current_value
                              OR d.suggested_fix IS DISTINCT FROM want.suggested_fix);
      CONTINUE;
    END IF;
    SELECT o.id INTO held FROM public.data_quality_issue o
     WHERE o.condition_key = issue_key AND o.status = 'resolved'
     ORDER BY o.resolved_at DESC NULLS FIRST LIMIT 1;
    IF FOUND THEN
      UPDATE public.data_quality_issue d
         SET status = 'open', resolved_at = NULL, severity = want.severity, current_value = want.current_value,
             suggested_fix = want.suggested_fix
       WHERE d.id = held;
    ELSE
      INSERT INTO public.data_quality_issue (id, created_at, updated_at, school_id, issue_type, severity, field_name,
                                             current_value, suggested_fix, status, condition_key)
      VALUES ('dq' || substr(md5(issue_key || ':' || clock_timestamp()::text), 1, 23), at, at, place.id, want.issue_type,
              want.severity, want.field_name, want.current_value, want.suggested_fix, 'open', issue_key);
    END IF;
  END LOOP;
END
$fn$;

-- pl_confirmation.confirm_visit_ssa and confirm_record for the visit's pending
-- staff SSA: the record, its school's readiness and its Core package. A year
-- another record already holds refuses the whole approval (SQLSTATE ED001).
CREATE OR REPLACE FUNCTION gateway_pl_review.confirm_visit_ssa(
  target varchar, reviewer varchar, at timestamptz, operational_fy varchar
) RETURNS TABLE (record_id varchar, school_pk varchar, school_name varchar, collected_by varchar, ssa_day timestamptz)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  item record;
  place record;
  ssa_state varchar;
  points integer;
  quality varchar;
  readiness varchar;
  done integer;
BEGIN
  FOR item IN
    SELECT s.id, s.school_id, s.fy, s.collected_by_user_id, s.date_of_ssa
      FROM public.ssa_record s
     WHERE s.source_activity_id = target AND s.deleted_at IS NULL AND s.verification_status = 'pending'
       AND s.collector_type IS DISTINCT FROM 'partner'
     ORDER BY s.id
       FOR UPDATE
  LOOP
    IF EXISTS (SELECT 1 FROM public.ssa_record o
                WHERE o.school_id = item.school_id AND o.fy = item.fy AND o.deleted_at IS NULL
                  AND o.verification_status = ANY (ARRAY['pending', 'confirmed']::varchar[]) AND o.id <> item.id) THEN
      RAISE EXCEPTION USING ERRCODE = 'ED001', MESSAGE = item.fy;
    END IF;
    UPDATE public.ssa_record
       SET verification_status = 'confirmed', verified_by_user_id = reviewer, verified_at = at, updated_at = at
     WHERE id = item.id;

    SELECT sc.id, sc.school_id, sc.name, sc.current_fy_ssa_status, sc.school_phone, sc.primary_contact_name,
           sc.enrollment, sc.account_owner_id, sc.account_owner_status, sc.cluster_id, sc.duplicate_status
      INTO place FROM public.school sc WHERE sc.id = item.school_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = place.id AND o.deleted_at IS NULL
                AND o.verification_status = 'confirmed' AND o.fy = operational_fy) THEN
      ssa_state := 'done';
    ELSIF EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = place.id AND o.deleted_at IS NULL
                   AND o.verification_status = 'pending' AND o.fy = operational_fy) THEN
      ssa_state := 'partner_assigned';
    ELSIF place.current_fy_ssa_status = ANY (ARRAY['done', 'partner_assigned']::varchar[]) THEN
      ssa_state := 'not_done';
    ELSE
      ssa_state := place.current_fy_ssa_status;
    END IF;
    -- School.recompute_quality_and_readiness.
    points := 100;
    IF COALESCE(place.school_phone, '') = '' THEN points := points - 15; END IF;
    IF COALESCE(place.primary_contact_name, '') = '' THEN points := points - 15; END IF;
    IF place.enrollment IS NULL OR place.enrollment <= 0 THEN points := points - 20; END IF;
    IF COALESCE(place.account_owner_id, '') = '' OR place.account_owner_status <> 'matched' THEN points := points - 20; END IF;
    IF COALESCE(place.cluster_id, '') = '' THEN points := points - 20; END IF;
    IF place.duplicate_status = 'potential' THEN
      quality := 'Duplicate Risk';
    ELSIF COALESCE(place.cluster_id, '') = '' OR points < 40 THEN
      quality := 'Missing Critical Data';
    ELSIF points >= 90 THEN
      quality := 'Clean';
    ELSIF points >= 70 THEN
      quality := 'Needs Review';
    ELSE
      quality := 'Needs Cleanup';
    END IF;
    IF COALESCE(place.cluster_id, '') = '' THEN
      readiness := 'requires_cluster';
    ELSIF ssa_state <> 'done' THEN
      readiness := 'ready_for_baseline_ssa';
    ELSE
      readiness := 'ready_for_support_planning';
    END IF;
    UPDATE public.school
       SET current_fy_ssa_status = ssa_state, planning_readiness = readiness,
           data_quality_score = GREATEST(points, 0), data_quality_status = quality, updated_at = at
     WHERE id = place.id;
    PERFORM gateway_pl_review.reconcile_school_issues(place.id, at);

    -- sync_core_assessment.
    done := CASE WHEN EXISTS (SELECT 1 FROM public.ssa_record o WHERE o.school_id = place.id AND o.fy = item.fy
                               AND o.deleted_at IS NULL AND o.verification_status = 'confirmed') THEN 1 ELSE 0 END;
    UPDATE public.core_plan c SET assessment_completed = done
     WHERE c.school_id = place.school_id AND c.fy = item.fy AND c.assessment_completed IS DISTINCT FROM done;

    record_id := item.id;
    school_pk := place.id;
    school_name := place.name;
    collected_by := item.collected_by_user_id;
    ssa_day := item.date_of_ssa;
    RETURN NEXT;
  END LOOP;
END
$fn$;

-- plan_alignment.settle_recommendations for verified work: the need is met,
-- or for a cluster session, met at the schools that attended and back in the
-- queue for the rest.
CREATE OR REPLACE FUNCTION gateway_pl_review.settle_recommendations(target varchar, at timestamptz)
RETURNS TABLE (delivered varchar[], released varchar[])
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  work record;
  attended varchar[];
BEGIN
  SELECT a.school_id, a.cluster_id, a.attended_school_ids INTO work FROM public.activity a WHERE a.id = target;
  IF work.cluster_id IS NOT NULL AND work.school_id IS NULL THEN
    SELECT array_agg(x.school_id) INTO attended FROM public.cluster_activity_attendance x
     WHERE x.activity_id = target AND x.attended;
    IF attended IS NULL THEN
      attended := COALESCE(work.attended_school_ids, ARRAY[]::varchar[]);
    END IF;
  END IF;
  SELECT COALESCE(array_agg(n.id ORDER BY n.id) FILTER (WHERE attended IS NULL OR n.school_id = ANY (attended)), ARRAY[]::varchar[]),
         COALESCE(array_agg(n.id ORDER BY n.id) FILTER (WHERE attended IS NOT NULL AND NOT COALESCE(n.school_id = ANY (attended), false)), ARRAY[]::varchar[])
    INTO delivered, released
    FROM public.ssa_recommendation n WHERE n.planned_activity_id = target AND n.state = 'planned';
  UPDATE public.ssa_recommendation n SET state = 'delivered', decided_at = at, updated_at = at WHERE n.id = ANY (delivered);
  UPDATE public.ssa_recommendation n
     SET state = 'accepted', planned_activity_id = NULL, decided_at = at, updated_at = at,
         decision_reason = 'The planned activity was not attended; the need is back in the queue.'
   WHERE n.id = ANY (released);
  RETURN NEXT;
END
$fn$;

-- The Business Transformation bridge: a loan-use visit answers the school's
-- oldest loan need still waiting for one.
CREATE OR REPLACE FUNCTION gateway_pl_review.link_loan_visit(link_id varchar, target varchar, at timestamptz)
RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  work record;
  need record;
BEGIN
  SELECT a.school_id, a.catalogue_item_id INTO work FROM public.activity a WHERE a.id = target;
  IF work.school_id IS NULL OR work.catalogue_item_id IS NULL
     OR NOT EXISTS (SELECT 1 FROM public.activity_catalogue_item c
                     WHERE c.id = work.catalogue_item_id AND c.stable_code = 'BT_UG_LOAN_USE_VERIFICATION') THEN
    RETURN false;
  END IF;
  SELECT r.id, l.id AS loan_id, l.case_id INTO need
    FROM public.bt_loan_verification_requirement r JOIN public.bt_mfi_loan l ON l.id = r.loan_id
   WHERE l.school_id = work.school_id AND r.activity_id IS NULL
     AND r.status = ANY (ARRAY['needs_scheduling', 'overdue']::varchar[])
   ORDER BY r.due_date, r.created_at
   LIMIT 1
     FOR UPDATE OF r;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  INSERT INTO public.bt_activity_link (id, created_at, updated_at, activity_id, case_id, loan_id, purpose)
  VALUES (link_id, at, at, target, need.case_id, need.loan_id, 'loan_use_verification')
  ON CONFLICT (activity_id) DO NOTHING;
  UPDATE public.bt_loan_verification_requirement
     SET activity_id = target, status = 'scheduled', updated_at = at
   WHERE id = need.id;
  RETURN true;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_pl_review.reconcile_school_issues(varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.revive_credits(varchar[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.update_period_target(varchar, numeric, numeric, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.confirm_visit_ssa(varchar, varchar, timestamptz, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.settle_recommendations(varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.link_loan_visit(varchar, varchar, timestamptz) FROM PUBLIC;

-- targets.ledger_sync.mark for one officer and year.
CREATE OR REPLACE FUNCTION gateway_pl_review.mark_ledger(
  officer varchar, year varchar, at timestamptz
) RETURNS void
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
  INSERT INTO public.target_ledger_dirty (owner_id, fy, marked_at) VALUES (officer, year, at)
  ON CONFLICT (owner_id, fy) DO UPDATE SET marked_at = EXCLUDED.marked_at;
$fn$;

REVOKE ALL ON FUNCTION gateway_pl_review.mark_ledger(varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.approve_completion(varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.return_completion(varchar, varchar, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_pl_review.enqueue_event(varchar, varchar, jsonb, varchar, timestamptz) FROM PUBLIC;
-- apps.pl_review.handed_in._hand_in: work holding its Salesforce ID, not yet
-- handed in, goes to the lead as Submit sends it, and its completion record
-- names the ID (update_or_create). False when it is no longer waiting.
CREATE OR REPLACE FUNCTION gateway_pl_review.hand_in_entered(
  target varchar, verification_id varchar, at timestamptz
) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  work record;
BEGIN
  SELECT a.status, a.evidence_status, COALESCE(a.salesforce_activity_id, '') AS sfid,
         COALESCE(NULLIF(a.responsible_staff_id, ''), 'system') AS owner
    INTO work FROM public.activity a WHERE a.id = target FOR UPDATE;
  IF NOT FOUND OR NOT (work.status = ANY (ARRAY['scheduled', 'rescheduled', 'in_progress', 'completion_started',
      'evidence_uploaded', 'evidence_accepted', 'salesforce_id_required', 'completed']::varchar[])) THEN
    RETURN false;
  END IF;
  UPDATE public.activity SET status = 'submitted_to_pl',
    evidence_status = CASE WHEN work.evidence_status = 'none' THEN 'accepted' ELSE work.evidence_status END,
    updated_at = at
  WHERE id = target;
  UPDATE public.activity_completion_verification SET salesforce_id = work.sfid, entered_by = work.owner,
    status = 'pending', updated_at = at
  WHERE activity_id = target;
  IF NOT FOUND THEN
    INSERT INTO public.activity_completion_verification (id, created_at, updated_at, salesforce_id, entered_by,
      entered_at, status, activity_id)
    VALUES (verification_id, at, at, work.sfid, work.owner, at, 'pending', target);
  END IF;
  RETURN true;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_pl_review.hand_in_entered(varchar, varchar, timestamptz) FROM PUBLIC;

RESET ROLE;

GRANT USAGE ON SCHEMA gateway_pl_review TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.approve_completion(varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.hand_in_entered(varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.return_completion(varchar, varchar, text, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.enqueue_event(varchar, varchar, jsonb, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.mark_ledger(varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.record_credit(varchar, varchar, varchar, numeric, jsonb, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.revive_credits(varchar[]) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.update_period_target(varchar, numeric, numeric, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.confirm_visit_ssa(varchar, varchar, timestamptz, varchar) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.settle_recommendations(varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.link_loan_visit(varchar, varchar, timestamptz) TO edify_activities_rw;
-- School.save's reconcile of the school's data-quality issues, after a save
-- that changes the school outside this schema (taking a school nobody holds).
GRANT EXECUTE ON FUNCTION gateway_pl_review.reconcile_school_issues(varchar, timestamptz) TO edify_activities_rw;
