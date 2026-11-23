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
-- One milestone credit per rule and activity.
GRANT SELECT (rule_id, activity_id) ON hr_milestone_progress_credit TO edify_pl_review_owner;
GRANT INSERT (id, created_at, updated_at, rule_id, activity_id, credited_value, source_snapshot,
              credited_at, reversed_reason)
  ON hr_milestone_progress_credit TO edify_pl_review_owner;
-- The owner's year, marked for the targets ledger to rebuild.
GRANT SELECT (owner_id, fy, marked_at) ON target_ledger_dirty TO edify_pl_review_owner;
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
                            'integrations.salesforce.activity']::varchar[])) THEN
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
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_pl_review TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.approve_completion(varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.return_completion(varchar, varchar, text, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.enqueue_event(varchar, varchar, jsonb, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.mark_ledger(varchar, varchar, timestamptz) TO edify_activities_rw;
GRANT EXECUTE ON FUNCTION gateway_pl_review.record_credit(varchar, varchar, varchar, numeric, jsonb, timestamptz) TO edify_activities_rw;
