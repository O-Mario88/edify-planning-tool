-- M11 Native Go Notification delivery and read-state transitions through
-- three narrow SECURITY DEFINER functions (docs/migration/03 §3.7, 185 Batch 5).
--
-- Eliminates the Django HTTP relay for cluster action notices
-- (apps/notifications/cluster_action_relay.py) and lets Go deliver workflow
-- notices and mark notifications read without granting direct INSERT/UPDATE
-- on public.notification to edify_gateway.
--
-- Idempotent. Applied by apply-roles.sh and integration TestMain.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'edify_notification_owner') THEN
    CREATE ROLE edify_notification_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT;
  END IF;
END
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM edify_notification_owner;
GRANT USAGE ON SCHEMA public TO edify_notification_owner;
GRANT SELECT (id, active_role, is_active, deleted_at) ON "user" TO edify_notification_owner;
GRANT SELECT (id, recipient_id, context_type, context_id, source_event_type, source_event_id, status, read_at)
  ON notification TO edify_notification_owner;
GRANT INSERT (id, created_at, updated_at, recipient_id, recipient_role, sender_id,
              title, body, category, context_type, context_id, target_route,
              action_label, action_required, priority, status,
              source_event_type, source_event_id, reminder_count)
  ON notification TO edify_notification_owner;
GRANT UPDATE (status, read_at, resolved_at, updated_at) ON notification TO edify_notification_owner;
GRANT SELECT, INSERT, UPDATE ON notification_preference TO edify_notification_owner;

CREATE SCHEMA IF NOT EXISTS gateway_notifications AUTHORIZATION edify_notification_owner;
REVOKE ALL ON SCHEMA gateway_notifications FROM PUBLIC;

SET ROLE edify_notification_owner;

CREATE OR REPLACE FUNCTION gateway_notifications.deliver(
  notif_id varchar, recipient varchar, sender varchar,
  notif_title varchar, notif_body text, notif_category varchar,
  ctx_type varchar, ctx_id varchar, route varchar,
  btn_label varchar, req_action boolean, prio varchar,
  evt_type varchar, evt_id varchar, at timestamptz
) RETURNS boolean
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  rec_role varchar;
BEGIN
  SELECT u.active_role INTO rec_role
    FROM public."user" u
   WHERE u.id = recipient AND u.is_active = true AND u.deleted_at IS NULL;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  IF COALESCE(evt_id, '') <> '' AND EXISTS (
    SELECT 1 FROM public.notification n
     WHERE n.recipient_id = recipient
       AND n.context_type = ctx_type
       AND n.context_id = ctx_id
       AND n.source_event_type = evt_type
       AND n.source_event_id = evt_id
  ) THEN
    RETURN false;
  END IF;
  INSERT INTO public.notification (
    id, created_at, updated_at, recipient_id, recipient_role, sender_id,
    title, body, category, context_type, context_id, target_route,
    action_label, action_required, priority, status,
    source_event_type, source_event_id, reminder_count
  ) VALUES (
    notif_id, at, at, recipient, rec_role, NULLIF(sender, ''),
    left(btrim(notif_title), 255), left(btrim(COALESCE(notif_body, '')), 4000),
    COALESCE(NULLIF(notif_category, ''), 'general'),
    NULLIF(ctx_type, ''), NULLIF(ctx_id, ''), NULLIF(left(route, 255), ''),
    NULLIF(left(btn_label, 64), ''), COALESCE(req_action, false),
    COALESCE(NULLIF(prio, ''), 'normal'), 'unread',
    NULLIF(left(evt_type, 64), ''), NULLIF(left(evt_id, 30), ''), 0
  );
  RETURN true;
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_notifications.mark_read(
  target_id varchar, owner_id varchar, at timestamptz
) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET status = 'read', read_at = COALESCE(read_at, at), updated_at = at
   WHERE id = target_id AND recipient_id = owner_id AND status = 'unread';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

CREATE OR REPLACE FUNCTION gateway_notifications.mark_all_read(
  owner_id varchar, at timestamptz
) RETURNS integer
  LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET status = 'read', read_at = COALESCE(read_at, at), updated_at = at
   WHERE recipient_id = owner_id AND status = 'unread';
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

-- A single selected notice may be archived in any live state.
-- An empty selection means the explicit "Archive All Read" operation.
CREATE OR REPLACE FUNCTION gateway_notifications.archive(owner_id varchar, target_id varchar)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification SET status = 'archived', updated_at = now()
   WHERE recipient_id = owner_id AND
         ((target_id <> '' AND id = target_id AND status <> 'archived') OR
          (target_id = '' AND status = 'read'));
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

-- Marks matching notifications resolved (e.g. closing an overdue reminder when
-- a school visit is handed in).
CREATE OR REPLACE FUNCTION gateway_notifications.resolve_context(
  evt_type varchar, ctx_type varchar, ctx_id varchar, at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET resolved_at = COALESCE(resolved_at, at),
         status      = CASE WHEN status = 'unread' THEN 'read' ELSE status END,
         read_at     = COALESCE(read_at, at),
         updated_at  = at
   WHERE context_type = ctx_type
     AND context_id = ctx_id
     AND (COALESCE(evt_type, '') = '' OR source_event_type = evt_type)
     AND resolved_at IS NULL;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

-- Upserts caller's notification delivery preferences (Step 3B).
CREATE OR REPLACE FUNCTION gateway_notifications.update_preferences(
  owner_id varchar,
  p_email_enabled boolean,
  p_push_enabled boolean,
  p_muted_categories jsonb,
  at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  v_id varchar;
BEGIN
  UPDATE public.notification_preference
     SET email_enabled          = p_email_enabled,
         push_enabled           = p_push_enabled,
         email_muted_categories = COALESCE(p_muted_categories, '[]'::jsonb),
         updated_at             = at
   WHERE user_id = owner_id;
  IF NOT FOUND THEN
    v_id := 'npr_' || substr(md5(owner_id || ':' || clock_timestamp()::text), 1, 22);
    INSERT INTO public.notification_preference (
      created_at, updated_at, id, user_id,
      email_enabled, email_muted_categories, push_enabled
    ) VALUES (
      at, at, v_id, owner_id,
      p_email_enabled, COALESCE(p_muted_categories, '[]'::jsonb), p_push_enabled
    );
  END IF;
  RETURN true;
END
$fn$;

REVOKE ALL ON FUNCTION gateway_notifications.archive(varchar, varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.deliver(varchar, varchar, varchar, varchar, text, varchar, varchar, varchar, varchar, varchar, boolean, varchar, varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.mark_read(varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.mark_all_read(varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.resolve_context(varchar, varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.update_preferences(varchar, boolean, boolean, jsonb, timestamptz) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_notifications TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.deliver(varchar, varchar, varchar, varchar, text, varchar, varchar, varchar, varchar, varchar, boolean, varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.mark_read(varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.mark_all_read(varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.archive(varchar, varchar) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.resolve_context(varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.update_preferences(varchar, boolean, boolean, jsonb, timestamptz) TO edify_gateway;
