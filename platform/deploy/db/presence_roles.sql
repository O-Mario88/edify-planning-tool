-- The presence stamp, for the requests the Go gateway answers itself
-- (docs/migration/65). The existing application stamps every request a
-- signed-in person makes in SlidingSessionMiddleware
-- (apps.accounts.presence.touch_presence / _next_beat / credit_presence_time):
-- one UPDATE of the person's own "user" row (last_seen_at, online_since,
-- last_seen_path, last_seen_action, last_seen_login_id), guarded on the beat
-- the request read so two requests cannot credit the same minutes, and, when
-- that guarded UPDATE wins, the time since the beat before it added to that
-- beat's slot in presence_time and to its sign-in's login_event
-- (active_seconds, last_active_at). A request Go answers never reaches that
-- middleware, so Go asks this one function for the same beat.
--
-- The coordinator's decision (2026-11-13): "a narrow writer role or function
-- limited to those columns". The function's owner is a NOLOGIN role nobody
-- is a member of, holding only those columns (and the SELECTs its filters
-- read). The gateway holds no UPDATE of "user", login_event or presence_time
-- of its own: it may only ask this function, which writes the beat of the
-- one person it names, at the database's own clock (a beat can never be
-- dated), and credits only the time that really passed since the beat the
-- caller read (the guard), bounded by the idle and final-beat thresholds.
-- What a beat's slot is called (section, working_on) is presence_labels'
-- reading of the earlier beat, computed by the caller.
--
-- EXECUTE is granted to edify_presence_rw only, which edify_gateway is a
-- member of. Applied after roles.sql (apply-roles.sh, the integration
-- TestMain). Idempotent. New database objects: production needs the owner's
-- approval at cutover.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_presence_owner') THEN
    CREATE ROLE edify_presence_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_presence_rw') THEN
    CREATE ROLE edify_presence_rw NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_presence_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_presence_rw;
GRANT USAGE ON SCHEMA public TO edify_presence_owner;
GRANT SELECT (id, last_seen_at, online_since, last_seen_path, last_seen_action, last_seen_login_id)
  ON "user" TO edify_presence_owner;
GRANT UPDATE (last_seen_at, online_since, last_seen_path, last_seen_action, last_seen_login_id)
  ON "user" TO edify_presence_owner;
GRANT SELECT (id, at, active_seconds, last_active_at) ON login_event TO edify_presence_owner;
GRANT UPDATE (active_seconds, last_active_at) ON login_event TO edify_presence_owner;
GRANT SELECT (id, user_id, day, section, working_on, seconds) ON presence_time TO edify_presence_owner;
GRANT INSERT (id, user_id, day, section, working_on, seconds) ON presence_time TO edify_presence_owner;
GRANT UPDATE (seconds) ON presence_time TO edify_presence_owner;

CREATE SCHEMA IF NOT EXISTS gateway_presence AUTHORIZATION edify_presence_owner;
REVOKE ALL ON SCHEMA gateway_presence FROM PUBLIC;

SET ROLE edify_presence_owner;
-- beat is _next_beat with touch_presence's values. page NULL: the request
-- has no footprint (path and action are left as they are); login_id NULL:
-- no sign-in to name. previous_seen NULL: no beat to credit (none read, or
-- its page is empty or untracked), so the UPDATE is not guarded. Returns the
-- seconds credited (0 when none).
CREATE OR REPLACE FUNCTION gateway_presence.beat(
  target_user varchar,
  page varchar,
  action varchar,
  login_id varchar,
  previous_seen timestamptz,
  previous_login varchar,
  previous_section varchar,
  previous_working_on varchar,
  new_slot_id varchar,
  idle_seconds integer,
  final_seconds integer,
  online_window_seconds integer,
  time_zone text
) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  stamp timestamptz := clock_timestamp();
  won integer := 0;
  gap double precision;
  credited integer;
BEGIN
  IF target_user IS NULL OR target_user = '' THEN
    RETURN 0;
  END IF;
  IF idle_seconds IS NULL OR idle_seconds < 1 OR idle_seconds > 86400
     OR final_seconds IS NULL OR final_seconds < 0 OR final_seconds > idle_seconds
     OR online_window_seconds IS NULL OR online_window_seconds < 1 OR online_window_seconds > 86400 THEN
    RAISE EXCEPTION 'gateway_presence.beat: thresholds out of range';
  END IF;
  IF previous_seen IS NOT NULL THEN
    IF previous_section IS NULL OR previous_working_on IS NULL OR new_slot_id IS NULL OR new_slot_id = '' THEN
      RAISE EXCEPTION 'gateway_presence.beat: a credited beat needs its slot';
    END IF;
    UPDATE public."user" u SET
      last_seen_at = stamp,
      online_since = CASE
        WHEN u.online_since IS NULL OR u.last_seen_at IS NULL
          OR u.last_seen_at < stamp - make_interval(secs => online_window_seconds) THEN stamp
        ELSE u.online_since END,
      last_seen_path = CASE WHEN page IS NULL THEN u.last_seen_path ELSE left(page, 255) END,
      last_seen_action = CASE WHEN page IS NULL THEN u.last_seen_action ELSE left(coalesce(action, ''), 255) END,
      last_seen_login_id = CASE WHEN login_id IS NULL OR login_id = '' THEN u.last_seen_login_id ELSE left(login_id, 30) END
    WHERE u.id = target_user AND u.last_seen_at = previous_seen;
    GET DIAGNOSTICS won = ROW_COUNT;
  END IF;
  IF won = 0 THEN
    UPDATE public."user" u SET
      last_seen_at = stamp,
      online_since = CASE
        WHEN u.online_since IS NULL OR u.last_seen_at IS NULL
          OR u.last_seen_at < stamp - make_interval(secs => online_window_seconds) THEN stamp
        ELSE u.online_since END,
      last_seen_path = CASE WHEN page IS NULL THEN u.last_seen_path ELSE left(page, 255) END,
      last_seen_action = CASE WHEN page IS NULL THEN u.last_seen_action ELSE left(coalesce(action, ''), 255) END,
      last_seen_login_id = CASE WHEN login_id IS NULL OR login_id = '' THEN u.last_seen_login_id ELSE left(login_id, 30) END
    WHERE u.id = target_user;
    RETURN 0;
  END IF;
  -- _credit_for: all of the gap while active, the final beat after idling.
  gap := extract(epoch FROM stamp - previous_seen);
  IF gap <= 0 THEN
    credited := 0;
  ELSIF gap <= idle_seconds THEN
    credited := floor(gap)::integer;
  ELSE
    credited := final_seconds;
  END IF;
  IF credited <= 0 THEN
    RETURN 0;
  END IF;
  IF previous_login IS NOT NULL AND previous_login <> '' THEN
    UPDATE public.login_event e SET
      active_seconds = e.active_seconds + credited,
      last_active_at = GREATEST(COALESCE(e.last_active_at, e.at), previous_seen + make_interval(secs => credited))
    WHERE e.id = previous_login;
  END IF;
  INSERT INTO public.presence_time AS p (id, user_id, day, section, working_on, seconds)
  VALUES (new_slot_id, target_user, (previous_seen AT TIME ZONE time_zone)::date,
          left(previous_section, 64), left(previous_working_on, 128), credited)
  ON CONFLICT (user_id, day, section, working_on) DO UPDATE SET seconds = p.seconds + EXCLUDED.seconds;
  RETURN credited;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_presence.beat(varchar, varchar, varchar, varchar, timestamptz, varchar, varchar, varchar, varchar, integer, integer, integer, text) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_presence TO edify_presence_rw;
GRANT EXECUTE ON FUNCTION gateway_presence.beat(varchar, varchar, varchar, varchar, timestamptz, varchar, varchar, varchar, varchar, integer, integer, integer, text)
  TO edify_presence_rw;
GRANT edify_presence_rw TO edify_gateway;
