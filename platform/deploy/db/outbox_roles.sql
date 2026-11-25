-- Django's outbox (apps.outbox.services) drained by Go with the existing
-- application absent: the Go worker claims only the event types it has a
-- handler for, so an event Go cannot run is never marked done and waits for
-- a handler. Claim and finish keep Django's rules: due is pending and
-- scheduled, or processing with an expired claim (a worker that died); a
-- reclaimed event counts the lost attempt and is dead-lettered when it has
-- used its attempts; a failure backs off 30 s × 2^attempts, at most an hour.
--
-- The functions' owner is a NOLOGIN role nobody is a member of, holding only
-- the outbox table. Applied by apply-roles.sh and the integration TestMain.
-- Idempotent. A new database object: production needs the owner's approval
-- at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_outbox_owner') THEN
    CREATE ROLE edify_outbox_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_outbox_owner;
GRANT USAGE ON SCHEMA public TO edify_outbox_owner;
GRANT SELECT, UPDATE (status, attempts, next_attempt_at, locked_by, locked_until, last_error, succeeded_at, updated_at)
  ON outbox_event TO edify_outbox_owner;

CREATE SCHEMA IF NOT EXISTS gateway_outbox AUTHORIZATION edify_outbox_owner;
REVOKE ALL ON SCHEMA gateway_outbox FROM PUBLIC;

SET ROLE edify_outbox_owner;
-- _claim_batch for the given event types: the claimed events, and those of
-- them dead-lettered as reclaimed (dead = true, not to be run).
CREATE OR REPLACE FUNCTION gateway_outbox.claim(
  p_types varchar[], p_worker varchar, p_now timestamptz, p_claim_seconds integer, p_limit integer
) RETURNS TABLE (id varchar, event_type varchar, payload jsonb, dead boolean)
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
BEGIN
  RETURN QUERY
  WITH due AS (
    SELECT e.id, e.status = 'processing' AS reclaimed
      FROM public.outbox_event e
     WHERE e.event_type = ANY (p_types)
       AND ((e.status = 'pending' AND e.next_attempt_at <= p_now)
            OR (e.status = 'processing' AND e.locked_until < p_now))
     ORDER BY e.next_attempt_at
     LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 500))
       FOR UPDATE SKIP LOCKED
  ), claimed AS (
    UPDATE public.outbox_event e SET
      status = CASE WHEN due.reclaimed AND e.attempts + 1 >= e.max_attempts THEN 'dead' ELSE 'processing' END,
      locked_by = CASE WHEN due.reclaimed AND e.attempts + 1 >= e.max_attempts THEN '' ELSE p_worker END,
      locked_until = CASE WHEN due.reclaimed AND e.attempts + 1 >= e.max_attempts THEN NULL
                          ELSE p_now + make_interval(secs => p_claim_seconds) END,
      attempts = CASE WHEN due.reclaimed THEN e.attempts + 1 ELSE e.attempts END,
      last_error = CASE WHEN due.reclaimed THEN 'Reclaimed after a worker died mid-handler.' ELSE e.last_error END
      FROM due WHERE e.id = due.id
    RETURNING e.id, e.event_type, e.payload, e.status = 'dead'
  )
  SELECT * FROM claimed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_outbox.claim(varchar[], varchar, timestamptz, integer, integer) FROM PUBLIC;

-- _finish: the attempt counted, and the event succeeded, backed off, or
-- dead-lettered. Answers the status left.
CREATE OR REPLACE FUNCTION gateway_outbox.finish(p_id varchar, p_error text, p_now timestamptz) RETURNS varchar
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v record;
  v_status varchar;
BEGIN
  SELECT e.attempts, e.max_attempts INTO v FROM public.outbox_event e WHERE e.id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN '';
  END IF;
  IF p_error IS NULL THEN
    v_status := 'succeeded';
    UPDATE public.outbox_event e SET attempts = v.attempts + 1, status = v_status, succeeded_at = p_now,
      last_error = '', locked_by = '', locked_until = NULL, updated_at = p_now WHERE e.id = p_id;
  ELSIF v.attempts + 1 >= v.max_attempts THEN
    v_status := 'dead';
    UPDATE public.outbox_event e SET attempts = v.attempts + 1, status = v_status, last_error = left(p_error, 4000),
      locked_by = '', locked_until = NULL, updated_at = p_now WHERE e.id = p_id;
  ELSE
    v_status := 'pending';
    UPDATE public.outbox_event e SET attempts = v.attempts + 1, status = v_status,
      next_attempt_at = p_now + make_interval(secs => LEAST(30 * (2 ^ (v.attempts + 1)), 3600)),
      last_error = left(p_error, 4000), locked_by = '', locked_until = NULL, updated_at = p_now WHERE e.id = p_id;
  END IF;
  RETURN v_status;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_outbox.finish(varchar, text, timestamptz) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_outbox TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_outbox.claim(varchar[], varchar, timestamptz, integer, integer) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_outbox.finish(varchar, text, timestamptz) TO edify_gateway;
