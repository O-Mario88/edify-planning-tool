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
-- notify_workflow: a recipient named by either id, and one live notice per condition.
GRANT SELECT (id, user_id) ON staff_profile TO edify_notification_owner;
GRANT SELECT (resolved_at, created_at, reminder_count) ON notification TO edify_notification_owner;
GRANT UPDATE (title, body, target_route, action_label, priority, action_required, reminder_count,
              last_reminded_at)
  ON notification TO edify_notification_owner;
-- queue_push_copy: one delivery row per device and round, and its durable event.
GRANT SELECT (priority) ON notification TO edify_notification_owner;
GRANT SELECT (notification_id, channel, round, target),
      INSERT (id, created_at, updated_at, notification_id, recipient_id, channel, round, target, status,
              attempts, provider_message_id, last_error)
  ON notification_delivery TO edify_notification_owner;
GRANT SELECT (idempotency_key),
      INSERT (id, created_at, updated_at, event_type, payload, idempotency_key, status, attempts,
              max_attempts, next_attempt_at, locked_by, last_error)
  ON outbox_event TO edify_notification_owner;

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
  -- push.open_destination: an unread notice becomes read; the save names
  -- status and read_at only, so updated_at is left as it was.
  UPDATE public.notification
     SET status = 'read', read_at = at
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
  -- notifications_page_view's mark_all_read: a queryset update, which
  -- leaves updated_at as it was.
  UPDATE public.notification
     SET status = 'read', read_at = at
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
  -- archive_single and archive_all_read: queryset updates, updated_at left.
  UPDATE public.notification SET status = 'archived'
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

-- apps.notifications.services.resolve_condition: every live notice of one
-- event about one record is closed and leaves the person's list.
CREATE OR REPLACE FUNCTION gateway_notifications.resolve_condition(
  evt_type varchar, ctx_type varchar, ctx_id varchar, at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET resolved_at = at, status = 'archived', action_required = false, updated_at = at
   WHERE source_event_type = evt_type
     AND context_type = ctx_type
     AND context_id = ctx_id
     AND resolved_at IS NULL;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;

-- WorkflowNotificationService.trigger for one recipient, named by a user or a
-- staff profile id: one live notice per condition, so a repeat brings the
-- existing notice back as unread rather than stacking another.
CREATE OR REPLACE FUNCTION gateway_notifications.notify_workflow(
  new_id varchar, recipient_ref varchar, notif_title varchar, notif_body text, notif_category varchar,
  ctx_type varchar, ctx_id varchar, route varchar, btn_label varchar, prio varchar, evt_type varchar,
  at timestamptz
) RETURNS TABLE (out_notification_id varchar, out_recipient_id varchar)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  person record;
  live varchar;
  urgent boolean := prio = ANY (ARRAY['high', 'urgent']::varchar[]);
BEGIN
  SELECT u.id, u.active_role INTO person FROM public."user" u WHERE u.id = recipient_ref;
  IF NOT FOUND THEN
    SELECT u.id, u.active_role INTO person
      FROM public.staff_profile sp JOIN public."user" u ON u.id = sp.user_id
     WHERE sp.id = recipient_ref;
    IF NOT FOUND THEN
      RETURN;
    END IF;
  END IF;
  SELECT n.id INTO live FROM public.notification n
   WHERE n.recipient_id = person.id AND n.source_event_type = evt_type
     -- context_type=None is IS NULL in the existing lookup; a notice with no
     -- context id is never matched, as the existing trigger only looks when
     -- there is one.
     AND n.context_type IS NOT DISTINCT FROM ctx_type AND n.context_id = ctx_id
     AND n.resolved_at IS NULL AND n.status <> 'archived'
   ORDER BY n.created_at DESC LIMIT 1 FOR UPDATE;
  IF FOUND THEN
    UPDATE public.notification n
       SET title = notif_title, body = notif_body, target_route = route, action_label = btn_label,
           priority = prio, action_required = urgent, reminder_count = COALESCE(n.reminder_count, 0) + 1,
           last_reminded_at = at, status = 'unread', read_at = NULL, updated_at = at
     WHERE n.id = live;
    out_notification_id := live;
  ELSE
    INSERT INTO public.notification (
      id, created_at, updated_at, recipient_id, recipient_role, title, body, category, context_type,
      context_id, target_route, action_label, action_required, priority, status, source_event_type,
      source_event_id, reminder_count
    ) VALUES (
      new_id, at, at, person.id, COALESCE(NULLIF(person.active_role, ''), 'Staff'), notif_title, notif_body,
      notif_category, ctx_type, ctx_id, route, btn_label, urgent, prio, 'unread', evt_type, COALESCE(ctx_id, ''), 0
    );
    out_notification_id := new_id;
  END IF;
  out_recipient_id := person.id;
  RETURN NEXT;
END
$fn$;

-- push.enqueue for one device: a copy the recipient turned off is recorded as
-- suppressed and not queued; a deactivated account is sent nothing.
CREATE OR REPLACE FUNCTION gateway_notifications.queue_push_copy(
  delivery_id varchar, event_id varchar, notice_id varchar, device varchar, at timestamptz
) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  notice record;
  turned_off boolean;
  this_round integer;
BEGIN
  SELECT n.recipient_id, n.priority, COALESCE(n.reminder_count, 0) AS reminders INTO notice
    FROM public.notification n
    JOIN public."user" u ON u.id = n.recipient_id AND u.is_active AND u.deleted_at IS NULL
   WHERE n.id = notice_id;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  this_round := notice.reminders;
  turned_off := notice.priority <> 'urgent' AND EXISTS (
    SELECT 1 FROM public.notification_preference p WHERE p.user_id = notice.recipient_id AND p.push_enabled = false);
  INSERT INTO public.notification_delivery (id, created_at, updated_at, notification_id, recipient_id, channel, round,
                                            target, status, attempts, provider_message_id, last_error)
  VALUES (delivery_id, at, at, notice_id, notice.recipient_id, 'push', this_round, device,
          CASE WHEN turned_off THEN 'suppressed' ELSE 'queued' END, 0, '', '')
  ON CONFLICT (notification_id, channel, round, target) DO NOTHING;
  IF NOT FOUND OR turned_off THEN
    RETURN false;
  END IF;
  INSERT INTO public.outbox_event (id, created_at, updated_at, event_type, payload, idempotency_key, status, attempts,
                                   max_attempts, next_attempt_at, locked_by, last_error)
  VALUES (event_id, at, at, 'notification.push',
          jsonb_build_object('notificationId', notice_id, 'subscriptionId', device, 'round', this_round),
          'push:' || notice_id || ':' || this_round || ':' || device, 'pending', 0, 8, at, '', '')
  ON CONFLICT (idempotency_key) DO NOTHING;
  RETURN true;
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
REVOKE ALL ON FUNCTION gateway_notifications.resolve_condition(varchar, varchar, varchar, timestamptz) FROM PUBLIC;
-- _do_daily_plan_notifications' first step: yesterday's live day-keyed
-- notices (the plan and the team monitor) describe a day that is over, so
-- every one not keyed to today is closed as the existing job closes it.
CREATE OR REPLACE FUNCTION gateway_notifications.close_stale_daily_notices(
  evt_types varchar[], keep_ctx varchar, at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET resolved_at = at, status = 'archived', action_required = false, updated_at = at
   WHERE source_event_type = ANY(evt_types)
     AND resolved_at IS NULL
     AND context_id IS DISTINCT FROM keep_ctx;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_notifications.close_stale_daily_notices(varchar[], varchar, timestamptz) FROM PUBLIC;
-- send_verification_reminders: a lead's earlier live reminder is answered by
-- tonight's, or by an empty queue, so every one not keyed to tonight is closed.
CREATE OR REPLACE FUNCTION gateway_notifications.close_stale_notices_for(
  recipient varchar, evt_type varchar, keep_ctx varchar, at timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
DECLARE
  changed integer;
BEGIN
  UPDATE public.notification
     SET resolved_at = at, status = 'archived', action_required = false, updated_at = at
   WHERE recipient_id = recipient
     AND source_event_type = evt_type
     AND resolved_at IS NULL
     AND context_id IS DISTINCT FROM keep_ctx;
  GET DIAGNOSTICS changed = ROW_COUNT;
  RETURN changed;
END
$fn$;
REVOKE ALL ON FUNCTION gateway_notifications.close_stale_notices_for(varchar, varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.notify_workflow(varchar, varchar, varchar, text, varchar, varchar, varchar, varchar, varchar, varchar, varchar, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION gateway_notifications.queue_push_copy(varchar, varchar, varchar, varchar, timestamptz) FROM PUBLIC;
RESET ROLE;

GRANT USAGE ON SCHEMA gateway_notifications TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.deliver(varchar, varchar, varchar, varchar, text, varchar, varchar, varchar, varchar, varchar, boolean, varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.mark_read(varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.mark_all_read(varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.archive(varchar, varchar) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.resolve_context(varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.update_preferences(varchar, boolean, boolean, jsonb, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.resolve_condition(varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.close_stale_daily_notices(varchar[], varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.close_stale_notices_for(varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.notify_workflow(varchar, varchar, varchar, text, varchar, varchar, varchar, varchar, varchar, varchar, varchar, timestamptz) TO edify_gateway;
GRANT EXECUTE ON FUNCTION gateway_notifications.queue_push_copy(varchar, varchar, varchar, varchar, timestamptz) TO edify_gateway;
